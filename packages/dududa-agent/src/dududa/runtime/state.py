from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol, TypeAlias

from dududa._compat import StrEnum
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import DraftResponse, Reaction, ValidatedFinalResponse
from dududa.domain.delivery import DeliveryReceipt, DeliveryRequest, DeliveryStatus
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import MessageEnvelope
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    Outcome,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
    freeze_json,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.memory.models import MemoryCandidate, MemorySubmissionReceipt
from dududa.models.contracts import RouteHint


class RuntimePhase(StrEnum):
    RECEIVED = "received"
    PREPROCESSED = "preprocessed"
    CONTEXT_READY = "context_ready"
    PERCEIVED = "perceived"
    DECIDED = "decided"
    TOOLS_PLANNED = "tools_planned"
    TOOLS_EXECUTED = "tools_executed"
    VALIDATED = "validated"
    COMPOSED = "composed"
    RENDERED = "rendered"
    READY_TO_EMIT = "ready_to_emit"
    DELIVERY_ACKNOWLEDGED = "delivery_acknowledged"
    MEMORY_EVALUATED = "memory_evaluated"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    FAILED = "failed"


class ProvisionalRuntimePayload(Protocol):
    """Minimal marker until the owning S08+ DTO module is implemented."""

    schema_version: int


PreprocessResult: TypeAlias = ProvisionalRuntimePayload
MemoryRetrievalResult: TypeAlias = ProvisionalRuntimePayload
ContextBuildResult: TypeAlias = ProvisionalRuntimePayload
PerceptionResult: TypeAlias = ProvisionalRuntimePayload
SocialDecision: TypeAlias = ProvisionalRuntimePayload
CapabilityRetrievalResult: TypeAlias = ProvisionalRuntimePayload
ToolPlan: TypeAlias = ProvisionalRuntimePayload
ToolObservation: TypeAlias = ProvisionalRuntimePayload
ToolValidationResult: TypeAlias = ProvisionalRuntimePayload


@dataclass(frozen=True, slots=True)
class RuntimeInvocationOptions:
    schema_version: int
    route_hint: RouteHint | None
    entrypoint_id: str
    feature_flags: Mapping[str, bool]
    feature_flag_revision: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.entrypoint_id, "entrypoint_id")
        require_non_empty(self.feature_flag_revision, "feature_flag_revision")
        if any(type(value) is not bool for value in self.feature_flags.values()):
            raise validation_error("invalid_feature_flag")
        object.__setattr__(self, "feature_flags", freeze_json(dict(self.feature_flags)))


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    schema_version: int
    message: MessageEnvelope
    actor: Actor
    received_at: datetime
    adapter_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_aware(self.received_at, "received_at")
        if (
            self.actor.platform != self.message.platform
            or self.actor.bot_id != self.message.bot_id
            or self.actor.user_id != self.message.user_id
        ):
            raise validation_error("connector_identity_mismatch")


@dataclass(frozen=True, slots=True)
class RuntimeStartRequest:
    schema_version: int
    connector_result: ConnectorResult
    options: RuntimeInvocationOptions
    start_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.start_digest), "start_digest")
        if self.start_digest != runtime_start_digest(
            self.connector_result,
            self.options,
            schema_version=self.schema_version,
        ):
            raise validation_error("runtime_start_digest_mismatch")


def runtime_start_digest(
    connector_result: ConnectorResult,
    options: RuntimeInvocationOptions,
    *,
    schema_version: int = 1,
) -> DigestString:
    _v1(schema_version)
    return canonical_digest(
        {
            "schema_version": schema_version,
            "connector_result": connector_result,
            "options": options,
        },
        domain="runtime:start-request:v1",
    )


@dataclass(frozen=True, slots=True)
class TraceEvent:
    schema_version: int
    event_id: str
    run_id: str
    trace_id: str
    phase: RuntimePhase
    event_type: str
    occurred_at: datetime
    reason_codes: tuple[str, ...]
    attributes: Mapping[str, JsonValue] = field(default_factory=dict)
    sensitivity: Sensitivity = Sensitivity.PUBLIC

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_aware(self.occurred_at, "occurred_at")
        object.__setattr__(self, "attributes", freeze_json(dict(self.attributes)))


