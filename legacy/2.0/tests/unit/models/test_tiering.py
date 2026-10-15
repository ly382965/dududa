from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    PrivacyLevel,
    RuntimeBudget,
)
from dududa.domain.task import (
    ContextPressure,
    TaskAmbiguity,
    TaskComplexityAssessment,
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.errors import DududaError, ErrorCategory
from dududa.models.contracts import ModelRole, ModelTier
from dududa.models.policy import (
    BootstrapTierPolicyDefinition,
    ConfidenceHandling,
    TierBudgetRequirement,
    TierPolicyDefinition,
    TierSelectionContext,
)
from dududa.models.tiering import (
    DeterministicModelTierPolicy,
    FixedPerceptionBootstrapTierPolicy,
    validate_bootstrap_tier_decision,
    validate_tier_decision,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def _revision() -> ComponentRevision:
    return ComponentRevision(
        "complexity-assessor",
        "1.0.0",
        "config-v1",
        DigestString("artifact-complexity-assessor"),
    )


def _assessment(
    level: TaskComplexityLevel = TaskComplexityLevel.MEDIUM,
    *,
    confidence: float = 0.9,
    reasoning_depth: TaskReasoningDepth = TaskReasoningDepth.MULTI_STEP,
    expected_tool_steps: int = 0,
    ambiguity: TaskAmbiguity = TaskAmbiguity.LOW,
    verification_required: bool = False,
    conflicting_evidence: bool = False,
    reason_codes: tuple[str, ...] = ("complexity_medium",),
) -> TaskComplexityAssessment:
    return TaskComplexityAssessment(
        schema_version=1,
        assessment_id="assessment-1",
        level=level,
        confidence=confidence,
        task_kind="direct_chat",
        context_pressure=ContextPressure.LOW,
        reasoning_depth=reasoning_depth,
        expected_tool_steps=expected_tool_steps,
        ambiguity=ambiguity,
        verification_required=verification_required,
        conflicting_evidence=conflicting_evidence,
        reason_codes=reason_codes,
        evidence_refs=("message:current",),
        assessor_revision=_revision(),
    )


def _budget(
    *,
    input_tokens: int = 8_000,
    output_tokens: int = 2_000,
    cost: Decimal | None = Decimal("8"),
    model_calls: int = 1,
) -> RuntimeBudget:
    return RuntimeBudget(
        model_calls_remaining=model_calls,
        tool_steps_remaining=0,
        retries_remaining=1,
        input_tokens_remaining=input_tokens,
        output_tokens_remaining=output_tokens,
        cost_units_remaining=cost,
    )


def _context(
    assessment: TaskComplexityAssessment | None = None,
    *,
    budget: RuntimeBudget | None = None,
    content_tokens: int = 512,
) -> TierSelectionContext:
    return TierSelectionContext(
        schema_version=1,
        selection_id="selection-1",
        role=ModelRole.DIRECT_CHAT,
        assessment=assessment or _assessment(),
        content_input_tokens_upper_bound=content_tokens,
        data_classification=PrivacyLevel.CONVERSATION,
        budget=budget or _budget(),
    )


def _definition(*, high_tier: ModelTier = ModelTier.OPUS) -> TierPolicyDefinition:
    return TierPolicyDefinition(
        schema_version=1,
        policy_id="direct-chat-tier-policy",
        role=ModelRole.DIRECT_CHAT,
        allowed_tiers=frozenset({ModelTier.HAIKU, ModelTier.SONNET, ModelTier.OPUS}),
        default_tier=ModelTier.SONNET,
        low_complexity_tier=ModelTier.HAIKU,
        high_complexity_tier=high_tier,
        low_confidence_threshold=0.6,
        minimum_high_tier_confidence=0.85,
        minimum_high_complexity_signals=2,
        high_complexity_reason_codes=frozenset(
            {
                "deep_reasoning",
                "independent_verification",
                "multi_constraint_synthesis",
            }
        ),
        tier_budget_requirements=(
            TierBudgetRequirement(1, ModelTier.HAIKU, 1_000, 256, Decimal("0.1")),
            TierBudgetRequirement(1, ModelTier.SONNET, 2_000, 512, Decimal("1")),
            TierBudgetRequirement(1, ModelTier.OPUS, 4_000, 1_024, Decimal("4")),
        ),
        policy_revision="direct-chat-tier-v1",
    )


class FixedBootstrapTierPolicyTests(unittest.TestCase):
    def test_bootstrap_is_only_perception_haiku_and_is_fully_bound(self) -> None:
        definition = BootstrapTierPolicyDefinition(
            1,
            "perception-bootstrap",
            ModelRole.PERCEPTION,
            ModelTier.HAIKU,
            "perception-bootstrap-v1",
            ("fixed_perception_haiku",),
        )
        decision = FixedPerceptionBootstrapTierPolicy(
            id_factory=lambda: "bootstrap-decision-1"
        ).decide(definition, now=NOW)

        self.assertIs(validate_bootstrap_tier_decision(decision, definition), decision)
        self.assertIs(decision.selected_tier, ModelTier.HAIKU)
        with self.assertRaises(DududaError):
            validate_bootstrap_tier_decision(
                replace(decision, policy_revision="forged"),
                definition,
            )


class DeterministicModelTierPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DeterministicModelTierPolicy(id_factory=lambda: "tier-decision-1")
        self.definition = _definition()

    def test_clear_low_selects_haiku(self) -> None:
        assessment = _assessment(
            TaskComplexityLevel.LOW,
            reasoning_depth=TaskReasoningDepth.SHALLOW,
            reason_codes=("complexity_low", "simple_retrieval"),
        )

        decision = self.policy.decide(
            _context(assessment),
            self.definition,
            now=NOW,
        )

        self.assertIs(decision.selected_tier, ModelTier.HAIKU)
        self.assertIs(decision.confidence_handling, ConfidenceHandling.DIRECT)

    def test_low_confidence_and_conflict_default_to_sonnet(self) -> None:
        cases = (
            (
                _assessment(confidence=0.59),
                ConfidenceHandling.LOW_CONFIDENCE_DEFAULT,
            ),
            (
                _assessment(conflicting_evidence=True),
                ConfidenceHandling.CONFLICT_DEFAULT,
            ),
        )
        for assessment, expected in cases:
            with self.subTest(expected=expected):
                decision = self.policy.decide(
                    _context(assessment),
                    self.definition,
                    now=NOW,
                )
                self.assertIs(decision.selected_tier, ModelTier.SONNET)
                self.assertIs(decision.confidence_handling, expected)

    def test_guarded_high_requires_two_signals_and_confidence(self) -> None:
        high = _assessment(
            TaskComplexityLevel.HIGH,
            confidence=0.9,
            reasoning_depth=TaskReasoningDepth.DEEP,
            verification_required=True,
            reason_codes=(
                "complexity_high",
                "deep_reasoning",
                "independent_verification",
            ),
        )
        one_signal = replace(
            high,
            reason_codes=("complexity_high", "deep_reasoning"),
        )

        self.assertIs(
            self.policy.decide(_context(high), self.definition, now=NOW).selected_tier,
            ModelTier.OPUS,
        )
        self.assertIs(
            self.policy.decide(
                _context(one_signal),
                self.definition,
                now=NOW,
            ).selected_tier,
            ModelTier.SONNET,
        )

    def test_role_policy_can_disallow_opus_without_changing_assessment(self) -> None:
        high = _assessment(
            TaskComplexityLevel.HIGH,
            confidence=0.9,
            reasoning_depth=TaskReasoningDepth.DEEP,
            reason_codes=("deep_reasoning", "independent_verification"),
        )

        decision = self.policy.decide(
            _context(high),
            _definition(high_tier=ModelTier.SONNET),
            now=NOW,
        )

        self.assertIs(decision.selected_tier, ModelTier.SONNET)

    def test_budget_caps_high_in_explicit_semantic_order(self) -> None:
        high = _assessment(
            TaskComplexityLevel.HIGH,
            reasoning_depth=TaskReasoningDepth.DEEP,
            reason_codes=("deep_reasoning", "independent_verification"),
        )
        sonnet_budget = _budget(
            input_tokens=2_500,
            output_tokens=600,
            cost=Decimal("2"),
        )

        decision = self.policy.decide(
            _context(high, budget=sonnet_budget),
            self.definition,
            now=NOW,
        )

        self.assertIs(decision.uncapped_tier, ModelTier.OPUS)
        self.assertIs(decision.selected_tier, ModelTier.SONNET)
        self.assertIs(decision.confidence_handling, ConfidenceHandling.BUDGET_CAPPED)

    def test_unknown_cost_ceiling_does_not_reject_otherwise_affordable_tier(
        self,
    ) -> None:
        decision = self.policy.decide(
            _context(budget=_budget(cost=None)),
            self.definition,
            now=NOW,
        )
        self.assertIs(decision.selected_tier, ModelTier.SONNET)

    def test_no_affordable_tier_raises_typed_budget_error(self) -> None:
        cases = (
            _budget(model_calls=0),
            _budget(input_tokens=999),
            _budget(output_tokens=255),
            _budget(cost=Decimal("0.09")),
        )
        for budget in cases:
            with (
                self.subTest(budget=budget),
                self.assertRaises(DududaError) as captured,
            ):
                self.policy.decide(
                    _context(budget=budget),
                    self.definition,
                    now=NOW,
                )
            self.assertIs(captured.exception.info.category, ErrorCategory.BUDGET)

    def test_decision_validator_recomputes_choice_and_all_bindings(self) -> None:
        value = _context()
        decision = self.policy.decide(value, self.definition, now=NOW)

        self.assertIs(
            validate_tier_decision(decision, value, self.definition),
            decision,
        )
        with self.assertRaises(DududaError):
            validate_tier_decision(
                replace(decision, selection_fingerprint=DigestString("forged")),
                value,
                self.definition,
            )


if __name__ == "__main__":
    unittest.main()
