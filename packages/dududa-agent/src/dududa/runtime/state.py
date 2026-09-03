from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TypeAlias

from dududa._compat import StrEnum
from dududa.capabilities.contracts import (
    CapabilityRetrievalResult,
    CapabilityRunReceipt,
    CapabilityRunRequest,
    CapabilityRunStatus,
    ToolObservation,
    ToolPlan,
    ToolValidationResult,
    UnobservedToolAttempt,
    ValidationAction,
)
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
from dududa.contracts.delivery import delivery_payload_digest, delivery_request_digest
from dududa.domain.content import DraftResponse, Reaction, ValidatedFinalResponse
from dududa.domain.delivery import (
    DeliveryReceipt,
    DeliveryRequest,
    DeliveryStatus,
    canonicalize_delivery_receipt,
    validate_delivery_receipt_against_request,
)
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import MessageDedupKey, MessageEnvelope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    JsonValue,
    Outcome,
    PrivacyLevel,
    ResourceUsage,
    RiskLevel,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
    freeze_json,
    require_aware,
    require_non_empty,
)
from dududa.domain.task import TaskComplexityAssessment
from dududa.errors import validation_error
from dududa.memory.models import (
    MemoryCandidate,
    MemoryRetrievalResult,
    MemorySubmissionReceipt,
)
from dududa.models.contracts import ModelRole, ModelTier, RouteDecision, RouteHint
from dududa.models.digests import (
    route_decision_digest,
    task_complexity_assessment_digest,
    tier_decision_digest,
)
from dududa.models.policy import TierDecision, TierSelectionContext
from dududa.models.tiering import validate_tier_decision
from dududa.perception.complexity import validate_task_complexity_assessment
from dududa.perception.contracts import (
    DecisionSignals,
    GroupInteractionMode,
    SocialAction,
    SocialDecision,
)
from dududa.perception.digests import (
    perception_context_digest,
    social_decision_digest,
)
from dududa.perception.social import validate_social_decision
from dududa.persona.contracts import (
    PersonaRendererMode,
    PersonaResolution,
)
from dududa.responses.budget import project_response_reservation
from dududa.responses.contracts import (
    ResponsePlan,
    ResponseProfileSelectionRequest,
)
from dududa.responses.digests import (
    detail_preference_evidence_digest,
    response_plan_digest,
    response_profile_preference_digest,
)
from dududa.runtime.authorization import (
    build_delivery_authorization_request,
    capability_plan_authorization_metadata,
    capability_plan_authorization_resource,
    response_authorization_metadata,
    response_authorization_resource,
)
from dududa.runtime.budget import (
    RuntimeModelBudgetPlan,
    RuntimeToolBudgetPlan,
    add_usage,
    charge_budget,
    ensure_budget_covers_plan,
    ensure_budget_covers_tool_plan,
    reservation_budget,
    usage_within_reservation,
    usage_within_tool_reservation,
    zero_usage_for_budget,
)
from dududa.runtime.capabilities import (
    project_capability_run_request,
    tool_context_privacy_level,
    tool_context_tokens_upper_bound,
    validated_tool_model_projection,
)
from dududa.runtime.contracts import (
    CurrentMessageContext,
    DirectChatExecutionReceipt,
    DirectChatFailureReceipt,
    OfflinePreprocessReceipt,
    OfflineRuntimePolicySnapshot,
    PerceptionExecutionReceipt,
    RuntimeAdmissionAction,
)
from dududa.runtime.selection import project_s10_decision_signals
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


PreprocessResult: TypeAlias = OfflinePreprocessReceipt
ContextBuildResult: TypeAlias = CurrentMessageContext


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
        require_non_empty(self.event_id, "trace_event_id")
        require_non_empty(self.run_id, "trace_run_id")
        require_non_empty(self.trace_id, "trace_id")
        if not isinstance(self.phase, RuntimePhase):
            raise validation_error("invalid_trace_phase")
        if self.event_type != "runtime.phase.entered":
            raise validation_error("invalid_trace_event_type")
        require_aware(self.occurred_at, "occurred_at")
        reasons = tuple(self.reason_codes)
        if reasons != tuple(sorted(set(reasons))) or any(
            not _safe_trace_code(item) for item in reasons
        ):
            raise validation_error("invalid_trace_reason_codes")
        attributes = dict(self.attributes)
        if (
            set(attributes) != {"sequence"}
            or type(attributes["sequence"]) is not int
            or attributes["sequence"] < 0
        ):
            raise validation_error("invalid_trace_attributes")
        if self.sensitivity is not Sensitivity.PUBLIC:
            raise validation_error("invalid_trace_sensitivity")
        expected_id = _runtime_trace_event_id(
            run_id=self.run_id,
            trace_id=self.trace_id,
            phase=self.phase,
            occurred_at=self.occurred_at,
            reason_codes=reasons,
            sequence=attributes["sequence"],
        )
        if self.event_id != expected_id:
            raise validation_error("runtime_trace_event_digest_mismatch")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "attributes", freeze_json(attributes))


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
    initial_budget: RuntimeBudget
    model_budget_plan: RuntimeModelBudgetPlan
    budget: RuntimeBudget
    charged_usage: ResourceUsage
    trace_context: TraceContext
    policy_snapshot_id: str
    runtime_policy: OfflineRuntimePolicySnapshot
    negotiated_bindings: tuple[NegotiatedBindingReceipt, ...] = ()
    tool_budget_plan: RuntimeToolBudgetPlan | None = None
    preprocess_result: PreprocessResult | None = None
    memory_retrieval: MemoryRetrievalResult | None = None
    current_context: ContextBuildResult | None = None
    response_authorization_request: AuthorizationRequest | None = None
    response_authorization: AuthorizationDecision | None = None
    perception_execution: PerceptionExecutionReceipt | None = None
    complexity_assessment: TaskComplexityAssessment | None = None
    complexity_source_digest: DigestString | None = None
    decision_signals: DecisionSignals | None = None
    social_decision: SocialDecision | None = None
    response_profile_request: ResponseProfileSelectionRequest | None = None
    response_plan: ResponsePlan | None = None
    persona_resolution: PersonaResolution | None = None
    tier_selection_context: TierSelectionContext | None = None
    tier_decision: TierDecision | None = None
    direct_route_decision: RouteDecision | None = None
    direct_chat_execution: DirectChatExecutionReceipt | None = None
    direct_chat_failure: DirectChatFailureReceipt | None = None
    capability_plan_authorization_request: AuthorizationRequest | None = None
    capability_plan_authorization: AuthorizationDecision | None = None
    capability_run_request: CapabilityRunRequest | None = None
    capability_retrieval: CapabilityRetrievalResult | None = None
    tool_plan: ToolPlan | None = None
    tool_observations: tuple[ToolObservation, ...] = ()
    tool_unobserved_attempts: tuple[UnobservedToolAttempt, ...] = ()
    tool_validation: ToolValidationResult | None = None
    capability_run_receipt: CapabilityRunReceipt | None = None
    capability_unverified_usage: ResourceUsage | None = None
    draft_response: DraftResponse | None = None
    final_response: ValidatedFinalResponse | None = None
    pending_result: RuntimeResult | None = None
    delivery_request: DeliveryRequest | None = None
    delivery_receipt: DeliveryReceipt | None = None
    reconciliation_expires_at: datetime | None = None
    pending_delivery_candidates: tuple[MemoryCandidate, ...] = ()
    memory_candidates: tuple[MemoryCandidate, ...] = ()
    memory_submissions: tuple[MemorySubmissionReceipt, ...] = ()
    completion: CompletionReceipt | None = None
    trace: tuple[TraceEvent, ...] = ()

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.run_id, "run_id")
        require_non_empty(str(self.start_digest), "start_digest")
        require_non_empty(self.policy_snapshot_id, "policy_snapshot_id")
        if not isinstance(self.runtime_policy, OfflineRuntimePolicySnapshot):
            raise validation_error("invalid_offline_runtime_policy_snapshot")
        if self.policy_snapshot_id != self.runtime_policy.snapshot_id:
            raise validation_error("runtime_policy_snapshot_id_mismatch")
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
        if not isinstance(self.initial_budget, RuntimeBudget):
            raise validation_error("invalid_initial_runtime_budget")
        if not isinstance(self.model_budget_plan, RuntimeModelBudgetPlan):
            raise validation_error("invalid_runtime_model_budget_plan")
        if not isinstance(self.budget, RuntimeBudget):
            raise validation_error("invalid_runtime_budget")
        if not isinstance(self.charged_usage, ResourceUsage):
            raise validation_error("invalid_runtime_charged_usage")
        if self.tool_budget_plan is not None and not isinstance(
            self.tool_budget_plan, RuntimeToolBudgetPlan
        ):
            raise validation_error("invalid_runtime_tool_budget_plan")
        connector_result = ConnectorResult(
            schema_version=1,
            message=self.message,
            actor=self.actor,
            received_at=self.received_at,
            adapter_revision=self.connector_revision,
        )
        if self.start_digest != runtime_start_digest(
            connector_result,
            self.invocation_options,
        ):
            raise validation_error("runtime_state_start_digest_mismatch")
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
            "tool_unobserved_attempts",
            "pending_delivery_candidates",
            "memory_candidates",
            "memory_submissions",
            "trace",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        validate_runtime_state(self)


def append_runtime_phase_trace(
    state: RuntimeState,
    phase: RuntimePhase,
    occurred_at: datetime,
    *,
    reason_codes: tuple[str, ...] = (),
) -> tuple[TraceEvent, ...]:
    """Append one content-free phase event to the immutable Runtime trace."""

    if not isinstance(state, RuntimeState) or not isinstance(phase, RuntimePhase):
        raise validation_error("invalid_runtime_trace_projection")
    require_aware(occurred_at, "runtime_trace_occurred_at")
    if state.trace and occurred_at < state.trace[-1].occurred_at:
        raise validation_error("runtime_trace_time_regression")
    normalized_reasons = tuple(sorted(set(reason_codes)))
    if any(not _safe_trace_code(item) for item in normalized_reasons):
        raise validation_error("invalid_trace_reason_codes")
    sequence = len(state.trace)
    return (
        *state.trace,
        TraceEvent(
            schema_version=1,
            event_id=_runtime_trace_event_id(
                run_id=state.run_id,
                trace_id=state.trace_context.trace_id,
                phase=phase,
                occurred_at=occurred_at,
                reason_codes=normalized_reasons,
                sequence=sequence,
            ),
            run_id=state.run_id,
            trace_id=state.trace_context.trace_id,
            phase=phase,
            event_type="runtime.phase.entered",
            occurred_at=occurred_at,
            reason_codes=normalized_reasons,
            attributes={"sequence": sequence},
            sensitivity=Sensitivity.PUBLIC,
        ),
    )


