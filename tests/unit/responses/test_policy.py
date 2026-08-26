from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    ResourceUsage,
)
from dududa.domain.task import TaskComplexityLevel, TaskReasoningDepth
from dududa.errors import DududaError
from dududa.models.contracts import ModelTier
from dududa.models.tiering import DeterministicModelTierPolicy
from dududa.perception.contracts import SocialAction
from dududa.ports.responses import ResponseProfilePolicy, VisibleTokenCounter
from dududa.responses import (
    AnswerProfile,
    DeterministicResponseProfilePolicy,
    ResponseProfilePreference,
    ResponseProfileSelectionRequest,
    UnicodeVisibleTokenCounter,
    detect_detail_preference,
    estimate_delivery_parts,
    pilot_response_profile_policy_config,
    project_response_reservation,
    response_plan_digest,
)

from tests.unit.models.test_tiering import (
    _assessment as tier_assessment,
)
from tests.unit.models.test_tiering import (
    _context as tier_context,
)
from tests.unit.models.test_tiering import (
    _definition as tier_definition,
)

NOW = datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)


def revision(name: str) -> ComponentRevision:
    return ComponentRevision(
        name,
        "1.0.0",
        "config-v1",
        DigestString(f"artifact:{name}"),
    )


def request(
    level: TaskComplexityLevel,
    requested: AnswerProfile | None,
    *,
    reasoning: TaskReasoningDepth | None = None,
    preference: ResponseProfilePreference | None = None,
    action: SocialAction = SocialAction.DIRECT_REPLY,
    available_tokens: int = 2_000,
    expected_tool_steps: int = 0,
) -> ResponseProfileSelectionRequest:
    phrases = {
        AnswerProfile.SHORT: "请用一句话回答。",
        AnswerProfile.MEDIUM: "请按中等长度回答。",
        AnswerProfile.LONG: "请详细解释。",
        None: "这个问题怎么处理？",
    }
    evidence = detect_detail_preference(
        "message:current",
        phrases[requested],
        detector_revision=revision("detail-detector"),
    )
    return ResponseProfileSelectionRequest(
        schema_version=1,
        selection_id="selection-1",
        actor_digest=DigestString("actor:1"),
        scope_digest=DigestString("scope:1"),
        persona_id="dududa",
        conversation_type=ConversationType.GROUP,
        current_message_ref="message:current",
        complexity_level=level,
        reasoning_depth=reasoning
        or {
            TaskComplexityLevel.LOW: TaskReasoningDepth.SHALLOW,
            TaskComplexityLevel.MEDIUM: TaskReasoningDepth.MULTI_STEP,
            TaskComplexityLevel.HIGH: TaskReasoningDepth.DEEP,
        }[level],
        expected_tool_steps=expected_tool_steps,
        verification_required=False,
        social_action=action,
        assessment_digest=DigestString("assessment:1"),
        social_decision_digest=DigestString("social:1"),
        detail_evidence=evidence,
        persistent_preference=preference,
        available_generated_tokens=available_tokens,
        maximum_response_characters=3_000,
        maximum_delivery_parts=6,
    )


def preference(
    profile: AnswerProfile = AnswerProfile.LONG,
) -> ResponseProfilePreference:
    return ResponseProfilePreference(
        1,
        profile,
        DigestString("actor:1"),
        DigestString("scope:1"),
        "dududa",
        1,
        "preference-source-v1",
        NOW - timedelta(days=1),
        NOW + timedelta(days=1),
    )


class ResponseProfilePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DeterministicResponseProfilePolicy(
            pilot_response_profile_policy_config(revision("profile-policy")),
            id_factory=lambda: "plan-1",
        )

    def test_policy_and_counter_implement_framework_neutral_ports(self) -> None:
        counter = UnicodeVisibleTokenCounter(revision("counter"))

        self.assertIsInstance(self.policy, ResponseProfilePolicy)
        self.assertIsInstance(counter, VisibleTokenCounter)

    def test_explicit_profile_is_orthogonal_to_all_complexity_levels(self) -> None:
        for level in TaskComplexityLevel:
            for profile in AnswerProfile:
                with self.subTest(level=level, profile=profile):
                    plan = self.policy.select(
                        request(level, profile),
                        now=NOW,
                    )
                    self.assertIs(plan.selected_profile, profile)
                    self.assertIs(plan.requested_profile, profile)
                    self.assertEqual(
                        plan.assessment_digest, DigestString("assessment:1")
                    )

    def test_required_tier_reasoning_profile_counterexamples_are_orthogonal(
        self,
    ) -> None:
        tier_policy = DeterministicModelTierPolicy(id_factory=lambda: "tier-decision-1")
        high = tier_assessment(
            TaskComplexityLevel.HIGH,
            reasoning_depth=TaskReasoningDepth.DEEP,
            reason_codes=(
                "complexity_high",
                "deep_reasoning",
                "independent_verification",
            ),
        )
        low = tier_assessment(
            TaskComplexityLevel.LOW,
            reasoning_depth=TaskReasoningDepth.SHALLOW,
            reason_codes=("complexity_low", "simple_retrieval"),
        )

        opus = tier_policy.decide(tier_context(high), tier_definition(), now=NOW)
        opus_short = self.policy.select(
            request(
                TaskComplexityLevel.HIGH,
                AnswerProfile.SHORT,
                reasoning=TaskReasoningDepth.DEEP,
            ),
            now=NOW,
        )
        haiku = tier_policy.decide(tier_context(low), tier_definition(), now=NOW)
        haiku_long = self.policy.select(
            request(
                TaskComplexityLevel.LOW,
                AnswerProfile.LONG,
                reasoning=TaskReasoningDepth.SHALLOW,
            ),
            now=NOW,
        )

        self.assertIs(opus.selected_tier, ModelTier.OPUS)
        self.assertIs(opus_short.selected_profile, AnswerProfile.SHORT)
        self.assertIs(haiku.selected_tier, ModelTier.HAIKU)
        self.assertIs(haiku_long.selected_profile, AnswerProfile.LONG)

    def test_task_defaults_clarification_and_runtime_caps_are_deterministic(
        self,
    ) -> None:
        expected = {
            TaskComplexityLevel.LOW: AnswerProfile.SHORT,
            TaskComplexityLevel.MEDIUM: AnswerProfile.MEDIUM,
            TaskComplexityLevel.HIGH: AnswerProfile.LONG,
        }
        for level, profile in expected.items():
            self.assertIs(
                self.policy.select(request(level, None), now=NOW).selected_profile,
                profile,
            )

        clarification = self.policy.select(
            request(
                TaskComplexityLevel.HIGH,
                AnswerProfile.LONG,
                action=SocialAction.ASK_CLARIFICATION,
            ),
            now=NOW,
        )
        self.assertIs(clarification.selected_profile, AnswerProfile.SHORT)

        capped = self.policy.select(
            request(
                TaskComplexityLevel.LOW,
                AnswerProfile.LONG,
                available_tokens=200,
            ),
            now=NOW,
        )
        self.assertIs(capped.selected_profile, AnswerProfile.LONG)
        self.assertEqual(capped.generated_token_limit, 200)
        self.assertEqual(capped.visible_token_limit, 200)
        self.assertIn("runtime_generated_token_cap_applied", capped.reason_codes)

    def test_tool_assisted_response_defaults_to_long_without_overriding_request(
        self,
    ) -> None:
        selected = self.policy.select(
            request(
                TaskComplexityLevel.LOW,
                None,
                action=SocialAction.USE_TOOLS,
                expected_tool_steps=1,
            ),
            now=NOW,
        )
        explicit = self.policy.select(
            request(
                TaskComplexityLevel.LOW,
                AnswerProfile.MEDIUM,
                action=SocialAction.USE_TOOLS,
                expected_tool_steps=1,
            ),
            now=NOW,
        )

        self.assertIs(selected.selected_profile, AnswerProfile.LONG)
        self.assertIn("tool_assisted_long_response", selected.reason_codes)
        self.assertIs(explicit.selected_profile, AnswerProfile.MEDIUM)

    def test_conversation_cap_narrows_profile_without_changing_tier_inputs(
        self,
    ) -> None:
        config = pilot_response_profile_policy_config(revision("profile-policy"))
        caps = dict(config.conversation_caps)
        caps[ConversationType.GROUP] = AnswerProfile.MEDIUM
        policy = DeterministicResponseProfilePolicy(
            replace(config, conversation_caps=caps),
            id_factory=lambda: "plan-1",
        )

        plan = policy.select(
            request(TaskComplexityLevel.LOW, AnswerProfile.LONG),
            now=NOW,
        )

        self.assertIs(plan.uncapped_profile, AnswerProfile.LONG)
        self.assertIs(plan.selected_profile, AnswerProfile.MEDIUM)
        self.assertIn("conversation_profile_cap_applied", plan.reason_codes)

    def test_preference_is_used_only_for_low_unconstrained_task_and_exact_scope(
        self,
    ) -> None:
        selected = self.policy.select(
            request(
                TaskComplexityLevel.LOW,
                None,
                preference=preference(),
            ),
            now=NOW,
        )
        self.assertIs(selected.selected_profile, AnswerProfile.LONG)
        self.assertIsNotNone(selected.persistent_preference_digest)

        forged = replace(preference(), scope_digest=DigestString("scope:other"))
        with self.assertRaises(DududaError) as raised:
            self.policy.select(
                request(
                    TaskComplexityLevel.LOW,
                    None,
                    preference=forged,
                ),
                now=NOW,
            )
        self.assertEqual(
            raised.exception.info.code,
            "response_profile_preference_binding_mismatch",
        )

        expired = replace(preference(), expires_at=NOW)
        fallback = self.policy.select(
            request(
                TaskComplexityLevel.LOW,
                None,
                preference=expired,
            ),
            now=NOW,
        )
        self.assertIs(fallback.selected_profile, AnswerProfile.SHORT)
        self.assertIn("persistent_preference_expired", fallback.reason_codes)

    def test_selection_fingerprint_is_stable_while_plan_identity_is_not(self) -> None:
        value = request(TaskComplexityLevel.MEDIUM, AnswerProfile.SHORT)
        first = self.policy.select(value, now=NOW)
        second = DeterministicResponseProfilePolicy(
            self.policy.config,
            id_factory=lambda: "plan-2",
        ).select(value, now=NOW)

        self.assertEqual(first.selection_fingerprint, second.selection_fingerprint)
        self.assertNotEqual(response_plan_digest(first), response_plan_digest(second))


