from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from dududa.bandit import (
    BanditAction,
    BanditActionProbability,
    BanditDecisionMode,
    BanditExecutionDisposition,
    BanditExecutionReceipt,
    BanditFeedbackDisposition,
    bandit_decision_digest,
    build_static_baseline_decision,
    validate_execution_receipt,
    validate_feedback,
)
from dududa.errors import DududaError
from dududa.models.contracts import ModelRole, ModelTier

from ._fixtures import (
    NOW,
    actions,
    context,
    endpoint_ref,
    execution_receipt,
    feedback,
    policy_ref,
    reward_policy_ref,
    router_evidence,
    static_decision,
    synthetic_decision,
)


class BanditDecisionTests(unittest.TestCase):
    def test_static_baseline_replays_router_planned_endpoint(self) -> None:
        eligible = actions()
        first = build_static_baseline_decision(
            decision_id="decision-order",
            context=context(),
            router_evidence=router_evidence(eligible[1].endpoint),
            actions=eligible,
            behavior_policy=policy_ref(),
            decided_at=NOW,
        )
        reverse = build_static_baseline_decision(
            decision_id="decision-order",
            context=context(),
            router_evidence=router_evidence(eligible[1].endpoint),
            actions=tuple(reversed(eligible)),
            behavior_policy=policy_ref(),
            decided_at=NOW,
        )
        self.assertEqual(first, reverse)
        self.assertEqual(first.chosen_action_id, "action-b")
        self.assertEqual(bandit_decision_digest(first), bandit_decision_digest(reverse))

    def test_synthetic_decision_is_order_normalized_and_sanitized(self) -> None:
        decision = synthetic_decision()
        reversed_decision = replace(
            decision,
            actions=tuple(reversed(decision.actions)),
            distribution=tuple(reversed(decision.distribution)),
        )
        self.assertEqual(decision, reversed_decision)
        field_names = {
            name
            for contract in (
                type(decision.context),
                type(decision.router_evidence),
                type(decision),
            )
            for name in contract.__dataclass_fields__
        }
        self.assertTrue(
            {"prompt", "answer", "qq_id", "group_id", "user_id", "memory"}.isdisjoint(
                field_names
            )
        )

    def test_invalid_action_sets_and_distributions_fail_closed(self) -> None:
        decision = synthetic_decision()
        cross_tier = BanditAction(
            1,
            "action-c",
            endpoint_ref("endpoint-c", tier=ModelTier.OPUS),
            ModelRole.DIRECT_CHAT,
        )
        cases = (
            {"actions": (decision.actions[0],)},
            {
                "actions": (decision.actions[0], cross_tier),
                "router_evidence": router_evidence(decision.actions[0].endpoint),
            },
            {"distribution": (decision.distribution[0],)},
            {
                "distribution": (
                    BanditActionProbability(1, "action-a", Decimal(1)),
                    BanditActionProbability(1, "action-b", Decimal(0)),
                )
            },
            {"static_baseline_action_id": "action-a"},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(DududaError):
                replace(decision, **changes)

    def test_static_mode_cannot_use_synthetic_distribution(self) -> None:
        with self.assertRaises(DududaError):
            replace(
                synthetic_decision(),
                mode=BanditDecisionMode.STATIC_BASELINE,
            )


class BanditBindingTests(unittest.TestCase):
    def test_execution_and_feedback_bind_exact_action(self) -> None:
        decision = static_decision()
        receipt = execution_receipt(decision)
        observation = feedback(decision, receipt)
        validate_execution_receipt(decision, receipt)
        validate_feedback(decision, receipt, observation, reward_policy_ref())

    def test_substituted_execution_and_unexecuted_feedback_fail_closed(self) -> None:
        decision = static_decision()
        receipt = execution_receipt(decision)
        substituted = replace(
            receipt,
            executed_endpoint=decision.actions[0].endpoint,
        )
        with self.assertRaises(DududaError):
            validate_execution_receipt(decision, substituted)

        not_executed = BanditExecutionReceipt(
            schema_version=1,
            receipt_id="not-executed",
            decision_id=decision.decision_id,
            decision_digest=bandit_decision_digest(decision),
            action_id=decision.chosen_action_id,
            disposition=BanditExecutionDisposition.NOT_EXECUTED,
            executed_endpoint=None,
            admission_result=None,
            executed_at=None,
            reason_codes=("admission_rejected",),
            recorded_at=NOW + timedelta(minutes=1),
        )
        with self.assertRaises(DududaError):
            validate_feedback(
                decision,
                not_executed,
                feedback(decision, receipt),
                reward_policy_ref(),
            )

    def test_feedback_reward_policy_mismatch_fails_closed(self) -> None:
        decision = static_decision()
        receipt = execution_receipt(decision)
        observation = feedback(decision, receipt)
        with self.assertRaises(DududaError):
            validate_feedback(decision, receipt, observation, policy_ref())

    def test_late_feedback_and_censored_zero_are_rejected(self) -> None:
        observed = feedback()
        with self.assertRaises(DududaError):
            replace(
                observed,
                recorded_at=observed.observation_ends_at + timedelta(seconds=1),
            )
        with self.assertRaises(DududaError):
            replace(
                observed,
                disposition=BanditFeedbackDisposition.CENSORED,
                components=(),
                combined_reward=Decimal(0),
                reason_codes=("no_feedback",),
                recorded_at=observed.observation_ends_at,
            )


if __name__ == "__main__":
    unittest.main()
