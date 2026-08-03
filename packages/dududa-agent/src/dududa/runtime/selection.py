from __future__ import annotations

from datetime import datetime

from dududa.domain.primitives import PrivacyLevel, RuntimeBudget
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
from dududa.perception.merge import PerceptionMergeConfig
from dududa.ports.models import ModelTierPolicy


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