@dataclass(frozen=True, slots=True)
class RuntimeState:
    schema_version: int
    run_id: str
    phase: RuntimePhase
    message: MessageEnvelope
    actor: Actor
    received_at: datetime
    connector_revision: ComponentRevision
    invocation_options: RuntimeInvocationOptions
    start_digest: DigestString
    conversation_scope: ConversationScope
    budget: RuntimeBudget
    trace_context: TraceContext
    policy_snapshot_id: str
    negotiated_bindings: tuple[NegotiatedBindingReceipt, ...] = ()
    preprocess_result: PreprocessResult | None = None
    memory_retrieval: MemoryRetrievalResult | None = None
    context_build: ContextBuildResult | None = None
    perception: PerceptionResult | None = None
    social_decision: SocialDecision | None = None
    capability_retrieval: CapabilityRetrievalResult | None = None
    tool_plan: ToolPlan | None = None
    tool_observations: tuple[ToolObservation, ...] = ()
    tool_validation: ToolValidationResult | None = None
    draft_response: DraftResponse | None = None
    final_response: ValidatedFinalResponse | None = None
    pending_result: RuntimeResult | None = None
    delivery_request: DeliveryRequest | None = None
    delivery_receipt: DeliveryReceipt | None = None
    reconciliation_expires_at: datetime | None = None
    pending_delivery_candidates: tuple[MemoryCandidate, ...] = ()
    memory_candidates: tuple[MemoryCandidate, ...] = ()
    memory_submissions: tuple[MemorySubmissionReceipt, ...] = ()
    trace: tuple[TraceEvent, ...] = ()

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.run_id, "run_id")
        require_non_empty(str(self.start_digest), "start_digest")
        require_non_empty(self.policy_snapshot_id, "policy_snapshot_id")
        require_aware(self.received_at, "received_at")
        if not isinstance(self.phase, RuntimePhase):
            raise validation_error("invalid_runtime_phase")
        if self.actor.platform != self.message.platform:
            raise validation_error("runtime_actor_message_mismatch")
        if (
            self.actor.bot_id != self.message.bot_id
            or self.actor.user_id != self.message.user_id
        ):
            raise validation_error("runtime_actor_message_mismatch")
        if (
            self.conversation_scope.platform != self.message.platform
            or self.conversation_scope.bot_id != self.message.bot_id
            or self.conversation_scope.conversation_type
            is not self.message.conversation_type
            or self.conversation_scope.conversation_id != self.message.conversation_id
            or self.conversation_scope.group_id != self.message.group_id
        ):
            raise validation_error("runtime_scope_message_mismatch")
        if self.reconciliation_expires_at is not None:
            require_aware(
                self.reconciliation_expires_at,
                "reconciliation_expires_at",
            )
            if self.reconciliation_expires_at <= self.received_at:
                raise validation_error("invalid_reconciliation_expiry")
        for field_name in (
            "negotiated_bindings",
            "tool_observations",
            "pending_delivery_candidates",
            "memory_candidates",
            "memory_submissions",
            "trace",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


@dataclass(frozen=True, slots=True)
class TraceSummary:
    schema_version: int
    trace_id: str
    phases: tuple[RuntimePhase, ...]
    degraded_components: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.trace_id, "trace_id")
        object.__setattr__(self, "phases", tuple(self.phases))
        object.__setattr__(
            self,
            "degraded_components",
            tuple(self.degraded_components),
        )
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True, slots=True)
class CompletionReceipt:
    schema_version: int
    run_id: str
    final_phase: RuntimePhase
    delivery_status: DeliveryStatus
    completed_at: datetime
    memory_submissions: tuple[MemorySubmissionReceipt, ...] = ()

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.run_id, "run_id")
        if not isinstance(self.final_phase, RuntimePhase):
            raise validation_error("invalid_completion_phase")
        if not isinstance(self.delivery_status, DeliveryStatus):
            raise validation_error("invalid_completion_delivery_status")
        require_aware(self.completed_at, "completed_at")
        if self.final_phase not in {
            RuntimePhase.COMPLETED,
            RuntimePhase.DEFERRED,
            RuntimePhase.FAILED,
        }:
            raise validation_error("completion_is_not_terminal")
        if self.delivery_status is not DeliveryStatus.NOT_REQUIRED:
            raise validation_error("completion_requires_not_required_delivery")
        object.__setattr__(self, "memory_submissions", tuple(self.memory_submissions))


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    schema_version: int
    run_id: str
    outcome: Outcome
    final_response: ValidatedFinalResponse | None
    reaction: Reaction | None
    delivery_request: DeliveryRequest | None
    completion: CompletionReceipt | None
    reason_codes: tuple[str, ...]
    trace_summary: TraceSummary

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.outcome, Outcome):
            raise validation_error("invalid_runtime_outcome")
        require_non_empty(self.run_id, "run_id")
        visible = self.final_response is not None or self.reaction is not None
        if self.outcome is Outcome.NO_REPLY:
            if visible or self.delivery_request is not None or self.completion is None:
                raise validation_error("invalid_no_reply_result")
        elif self.outcome is Outcome.REACTION:
            if self.reaction is None or self.final_response is not None:
                raise validation_error("invalid_reaction_result")
        elif self.outcome is Outcome.RESPONSE:
            if self.final_response is None or self.reaction is not None:
                raise validation_error("invalid_response_result")
        elif self.outcome in {Outcome.DEFERRED, Outcome.FAILED}:
            if self.reaction is not None:
                raise validation_error("invalid_terminal_result")
            if self.final_response is None and self.completion is None:
                raise validation_error("invalid_terminal_result")
            if self.final_response is not None and self.completion is not None:
                raise validation_error("invalid_terminal_result")
        if visible:
            if self.delivery_request is None or self.completion is not None:
                raise validation_error("visible_result_requires_delivery")
        elif self.delivery_request is not None:
            raise validation_error("empty_result_cannot_request_delivery")
        if self.delivery_request is not None:
            if self.delivery_request.run_id != self.run_id:
                raise validation_error("delivery_run_mismatch")
            if self.delivery_request.outcome is not self.outcome:
                raise validation_error("delivery_outcome_mismatch")
            if self.final_response is not self.delivery_request.response:
                raise validation_error("delivery_response_mismatch")
            if self.reaction is not self.delivery_request.reaction:
                raise validation_error("delivery_reaction_mismatch")
        if self.completion is not None:
            if self.completion.run_id != self.run_id:
                raise validation_error("completion_run_mismatch")
            expected_phase = {
                Outcome.NO_REPLY: RuntimePhase.COMPLETED,
                Outcome.DEFERRED: RuntimePhase.DEFERRED,
                Outcome.FAILED: RuntimePhase.FAILED,
            }.get(self.outcome)
            if (
                expected_phase is None
                or self.completion.final_phase is not expected_phase
            ):
                raise validation_error("completion_outcome_mismatch")


