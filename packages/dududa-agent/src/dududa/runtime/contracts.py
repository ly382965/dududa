from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.delivery import DeliveryStatus
from dududa.domain.identity import ResolvedIdentityRef
from dududa.domain.message import MessageReference
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    Outcome,
    PrivacyLevel,
    ResourceUsage,
    SchemaRef,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.models.contracts import ModelRole, ModelTier, ModelUsage, RouteDecision
from dududa.models.digests import route_decision_digest
from dududa.models.policy import TierPolicyDefinition
from dududa.perception.complexity import ComplexityAssessorConfig
from dududa.perception.contracts import (
    GroupInteractionMode,
    PerceptionContext,
    PerceptionModelStatus,
    PerceptionResult,
)
from dududa.perception.digests import perception_result_digest
from dududa.perception.social import SocialDecisionConfig


class RuntimeAdmissionAction(StrEnum):
    PROCEED = "proceed"
    IGNORE = "ignore"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class OfflineRuntimePolicySnapshot:
    schema_version: int
    snapshot_id: str
    authorization_policy_revision: str
    group_mode: GroupInteractionMode
    complexity_assessor: ComplexityAssessorConfig
    social_decision: SocialDecisionConfig
    direct_chat_tier: TierPolicyDefinition
    capability_input_schemas: tuple[SchemaRef, ...] = ()
    capability_maximum_attempts: int = 4

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.snapshot_id, "runtime_policy_snapshot_id")
        require_non_empty(
            self.authorization_policy_revision,
            "runtime_authorization_policy_revision",
        )
        if not isinstance(self.group_mode, GroupInteractionMode):
            raise validation_error("invalid_runtime_group_mode")
        if not isinstance(self.complexity_assessor, ComplexityAssessorConfig):
            raise validation_error("invalid_runtime_complexity_policy")
        if not isinstance(self.social_decision, SocialDecisionConfig):
            raise validation_error("invalid_runtime_social_policy")
        if not isinstance(self.direct_chat_tier, TierPolicyDefinition):
            raise validation_error("invalid_runtime_tier_policy")
        if self.direct_chat_tier.role is not ModelRole.DIRECT_CHAT:
            raise validation_error("runtime_tier_policy_role_mismatch")
        schemas = tuple(self.capability_input_schemas)
        if len(schemas) > 64 or any(
            not isinstance(item, SchemaRef) for item in schemas
        ):
            raise validation_error("invalid_runtime_capability_input_schemas")
        schema_keys = tuple(
            (item.schema_id, item.schema_version, item.digest) for item in schemas
        )
        if len(schema_keys) != len(set(schema_keys)):
            raise validation_error("duplicate_runtime_capability_input_schema")
        if (
            type(self.capability_maximum_attempts) is not int
            or not 1 <= self.capability_maximum_attempts <= 8
        ):
            raise validation_error("invalid_runtime_capability_attempt_limit")
        object.__setattr__(self, "capability_input_schemas", schemas)
        generated_high_codes = {
            code.value for code in self.complexity_assessor.high_signal_codes
        }
        if (
            not self.direct_chat_tier.high_complexity_reason_codes
            <= generated_high_codes
        ):
            raise validation_error("runtime_tier_policy_uses_unproducible_signal")


@dataclass(frozen=True, slots=True)
class OfflinePreprocessReceipt:
    schema_version: int
    message_digest: DigestString
    actor_digest: DigestString
    action: RuntimeAdmissionAction
    data_classification: PrivacyLevel
    explicit_interaction: bool
    reason_codes: tuple[str, ...]
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.message_digest), "preprocess_message_digest")
        require_non_empty(str(self.actor_digest), "preprocess_actor_digest")
        if not isinstance(self.action, RuntimeAdmissionAction):
            raise validation_error("invalid_runtime_admission_action")
        if not isinstance(self.data_classification, PrivacyLevel):
            raise validation_error("invalid_runtime_data_classification")
        if type(self.explicit_interaction) is not bool:
            raise validation_error("invalid_explicit_interaction_flag")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_preprocess_revision")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes, "preprocess_reason_codes", required=True
            ),
        )


