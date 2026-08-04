from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
from dududa.contracts.delivery import (
    DeliveryAuthorizationIntent,
    delivery_authorization_metadata,
    delivery_authorization_resource,
    delivery_payload_digest,
    delivery_request_digest,
)
from dududa.domain.content import ValidatedFinalResponse
from dududa.domain.delivery import (
    canonicalize_delivery_receipt,
    DeliveryConstraints,
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryRequest,
    DeliveryStatus,
    plan_delivery_parts,
)
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import MessageReference
from dududa.domain.primitives import Outcome, require_aware
from dududa.errors import DududaError, ErrorCategory, error, validation_error
from dududa.security.digests import (
    actor_digest,
    authorization_metadata_digest,
    authorization_request_digest,
    resource_digest,
    scope_digest,
)
from dududa.security.models import (
    AuthorizationDecision,
    AuthorizationEffect,
    AuthorizationRequest,
)
from dududa.security.ports import AuthorizationDecisionVerifier

from .authorization import build_delivery_authorization_request
from .contracts import (
    DeliveryReconciliationAction,
    DeliveryReconciliationReceipt,
)
from .state import (
    CompletionReceipt,
    RuntimePhase,
    RuntimeState,
    transition,
    validate_runtime_state,
)


@dataclass(frozen=True, slots=True)
class DeliveryRequestPlan:
    schema_version: int
    intent: DeliveryAuthorizationIntent
    response: ValidatedFinalResponse
    authorization_request: AuthorizationRequest

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.intent, DeliveryAuthorizationIntent):
            raise validation_error("invalid_delivery_authorization_intent")
        if not isinstance(self.response, ValidatedFinalResponse):
            raise validation_error("invalid_delivery_plan_response")
        if not isinstance(self.authorization_request, AuthorizationRequest):
            raise validation_error("invalid_delivery_authorization_request")
        if self.intent.payload_digest != delivery_payload_digest(self.response):
            raise validation_error("delivery_plan_payload_mismatch")
        if self.authorization_request.actor.platform != self.intent.scope.platform:
            raise validation_error("delivery_plan_actor_scope_mismatch")
        if (
            self.authorization_request.conversation_scope != self.intent.scope
            or self.authorization_request.resource
            != delivery_authorization_resource(self.intent)
            or self.authorization_request.metadata
            != delivery_authorization_metadata(
                self.intent,
                policy_snapshot_id=str(
                    self.authorization_request.metadata["policy_snapshot_id"]
                ),
            )
            or authorization_request_digest(self.authorization_request)
            != self.authorization_request.request_digest
        ):
            raise validation_error("delivery_plan_authorization_mismatch")


@dataclass(frozen=True, slots=True)
class DeliveryRequestBuilderConfig:
    schema_version: int
    constraints: DeliveryConstraints
    adapter_binding: NegotiatedBindingReceipt

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.constraints, DeliveryConstraints):
            raise validation_error("invalid_delivery_constraints")
        if not isinstance(self.adapter_binding, NegotiatedBindingReceipt):
            raise validation_error("invalid_delivery_adapter_binding")
        if (
            self.adapter_binding.port_id != "output-adapter"
            or "deliver" not in self.adapter_binding.operation_schema_digests
        ):
            raise validation_error("invalid_delivery_adapter_binding")


