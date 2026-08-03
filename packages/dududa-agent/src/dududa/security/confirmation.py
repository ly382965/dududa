from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import uuid

from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext

from .digests import (
    actor_digest,
    authorization_decision_digest,
    confirmation_consume_request_digest,
    confirmation_request_digest,
    scope_digest,
)
from .models import (
    AuthorizationEffect,
    ConfirmationConsumeRequest,
    ConfirmationGrant,
    ConfirmationRequest,
    ConfirmationRequirement,
)
from .ports import AuthorizationDecisionVerifier


class InMemoryConfirmationService:
    """Atomic, single-process confirmation store used by compatibility mode and tests."""

    def __init__(
        self,
        *,
        policy_revision: str,
        authorization_verifier: AuthorizationDecisionVerifier,
        maximum_ttl: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not policy_revision.strip() or maximum_ttl <= timedelta(0):
            raise ValueError("invalid confirmation service config")
        if not callable(getattr(authorization_verifier, "verify", None)):
            raise ValueError("authorization verifier is required")
        self._policy_revision = policy_revision
        self._authorization_verifier = authorization_verifier
        self._maximum_ttl = maximum_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._requirements: dict[str, ConfirmationRequirement] = {}
        self._consumed: set[str] = set()
        self._lock = asyncio.Lock()

    async def issue(
        self,
        request: ConfirmationRequest,
        *,
        call: PortCallContext,
    ) -> ConfirmationRequirement:
        if confirmation_request_digest(request) != request.request_digest:
            raise _confirmation_error("confirmation_request_digest_mismatch")
        now = self._clock()
        if call.cancellation.is_cancelled or call.deadline <= now:
            raise _confirmation_error("confirmation_call_cancelled_or_expired")
        if request.ttl > self._maximum_ttl:
            raise _confirmation_error("confirmation_ttl_exceeds_limit")
        if (
            request.actor.platform != request.conversation_scope.platform
            or request.actor.bot_id != request.conversation_scope.bot_id
        ):
            raise _confirmation_error("confirmation_identity_scope_mismatch")
        requirement = ConfirmationRequirement(
            schema_version=1,
            confirmation_id=self._id_factory(),
            request_digest=request.request_digest,
            actor_digest=actor_digest(request.actor),
            scope_digest=scope_digest(request.conversation_scope),
            action=request.action,
            payload_digest=request.payload_digest,
            required_permission=request.required_permission,
            public_prompt_key="security.confirmation_required",
            policy_revision=self._policy_revision,
            created_at=now,
            expires_at=now + request.ttl,
        )
        async with self._lock:
            self._requirements[requirement.confirmation_id] = requirement
        return requirement

    async def consume(
        self,
        request: ConfirmationConsumeRequest,
        *,
        call: PortCallContext,
    ) -> ConfirmationGrant:
        if confirmation_consume_request_digest(request) != request.request_digest:
            raise _confirmation_error("confirmation_consume_digest_mismatch")
        now = self._clock()
        if call.cancellation.is_cancelled or call.deadline <= now:
            raise _confirmation_error("confirmation_call_cancelled_or_expired")
        async with self._lock:
            requirement = self._requirements.get(request.confirmation_id)
            if requirement is None or request.confirmation_id in self._consumed:
                raise _confirmation_error("confirmation_missing_or_consumed")
            self._validate_binding(requirement, request, now)
            self._consumed.add(request.confirmation_id)
        return ConfirmationGrant(
            schema_version=1,
            confirmation_id=requirement.confirmation_id,
            consume_request_digest=request.request_digest,
            actor_digest=requirement.actor_digest,
            scope_digest=requirement.scope_digest,
            action=requirement.action,
            payload_digest=requirement.payload_digest,
            required_permission=requirement.required_permission,
            execution_id=request.execution_id,
            idempotency_key=request.idempotency_key,
            authorization_digest=authorization_decision_digest(request.authorization),
            policy_revision=self._policy_revision,
            created_at=requirement.created_at,
            consumed_at=now,
            expires_at=requirement.expires_at,
        )

    def _validate_binding(
        self,
        requirement: ConfirmationRequirement,
        request: ConfirmationConsumeRequest,
        now: datetime,
    ) -> None:
        if now >= requirement.expires_at:
            raise _confirmation_error("confirmation_expired")
        expected_actor = actor_digest(request.actor)
        expected_scope = scope_digest(request.conversation_scope)
        fields_match = (
            requirement.actor_digest == expected_actor
            and requirement.scope_digest == expected_scope
            and requirement.action == request.action
            and requirement.payload_digest == request.payload_digest
            and requirement.required_permission == request.required_permission
        )
        if not fields_match:
            raise _confirmation_error("confirmation_binding_mismatch")
        authorization = request.authorization
        authorization_matches = (
            authorization.effect is AuthorizationEffect.ALLOW
            and authorization.actor_digest == expected_actor
            and authorization.scope_digest == expected_scope
            and authorization.action == request.action
            and authorization.policy_revision == self._policy_revision
            and authorization.decided_at <= now
            and authorization.expires_at > now
            and self._authorization_verifier.verify(authorization, at=now)
        )
        if not authorization_matches:
            raise _confirmation_error("confirmation_authorization_invalid")


def _confirmation_error(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "security.confirmation_invalid")
