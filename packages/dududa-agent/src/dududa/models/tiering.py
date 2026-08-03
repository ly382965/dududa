from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
import uuid

from dududa.domain.primitives import require_aware
from dududa.domain.task import (
    TaskAmbiguity,
    TaskComplexityAssessment,
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.errors import ErrorCategory, error, validation_error

from .contracts import ModelTier
from .digests import (
    bootstrap_tier_policy_definition_digest,
    bootstrap_tier_selection_fingerprint,
    task_complexity_assessment_digest,
    tier_policy_definition_digest,
    tier_selection_context_digest,
    tier_selection_fingerprint,
)
from .policy import (
    BootstrapTierDecision,
    BootstrapTierPolicyDefinition,
    ConfidenceHandling,
    TierBudgetRequirement,
    TierDecision,
    TierPolicyDefinition,
    TierSelectionContext,
)


class FixedPerceptionBootstrapTierPolicy:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def decide(
        self,
        definition: BootstrapTierPolicyDefinition,
        *,
        now: datetime | None = None,
    ) -> BootstrapTierDecision:
        if not isinstance(definition, BootstrapTierPolicyDefinition):
            raise validation_error("invalid_bootstrap_tier_policy_definition")
        decided_at = now if now is not None else self._clock()
        require_aware(decided_at, "decided_at")
        policy_digest = bootstrap_tier_policy_definition_digest(definition)
        return BootstrapTierDecision(
            schema_version=1,
            decision_id=self._id_factory(),
            role=definition.role,
            selected_tier=definition.selected_tier,
            selection_fingerprint=bootstrap_tier_selection_fingerprint(
                role=definition.role,
                selected_tier=definition.selected_tier,
                tier_policy_digest=policy_digest,
                policy_revision=definition.policy_revision,
                reason_codes=definition.reason_codes,
            ),
            tier_policy_digest=policy_digest,
            policy_revision=definition.policy_revision,
            reason_codes=definition.reason_codes,
            decided_at=decided_at,
        )


class DeterministicModelTierPolicy:
    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def decide(
        self,
        context: TierSelectionContext,
        definition: TierPolicyDefinition,
        *,
        now: datetime,
    ) -> TierDecision:
        if not isinstance(context, TierSelectionContext):
            raise validation_error("invalid_tier_selection_context")
        if not isinstance(definition, TierPolicyDefinition):
            raise validation_error("invalid_tier_policy_definition")
        require_aware(now, "decided_at")
        if context.role is not definition.role:
            raise validation_error("tier_policy_role_mismatch")
        uncapped, selected, handling, reasons = _selection(context, definition)
        return TierDecision(
            schema_version=1,
            decision_id=self._id_factory(),
            role=context.role,
            selected_tier=selected,
            uncapped_tier=uncapped,
            assessment_digest=task_complexity_assessment_digest(context.assessment),
            selection_context_digest=tier_selection_context_digest(context),
            selection_fingerprint=tier_selection_fingerprint(context, definition),
            tier_policy_digest=tier_policy_definition_digest(definition),
            policy_revision=definition.policy_revision,
            confidence_handling=handling,
            reason_codes=reasons,
            decided_at=now,
        )


def validate_bootstrap_tier_decision(
    decision: BootstrapTierDecision,
    definition: BootstrapTierPolicyDefinition,
) -> BootstrapTierDecision:
    if not isinstance(decision, BootstrapTierDecision):
        raise validation_error("invalid_bootstrap_tier_decision")
    if not isinstance(definition, BootstrapTierPolicyDefinition):
        raise validation_error("invalid_bootstrap_tier_policy_definition")
    policy_digest = bootstrap_tier_policy_definition_digest(definition)
    fingerprint = bootstrap_tier_selection_fingerprint(
        role=definition.role,
        selected_tier=definition.selected_tier,
        tier_policy_digest=policy_digest,
        policy_revision=definition.policy_revision,
        reason_codes=definition.reason_codes,
    )
    if (
        decision.role is not definition.role
        or decision.selected_tier is not definition.selected_tier
        or decision.tier_policy_digest != policy_digest
        or decision.selection_fingerprint != fingerprint
        or decision.policy_revision != definition.policy_revision
        or decision.reason_codes != definition.reason_codes
    ):
        raise validation_error("bootstrap_tier_decision_binding_mismatch")
    return decision


def validate_tier_decision(
    decision: TierDecision,
    context: TierSelectionContext,
    definition: TierPolicyDefinition,
) -> TierDecision:
    if not isinstance(decision, TierDecision):
        raise validation_error("invalid_tier_decision")
    if not isinstance(context, TierSelectionContext):
        raise validation_error("invalid_tier_selection_context")
    if not isinstance(definition, TierPolicyDefinition):
        raise validation_error("invalid_tier_policy_definition")
    if context.role is not definition.role or decision.role is not context.role:
        raise validation_error("tier_decision_role_mismatch")
    uncapped, selected, handling, reasons = _selection(context, definition)
    if (
        decision.assessment_digest
        != task_complexity_assessment_digest(context.assessment)
        or decision.selection_context_digest != tier_selection_context_digest(context)
        or decision.selection_fingerprint
        != tier_selection_fingerprint(context, definition)
        or decision.tier_policy_digest != tier_policy_definition_digest(definition)
        or decision.policy_revision != definition.policy_revision
        or decision.uncapped_tier is not uncapped
        or decision.selected_tier is not selected
        or decision.confidence_handling is not handling
        or decision.reason_codes != reasons
    ):
        raise validation_error("tier_decision_binding_mismatch")
    return decision


def _selection(
    context: TierSelectionContext,
    definition: TierPolicyDefinition,
) -> tuple[ModelTier, ModelTier, ConfidenceHandling, tuple[str, ...]]:
    assessment = context.assessment
    high_signal_count = len(
        set(assessment.reason_codes) & definition.high_complexity_reason_codes
    )
    if assessment.conflicting_evidence:
        uncapped = definition.default_tier
        handling = ConfidenceHandling.CONFLICT_DEFAULT
        reasons = {"conflicting_complexity_evidence", "default_tier_selected"}
    elif assessment.confidence < definition.low_confidence_threshold:
        uncapped = definition.default_tier
        handling = ConfidenceHandling.LOW_CONFIDENCE_DEFAULT
        reasons = {"low_complexity_confidence", "default_tier_selected"}
    elif _clear_low(assessment):
        uncapped = definition.low_complexity_tier
        handling = ConfidenceHandling.DIRECT
        reasons = {"clear_low_complexity_evidence"}
    elif (
        assessment.level is TaskComplexityLevel.HIGH
        and assessment.confidence >= definition.minimum_high_tier_confidence
        and high_signal_count >= definition.minimum_high_complexity_signals
    ):
        uncapped = definition.high_complexity_tier
        handling = ConfidenceHandling.DIRECT
        reasons = {"guarded_high_complexity_evidence"}
    else:
        uncapped = definition.default_tier
        handling = ConfidenceHandling.DIRECT
        reasons = {"default_tier_selected"}
        if assessment.level is TaskComplexityLevel.HIGH:
            reasons.add("high_tier_guard_not_met")

    selected = _first_affordable_tier(context, definition, uncapped)
    if selected is not uncapped:
        handling = ConfidenceHandling.BUDGET_CAPPED
        reasons.add("budget_capped")
    else:
        reasons.add("budget_allows_selected_tier")
    return uncapped, selected, handling, tuple(sorted(reasons))


def _clear_low(assessment: TaskComplexityAssessment) -> bool:
    return (
        assessment.level is TaskComplexityLevel.LOW
        and assessment.reasoning_depth is TaskReasoningDepth.SHALLOW
        and assessment.expected_tool_steps == 0
        and assessment.ambiguity is TaskAmbiguity.LOW
        and not assessment.verification_required
        and not assessment.conflicting_evidence
    )


def _first_affordable_tier(
    context: TierSelectionContext,
    definition: TierPolicyDefinition,
    uncapped: ModelTier,
) -> ModelTier:
    candidates = [uncapped]
    if uncapped is definition.high_complexity_tier:
        candidates.extend((definition.default_tier, definition.low_complexity_tier))
    elif uncapped is definition.default_tier:
        candidates.append(definition.low_complexity_tier)
    ordered: list[ModelTier] = []
    for candidate in candidates:
        if candidate in definition.allowed_tiers and candidate not in ordered:
            ordered.append(candidate)
    requirements = {
        requirement.tier: requirement
        for requirement in definition.tier_budget_requirements
    }
    for candidate in ordered:
        if _affordable(context, requirements[candidate]):
            return candidate
    raise error(
        "tier_budget_exhausted",
        ErrorCategory.BUDGET,
        "request.budget_exhausted",
        "no_affordable_model_tier",
    )


def _affordable(
    context: TierSelectionContext,
    requirement: TierBudgetRequirement,
) -> bool:
    budget = context.budget
    if budget.model_calls_remaining < 1:
        return False
    if budget.input_tokens_remaining < max(
        context.content_input_tokens_upper_bound,
        requirement.minimum_input_tokens_remaining,
    ):
        return False
    if budget.output_tokens_remaining < requirement.minimum_generated_tokens_remaining:
        return False
    if budget.cost_units_remaining is not None:
        required = requirement.minimum_cost_units_remaining
        if not isinstance(required, Decimal) or budget.cost_units_remaining < required:
            return False
    return True