def _runtime_trace_event_id(
    *,
    run_id: str,
    trace_id: str,
    phase: RuntimePhase,
    occurred_at: datetime,
    reason_codes: tuple[str, ...],
    sequence: int,
) -> str:
    return str(
        canonical_digest(
            {
                "schema_version": 1,
                "run_id": run_id,
                "trace_id": trace_id,
                "phase": phase,
                "event_type": "runtime.phase.entered",
                "occurred_at": occurred_at,
                "reason_codes": reason_codes,
                "sequence": sequence,
            },
            domain="runtime:phase-trace-event:v1",
        )
    )


def _safe_trace_code(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value.isascii()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


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
class RuntimeSelectionSummary:
    schema_version: int
    selected_tier: ModelTier
    tier_decision_digest: DigestString
    route_decision_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.selected_tier, ModelTier):
            raise validation_error("invalid_runtime_selected_tier")
        require_non_empty(str(self.tier_decision_digest), "tier_decision_digest")
        require_non_empty(str(self.route_decision_digest), "route_decision_digest")


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
    selection_summary: RuntimeSelectionSummary | None = None

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
            if self.final_response != self.delivery_request.response:
                raise validation_error("delivery_response_mismatch")
            if self.reaction != self.delivery_request.reaction:
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
        if self.selection_summary is not None and not isinstance(
            self.selection_summary,
            RuntimeSelectionSummary,
        ):
            raise validation_error("invalid_runtime_selection_summary")


@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    schema_version: int
    state: RuntimeState
    revision: int
    expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.state, RuntimeState):
            raise validation_error("invalid_runtime_checkpoint_state")
        if type(self.revision) is not int or self.revision < 1:
            raise validation_error("invalid_runtime_checkpoint_revision")
        require_aware(self.expires_at, "runtime_checkpoint_expires_at")


class RuntimeCommitDisposition(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class RuntimeDedupRecord:
    schema_version: int
    message_dedup_key: MessageDedupKey
    run_id: str
    start_digest: DigestString
    last_revision: int
    outcome: Outcome | None
    expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.message_dedup_key, MessageDedupKey):
            raise validation_error("invalid_runtime_dedup_key")
        require_non_empty(self.run_id, "runtime_dedup_run_id")
        require_non_empty(str(self.start_digest), "runtime_dedup_start_digest")
        if type(self.last_revision) is not int or self.last_revision < 1:
            raise validation_error("invalid_runtime_dedup_revision")
        if self.outcome is not None and not isinstance(self.outcome, Outcome):
            raise validation_error("invalid_runtime_dedup_outcome")
        require_aware(self.expires_at, "runtime_dedup_expires_at")


@dataclass(frozen=True, slots=True)
class RuntimeCommitRequest:
    schema_version: int
    run_id: str
    message_dedup_key: MessageDedupKey
    expected_revision: int | None
    next_state: RuntimeState

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.run_id, "runtime_commit_run_id")
        if not isinstance(self.message_dedup_key, MessageDedupKey):
            raise validation_error("invalid_runtime_commit_dedup_key")
        if self.expected_revision is not None and (
            type(self.expected_revision) is not int or self.expected_revision < 1
        ):
            raise validation_error("invalid_runtime_expected_revision")
        if not isinstance(self.next_state, RuntimeState):
            raise validation_error("invalid_runtime_commit_state")
        if (
            self.next_state.run_id != self.run_id
            or self.next_state.message.dedup_key != self.message_dedup_key
        ):
            raise validation_error("runtime_commit_root_mismatch")


@dataclass(frozen=True, slots=True)
class RuntimeCommitResult:
    schema_version: int
    disposition: RuntimeCommitDisposition
    checkpoint: RuntimeCheckpoint | None
    dedup_record: RuntimeDedupRecord

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.disposition, RuntimeCommitDisposition):
            raise validation_error("invalid_runtime_commit_disposition")
        if not isinstance(self.dedup_record, RuntimeDedupRecord):
            raise validation_error("invalid_runtime_commit_dedup_record")
        if self.checkpoint is not None and not isinstance(
            self.checkpoint, RuntimeCheckpoint
        ):
            raise validation_error("invalid_runtime_commit_checkpoint")
        if (
            self.disposition is not RuntimeCommitDisposition.DUPLICATE
            and self.checkpoint is None
        ):
            raise validation_error("runtime_commit_missing_checkpoint")
        if self.checkpoint is not None and (
            self.checkpoint.state.run_id != self.dedup_record.run_id
            or self.checkpoint.revision != self.dedup_record.last_revision
        ):
            raise validation_error("runtime_commit_result_mismatch")


_IMMUTABLE_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "message",
        "actor",
        "received_at",
        "connector_revision",
        "invocation_options",
        "start_digest",
        "conversation_scope",
        "initial_budget",
        "model_budget_plan",
        "trace_context",
        "policy_snapshot_id",
        "runtime_policy",
        "negotiated_bindings",
        "tool_budget_plan",
    }
)

_IMMUTABLE_STAGE_FIELDS = frozenset(
    {
        "preprocess_result",
        "current_context",
        "response_authorization_request",
        "response_authorization",
        "perception_execution",
        "complexity_assessment",
        "complexity_source_digest",
        "decision_signals",
        "social_decision",
        "response_profile_request",
        "response_plan",
        "persona_resolution",
        "tier_selection_context",
        "tier_decision",
        "direct_route_decision",
        "direct_chat_execution",
        "direct_chat_failure",
        "capability_plan_authorization_request",
        "capability_plan_authorization",
        "capability_run_request",
        "capability_retrieval",
        "tool_plan",
        "tool_validation",
        "capability_run_receipt",
        "capability_unverified_usage",
        "draft_response",
        "final_response",
        "pending_result",
        "delivery_request",
    }
)