@dataclass(frozen=True, slots=True)
class RuntimeIdentityBinding:
    schema_version: int
    identity_ref: str
    resolved: ResolvedIdentityRef

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.identity_ref, "runtime_identity_ref")
        if not isinstance(self.resolved, ResolvedIdentityRef):
            raise validation_error("invalid_resolved_identity")
        if self.resolved.identity_ref != self.identity_ref:
            raise validation_error("runtime_identity_binding_mismatch")


@dataclass(frozen=True, slots=True)
class CurrentMessageContext:
    schema_version: int
    perception: PerceptionContext
    identity_bindings: tuple[RuntimeIdentityBinding, ...]
    current_author_identity_ref: str
    current_message_reference: MessageReference
    builder_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.perception, PerceptionContext):
            raise validation_error("invalid_current_message_perception")
        if not isinstance(self.current_message_reference, MessageReference):
            raise validation_error("invalid_current_message_reference")
        if not isinstance(self.builder_revision, ComponentRevision):
            raise validation_error("invalid_context_builder_revision")
        require_non_empty(
            self.current_author_identity_ref,
            "current_author_identity_ref",
        )
        bindings = tuple(self.identity_bindings)
        if not bindings or not all(
            isinstance(binding, RuntimeIdentityBinding) for binding in bindings
        ):
            raise validation_error("invalid_runtime_identity_bindings")
        references = tuple(binding.identity_ref for binding in bindings)
        if len(references) != len(set(references)):
            raise validation_error("duplicate_runtime_identity_binding")
        known = {identity.identity_ref for identity in self.perception.identities}
        if not set(references) <= known:
            raise validation_error("runtime_identity_not_in_perception_context")
        if self.perception.bot_identity_ref in references:
            raise validation_error("runtime_bot_identity_cannot_be_delivery_target")
        if self.current_author_identity_ref not in references:
            raise validation_error("unknown_current_author_identity")
        scope = self.current_message_reference
        for binding in bindings:
            actor_ref = binding.resolved.actor_ref
            if actor_ref.platform != scope.platform or actor_ref.bot_id != scope.bot_id:
                raise validation_error("runtime_identity_scope_mismatch")
        object.__setattr__(
            self,
            "identity_bindings",
            tuple(sorted(bindings, key=lambda item: item.identity_ref)),
        )

    def resolve(self, identity_ref: str) -> ResolvedIdentityRef:
        for binding in self.identity_bindings:
            if binding.identity_ref == identity_ref:
                return binding.resolved
        raise validation_error("unknown_runtime_identity_target")


@dataclass(frozen=True, slots=True)
class PerceptionExecutionReceipt:
    schema_version: int
    result: PerceptionResult
    model_call_started: bool
    request_fingerprint: DigestString | None
    route_decision: RouteDecision | None
    reported_usage: ModelUsage | None
    model_status: PerceptionModelStatus
    failure_code: str | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.result, PerceptionResult):
            raise validation_error("invalid_perception_execution_result")
        if type(self.model_call_started) is not bool:
            raise validation_error("invalid_model_call_started")
        if not isinstance(self.model_status, PerceptionModelStatus):
            raise validation_error("invalid_perception_execution_status")
        if self.model_status is not self.result.model_status:
            raise validation_error("perception_execution_status_mismatch")
        if self.request_fingerprint is not None:
            require_non_empty(str(self.request_fingerprint), "request_fingerprint")
        if self.route_decision is not None:
            if not isinstance(self.route_decision, RouteDecision):
                raise validation_error("invalid_perception_route_decision")
            if self.route_decision.role is not ModelRole.PERCEPTION:
                raise validation_error("perception_route_role_mismatch")
            route_digest = route_decision_digest(self.route_decision)
            if self.result.model_route_receipt_digest != route_digest:
                raise validation_error("perception_route_receipt_mismatch")
            if (
                self.request_fingerprint
                != self.route_decision.model_request_fingerprint
            ):
                raise validation_error("perception_request_fingerprint_mismatch")
            if self.model_call_started != bool(self.route_decision.attempts):
                raise validation_error("perception_attempt_evidence_mismatch")
        elif self.result.model_route_receipt_digest is not None:
            raise validation_error("missing_perception_route_decision")
        if self.reported_usage is not None and not isinstance(
            self.reported_usage, ModelUsage
        ):
            raise validation_error("invalid_perception_reported_usage")
        if self.model_call_started and self.request_fingerprint is None:
            raise validation_error("started_perception_has_no_request_fingerprint")
        if not self.model_call_started and self.reported_usage is not None:
            raise validation_error("unstarted_perception_has_execution_receipt")
        if self.model_status is PerceptionModelStatus.VALID:
            if not self.model_call_started or self.route_decision is None:
                raise validation_error("valid_perception_has_no_route")
            if self.failure_code is not None:
                raise validation_error("valid_perception_has_failure")
        elif self.failure_code is not None:
            require_non_empty(self.failure_code, "perception_failure_code")

    @property
    def result_digest(self) -> DigestString:
        return perception_result_digest(self.result)


