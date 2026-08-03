from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import uuid

from dududa.contracts.canonical import canonical_digest
from dududa.domain.delivery import DeliveryStatus
from dududa.domain.primitives import ComponentRevision, DigestString, Sensitivity
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext
from dududa.security.digests import (
    actor_digest,
    authorization_decision_digest,
    scope_digest,
)
from dududa.security.models import AuthorizationEffect, RedactionRequest
from dududa.security.redaction import DefaultRedactor

from .digests import (
    memory_candidate_digest,
    memory_content_hash,
    memory_write_request_digest,
)
from .models import (
    DeliveryDependency,
    MemoryRecord,
    MemorySource,
    MemoryType,
    MemoryWriteAction,
    MemoryWriteCommand,
    MemoryWriteDecision,
    MemoryWriteRequest,
    Visibility,
)


class ExplicitMemoryWriteGate:
    """Allows only explicit user memory; automatic extraction remains disabled."""

    def __init__(
        self,
        *,
        policy_revision: str = "memory-write-policy-v1",
        maximum_ttl: timedelta = timedelta(days=365),
        decision_ttl: timedelta = timedelta(minutes=1),
        redactor: DefaultRedactor | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._policy_revision = policy_revision
        self._maximum_ttl = maximum_ttl
        self._decision_ttl = decision_ttl
        self._redactor = redactor or DefaultRedactor()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._revision = ComponentRevision(
            "memory.explicit-write-gate",
            "1",
            policy_revision,
            DigestString("builtin"),
        )
        self._issued_decisions: dict[str, MemoryWriteDecision] = {}

    async def evaluate(
        self,
        request: MemoryWriteRequest,
        *,
        call: PortCallContext,
    ) -> MemoryWriteDecision:
        now = self._clock()
        if call.cancellation.is_cancelled or call.deadline <= now:
            raise _gate_error("memory_write_call_cancelled_or_expired")
        if memory_write_request_digest(request) != request.request_digest:
            raise _gate_error("memory_write_request_digest_mismatch")
        candidate = request.candidate
        actor_hash = actor_digest(request.actor)
        conversation_hash = scope_digest(request.conversation_scope)
        candidate_hash = memory_candidate_digest(candidate)
        authorization_hash = authorization_decision_digest(request.authorization)
        confirmation_hash = (
            canonical_digest(
                request.confirmation, domain="security:confirmation-grant:v1"
            )
            if request.confirmation is not None
            else None
        )
        reasons = self._rejection_reasons(request, now)
        normalized: MemoryRecord | None = None
        action = MemoryWriteAction.REJECT
        if not reasons:
            created_at = now
            expires_at = (
                created_at + candidate.proposed_ttl
                if candidate.proposed_ttl is not None
                else None
            )
            normalized = MemoryRecord(
                1,
                self._id_factory(),
                candidate.proposed_scope,
                candidate.proposed_content.strip(),
                candidate.source,
                created_at,
                created_at,
                candidate.confidence,
                expires_at,
                candidate.sensitivity_hint,
                Visibility.CURRENT_CONVERSATION,
                candidate.evidence,
                memory_content_hash(candidate.proposed_content.strip()),
                1,
            )
            action = MemoryWriteAction.ALLOW
            reasons = ("explicit_user_memory",)
        decision = MemoryWriteDecision(
            1,
            self._id_factory(),
            request.request_digest,
            candidate.candidate_id,
            candidate_hash,
            actor_hash,
            conversation_hash,
            request.delivery_id,
            request.delivery_status,
            request.delivery_receipt_digest,
            confirmation_hash,
            authorization_hash,
            request.idempotency_key,
            action,
            tuple(reasons),
            normalized,
            None,
            None,
            self._policy_revision,
            self._revision,
            now + self._decision_ttl,
        )
        self._issued_decisions[decision.decision_id] = decision
        return decision

    def verify_decision(
        self,
        decision: MemoryWriteDecision,
        *,
        at: datetime | None = None,
    ) -> bool:
        now = at or self._clock()
        return (
            self._issued_decisions.get(decision.decision_id) == decision
            and decision.gate_revision == self._revision
            and now < decision.decision_expires_at
        )

    def command(
        self,
        request: MemoryWriteRequest,
        decision: MemoryWriteDecision,
        *,
        command_id: str | None = None,
    ) -> MemoryWriteCommand:
        if decision.request_digest != request.request_digest:
            raise _gate_error("memory_decision_request_mismatch")
        return MemoryWriteCommand(
            1,
            command_id or self._id_factory(),
            request.request_digest,
            decision,
            request.actor,
            request.conversation_scope,
            request.delivery_id,
            request.delivery_status,
            request.delivery_receipt_digest,
            request.confirmation,
            request.authorization,
            request.idempotency_key,
        )

    def _rejection_reasons(
        self,
        request: MemoryWriteRequest,
        now: datetime,
    ) -> tuple[str, ...]:
        candidate = request.candidate
        scope = candidate.proposed_scope
        conversation = request.conversation_scope
        if candidate.source is not MemorySource.EXPLICIT_USER_REQUEST:
            return ("automatic_memory_write_disabled",)
        if candidate.proposed_type is not MemoryType.EXPLICIT_USER_MEMORY:
            return ("explicit_command_requires_explicit_memory_type",)
        if scope.memory_type is not candidate.proposed_type:
            return ("memory_type_scope_mismatch",)
        if (
            request.actor.platform != conversation.platform
            or request.actor.bot_id != conversation.bot_id
            or scope.platform != conversation.platform
            or scope.bot_id != conversation.bot_id
            or scope.conversation_type is not conversation.conversation_type
            or scope.conversation_id != conversation.conversation_id
            or scope.group_id != conversation.group_id
            or scope.persona_id != conversation.persona_id
            or scope.user_id != request.actor.user_id
        ):
            return ("memory_scope_mismatch",)
        if candidate.sensitivity_hint in {
            Sensitivity.SENSITIVE,
            Sensitivity.RESTRICTED,
        }:
            return ("sensitive_memory_rejected",)
        if (
            candidate.proposed_ttl is not None
            and candidate.proposed_ttl > self._maximum_ttl
        ):
            return ("memory_ttl_exceeds_limit",)
        if candidate.delivery_dependency is DeliveryDependency.SUCCESS_REQUIRED:
            if (
                request.delivery_status is not DeliveryStatus.SUCCEEDED
                or not request.delivery_id
                or request.delivery_receipt_digest is None
            ):
                return ("delivery_not_succeeded",)
        elif candidate.delivery_dependency is not DeliveryDependency.NONE:
            return ("invalid_delivery_dependency",)
        authorization = request.authorization
        if (
            authorization.effect is not AuthorizationEffect.ALLOW
            or str(authorization.action) != "memory.write"
            or authorization.actor_digest != actor_digest(request.actor)
            or authorization.scope_digest != scope_digest(conversation)
            or authorization.decided_at > now
            or authorization.expires_at <= now
        ):
            return ("memory_write_not_authorized",)
        redaction = self._redactor.redact(
            RedactionRequest(
                1,
                {"content": candidate.proposed_content},
                candidate.sensitivity_hint,
                "memory_write",
            )
        )
        if redaction.changed:
            return ("credential_or_sensitive_pattern",)
        return ()


def _gate_error(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "memory.write_rejected")