_ALLOWED_TRANSITIONS: Mapping[RuntimePhase, frozenset[RuntimePhase]] = {
    RuntimePhase.RECEIVED: frozenset(
        {RuntimePhase.PREPROCESSED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.PREPROCESSED: frozenset(
        {RuntimePhase.CONTEXT_READY, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.CONTEXT_READY: frozenset(
        {RuntimePhase.PERCEIVED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.PERCEIVED: frozenset(
        {RuntimePhase.DECIDED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.DECIDED: frozenset(
        {
            RuntimePhase.TOOLS_PLANNED,
            RuntimePhase.COMPOSED,
            RuntimePhase.READY_TO_EMIT,
            RuntimePhase.MEMORY_EVALUATED,
            RuntimePhase.DEFERRED,
            RuntimePhase.FAILED,
        }
    ),
    RuntimePhase.TOOLS_PLANNED: frozenset(
        {RuntimePhase.TOOLS_EXECUTED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.TOOLS_EXECUTED: frozenset(
        {RuntimePhase.VALIDATED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.VALIDATED: frozenset(
        {RuntimePhase.COMPOSED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.COMPOSED: frozenset(
        {RuntimePhase.RENDERED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.RENDERED: frozenset(
        {RuntimePhase.READY_TO_EMIT, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.READY_TO_EMIT: frozenset(
        {RuntimePhase.DELIVERY_ACKNOWLEDGED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.DELIVERY_ACKNOWLEDGED: frozenset(
        {RuntimePhase.MEMORY_EVALUATED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.MEMORY_EVALUATED: frozenset(
        {RuntimePhase.COMPLETED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.COMPLETED: frozenset(),
    RuntimePhase.DEFERRED: frozenset(),
    RuntimePhase.FAILED: frozenset(),
}


def transition(
    state: RuntimeState, next_phase: RuntimePhase, **changes: object
) -> RuntimeState:
    if next_phase not in _ALLOWED_TRANSITIONS[state.phase]:
        raise validation_error(
            "invalid_runtime_transition", state.phase.value, next_phase.value
        )
    if "phase" in changes:
        raise validation_error("phase_cannot_be_overridden")
    return replace(state, phase=next_phase, **changes)


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