@dataclass(frozen=True, slots=True)
class DirectChatContent:
    schema_version: int
    content_id: str
    text: str
    source_refs: tuple[str, ...]
    model_request_fingerprint: DigestString
    model_response_digest: DigestString
    response_plan_digest: DigestString | None = None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.content_id, "direct_chat_content_id")
        require_non_empty(self.text, "direct_chat_text")
        if len(self.text) > 64_000:
            raise validation_error("direct_chat_text_too_long")
        require_non_empty(
            str(self.model_request_fingerprint),
            "model_request_fingerprint",
        )
        require_non_empty(str(self.model_response_digest), "model_response_digest")
        if self.response_plan_digest is not None:
            require_non_empty(
                str(self.response_plan_digest),
                "response_plan_digest",
            )
        object.__setattr__(
            self,
            "source_refs",
            _unique_strings(self.source_refs, "direct_chat_source_refs", required=True),
        )


@dataclass(frozen=True, slots=True)
class DirectChatExecutionReceipt:
    schema_version: int
    content: DirectChatContent
    route_decision: RouteDecision
    reported_usage: ModelUsage | None
    charged_usage: ResourceUsage

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.content, DirectChatContent):
            raise validation_error("invalid_direct_chat_content")
        if not isinstance(self.route_decision, RouteDecision):
            raise validation_error("invalid_direct_chat_route")
        if self.route_decision.role is not ModelRole.DIRECT_CHAT:
            raise validation_error("direct_chat_route_role_mismatch")
        if self.route_decision.terminal_failure_kind is not None:
            raise validation_error("direct_chat_route_failed")
        if (
            self.route_decision.selected_tier is None
            or self.route_decision.selected_endpoint is None
            or not self.route_decision.attempts
        ):
            raise validation_error("direct_chat_route_has_no_selected_endpoint")
        if (
            self.content.model_request_fingerprint
            != self.route_decision.model_request_fingerprint
        ):
            raise validation_error("direct_chat_request_fingerprint_mismatch")
        if self.reported_usage is not None and not isinstance(
            self.reported_usage, ModelUsage
        ):
            raise validation_error("invalid_direct_chat_reported_usage")
        if not isinstance(self.charged_usage, ResourceUsage):
            raise validation_error("invalid_direct_chat_charged_usage")
        if self.charged_usage.model_calls != 1 or self.charged_usage.tool_steps != 0:
            raise validation_error("invalid_direct_chat_charge")


@dataclass(frozen=True, slots=True)
class DirectChatFailureReceipt:
    schema_version: int
    model_call_started: bool
    request_fingerprint: DigestString
    route_decision: RouteDecision | None
    reported_usage: ModelUsage | None
    charged_usage: ResourceUsage
    failure_code: str
    response_plan_digest: DigestString | None = None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if type(self.model_call_started) is not bool:
            raise validation_error("invalid_direct_chat_failure_started_flag")
        require_non_empty(
            str(self.request_fingerprint),
            "direct_chat_failure_request_fingerprint",
        )
        require_non_empty(self.failure_code, "direct_chat_failure_code")
        if self.response_plan_digest is not None:
            require_non_empty(
                str(self.response_plan_digest),
                "response_plan_digest",
            )
        if self.route_decision is not None:
            if not isinstance(self.route_decision, RouteDecision):
                raise validation_error("invalid_direct_chat_failure_route")
            if (
                self.route_decision.role is not ModelRole.DIRECT_CHAT
                or self.route_decision.model_request_fingerprint
                != self.request_fingerprint
                or bool(self.route_decision.attempts) is not self.model_call_started
            ):
                raise validation_error("direct_chat_failure_route_mismatch")
        if self.reported_usage is not None and not isinstance(
            self.reported_usage,
            ModelUsage,
        ):
            raise validation_error("invalid_direct_chat_failure_usage")
        if not isinstance(self.charged_usage, ResourceUsage):
            raise validation_error("invalid_direct_chat_failure_charge")
        if self.charged_usage.model_calls != 1 or self.charged_usage.tool_steps != 0:
            raise validation_error("invalid_direct_chat_failure_charge")