class DeliveryRequestBuilder:
    def __init__(
        self,
        config: DeliveryRequestBuilderConfig,
        authorization_verifier: AuthorizationDecisionVerifier,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(config, DeliveryRequestBuilderConfig):
            raise TypeError("invalid Delivery Request Builder config")
        if not callable(getattr(authorization_verifier, "verify", None)):
            raise TypeError("authorization verifier does not implement verify")
        self._config = config
        self._authorization_verifier = authorization_verifier
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def config(self) -> DeliveryRequestBuilderConfig:
        return self._config

    def plan(
        self,
        *,
        run_id: str,
        response: ValidatedFinalResponse,
        actor: Actor,
        scope: ConversationScope,
        reply_to: MessageReference | None,
        policy_snapshot_id: str,
    ) -> DeliveryRequestPlan:
        if not isinstance(response, ValidatedFinalResponse):
            raise validation_error("invalid_delivery_plan_response")
        if not isinstance(actor, Actor) or not isinstance(scope, ConversationScope):
            raise validation_error("invalid_delivery_plan_identity")
        payload_digest = delivery_payload_digest(response)
        delivery_id = str(
            canonical_digest(
                {
                    "run_id": run_id,
                    "payload_digest": payload_digest,
                    "scope": scope,
                    "reply_to": reply_to,
                    "attempt": 1,
                },
                domain="delivery:id:v1",
            )
        )
        idempotency_key = str(
            canonical_digest(
                {
                    "delivery_id": delivery_id,
                    "payload_digest": payload_digest,
                    "constraints": self._config.constraints,
                    "adapter_binding": self._config.adapter_binding,
                },
                domain="delivery:request-plan:v1",
            )
        )
        parts = plan_delivery_parts(
            delivery_id,
            response,
            None,
            reply_to=reply_to,
            constraints=self._config.constraints,
            payload_digest=payload_digest,
        )
        intent = DeliveryAuthorizationIntent(
            schema_version=1,
            delivery_id=delivery_id,
            run_id=run_id,
            payload_digest=payload_digest,
            idempotency_key=idempotency_key,
            attempt=1,
            outcome=Outcome.RESPONSE,
            scope=scope,
            reply_to=reply_to,
            constraints=self._config.constraints,
            part_intents=parts,
            attachment_access=(),
            adapter_binding=self._config.adapter_binding,
        )
        authorization = build_delivery_authorization_request(
            actor,
            intent,
            policy_snapshot_id=policy_snapshot_id,
        )
        return DeliveryRequestPlan(1, intent, response, authorization)

    def finalize(
        self,
        plan: DeliveryRequestPlan,
        authorization: AuthorizationDecision,
    ) -> DeliveryRequest:
        if not isinstance(plan, DeliveryRequestPlan):
            raise validation_error("invalid_delivery_request_plan")
        if not isinstance(authorization, AuthorizationDecision):
            raise validation_error("invalid_delivery_authorization")
        now = self._now()
        request = plan.authorization_request
        if (
            authorization.effect is not AuthorizationEffect.ALLOW
            or authorization.request_digest != request.request_digest
            or authorization.actor_digest != actor_digest(request.actor)
            or authorization.scope_digest != scope_digest(request.conversation_scope)
            or authorization.action != request.action
            or authorization.resource_digest != resource_digest(request.resource)
            or authorization.capability_id != request.capability_id
            or authorization.risk_level is not request.risk_level
            or authorization.metadata_digest
            != authorization_metadata_digest(request.metadata)
            or not self._authorization_verifier.verify(authorization, at=now)
        ):
            raise validation_error("delivery_authorization_decision_mismatch")
        intent = plan.intent
        delivery = DeliveryRequest(
            schema_version=1,
            delivery_id=intent.delivery_id,
            run_id=intent.run_id,
            request_digest=canonical_digest({}, domain="pending:v1"),
            payload_digest=intent.payload_digest,
            idempotency_key=intent.idempotency_key,
            attempt=intent.attempt,
            outcome=intent.outcome,
            response=plan.response,
            reaction=None,
            scope=intent.scope,
            reply_to=intent.reply_to,
            constraints=intent.constraints,
            part_intents=intent.part_intents,
            authorization=authorization,
            attachment_access=(),
            adapter_binding=intent.adapter_binding,
        )
        return replace(delivery, request_digest=delivery_request_digest(delivery))

    def _now(self) -> datetime:
        now = self._clock()
        require_aware(now, "delivery_builder_clock")
        return now


def acknowledge_delivery_state(
    state: RuntimeState,
    receipt: DeliveryReceipt,
    *,
    completed_at: datetime,
) -> RuntimeState:
    return delivery_acknowledgement_states(
        state,
        receipt,
        completed_at=completed_at,
    )[-1]


def delivery_acknowledgement_states(
    state: RuntimeState,
    receipt: DeliveryReceipt,
    *,
    completed_at: datetime,
) -> tuple[RuntimeState, ...]:
    require_aware(completed_at, "delivery_completed_at")
    if not isinstance(receipt, DeliveryReceipt):
        raise validation_error("invalid_delivery_acknowledgement_receipt")
    if completed_at < receipt.acknowledged_at:
        raise validation_error("delivery_completion_precedes_acknowledgement")
    request = state.delivery_request
    if request is None:
        raise validation_error("delivery_acknowledgement_without_request")
    receipt = canonicalize_delivery_receipt(request, receipt)
    if state.phase is RuntimePhase.COMPLETED:
        if state.delivery_receipt == receipt:
            return (state,)
        raise _conflict("delivery_acknowledgement_conflict")
    if state.phase not in {
        RuntimePhase.READY_TO_EMIT,
        RuntimePhase.DELIVERY_ACKNOWLEDGED,
        RuntimePhase.MEMORY_EVALUATED,
    }:
        raise _conflict("runtime_not_ready_for_delivery_acknowledgement")
    states: list[RuntimeState] = []
    current = state
    expected_expiry = (
        receipt.acknowledged_at + request.constraints.reconciliation_window
    )
    if current.phase is RuntimePhase.READY_TO_EMIT:
        current = transition(
            current,
            RuntimePhase.DELIVERY_ACKNOWLEDGED,
            delivery_receipt=receipt,
            reconciliation_expires_at=expected_expiry,
        )
        states.append(current)
    elif (
        current.delivery_receipt != receipt
        or current.reconciliation_expires_at != expected_expiry
    ):
        raise _conflict("delivery_acknowledgement_conflict")
    if current.phase is RuntimePhase.DELIVERY_ACKNOWLEDGED:
        current = transition(current, RuntimePhase.MEMORY_EVALUATED)
        states.append(current)
    completion = CompletionReceipt(
        schema_version=1,
        run_id=state.run_id,
        final_phase=RuntimePhase.COMPLETED,
        delivery_status=receipt.status,
        completed_at=completed_at,
        memory_submissions=(),
    )
    completed = transition(current, RuntimePhase.COMPLETED, completion=completion)
    states.append(completed)
    return tuple(states)


def reconcile_completed_delivery(
    state: RuntimeState,
    receipt: DeliveryReceipt,
    *,
    now: datetime,
) -> tuple[RuntimeState, DeliveryReconciliationReceipt]:
    require_aware(now, "delivery_reconciled_at")
    if (
        state.phase is not RuntimePhase.COMPLETED
        or state.delivery_request is None
        or state.delivery_receipt is None
        or state.completion is None
        or state.reconciliation_expires_at is None
    ):
        raise _conflict("runtime_delivery_not_reconcilable")
    try:
        receipt = canonicalize_delivery_receipt(state.delivery_request, receipt)
    except DududaError:
        previous = state.delivery_receipt
        return state, _reconciliation_receipt(
            state,
            DeliveryReconciliationAction.CONFLICT,
            previous.status,
            previous.status,
            ("delivery_reconciliation_binding_conflict",),
            now,
        )
    previous = state.delivery_receipt
    if receipt == previous:
        return state, _reconciliation_receipt(
            state,
            DeliveryReconciliationAction.NO_CHANGE,
            previous.status,
            previous.status,
            ("exact_delivery_receipt_replay",),
            now,
        )
    if now >= state.reconciliation_expires_at:
        return state, _reconciliation_receipt(
            state,
            DeliveryReconciliationAction.EXPIRED,
            previous.status,
            previous.status,
            ("delivery_reconciliation_window_expired",),
            now,
        )
    if receipt.acknowledged_at > now:
        return state, _reconciliation_receipt(
            state,
            DeliveryReconciliationAction.CONFLICT,
            previous.status,
            previous.status,
            ("delivery_acknowledgement_in_future",),
            now,
        )
    if receipt.acknowledged_at < previous.acknowledged_at:
        return state, _reconciliation_receipt(
            state,
            DeliveryReconciliationAction.CONFLICT,
            previous.status,
            previous.status,
            ("delivery_acknowledgement_time_regression",),
            now,
        )
    merged, conflict_code = _merge_delivery_receipts(
        state.delivery_request,
        previous,
        receipt,
    )
    if conflict_code is not None:
        return state, _reconciliation_receipt(
            state,
            DeliveryReconciliationAction.CONFLICT,
            previous.status,
            previous.status,
            (conflict_code,),
            now,
        )
    if merged == previous:
        return state, _reconciliation_receipt(
            state,
            DeliveryReconciliationAction.NO_CHANGE,
            previous.status,
            previous.status,
            ("delivery_evidence_unchanged",),
            now,
        )
    updated = replace(
        state,
        delivery_receipt=merged,
        completion=replace(state.completion, delivery_status=merged.status),
    )
    validate_runtime_state(updated, previous=state)
    return updated, _reconciliation_receipt(
        updated,
        DeliveryReconciliationAction.IMPROVED,
        previous.status,
        merged.status,
        ("delivery_evidence_improved",),
        now,
    )


def _merge_delivery_receipts(
    request: DeliveryRequest,
    previous: DeliveryReceipt,
    current: DeliveryReceipt,
) -> tuple[DeliveryReceipt, str | None]:
    previous_by_id = {part.part_id: part for part in previous.parts}
    current_by_id = {part.part_id: part for part in current.parts}
    merged: dict[str, DeliveryPartReceipt] = dict(previous_by_id)
    rank = {
        DeliveryPartStatus.UNKNOWN: 0,
        DeliveryPartStatus.FAILED: 1,
        DeliveryPartStatus.SUCCEEDED: 2,
    }
    for part_id, candidate in current_by_id.items():
        existing = previous_by_id.get(part_id)
        if existing is None:
            merged[part_id] = candidate
            continue
        if existing.content_digest != candidate.content_digest:
            return previous, "delivery_part_content_conflict"
        if (
            existing.platform_message_ref is not None
            and candidate.platform_message_ref is not None
            and existing.platform_message_ref != candidate.platform_message_ref
        ):
            return previous, "delivery_part_platform_reference_conflict"
        if rank[candidate.status] < rank[existing.status]:
            return previous, "delivery_part_status_regression"
        if rank[candidate.status] > rank[existing.status]:
            merged[part_id] = replace(
                candidate,
                platform_message_ref=(
                    candidate.platform_message_ref or existing.platform_message_ref
                ),
            )
        elif existing.platform_message_ref is None and candidate.platform_message_ref:
            merged[part_id] = replace(
                existing,
                platform_message_ref=candidate.platform_message_ref,
            )
    for intent in request.part_intents:
        if intent.part_id not in merged:
            merged[intent.part_id] = DeliveryPartReceipt(
                schema_version=1,
                part_id=intent.part_id,
                content_digest=intent.content_digest,
                status=DeliveryPartStatus.UNKNOWN,
                platform_message_ref=None,
                error_code="delivery_part_not_acknowledged",
            )
    ordered = tuple(
        merged[intent.part_id]
        for intent in request.part_intents
        if intent.part_id in merged
    )
    statuses = {part.status for part in ordered}
    planned_ids = {part.part_id for part in request.part_intents}
    observed_ids = {part.part_id for part in ordered}
    if statuses == {DeliveryPartStatus.SUCCEEDED} and observed_ids == planned_ids:
        status = DeliveryStatus.SUCCEEDED
        error_code = None
    elif DeliveryPartStatus.SUCCEEDED in statuses:
        status = DeliveryStatus.PARTIAL
        error_code = current.error_code or previous.error_code or "delivery_partial"
    elif DeliveryPartStatus.UNKNOWN in statuses:
        status = DeliveryStatus.UNKNOWN
        error_code = current.error_code or previous.error_code
    else:
        status = DeliveryStatus.FAILED
        error_code = current.error_code or previous.error_code or "delivery_failed"
    return (
        DeliveryReceipt(
            schema_version=1,
            delivery_id=previous.delivery_id,
            run_id=previous.run_id,
            delivery_request_digest=previous.delivery_request_digest,
            idempotency_key=previous.idempotency_key,
            attempt=previous.attempt,
            adapter_revision=previous.adapter_revision,
            status=status,
            parts=ordered,
            acknowledged_at=previous.acknowledged_at,
            error_code=error_code,
        ),
        None,
    )


def _reconciliation_receipt(
    state: RuntimeState,
    action: DeliveryReconciliationAction,
    previous_status: DeliveryStatus,
    current_status: DeliveryStatus,
    reason_codes: tuple[str, ...],
    now: datetime,
) -> DeliveryReconciliationReceipt:
    request = state.delivery_request
    if request is None:
        raise validation_error("delivery_reconciliation_without_request")
    return DeliveryReconciliationReceipt(
        schema_version=1,
        run_id=state.run_id,
        delivery_id=request.delivery_id,
        action=action,
        previous_status=previous_status,
        current_status=current_status,
        reason_codes=reason_codes,
        reconciled_at=now,
    )


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")
