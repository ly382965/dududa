from __future__ import annotations

from datetime import datetime

from dududa.domain.primitives import ConversationType, PrivacyLevel, RuntimeBudget
from dududa.domain.task import TaskComplexityAssessment
from dududa.errors import validation_error
from dududa.models.contracts import ModelRole
from dududa.models.policy import (
    TierDecision,
    TierPolicyDefinition,
    TierSelectionContext,
)
from dududa.models.tiering import validate_tier_decision
from dududa.perception.complexity import ComplexityAssessorConfig
from dududa.perception.contracts import (
    AuthorizationView,
    DecisionSignals,
    GroupInteractionMode,
)
from dududa.perception.merge import PerceptionMergeConfig
from dududa.ports.models import ModelTierPolicy
from dududa.security.models import AuthorizationDecision, AuthorizationEffect


def project_s10_decision_signals(
    *,
    authorization: AuthorizationDecision,
    duplicate_or_self_message: bool,
    explicit_interaction: bool,
    conversation_type: ConversationType,
    data_classification: PrivacyLevel,
    group_mode: GroupInteractionMode,
    known_target: bool,
    tool_authorization: AuthorizationDecision | None = None,
    tools_enabled: bool = False,
) -> DecisionSignals:
    if not isinstance(authorization, AuthorizationDecision):
        raise validation_error("invalid_response_authorization")
    if type(duplicate_or_self_message) is not bool:
        raise validation_error("invalid_duplicate_or_self_signal")
    if type(explicit_interaction) is not bool:
        raise validation_error("invalid_explicit_interaction_signal")
    if not isinstance(conversation_type, ConversationType):
        raise validation_error("invalid_decision_conversation_type")
    if not isinstance(data_classification, PrivacyLevel):
        raise validation_error("invalid_decision_data_classification")
    if not isinstance(group_mode, GroupInteractionMode):
        raise validation_error("invalid_decision_group_mode")
    if type(known_target) is not bool:
        raise validation_error("invalid_known_target_signal")
    if tool_authorization is not None and not isinstance(
        tool_authorization, AuthorizationDecision
    ):
        raise validation_error("invalid_tool_authorization")
    if type(tools_enabled) is not bool:
        raise validation_error("invalid_tools_enabled_signal")
    authorization_reasons = set(
        authorization.reason_codes or ("authorization_reason_unspecified",)
    )
    if tool_authorization is not None:
        authorization_reasons.update(
            tool_authorization.reason_codes
            or ("tool_authorization_reason_unspecified",)
        )
    private_data_boundary = (
        conversation_type is not ConversationType.PRIVATE
        and data_classification
        in {PrivacyLevel.PERSONAL, PrivacyLevel.SENSITIVE, PrivacyLevel.RESTRICTED}
    )
    return DecisionSignals(
        schema_version=1,
        authorization=AuthorizationView(
            schema_version=1,
            can_respond=authorization.effect is AuthorizationEffect.ALLOW,
            can_use_tools=(
                tool_authorization is not None
                and tool_authorization.effect is AuthorizationEffect.ALLOW
            ),
            reason_codes=tuple(sorted(authorization_reasons)),
        ),
        duplicate_or_self_message=duplicate_or_self_message,
        explicit_interaction=explicit_interaction,
        private_conversation=conversation_type is ConversationType.PRIVATE,
        group_mode=group_mode,
        rate_limited=False,
        private_data_boundary=private_data_boundary,
        tools_enabled=tools_enabled,
        known_target=known_target,
    )


def project_tier_selection_context(
    *,
    selection_id: str,
    role: ModelRole,
    assessment: TaskComplexityAssessment,
    content_input_tokens_upper_bound: int,
    data_classification: PrivacyLevel,
    budget: RuntimeBudget,
) -> TierSelectionContext:
    return TierSelectionContext(
        schema_version=1,
        selection_id=selection_id,
        role=role,
        assessment=assessment,
        content_input_tokens_upper_bound=content_input_tokens_upper_bound,
        data_classification=data_classification,
        budget=budget,
    )


def select_model_tier(
    *,
    context: TierSelectionContext,
    definition: TierPolicyDefinition,
    policy: ModelTierPolicy,
    now: datetime,
) -> TierDecision:
    if not isinstance(policy, ModelTierPolicy):
        raise validation_error("invalid_model_tier_policy")
    decision = policy.decide(context, definition, now=now)
    return validate_tier_decision(decision, context, definition)


def validate_selection_configuration(
    *,
    merge: PerceptionMergeConfig,
    assessor: ComplexityAssessorConfig,
    tier: TierPolicyDefinition,
) -> None:
    if not isinstance(merge, PerceptionMergeConfig):
        raise validation_error("invalid_perception_merge_config")
    if not isinstance(assessor, ComplexityAssessorConfig):
        raise validation_error("invalid_complexity_assessor_config")
    if not isinstance(tier, TierPolicyDefinition):
        raise validation_error("invalid_tier_policy_definition")
    if (
        merge.fallback_confidence_ceiling >= tier.low_confidence_threshold
        or merge.conflict_confidence_ceiling >= tier.low_confidence_threshold
    ):
        raise validation_error("unsafe_perception_tier_confidence_boundary")
    generated_high_codes = {code.value for code in assessor.high_signal_codes}
    if not tier.high_complexity_reason_codes <= generated_high_codes:
        raise validation_error("tier_policy_uses_unproducible_high_signal")