class DeliveryReconciliationAction(StrEnum):
    NO_CHANGE = "no_change"
    IMPROVED = "improved"
    CONFLICT = "conflict"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DeliveryReconciliationReceipt:
    schema_version: int
    run_id: str
    delivery_id: str
    action: DeliveryReconciliationAction
    previous_status: DeliveryStatus
    current_status: DeliveryStatus
    reason_codes: tuple[str, ...]
    reconciled_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.run_id, "reconciliation_run_id")
        require_non_empty(self.delivery_id, "reconciliation_delivery_id")
        if not isinstance(self.action, DeliveryReconciliationAction):
            raise validation_error("invalid_reconciliation_action")
        if not isinstance(self.previous_status, DeliveryStatus) or not isinstance(
            self.current_status, DeliveryStatus
        ):
            raise validation_error("invalid_reconciliation_delivery_status")
        require_aware(self.reconciled_at, "reconciled_at")
        object.__setattr__(
            self,
            "reason_codes",
            _unique_strings(
                self.reason_codes,
                "reconciliation_reason_codes",
                required=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class ShadowRunReceipt:
    schema_version: int
    run_id: str
    outcome: Outcome
    selected_tier: ModelTier | None
    tier_decision_digest: DigestString | None
    route_decision_digest: DigestString | None
    candidate_delivery_digest: DigestString | None
    reason_codes: tuple[str, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.run_id, "shadow_run_id")
        if not isinstance(self.outcome, Outcome):
            raise validation_error("invalid_shadow_outcome")
        if self.selected_tier is not None and not isinstance(
            self.selected_tier, ModelTier
        ):
            raise validation_error("invalid_shadow_selected_tier")
        for field_name in (
            "tier_decision_digest",
            "route_decision_digest",
            "candidate_delivery_digest",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_non_empty(str(value), field_name)
        selection_values = (
            self.selected_tier,
            self.tier_decision_digest,
            self.route_decision_digest,
        )
        if any(value is not None for value in selection_values) and not all(
            value is not None for value in selection_values
        ):
            raise validation_error("incomplete_shadow_selection_evidence")
        if self.outcome is Outcome.RESPONSE:
            if self.candidate_delivery_digest is None:
                raise validation_error("shadow_response_has_no_candidate_digest")
        elif self.candidate_delivery_digest is not None:
            raise validation_error("shadow_non_response_has_candidate_digest")
        require_aware(self.recorded_at, "shadow_recorded_at")
        reason_codes = _unique_strings(
            self.reason_codes,
            "shadow_reason_codes",
            required=True,
        )
        allowed_reason_characters = frozenset(
            "abcdefghijklmnopqrstuvwxyz0123456789._:-"
        )
        if len(reason_codes) > 64 or any(
            len(reason) > 128
            or reason != reason.strip()
            or any(character not in allowed_reason_characters for character in reason)
            for reason in reason_codes
        ):
            raise validation_error("unsafe_shadow_reason_code")
        object.__setattr__(self, "reason_codes", reason_codes)


def current_message_context_digest(value: CurrentMessageContext) -> DigestString:
    return canonical_digest(value, domain="runtime:current-message-context:v1")


def direct_chat_content_digest(value: DirectChatContent) -> DigestString:
    return canonical_digest(value, domain="runtime:direct-chat-content:v1")


def _unique_strings(
    values: tuple[str, ...],
    field_name: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_collection", field_name)
    materialized = tuple(values)
    if required and not materialized:
        raise validation_error("empty_collection", field_name)
    if any(not isinstance(value, str) or not value.strip() for value in materialized):
        raise validation_error("empty_collection_item", field_name)
    if len(materialized) != len(set(materialized)):
        raise validation_error("duplicate_identifier", field_name)
    return tuple(sorted(materialized))


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