_TERMINAL_PHASES = frozenset(
    {RuntimePhase.COMPLETED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
)

_TOOL_PHASES = frozenset(
    {
        RuntimePhase.TOOLS_PLANNED,
        RuntimePhase.TOOLS_EXECUTED,
        RuntimePhase.VALIDATED,
    }
)

_PHASE_MAX_ARTIFACT_RANK: Mapping[RuntimePhase, int] = {
    RuntimePhase.RECEIVED: 0,
    RuntimePhase.PREPROCESSED: 1,
    RuntimePhase.CONTEXT_READY: 2,
    RuntimePhase.PERCEIVED: 3,
    RuntimePhase.DECIDED: 4,
    RuntimePhase.TOOLS_PLANNED: 5,
    RuntimePhase.TOOLS_EXECUTED: 6,
    RuntimePhase.VALIDATED: 7,
    RuntimePhase.COMPOSED: 8,
    RuntimePhase.RENDERED: 9,
    RuntimePhase.READY_TO_EMIT: 10,
    RuntimePhase.DELIVERY_ACKNOWLEDGED: 11,
    RuntimePhase.MEMORY_EVALUATED: 12,
}

_ARTIFACT_RANK: Mapping[str, int] = {
    "preprocess_result": 1,
    "current_context": 2,
    "response_authorization_request": 2,
    "response_authorization": 2,
    "perception_execution": 3,
    "complexity_assessment": 3,
    "complexity_source_digest": 3,
    "decision_signals": 4,
    "social_decision": 4,
    "response_profile_request": 4,
    "response_plan": 4,
    "persona_resolution": 4,
    "tier_selection_context": 4,
    "tier_decision": 4,
    "capability_plan_authorization_request": 4,
    "capability_plan_authorization": 4,
    "capability_run_request": 4,
    "capability_retrieval": 5,
    "tool_plan": 5,
    "tool_validation": 7,
    "capability_run_receipt": 7,
    "capability_unverified_usage": 4,
    "direct_route_decision": 8,
    "direct_chat_execution": 8,
    "direct_chat_failure": 8,
    "draft_response": 8,
    "final_response": 9,
    "pending_result": 10,
    "delivery_request": 10,
    "delivery_receipt": 11,
    "reconciliation_expires_at": 11,
    "completion": 13,
}


def validate_runtime_state(
    state: RuntimeState,
    *,
    previous: RuntimeState | None = None,
) -> RuntimeState:
    if not isinstance(state, RuntimeState):
        raise validation_error("invalid_runtime_state")
    ensure_budget_covers_plan(state.initial_budget, state.model_budget_plan)
    if state.tool_budget_plan is not None:
        ensure_budget_covers_tool_plan(
            state.initial_budget,
            state.model_budget_plan,
            state.tool_budget_plan,
        )
        if (
            state.runtime_policy.capability_maximum_attempts
            > state.tool_budget_plan.reservation.tool_steps
        ):
            raise validation_error("runtime_tool_attempt_budget_mismatch")
    _validate_budget_accounting(state)
    _validate_runtime_trace(state)
    _validate_disabled_fields(state)
    _validate_artifact_types_and_bindings(state)
    _validate_phase_payloads(state)
    if previous is not None:
        _validate_state_revision(previous, state)
    return state


def _validate_runtime_trace(state: RuntimeState) -> None:
    if not state.trace:
        return
    previous: TraceEvent | None = None
    for sequence, event in enumerate(state.trace):
        if not isinstance(event, TraceEvent):
            raise validation_error("invalid_runtime_trace_event")
        if (
            event.run_id != state.run_id
            or event.trace_id != state.trace_context.trace_id
            or event.attributes["sequence"] != sequence
        ):
            raise validation_error("runtime_trace_binding_mismatch")
        if previous is None:
            if event.phase is not RuntimePhase.RECEIVED:
                raise validation_error("runtime_trace_missing_received")
        else:
            if (
                event.phase not in _ALLOWED_TRANSITIONS[previous.phase]
                or event.occurred_at < previous.occurred_at
            ):
                raise validation_error("invalid_runtime_trace_transition")
        previous = event
    if state.trace[-1].phase is not state.phase:
        raise validation_error("runtime_trace_phase_mismatch")


def _validate_budget_accounting(state: RuntimeState) -> None:
    total_plan = add_usage(
        state.model_budget_plan.perception_reservation,
        state.model_budget_plan.direct_chat_reservation,
    )
    tool_usage = _runtime_tool_usage(state)
    if (
        tool_usage.model_calls != 0
        or tool_usage.input_tokens != 0
        or tool_usage.output_tokens != 0
    ):
        raise validation_error("runtime_tool_usage_has_model_charge")
    if state.tool_budget_plan is None:
        if tool_usage.tool_steps or tool_usage.retries:
            raise validation_error("runtime_tool_usage_without_budget_plan")
    elif not usage_within_tool_reservation(
        tool_usage,
        state.tool_budget_plan.reservation,
    ):
        raise validation_error("runtime_tool_usage_exceeds_reservation")
    model_usage = _expected_model_usage(state)
    if not _usage_covers(total_plan, model_usage):
        raise validation_error("runtime_charge_exceeds_model_budget_plan")
    if charge_budget(state.initial_budget, state.charged_usage) != state.budget:
        raise validation_error("runtime_budget_charge_mismatch")

    expected = add_usage(model_usage, tool_usage)
    if state.charged_usage != expected:
        raise validation_error("runtime_charge_evidence_mismatch")


def _expected_model_usage(state: RuntimeState) -> ResourceUsage:
    expected = zero_usage_for_budget(state.initial_budget)
    if (
        state.perception_execution is not None
        and state.perception_execution.model_call_started
    ):
        expected = state.model_budget_plan.perception_reservation
    if (
        state.direct_route_decision is not None and state.direct_route_decision.attempts
    ) or (
        state.direct_chat_failure is not None
        and state.direct_chat_failure.model_call_started
    ):
        expected = add_usage(
            expected,
            _runtime_direct_chat_reservation(state),
        )
    return expected


def _runtime_direct_chat_reservation(state: RuntimeState) -> ResourceUsage:
    base = state.model_budget_plan.direct_chat_reservation
    if state.response_plan is None:
        return base
    return project_response_reservation(base, state.response_plan)


def _runtime_tool_usage(state: RuntimeState) -> ResourceUsage:
    if state.capability_unverified_usage is not None:
        return state.capability_unverified_usage
    if state.capability_run_receipt is not None:
        return state.capability_run_receipt.usage
    usage = zero_usage_for_budget(
        reservation_budget(state.tool_budget_plan.reservation)
        if state.tool_budget_plan is not None
        else state.initial_budget
    )
    for observation in state.tool_observations:
        usage = add_usage(usage, observation.usage)
    for attempt in state.tool_unobserved_attempts:
        usage = add_usage(usage, attempt.usage)
    return usage


def _validate_disabled_fields(state: RuntimeState) -> None:
    response_profiles_enabled = state.invocation_options.feature_flags.get(
        "response_profiles", False
    )
    if not response_profiles_enabled and (
        state.response_profile_request is not None or state.response_plan is not None
    ):
        raise validation_error("response_profile_state_without_feature")
    tools_enabled = state.invocation_options.feature_flags.get("tools", False)
    tool_artifacts = (
        state.capability_plan_authorization_request,
        state.capability_plan_authorization,
        state.capability_run_request,
        state.capability_retrieval,
        state.tool_plan,
        state.tool_validation,
        state.capability_run_receipt,
        state.capability_unverified_usage,
    )
    if not tools_enabled:
        if state.phase in _TOOL_PHASES:
            raise validation_error("s10_tool_phase_forbidden")
        if (
            state.tool_budget_plan is not None
            or any(item is not None for item in tool_artifacts)
            or state.tool_observations
            or state.tool_unobserved_attempts
        ):
            raise validation_error("s10_memory_or_tool_state_forbidden")
    if (
        state.memory_retrieval is not None
        or state.pending_delivery_candidates
        or state.memory_candidates
        or state.memory_submissions
    ):
        raise validation_error("s10_memory_or_tool_state_forbidden")


def _validate_artifact_types_and_bindings(state: RuntimeState) -> None:
    preprocess = state.preprocess_result
    context = state.current_context
    response_authorization_request = state.response_authorization_request
    response_authorization = state.response_authorization
    perception_execution = state.perception_execution
    assessment = state.complexity_assessment
    decision_signals = state.decision_signals
    social = state.social_decision
    response_profile_request = state.response_profile_request
    response_plan = state.response_plan
    persona_resolution = state.persona_resolution
    tier_context = state.tier_selection_context
    tier = state.tier_decision
    direct_route = state.direct_route_decision
    direct = state.direct_chat_execution
    direct_failure = state.direct_chat_failure
    capability_plan_authorization_request = state.capability_plan_authorization_request
    capability_plan_authorization = state.capability_plan_authorization
    capability_run_request = state.capability_run_request
    capability_retrieval = state.capability_retrieval
    tool_plan = state.tool_plan
    tool_validation = state.tool_validation
    capability_run_receipt = state.capability_run_receipt
    capability_unverified_usage = state.capability_unverified_usage

    _optional_instance(preprocess, OfflinePreprocessReceipt, "preprocess_result")
    _optional_instance(context, CurrentMessageContext, "current_context")
    _optional_instance(
        response_authorization_request,
        AuthorizationRequest,
        "response_authorization_request",
    )
    _optional_instance(
        response_authorization,
        AuthorizationDecision,
        "response_authorization",
    )
    _optional_instance(
        perception_execution,
        PerceptionExecutionReceipt,
        "perception_execution",
    )
    _optional_instance(assessment, TaskComplexityAssessment, "complexity_assessment")
    _optional_instance(decision_signals, DecisionSignals, "decision_signals")
    _optional_instance(social, SocialDecision, "social_decision")
    _optional_instance(
        response_profile_request,
        ResponseProfileSelectionRequest,
        "response_profile_request",
    )
    _optional_instance(response_plan, ResponsePlan, "response_plan")
    _optional_instance(
        persona_resolution,
        PersonaResolution,
        "persona_resolution",
    )
    _optional_instance(tier_context, TierSelectionContext, "tier_selection_context")
    _optional_instance(tier, TierDecision, "tier_decision")
    _optional_instance(direct_route, RouteDecision, "direct_route_decision")
    _optional_instance(direct, DirectChatExecutionReceipt, "direct_chat_execution")
    _optional_instance(
        direct_failure,
        DirectChatFailureReceipt,
        "direct_chat_failure",
    )
    _optional_instance(
        capability_plan_authorization_request,
        AuthorizationRequest,
        "capability_plan_authorization_request",
    )
    _optional_instance(
        capability_plan_authorization,
        AuthorizationDecision,
        "capability_plan_authorization",
    )
    _optional_instance(
        capability_run_request,
        CapabilityRunRequest,
        "capability_run_request",
    )
    _optional_instance(
        capability_retrieval,
        CapabilityRetrievalResult,
        "capability_retrieval",
    )
    _optional_instance(tool_plan, ToolPlan, "tool_plan")
    if any(not isinstance(item, ToolObservation) for item in state.tool_observations):
        raise validation_error("invalid_runtime_artifact", "tool_observations")
    if any(
        not isinstance(item, UnobservedToolAttempt)
        for item in state.tool_unobserved_attempts
    ):
        raise validation_error("invalid_runtime_artifact", "tool_unobserved_attempts")
    _optional_instance(tool_validation, ToolValidationResult, "tool_validation")
    _optional_instance(
        capability_run_receipt,
        CapabilityRunReceipt,
        "capability_run_receipt",
    )
    _optional_instance(
        capability_unverified_usage,
        ResourceUsage,
        "capability_unverified_usage",
    )
    _optional_instance(state.draft_response, DraftResponse, "draft_response")
    _optional_instance(
        state.final_response,
        ValidatedFinalResponse,
        "final_response",
    )
    _optional_instance(state.pending_result, RuntimeResult, "pending_result")
    _optional_instance(state.delivery_request, DeliveryRequest, "delivery_request")
    _optional_instance(state.delivery_receipt, DeliveryReceipt, "delivery_receipt")
    _optional_instance(state.completion, CompletionReceipt, "completion")

    _validate_response_profile_bindings(state)

    if preprocess is not None:
        _validate_preprocess_binding(preprocess, state)

    if context is not None:
        if (
            preprocess is None
            or preprocess.action is not RuntimeAdmissionAction.PROCEED
        ):
            raise validation_error("runtime_context_without_admission")
        reference = context.current_message_reference
        if (
            reference.platform != state.message.platform
            or reference.bot_id != state.message.bot_id
            or reference.conversation_id != state.message.conversation_id
            or reference.message_id != state.message.message_id
        ):
            raise validation_error("runtime_context_message_mismatch")
        if context.perception.scope_digest != scope_digest(state.conversation_scope):
            raise validation_error("runtime_context_scope_mismatch")
        perception_context = context.perception
        if (
            perception_context.conversation_type is not state.message.conversation_type
            or perception_context.data_classification
            is not preprocess.data_classification
            or len(perception_context.messages) != 1
        ):
            raise validation_error("runtime_context_projection_mismatch")
        current_message = perception_context.messages[0]
        if (
            current_message.message_ref != perception_context.current_message_ref
            or current_message.author_identity_ref
            != context.current_author_identity_ref
            or current_message.text != state.message.text
            or current_message.reply_to_message_ref is not None
            or current_message.is_bot_authored
        ):
            raise validation_error("runtime_context_message_projection_mismatch")
        author = context.resolve(context.current_author_identity_ref)
        if author.actor_ref.opaque_actor_id != state.actor.user_id:
            raise validation_error("runtime_context_actor_mismatch")
        actual_mentions = {
            (
                state.message.bot_id
                if identity_ref == perception_context.bot_identity_ref
                else context.resolve(identity_ref).actor_ref.opaque_actor_id
            )
            for identity_ref in current_message.mentioned_identity_refs
        }
        expected_mentions = {mention.user_id for mention in state.message.mentions}
        if actual_mentions != expected_mentions:
            raise validation_error("runtime_context_mention_projection_mismatch")

    if (response_authorization_request is None) != (response_authorization is None):
        raise validation_error("incomplete_response_authorization_evidence")
    if (
        response_authorization_request is not None
        and response_authorization is not None
    ):
        if context is None:
            raise validation_error("response_authorization_without_context")
        if (
            response_authorization_request.resource
            != response_authorization_resource(state.conversation_scope)
            or response_authorization_request.metadata
            != response_authorization_metadata(
                policy_snapshot_id=state.policy_snapshot_id,
            )
            or response_authorization_request.capability_id is not None
            or response_authorization_request.risk_level is not RiskLevel.LOW
        ):
            raise validation_error("runtime_response_authorization_scope_mismatch")
        _validate_authorization_evidence(
            response_authorization_request,
            response_authorization,
            state,
            action="message.respond",
            require_allow=False,
        )

    _validate_capability_artifact_bindings(state)

    if perception_execution is not None:
        if context is None:
            raise validation_error("perception_execution_without_context")
        if perception_execution.result.context_digest != perception_context_digest(
            context.perception
        ):
            raise validation_error("runtime_perception_context_mismatch")
        route = perception_execution.route_decision
        if route is not None and (
            route.role is not ModelRole.PERCEPTION
            or route.requested_tier is not ModelTier.HAIKU
            or (
                route.selected_tier is not None
                and route.selected_tier is not ModelTier.HAIKU
            )
        ):
            raise validation_error("runtime_perception_bootstrap_tier_mismatch")
        if not usage_within_reservation(
            perception_execution.reported_usage,
            state.model_budget_plan.perception_reservation,
        ):
            raise validation_error("perception_usage_exceeds_runtime_reservation")

    if assessment is not None:
        if perception_execution is None or context is None:
            raise validation_error("complexity_assessment_without_perception")
        if state.complexity_source_digest != perception_execution.result_digest:
            raise validation_error("complexity_source_digest_mismatch")
        result = perception_execution.result
        validate_task_complexity_assessment(
            assessment,
            context.perception,
            result,
            state.runtime_policy.complexity_assessor,
        )
        allowed_evidence = {item.message_ref for item in context.perception.messages}
        if not set(assessment.evidence_refs) <= allowed_evidence:
            raise validation_error("complexity_evidence_outside_context")
    elif state.complexity_source_digest is not None:
        raise validation_error("complexity_source_without_assessment")

    if decision_signals is not None:
        if (
            perception_execution is None
            or context is None
            or preprocess is None
            or response_authorization is None
        ):
            raise validation_error("decision_signals_without_inputs")
        result = perception_execution.result
        known_target = bool(result.target_identity_refs)
        for identity_ref in result.target_identity_refs:
            context.resolve(identity_ref)
        expected_signals = project_s10_decision_signals(
            authorization=response_authorization,
            duplicate_or_self_message=state.actor.user_id == state.message.bot_id,
            explicit_interaction=preprocess.explicit_interaction,
            conversation_type=state.message.conversation_type,
            data_classification=preprocess.data_classification,
            group_mode=(
                GroupInteractionMode.ACTIVE
                if state.invocation_options.feature_flags.get(
                    "proactive_group_participation",
                    False,
                )
                else state.runtime_policy.group_mode
            ),
            known_target=known_target,
            tool_authorization=capability_plan_authorization,
            tools_enabled=state.invocation_options.feature_flags.get("tools", False),
        )
        if decision_signals != expected_signals:
            raise validation_error("runtime_decision_signals_mismatch")

    if social is not None:
        if perception_execution is None or context is None:
            raise validation_error("social_decision_without_perception")
        if decision_signals is None:
            raise validation_error("social_decision_without_signals")
        if social.perception_result_digest != perception_execution.result_digest:
            raise validation_error("social_perception_digest_mismatch")
        for identity_ref in social.target_identity_refs:
            context.resolve(identity_ref)
        if social.action is SocialAction.REACT:
            raise validation_error("s10_social_action_out_of_scope")
        validate_social_decision(
            social,
            perception_execution.result,
            decision_signals,
            state.runtime_policy.social_decision,
        )
        if (
            response_authorization is not None
            and not response_authorization.decided_at
            <= social.decided_at
            < response_authorization.expires_at
        ):
            raise validation_error("social_decision_outside_authorization_window")
        if social.action in {
            SocialAction.DIRECT_REPLY,
            SocialAction.ASK_CLARIFICATION,
            SocialAction.USE_TOOLS,
        } and (
            response_authorization is None
            or response_authorization.effect is not AuthorizationEffect.ALLOW
        ):
            raise validation_error("visible_social_action_not_authorized")
        if social.action is SocialAction.USE_TOOLS and (
            capability_plan_authorization is None
            or capability_plan_authorization.effect is not AuthorizationEffect.ALLOW
            or not capability_plan_authorization.decided_at
            <= social.decided_at
            < capability_plan_authorization.expires_at
        ):
            raise validation_error("tool_social_action_not_currently_authorized")

    if (tier_context is None) != (tier is None):
        raise validation_error("incomplete_runtime_tier_selection")
    if tier_context is not None and tier is not None:
        if social is None or social.action not in {
            SocialAction.DIRECT_REPLY,
            SocialAction.USE_TOOLS,
        }:
            raise validation_error("tier_selection_without_direct_reply")
        if assessment is None or context is None:
            raise validation_error("tier_selection_without_assessment")
        expected_content_tokens = context.perception.content_input_tokens_upper_bound
        if social.action is SocialAction.USE_TOOLS:
            if (
                capability_run_receipt is None
                or capability_run_receipt.status is not CapabilityRunStatus.COMPLETED
            ):
                raise validation_error("tool_tier_without_completed_capability_run")
            expected_content_tokens += tool_context_tokens_upper_bound(
                capability_run_receipt
            )
        if (
            tier_context.role is not ModelRole.DIRECT_CHAT
            or tier_context.assessment != assessment
            or tier_context.content_input_tokens_upper_bound != expected_content_tokens
            or tier_context.data_classification
            is not (
                tool_context_privacy_level(
                    capability_run_receipt,
                    context.perception.data_classification,
                )
                if social.action is SocialAction.USE_TOOLS
                else context.perception.data_classification
            )
            or tier_context.budget
            != reservation_budget(_runtime_direct_chat_reservation(state))
        ):
            raise validation_error("tier_selection_context_mismatch")
        validate_tier_decision(
            tier,
            tier_context,
            state.runtime_policy.direct_chat_tier,
        )
        if social is not None and tier.decided_at < social.decided_at:
            raise validation_error("tier_decision_precedes_social_decision")

    if direct_route is not None:
        if tier is None:
            raise validation_error("direct_route_without_tier_decision")
        if (
            direct_route.role is not ModelRole.DIRECT_CHAT
            or direct_route.requested_tier is not tier.selected_tier
            or direct_route.tier_authority_digest != tier_decision_digest(tier)
            or direct_route.tier_selection_fingerprint != tier.selection_fingerprint
        ):
            raise validation_error("direct_route_tier_binding_mismatch")

    if direct is not None:
        if direct_failure is not None:
            raise validation_error("direct_chat_has_success_and_failure")
        if direct_route is None or direct.route_decision != direct_route:
            raise validation_error("direct_execution_route_mismatch")
        direct_reservation = _runtime_direct_chat_reservation(state)
        if direct.charged_usage != direct_reservation:
            raise validation_error("direct_chat_charge_mismatch")
        if not usage_within_reservation(
            direct.reported_usage,
            direct_reservation,
        ):
            raise validation_error("direct_chat_usage_exceeds_runtime_reservation")
        if context is None or set(direct.content.source_refs) != set(
            _expected_direct_source_refs(state)
        ):
            raise validation_error("direct_chat_source_outside_context")

    if direct_failure is not None:
        if direct is not None:
            raise validation_error("direct_chat_has_success_and_failure")
        if direct_failure.route_decision != direct_route:
            raise validation_error("direct_failure_route_mismatch")
        direct_reservation = _runtime_direct_chat_reservation(state)
        if direct_failure.charged_usage != direct_reservation:
            raise validation_error("direct_chat_failure_charge_mismatch")
        if not usage_within_reservation(
            direct_failure.reported_usage,
            direct_reservation,
        ):
            raise validation_error("direct_chat_failure_usage_exceeds_reservation")

    _validate_response_and_delivery_bindings(state)


def _validate_response_profile_bindings(state: RuntimeState) -> None:
    enabled = state.invocation_options.feature_flags.get("response_profiles", False)
    request = state.response_profile_request
    plan = state.response_plan
    persona_resolution = state.persona_resolution
    social = state.social_decision
    assessment = state.complexity_assessment
    context = state.current_context
    if persona_resolution is not None:
        _validate_runtime_persona_resolution(state, persona_resolution)
    if not enabled:
        return
    evidence = (request, plan)
    if any(item is None for item in evidence) and any(
        item is not None for item in evidence
    ):
        raise validation_error("incomplete_runtime_response_profile_evidence")
    if social is None:
        if request is not None:
            raise validation_error("response_profile_before_social_decision")
        return
    visible_action = social.action in {
        SocialAction.DIRECT_REPLY,
        SocialAction.USE_TOOLS,
        SocialAction.ASK_CLARIFICATION,
    }
    tool_response_ready = (
        social.action is SocialAction.USE_TOOLS
        and state.capability_run_receipt is not None
        and state.capability_run_receipt.status is CapabilityRunStatus.COMPLETED
        and state.tier_decision is not None
    )
    evidence_required = (
        social.action
        in {
            SocialAction.DIRECT_REPLY,
            SocialAction.ASK_CLARIFICATION,
        }
        or tool_response_ready
    )
    if not visible_action:
        if request is not None:
            raise validation_error("response_profile_for_non_visible_action")
        return
    if not evidence_required:
        if request is not None:
            raise validation_error("tool_response_profile_before_validation")
        return
    if (
        request is None
        or plan is None
        or persona_resolution is None
        or assessment is None
        or context is None
    ):
        raise validation_error("runtime_response_profile_evidence_missing")
    if (
        request.actor_digest != actor_digest(state.actor)
        or request.scope_digest != scope_digest(state.conversation_scope)
        or request.persona_id != state.conversation_scope.persona_id
        or request.conversation_type is not state.conversation_scope.conversation_type
        or request.current_message_ref != context.perception.current_message_ref
        or request.detail_evidence.message_ref != context.perception.current_message_ref
        or request.complexity_level is not assessment.level
        or request.reasoning_depth is not assessment.reasoning_depth
        or request.expected_tool_steps != assessment.expected_tool_steps
        or request.verification_required is not assessment.verification_required
        or request.social_action is not social.action
        or request.assessment_digest != task_complexity_assessment_digest(assessment)
        or request.social_decision_digest != social_decision_digest(social)
    ):
        raise validation_error("runtime_response_profile_request_mismatch")
    preference = request.persistent_preference
    if preference is not None and (
        preference.actor_digest != request.actor_digest
        or preference.scope_digest != request.scope_digest
        or preference.persona_id != request.persona_id
    ):
        raise validation_error("runtime_response_preference_scope_mismatch")
    expected_preference_digest = (
        response_profile_preference_digest(preference)
        if preference is not None
        else None
    )
    if (
        plan.assessment_digest != request.assessment_digest
        or plan.social_decision_digest != request.social_decision_digest
        or plan.detail_evidence_digest
        != detail_preference_evidence_digest(request.detail_evidence)
        or plan.persistent_preference_digest != expected_preference_digest
        or plan.generated_token_limit
        > state.model_budget_plan.direct_chat_reservation.output_tokens
        or plan.decided_at < social.decided_at
    ):
        raise validation_error("runtime_response_plan_binding_mismatch")
    if (
        social.response_constraints.max_characters is not None
        and plan.visible_character_limit > social.response_constraints.max_characters
    ):
        raise validation_error("runtime_response_plan_exceeds_social_limit")


def _validate_runtime_persona_resolution(
    state: RuntimeState,
    resolution: PersonaResolution,
) -> None:
    expected_id = state.conversation_scope.persona_id
    if resolution.requested_persona_id != expected_id:
        raise validation_error("runtime_persona_resolution_scope_mismatch")
    if resolution.fallback_used:
        valid = (
            resolution.definition.persona_id == "neutral"
            and resolution.reason_code == "neutral_persona_fallback"
        )
    else:
        valid = (
            resolution.definition.persona_id == expected_id
            and (
                resolution.requested_version is None
                or resolution.definition.version == resolution.requested_version
            )
            and resolution.reason_code == "requested_persona_resolved"
        )
    if not valid:
        raise validation_error("runtime_persona_resolution_semantics_mismatch")
    if resolution.definition.renderer_mode is not PersonaRendererMode.DETERMINISTIC:
        raise validation_error("runtime_persona_renderer_mode_unsupported")


def _validate_capability_artifact_bindings(state: RuntimeState) -> None:
    request = state.capability_run_request
    authorization_request = state.capability_plan_authorization_request
    authorization = state.capability_plan_authorization
    evidence = (request, authorization_request, authorization)
    if any(item is not None for item in evidence) and not all(
        item is not None for item in evidence
    ):
        raise validation_error("incomplete_capability_plan_authorization_evidence")

    if request is None:
        if (
            state.capability_retrieval is not None
            or state.tool_plan is not None
            or state.tool_observations
            or state.tool_unobserved_attempts
            or state.tool_validation is not None
            or state.capability_run_receipt is not None
            or state.capability_unverified_usage is not None
        ):
            raise validation_error("runtime_tool_artifact_without_run_request")
        return

    assert authorization_request is not None
    assert authorization is not None
    if state.current_context is None or state.perception_execution is None:
        raise validation_error("runtime_capability_request_without_perception")
    expected_request = project_capability_run_request(
        state.current_context,
        state.perception_execution.result,
        state.actor,
        state.conversation_scope,
        available_input_schemas=state.runtime_policy.capability_input_schemas,
        maximum_attempts=state.runtime_policy.capability_maximum_attempts,
    )
    if request != expected_request:
        raise validation_error("runtime_capability_request_projection_mismatch")
    if (
        authorization_request.resource
        != capability_plan_authorization_resource(
            state.conversation_scope,
            run_id=state.run_id,
        )
        or authorization_request.metadata
        != capability_plan_authorization_metadata(
            policy_snapshot_id=state.policy_snapshot_id,
            query_digest=str(request.query.query_digest),
        )
        or authorization_request.capability_id is not None
        or authorization_request.risk_level is not RiskLevel.LOW
    ):
        raise validation_error("runtime_capability_plan_authorization_scope_mismatch")
    _validate_authorization_evidence(
        authorization_request,
        authorization,
        state,
        action="capability.plan",
        require_allow=False,
    )

    retrieval = state.capability_retrieval
    plan = state.tool_plan
    observations = state.tool_observations
    unobserved_attempts = state.tool_unobserved_attempts
    validation = state.tool_validation
    receipt = state.capability_run_receipt
    unverified_usage = state.capability_unverified_usage
    if any(
        (
            retrieval is not None,
            plan is not None,
            bool(observations),
            bool(unobserved_attempts),
            validation is not None,
            receipt is not None,
            unverified_usage is not None,
        )
    ) and (
        state.social_decision is None
        or state.social_decision.action is not SocialAction.USE_TOOLS
        or authorization.effect is not AuthorizationEffect.ALLOW
    ):
        raise validation_error("runtime_tool_execution_without_plan_authorization")
    if unverified_usage is not None and (
        state.phase is not RuntimePhase.FAILED
        or state.tool_budget_plan is None
        or unverified_usage != state.tool_budget_plan.reservation
        or retrieval is not None
        or plan is not None
        or observations
        or unobserved_attempts
        or validation is not None
        or receipt is not None
    ):
        raise validation_error("invalid_runtime_capability_unverified_usage")
    if retrieval is not None and (
        retrieval.query_digest != request.query.query_digest
        or retrieval.policy_revision != state.policy_snapshot_id
    ):
        raise validation_error("runtime_capability_retrieval_binding_mismatch")
    if plan is not None and (
        retrieval is None or plan.retrieval_result_digest != retrieval.result_digest
    ):
        raise validation_error("runtime_tool_plan_retrieval_mismatch")
    if observations or unobserved_attempts:
        if plan is None or retrieval is None:
            raise validation_error("runtime_tool_observation_without_plan")
        step_by_id = {item.step_id: item for item in plan.steps}
        invocation_ids: set[str] = set()
        attempts = (*observations, *unobserved_attempts)
        if len(attempts) > request.maximum_attempts:
            raise validation_error("runtime_tool_attempt_limit_exceeded")
        for attempt in attempts:
            step = step_by_id.get(attempt.step_id)
            if (
                step is None
                or attempt.invocation_id in invocation_ids
                or attempt.plan_id != plan.plan_id
                or attempt.plan_digest != plan.plan_digest
                or attempt.logical_operation_id != step.logical_operation_id
                or attempt.capability_id != step.capability_id
                or attempt.definition_digest != step.definition_digest
                or attempt.catalog_snapshot_id != retrieval.catalog_snapshot_id
                or attempt.catalog_digest != retrieval.catalog_digest
                or attempt.policy_revision != retrieval.policy_revision
            ):
                raise validation_error("runtime_tool_observation_binding_mismatch")
            invocation_ids.add(attempt.invocation_id)
        attempts_by_step: dict[str, list[int]] = {}
        for attempt in attempts:
            attempts_by_step.setdefault(attempt.step_id, []).append(attempt.attempt)
        if any(
            sorted(values) != list(range(1, max(values) + 1))
            for values in attempts_by_step.values()
        ):
            raise validation_error("runtime_tool_attempt_sequence_invalid")
    if validation is not None and receipt is None:
        raise validation_error("runtime_tool_validation_without_receipt")
    if receipt is not None:
        if (
            receipt.run_id != state.run_id
            or receipt.request != request
            or receipt.request_digest != request.request_digest
            or receipt.retrieval != retrieval
            or receipt.plan != plan
            or receipt.observations != observations
            or receipt.unobserved_attempts != unobserved_attempts
            or receipt.validation != validation
        ):
            raise validation_error("runtime_capability_receipt_binding_mismatch")
        if receipt.status is CapabilityRunStatus.COMPLETED and (
            validation is None
            or validation.action is not ValidationAction.FINISH
            or not validation.accepted_observations
        ):
            raise validation_error("runtime_completed_capability_not_validated")


def _expected_direct_source_refs(state: RuntimeState) -> tuple[str, ...]:
    context = state.current_context
    social = state.social_decision
    if context is None or social is None:
        raise validation_error("runtime_direct_source_without_context")
    source_refs = {context.perception.current_message_ref}
    if social.action is SocialAction.USE_TOOLS:
        receipt = state.capability_run_receipt
        if receipt is None:
            raise validation_error("runtime_direct_source_without_capability_receipt")
        _, tool_sources, _ = validated_tool_model_projection(
            receipt,
            maximum_bytes=1_048_576,
        )
        source_refs.update(tool_sources)
    return tuple(sorted(source_refs))


def _validate_response_and_delivery_bindings(state: RuntimeState) -> None:
    social = state.social_decision
    context = state.current_context
    tier = state.tier_decision
    direct_route = state.direct_route_decision
    draft = state.draft_response
    final = state.final_response
    request = state.delivery_request
    receipt = state.delivery_receipt
    response_plan = state.response_plan
    persona_resolution = state.persona_resolution
    expected_plan_digest = (
        response_plan_digest(response_plan) if response_plan is not None else None
    )

    if state.direct_chat_execution is not None and (
        state.direct_chat_execution.content.response_plan_digest != expected_plan_digest
    ):
        raise validation_error("runtime_direct_response_plan_mismatch")
    if state.direct_chat_failure is not None and (
        state.direct_chat_failure.response_plan_digest != expected_plan_digest
    ):
        raise validation_error("runtime_direct_failure_plan_mismatch")

    if draft is not None:
        if (
            social is None
            or context is None
            or social.action
            not in {
                SocialAction.DIRECT_REPLY,
                SocialAction.ASK_CLARIFICATION,
                SocialAction.USE_TOOLS,
            }
        ):
            raise validation_error("draft_without_visible_social_decision")
        expected_targets = tuple(
            context.resolve(identity_ref)
            for identity_ref in social.target_identity_refs
        )
        if (
            draft.target_users != expected_targets
            or draft.immutable_constraints != social.response_constraints
        ):
            raise validation_error("draft_social_binding_mismatch")
        if draft.response_plan_digest != expected_plan_digest:
            raise validation_error("runtime_draft_response_plan_mismatch")
        if social.action is SocialAction.USE_TOOLS and _is_capability_failure_response(
            state
        ):
            if (
                draft.intent != "capability_unavailable"
                or draft.refusal is None
                or draft.refusal.reason_code != "capability_unavailable"
                or len(draft.content_blocks) != 1
                or draft.content_blocks[0].source_refs
                != (context.perception.current_message_ref,)
            ):
                raise validation_error("runtime_capability_failure_draft_mismatch")
        elif social.action in {SocialAction.DIRECT_REPLY, SocialAction.USE_TOOLS}:
            direct = state.direct_chat_execution
            if direct is None or len(draft.content_blocks) != 1:
                raise validation_error("direct_draft_content_missing")
            block = draft.content_blocks[0]
            if (
                block.content != direct.content.text
                or block.source_refs != direct.content.source_refs
                or tuple(sorted(block.source_refs))
                != _expected_direct_source_refs(state)
            ):
                raise validation_error("direct_draft_content_mismatch")

    if final is not None:
        if draft is None:
            raise validation_error("final_response_without_draft")
        actual_draft_digest = canonical_digest(draft, domain="response:draft:v1")
        if final.render_validation.draft_digest != actual_draft_digest:
            raise validation_error("runtime_final_draft_digest_mismatch")
        if final.response.render_metadata.response_plan_digest != expected_plan_digest:
            raise validation_error("runtime_final_response_plan_mismatch")
        if _rendered_persona_binding(final) != _persona_resolution_binding(
            persona_resolution
        ):
            raise validation_error("runtime_final_persona_resolution_mismatch")
        profile_validation = final.profile_validation
        if response_plan is None:
            if profile_validation is not None:
                raise validation_error("legacy_final_has_profile_validation")
        elif (
            profile_validation is None
            or not profile_validation.valid
            or profile_validation.response_plan_digest != expected_plan_digest
            or profile_validation.selected_profile
            != response_plan.selected_profile.value
        ):
            raise validation_error("runtime_profile_validation_mismatch")
        protected_fields = (
            "fact_anchors",
            "citations",
            "uncertainty",
            "warnings",
            "refusal",
            "immutable_constraints",
            "target_users",
            "attachments",
        )
        if any(
            getattr(final.response, field_name) != getattr(draft, field_name)
            for field_name in protected_fields
        ):
            raise validation_error("runtime_final_draft_binding_mismatch")
        if final.content_safety.actor_digest != actor_digest(
            state.actor
        ) or final.content_safety.scope_digest != scope_digest(
            state.conversation_scope
        ):
            raise validation_error("runtime_final_safety_identity_mismatch")

    if request is not None:
        if final is None or request.response != final or request.reaction is not None:
            raise validation_error("runtime_delivery_payload_mismatch")
        if request.run_id != state.run_id or request.scope != state.conversation_scope:
            raise validation_error("runtime_delivery_root_mismatch")
        if request.payload_digest != delivery_payload_digest(
            final
        ) or request.request_digest != delivery_request_digest(request):
            raise validation_error("runtime_delivery_digest_mismatch")
        if response_plan is not None and (
            len(request.part_intents) > response_plan.delivery_part_limit
        ):
            raise validation_error("runtime_delivery_part_limit_exceeded")
        expected_authorization_request = build_delivery_authorization_request(
            state.actor,
            request,
            policy_snapshot_id=state.policy_snapshot_id,
        )
        _validate_authorization_evidence(
            expected_authorization_request,
            request.authorization,
            state,
            action="message.send",
            require_allow=True,
        )
        if request.adapter_binding not in state.negotiated_bindings:
            raise validation_error("runtime_delivery_binding_not_negotiated")

    if receipt is not None:
        if request is None:
            raise validation_error("delivery_receipt_without_request")
        validate_delivery_receipt_against_request(request, receipt)
        if receipt != canonicalize_delivery_receipt(request, receipt):
            raise validation_error("noncanonical_runtime_delivery_receipt")
        expected_expiry = (
            receipt.acknowledged_at + request.constraints.reconciliation_window
        )
        if state.reconciliation_expires_at != expected_expiry:
            raise validation_error("delivery_reconciliation_expiry_mismatch")
    elif state.reconciliation_expires_at is not None:
        raise validation_error("reconciliation_expiry_without_receipt")

    result = state.pending_result
    if result is not None:
        if (
            result.run_id != state.run_id
            or result.trace_summary.trace_id != state.trace_context.trace_id
        ):
            raise validation_error("runtime_result_root_mismatch")
        if request is not None and (
            result.delivery_request != request
            or result.final_response != final
            or result.outcome is not request.outcome
        ):
            raise validation_error("runtime_result_delivery_mismatch")
        if request is not None and tier is not None and direct_route is not None:
            expected_selection = RuntimeSelectionSummary(
                schema_version=1,
                selected_tier=tier.selected_tier,
                tier_decision_digest=tier_decision_digest(tier),
                route_decision_digest=route_decision_digest(direct_route),
            )
            if result.selection_summary != expected_selection:
                raise validation_error("runtime_result_selection_summary_mismatch")
        elif result.selection_summary is not None:
            raise validation_error("runtime_result_selection_without_route")

    completion = state.completion
    if completion is not None:
        if (
            completion.run_id != state.run_id
            or completion.final_phase is not state.phase
        ):
            raise validation_error("runtime_completion_root_mismatch")
        if completion.memory_submissions != state.memory_submissions:
            raise validation_error("runtime_completion_memory_mismatch")
        if receipt is None:
            if completion.delivery_status is not DeliveryStatus.NOT_REQUIRED:
                raise validation_error("completion_requires_delivery_receipt")
        elif completion.delivery_status is not receipt.status:
            raise validation_error("completion_delivery_status_mismatch")


def _validate_phase_payloads(state: RuntimeState) -> None:
    if state.phase not in _TERMINAL_PHASES:
        maximum = _PHASE_MAX_ARTIFACT_RANK[state.phase]
        for field_name, rank in _ARTIFACT_RANK.items():
            value = getattr(state, field_name)
            present = value is not None
            if present and rank > maximum:
                raise validation_error("runtime_artifact_before_phase", field_name)
        if (state.tool_observations or state.tool_unobserved_attempts) and maximum < 6:
            raise validation_error("runtime_artifact_before_phase", "tool_observations")

    if state.phase is RuntimePhase.RECEIVED:
        return
    if state.phase in _TERMINAL_PHASES:
        _validate_terminal_phase(state)
        return
    if state.preprocess_result is None:
        raise validation_error("runtime_phase_missing_preprocess")
    if state.phase is RuntimePhase.PREPROCESSED:
        return
    if state.phase is RuntimePhase.MEMORY_EVALUATED:
        _validate_memory_evaluated_path(state)
        return

    _require_context_prefix(state)
    if state.phase is RuntimePhase.CONTEXT_READY:
        return
    _require_perceived_prefix(state)
    if state.phase is RuntimePhase.PERCEIVED:
        return
    _require_decided_prefix(state)
    if state.phase is RuntimePhase.DECIDED:
        return
    if state.phase is RuntimePhase.TOOLS_PLANNED:
        _require_tool_planned_prefix(state)
        return
    if state.phase is RuntimePhase.TOOLS_EXECUTED:
        _require_tool_executed_prefix(state)
        return
    if state.phase is RuntimePhase.VALIDATED:
        if _is_capability_failure_response(state):
            _require_failed_tool_prefix(state)
        else:
            _require_validated_tool_prefix(state)
        return
    _require_composed_prefix(state)
    if state.phase is RuntimePhase.COMPOSED:
        return
    if state.final_response is None:
        raise validation_error("runtime_phase_missing_final_response")
    if state.phase is RuntimePhase.RENDERED:
        return
    if state.delivery_request is None or state.pending_result is None:
        raise validation_error("runtime_phase_missing_delivery_request")
    if state.phase is RuntimePhase.READY_TO_EMIT:
        return
    if state.delivery_receipt is None or state.reconciliation_expires_at is None:
        raise validation_error("runtime_phase_missing_delivery_receipt")


def _require_context_prefix(state: RuntimeState) -> None:
    if (
        state.preprocess_result is None
        or state.preprocess_result.action is not RuntimeAdmissionAction.PROCEED
        or state.current_context is None
        or state.response_authorization_request is None
        or state.response_authorization is None
    ):
        raise validation_error("runtime_phase_missing_context")


def _require_perceived_prefix(state: RuntimeState) -> None:
    if (
        state.perception_execution is None
        or state.complexity_assessment is None
        or state.complexity_source_digest is None
    ):
        raise validation_error("runtime_phase_missing_perception")


def _require_decided_prefix(state: RuntimeState) -> None:
    social = state.social_decision
    if social is None:
        raise validation_error("runtime_phase_missing_social_decision")
    if social.action is SocialAction.DIRECT_REPLY:
        if state.tier_selection_context is None or state.tier_decision is None:
            raise validation_error("runtime_phase_missing_tier_decision")
    elif social.action is SocialAction.USE_TOOLS:
        if (state.tier_selection_context is None) is not (state.tier_decision is None):
            raise validation_error("incomplete_tool_tier_selection")
    elif state.tier_selection_context is not None or state.tier_decision is not None:
        raise validation_error("non_direct_decision_has_tier_selection")


def _require_tool_planned_prefix(state: RuntimeState) -> None:
    social = state.social_decision
    authorization = state.capability_plan_authorization
    if (
        social is None
        or social.action is not SocialAction.USE_TOOLS
        or authorization is None
        or authorization.effect is not AuthorizationEffect.ALLOW
        or state.capability_run_request is None
        or state.capability_retrieval is None
        or state.tool_plan is None
    ):
        raise validation_error("runtime_phase_missing_tool_plan")
    if state.tier_decision is not None or state.tier_selection_context is not None:
        raise validation_error("runtime_tool_tier_selected_before_validation")


def _require_tool_executed_prefix(state: RuntimeState) -> None:
    _require_tool_planned_prefix(state)
    if not state.tool_observations and not state.tool_unobserved_attempts:
        raise validation_error("runtime_phase_missing_tool_observation")
    if state.tool_validation is not None or state.capability_run_receipt is not None:
        raise validation_error("runtime_tool_validation_before_phase")


def _require_validated_tool_prefix(state: RuntimeState) -> None:
    social = state.social_decision
    receipt = state.capability_run_receipt
    if (
        social is None
        or social.action is not SocialAction.USE_TOOLS
        or state.capability_run_request is None
        or state.capability_retrieval is None
        or state.tool_plan is None
        or not state.tool_observations
        or state.tool_unobserved_attempts
        or state.tool_validation is None
        or receipt is None
        or receipt.status is not CapabilityRunStatus.COMPLETED
        or state.tier_selection_context is None
        or state.tier_decision is None
    ):
        raise validation_error("runtime_phase_missing_validated_tool_result")


def _is_capability_failure_response(state: RuntimeState) -> bool:
    """Return whether the state carries a verified, user-visible tool failure."""

    social = state.social_decision
    receipt = state.capability_run_receipt
    return (
        social is not None
        and social.action is SocialAction.USE_TOOLS
        and receipt is not None
        and receipt.status
        in {CapabilityRunStatus.DEFERRED, CapabilityRunStatus.FAILED}
    )


def _require_failed_tool_prefix(state: RuntimeState) -> None:
    """Validate the prefix used by a deterministic Capability failure reply."""

    _require_context_prefix(state)
    _require_perceived_prefix(state)
    _require_decided_prefix(state)
    social = state.social_decision
    receipt = state.capability_run_receipt
    if (
        social is None
        or social.action is not SocialAction.USE_TOOLS
        or state.capability_run_request is None
        or receipt is None
        or receipt.status
        not in {CapabilityRunStatus.DEFERRED, CapabilityRunStatus.FAILED}
    ):
        raise validation_error("runtime_phase_missing_failed_tool_result")
    # A failed Capability must never acquire a model route or execution receipt.
    if any(
        value is not None
        for value in (
            state.tier_selection_context,
            state.tier_decision,
            state.direct_route_decision,
            state.direct_chat_execution,
            state.direct_chat_failure,
        )
    ):
        raise validation_error("runtime_failed_tool_has_model_execution")


def _require_composed_prefix(state: RuntimeState) -> None:
    social = state.social_decision
    if social is None or state.draft_response is None:
        raise validation_error("runtime_phase_missing_draft")
    if social.action is SocialAction.DIRECT_REPLY:
        if state.direct_route_decision is None or state.direct_chat_execution is None:
            raise validation_error("runtime_phase_missing_direct_chat")
    elif social.action is SocialAction.USE_TOOLS:
        if _is_capability_failure_response(state):
            _require_failed_tool_prefix(state)
            return
        _require_validated_tool_prefix(state)
        if state.direct_route_decision is None or state.direct_chat_execution is None:
            raise validation_error("runtime_phase_missing_direct_chat")
    elif social.action is SocialAction.ASK_CLARIFICATION:
        if (
            state.direct_route_decision is not None
            or state.direct_chat_execution is not None
        ):
            raise validation_error("clarification_used_direct_chat")
    else:
        raise validation_error("non_visible_decision_cannot_compose")


def _validate_memory_evaluated_path(state: RuntimeState) -> None:
    if state.current_context is None:
        if (
            state.preprocess_result is None
            or state.preprocess_result.action is not RuntimeAdmissionAction.IGNORE
        ):
            raise validation_error("invalid_admission_ignore_path")
        _forbid_after_preprocess(state)
        return
    _require_context_prefix(state)
    _require_perceived_prefix(state)
    _require_decided_prefix(state)
    if state.delivery_request is None:
        if (
            state.social_decision is None
            or state.social_decision.action is not SocialAction.IGNORE
        ):
            raise validation_error("invalid_social_ignore_path")
        _forbid_visible_output(state)
        return
    _require_composed_prefix(state)
    if (
        state.final_response is None
        or state.pending_result is None
        or state.delivery_receipt is None
    ):
        raise validation_error("invalid_delivery_completion_path")


def _validate_terminal_phase(state: RuntimeState) -> None:
    completion = state.completion
    result = state.pending_result
    if completion is None or result is None:
        raise validation_error("terminal_runtime_missing_result")
    if state.phase is RuntimePhase.COMPLETED:
        if state.delivery_request is None:
            if (
                result.outcome is not Outcome.NO_REPLY
                or result.completion != completion
            ):
                raise validation_error("invalid_completed_no_reply_result")
            if state.current_context is None:
                if (
                    state.preprocess_result is None
                    or state.preprocess_result.action
                    is not RuntimeAdmissionAction.IGNORE
                ):
                    raise validation_error("invalid_completed_admission_ignore")
                _forbid_after_preprocess(state)
            else:
                _require_context_prefix(state)
                _require_perceived_prefix(state)
                _require_decided_prefix(state)
                if (
                    state.social_decision is None
                    or state.social_decision.action is not SocialAction.IGNORE
                ):
                    raise validation_error("invalid_completed_social_ignore")
                _forbid_visible_output(state)
        else:
            _require_context_prefix(state)
            _require_perceived_prefix(state)
            _require_decided_prefix(state)
            _require_composed_prefix(state)
            if (
                state.final_response is None
                or state.delivery_receipt is None
                or result.delivery_request != state.delivery_request
                or result.completion is not None
            ):
                raise validation_error("invalid_completed_delivery_result")
        return

    if state.delivery_request is not None or state.delivery_receipt is not None:
        raise validation_error("early_terminal_state_has_delivery")
    if (
        state.social_decision is not None
        and state.social_decision.action is SocialAction.USE_TOOLS
    ):
        _validate_tool_terminal_path(state)
    expected_outcome = (
        Outcome.DEFERRED if state.phase is RuntimePhase.DEFERRED else Outcome.FAILED
    )
    if result.outcome is not expected_outcome or result.completion != completion:
        raise validation_error("terminal_runtime_result_mismatch")
    if completion.delivery_status is not DeliveryStatus.NOT_REQUIRED:
        raise validation_error("early_terminal_delivery_status_mismatch")


def _validate_tool_terminal_path(state: RuntimeState) -> None:
    _require_context_prefix(state)
    _require_perceived_prefix(state)
    _require_decided_prefix(state)
    receipt = state.capability_run_receipt
    if receipt is None:
        _forbid_visible_output(state)
        return
    if receipt.status is not CapabilityRunStatus.COMPLETED:
        _forbid_visible_output(state)
        return
    _require_validated_tool_prefix(state)


def _persona_resolution_binding(
    resolution: PersonaResolution | None,
) -> tuple[object, ...] | None:
    if resolution is None:
        return None
    return (
        resolution.definition.persona_id,
        resolution.definition.version,
        resolution.definition.source_digest,
        resolution.catalog_digest,
        resolution.snapshot_id,
        resolution.fallback_used,
        resolution.definition.renderer_mode.value,
        resolution.requested_persona_id,
        resolution.requested_version,
        resolution.reason_code,
    )


def _rendered_persona_binding(
    final: ValidatedFinalResponse,
) -> tuple[object, ...] | None:
    metadata = final.response.render_metadata
    if metadata.persona_source_digest is None:
        return None
    return (
        metadata.persona_id,
        metadata.persona_version,
        metadata.persona_source_digest,
        metadata.persona_catalog_digest,
        metadata.persona_catalog_snapshot_id,
        metadata.persona_fallback_used,
        metadata.persona_render_mode,
        metadata.requested_persona_id,
        metadata.requested_persona_version,
        metadata.persona_resolution_reason,
    )


def _forbid_after_preprocess(state: RuntimeState) -> None:
    for field_name in (
        "current_context",
        "response_authorization_request",
        "response_authorization",
        "perception_execution",
        "complexity_assessment",
        "complexity_source_digest",
        "decision_signals",
        "social_decision",
        "response_profile_request",
        "response_plan",
        "persona_resolution",
        "tier_selection_context",
        "tier_decision",
        "direct_route_decision",
        "direct_chat_execution",
        "direct_chat_failure",
        "draft_response",
        "final_response",
        "delivery_request",
        "delivery_receipt",
        "reconciliation_expires_at",
    ):
        if getattr(state, field_name) is not None:
            raise validation_error("admission_ignore_has_later_artifact", field_name)


def _forbid_visible_output(state: RuntimeState) -> None:
    for field_name in (
        "response_profile_request",
        "response_plan",
        "persona_resolution",
        "direct_route_decision",
        "direct_chat_execution",
        "direct_chat_failure",
        "draft_response",
        "final_response",
        "delivery_request",
        "delivery_receipt",
        "reconciliation_expires_at",
    ):
        if getattr(state, field_name) is not None:
            raise validation_error("ignore_path_has_visible_output", field_name)


def _validate_state_revision(previous: RuntimeState, current: RuntimeState) -> None:
    if not isinstance(previous, RuntimeState):
        raise validation_error("invalid_previous_runtime_state")
    for field_name in _IMMUTABLE_ROOT_FIELDS:
        if getattr(previous, field_name) != getattr(current, field_name):
            raise validation_error("runtime_root_changed", field_name)
    if previous.phase != current.phase:
        if current.phase not in _ALLOWED_TRANSITIONS[previous.phase]:
            raise validation_error(
                "invalid_runtime_transition",
                previous.phase.value,
                current.phase.value,
            )
    elif previous.phase is not RuntimePhase.COMPLETED:
        raise validation_error("runtime_phase_revision_forbidden")
    else:
        _validate_completed_revision(previous, current)
    for field_name in _IMMUTABLE_STAGE_FIELDS:
        old = getattr(previous, field_name)
        if old is not None and getattr(current, field_name) != old:
            raise validation_error("runtime_artifact_changed", field_name)
    if previous.tool_observations and (
        current.tool_observations != previous.tool_observations
    ):
        raise validation_error("runtime_artifact_changed", "tool_observations")
    if previous.tool_unobserved_attempts and (
        current.tool_unobserved_attempts != previous.tool_unobserved_attempts
    ):
        raise validation_error("runtime_artifact_changed", "tool_unobserved_attempts")
    if current.trace[: len(previous.trace)] != previous.trace:
        raise validation_error("runtime_trace_not_append_only")
    _validate_budget_monotonic(previous, current)


def _validate_completed_revision(
    previous: RuntimeState,
    current: RuntimeState,
) -> None:
    allowed_changes = {"delivery_receipt", "completion", "trace"}
    for field_name in previous.__dataclass_fields__:
        if field_name not in allowed_changes and getattr(
            previous, field_name
        ) != getattr(current, field_name):
            raise validation_error("completed_runtime_field_changed", field_name)
    if (
        previous.delivery_request is None
        or previous.delivery_receipt is None
        or previous.completion is None
        or current.delivery_receipt is None
        or current.completion is None
    ):
        raise validation_error("completed_runtime_not_reconcilable")
    if (
        current.delivery_receipt.acknowledged_at
        != previous.delivery_receipt.acknowledged_at
        or current.completion.completed_at != previous.completion.completed_at
    ):
        raise validation_error("completed_runtime_timestamp_changed")
    previous_parts = {part.part_id: part for part in previous.delivery_receipt.parts}
    current_parts = {part.part_id: part for part in current.delivery_receipt.parts}
    rank = {
        "unknown": 0,
        "failed": 1,
        "succeeded": 2,
    }
    for part_id, old in previous_parts.items():
        new = current_parts.get(part_id)
        if (
            new is None
            or new.content_digest != old.content_digest
            or rank[new.status.value] < rank[old.status.value]
            or (
                old.platform_message_ref is not None
                and new.platform_message_ref is not None
                and old.platform_message_ref != new.platform_message_ref
            )
        ):
            raise validation_error("completed_delivery_evidence_regressed", part_id)


def _validate_budget_monotonic(previous: RuntimeState, current: RuntimeState) -> None:
    previous_budget = previous.budget
    current_budget = current.budget
    for field_name in (
        "model_calls_remaining",
        "tool_steps_remaining",
        "retries_remaining",
        "input_tokens_remaining",
        "output_tokens_remaining",
    ):
        if getattr(current_budget, field_name) > getattr(previous_budget, field_name):
            raise validation_error("runtime_budget_increased", field_name)
    if (
        previous_budget.cost_units_remaining is None
        or current_budget.cost_units_remaining is None
    ):
        if previous_budget.cost_units_remaining != current_budget.cost_units_remaining:
            raise validation_error("runtime_budget_cost_mode_changed")
    elif current_budget.cost_units_remaining > previous_budget.cost_units_remaining:
        raise validation_error("runtime_budget_increased", "cost_units_remaining")
    if not _usage_covers(current.charged_usage, previous.charged_usage):
        raise validation_error("runtime_charged_usage_decreased")


def _validate_preprocess_binding(
    receipt: OfflinePreprocessReceipt,
    state: RuntimeState,
) -> None:
    if receipt.message_digest != canonical_digest(
        state.message, domain="runtime:admission-message:v1"
    ) or receipt.actor_digest != actor_digest(state.actor):
        raise validation_error("runtime_preprocess_input_mismatch")
    if receipt.data_classification is PrivacyLevel.RESTRICTED:
        raise validation_error("runtime_restricted_input_forbidden")
    explicit = state.message.conversation_type is ConversationType.PRIVATE or any(
        mention.platform == state.message.platform
        and mention.user_id == state.message.bot_id
        for mention in state.message.mentions
    )
    proactive = state.invocation_options.feature_flags.get(
        "proactive_group_participation",
        False,
    )
    if state.actor.user_id == state.message.bot_id:
        expected_action = RuntimeAdmissionAction.IGNORE
        expected_reasons = ("self_message",)
    elif state.message.attachments:
        expected_action = RuntimeAdmissionAction.DEFER
        expected_reasons = ("attachments_disabled",)
    elif not state.message.text.strip():
        expected_action = RuntimeAdmissionAction.IGNORE
        expected_reasons = ("empty_text_message",)
    elif state.message.conversation_type is ConversationType.CHANNEL:
        expected_action = RuntimeAdmissionAction.IGNORE
        expected_reasons = ("channel_out_of_scope",)
    elif (
        state.message.conversation_type is ConversationType.GROUP
        and not explicit
        and not proactive
    ):
        expected_action = RuntimeAdmissionAction.IGNORE
        expected_reasons = ("group_explicit_mention_required",)
    else:
        expected_action = RuntimeAdmissionAction.PROCEED
        expected_reasons = (
            ("proactive_group_text_admitted",)
            if proactive and not explicit
            else ("s10_text_admitted",)
        )
    if (
        receipt.explicit_interaction is not explicit
        or receipt.action is not expected_action
        or receipt.reason_codes != expected_reasons
    ):
        raise validation_error("runtime_preprocess_decision_mismatch")


def _validate_authorization(
    decision: AuthorizationDecision,
    state: RuntimeState,
    *,
    action: str,
    require_allow: bool,
) -> None:
    if (
        str(decision.action) != action
        or decision.actor_digest != actor_digest(state.actor)
        or decision.scope_digest != scope_digest(state.conversation_scope)
    ):
        raise validation_error("runtime_authorization_binding_mismatch", action)
    if require_allow and decision.effect is not AuthorizationEffect.ALLOW:
        raise validation_error("runtime_authorization_not_allowed", action)


def _validate_authorization_evidence(
    request: AuthorizationRequest,
    decision: AuthorizationDecision,
    state: RuntimeState,
    *,
    action: str,
    require_allow: bool,
) -> None:
    if (
        request.actor != state.actor
        or request.conversation_scope != state.conversation_scope
        or str(request.action) != action
        or request.request_digest != authorization_request_digest(request)
    ):
        raise validation_error("runtime_authorization_request_mismatch", action)
    if (
        decision.request_digest != request.request_digest
        or decision.actor_digest != actor_digest(request.actor)
        or decision.scope_digest != scope_digest(request.conversation_scope)
        or decision.action != request.action
        or decision.resource_digest != resource_digest(request.resource)
        or decision.capability_id != request.capability_id
        or decision.risk_level is not request.risk_level
        or decision.metadata_digest != authorization_metadata_digest(request.metadata)
        or decision.policy_revision
        != state.runtime_policy.authorization_policy_revision
        or decision.decided_at < state.received_at
    ):
        raise validation_error("runtime_authorization_decision_mismatch", action)
    _validate_authorization(
        decision,
        state,
        action=action,
        require_allow=require_allow,
    )


def _usage_covers(limit: ResourceUsage, value: ResourceUsage) -> bool:
    if any(
        getattr(value, field_name) > getattr(limit, field_name)
        for field_name in (
            "model_calls",
            "tool_steps",
            "retries",
            "input_tokens",
            "output_tokens",
        )
    ):
        return False
    if limit.cost_units is None or value.cost_units is None:
        return limit.cost_units is value.cost_units
    return value.cost_units <= limit.cost_units


def _optional_instance(value: object, expected: type[object], field_name: str) -> None:
    if value is not None and not isinstance(value, expected):
        raise validation_error("invalid_runtime_artifact", field_name)


_ALLOWED_TRANSITIONS: Mapping[RuntimePhase, frozenset[RuntimePhase]] = {
    RuntimePhase.RECEIVED: frozenset(
        {RuntimePhase.PREPROCESSED, RuntimePhase.DEFERRED, RuntimePhase.FAILED}
    ),
    RuntimePhase.PREPROCESSED: frozenset(
        {
            RuntimePhase.CONTEXT_READY,
            RuntimePhase.MEMORY_EVALUATED,
            RuntimePhase.DEFERRED,
            RuntimePhase.FAILED,
        }
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
            RuntimePhase.VALIDATED,
            RuntimePhase.COMPOSED,
            RuntimePhase.READY_TO_EMIT,
            RuntimePhase.MEMORY_EVALUATED,
            RuntimePhase.DEFERRED,
            RuntimePhase.FAILED,
        }
    ),
    RuntimePhase.TOOLS_PLANNED: frozenset(
        {
            RuntimePhase.TOOLS_EXECUTED,
            RuntimePhase.VALIDATED,
            RuntimePhase.DEFERRED,
            RuntimePhase.FAILED,
        }
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
    state: RuntimeState,
    next_phase: RuntimePhase,
    *,
    occurred_at: datetime | None = None,
    trace_reason_codes: tuple[str, ...] = (),
    **changes: object,
) -> RuntimeState:
    if next_phase not in _ALLOWED_TRANSITIONS[state.phase]:
        raise validation_error(
            "invalid_runtime_transition", state.phase.value, next_phase.value
        )
    if "phase" in changes:
        raise validation_error("phase_cannot_be_overridden")
    if occurred_at is None and trace_reason_codes:
        raise validation_error("trace_reason_without_timestamp")
    if occurred_at is not None:
        if "trace" in changes:
            raise validation_error("runtime_trace_cannot_be_overridden")
        changes["trace"] = append_runtime_phase_trace(
            state,
            next_phase,
            occurred_at,
            reason_codes=trace_reason_codes,
        )
    forbidden = set(changes) & _IMMUTABLE_ROOT_FIELDS
    if forbidden:
        raise validation_error("runtime_root_cannot_change", *sorted(forbidden))
    updated = replace(state, phase=next_phase, **changes)
    validate_runtime_state(updated, previous=state)
    return updated


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