class ResponseEvidenceAndBudgetTests(unittest.TestCase):
    def test_detector_rejects_conflict_and_does_not_treat_plain_noun_as_directive(
        self,
    ) -> None:
        conflict = detect_detail_preference(
            "message:1",
            "请简短回答，但也请详细解释。",
            detector_revision=revision("detector"),
        )
        plain = detect_detail_preference(
            "message:2",
            "这里的 detailed answer 是论文中的字段名",
            detector_revision=revision("detector"),
        )
        plain_chinese = detect_detail_preference(
            "message:3",
            "论文中有一个一句话回答字段",
            detector_revision=revision("detector"),
        )

        self.assertIsNone(conflict.requested_profile)
        self.assertEqual(conflict.reason_codes, ("conflicting_detail_preferences",))
        self.assertIsNone(plain.requested_profile)
        self.assertIsNone(plain_chinese.requested_profile)

    def test_unicode_counter_and_delivery_projection_are_stable(self) -> None:
        counter = UnicodeVisibleTokenCounter(revision("counter"))

        self.assertEqual(counter.count("你好, GPT 5!"), 6)
        self.assertEqual(counter.count("e\u0301"), 1)
        self.assertEqual(estimate_delivery_parts(("a" * 501,), 500), 2)
        self.assertEqual(estimate_delivery_parts(("",), 500), 0)

    def test_budget_projection_only_narrows_output_reservation(self) -> None:
        policy = DeterministicResponseProfilePolicy(
            pilot_response_profile_policy_config(revision("policy")),
            id_factory=lambda: "plan-1",
        )
        plan = policy.select(
            request(
                TaskComplexityLevel.LOW,
                AnswerProfile.SHORT,
                available_tokens=128,
            ),
            now=NOW,
        )
        base = ResourceUsage(1, 1, 0, 1, 2_000, 500, Decimal(2))

        projected = project_response_reservation(base, plan)

        self.assertEqual(projected.output_tokens, 128)
        self.assertEqual(projected.input_tokens, base.input_tokens)
        self.assertEqual(projected.cost_units, base.cost_units)
        self.assertEqual(projected.model_calls, 1)


if __name__ == "__main__":
    unittest.main()
