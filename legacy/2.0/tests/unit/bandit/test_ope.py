from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from dududa.bandit import (
    BanditFeedbackDisposition,
    bandit_decision_digest,
    evaluate_ope,
    validate_ope_sample_binding,
    validate_ope_samples,
)
from dududa.errors import DududaError

from ._fixtures import ope_policy, ope_sample, synthetic_decision


def golden_samples():
    return (
        ope_sample("sample-1", reward=Decimal(1)),
        ope_sample(
            "sample-2",
            action_id="action-b",
            behavior=("0.75", "0.25"),
            reward=Decimal(0),
            logged_prediction=Decimal("0.2"),
            evaluation_prediction=Decimal("0.3"),
        ),
        ope_sample(
            "sample-3",
            reward=Decimal("0.5"),
            logged_prediction=Decimal("0.4"),
            evaluation_prediction=Decimal("0.5"),
        ),
        ope_sample(
            "sample-4",
            action_id="action-b",
            behavior=("0.75", "0.25"),
            reward=Decimal(1),
            logged_prediction=Decimal("0.7"),
            evaluation_prediction=Decimal("0.8"),
        ),
    )


class BanditOpeTests(unittest.TestCase):
    def test_decimal_golden_and_input_order_are_exact(self) -> None:
        samples = golden_samples()
        report = evaluate_ope(samples, ope_policy())
        reverse = evaluate_ope(tuple(reversed(samples)), ope_policy())
        self.assertEqual(report, reverse)
        self.assertEqual(report.ips, Decimal("0.812500000000"))
        self.assertEqual(report.snips, Decimal("0.650000000000"))
        self.assertEqual(report.doubly_robust, Decimal("0.787500000000"))
        self.assertEqual(
            report.effective_sample_size,
            Decimal("3.846153846154"),
        )

    def test_complete_distribution_support_is_enforced(self) -> None:
        sample = ope_sample(
            "unsupported",
            behavior=("1", "0"),
            evaluation=("0.5", "0.5"),
        )
        validation = validate_ope_samples((sample,), ope_policy())
        self.assertFalse(validation.valid)
        self.assertEqual(validation.support_coverage, Decimal(0))
        self.assertIn(
            "evaluation_action_without_support",
            {item.reason_code for item in validation.issues},
        )
        with self.assertRaises(DududaError):
            evaluate_ope((sample,), ope_policy())

    def test_ope_sample_binds_exact_decision_distribution(self) -> None:
        decision = synthetic_decision()
        sample = ope_sample(
            "bound",
            decision_id=decision.decision_id,
            behavior=("0.6", "0.4"),
        )
        sample = replace(sample, decision_digest=bandit_decision_digest(decision))
        validate_ope_sample_binding(decision, sample)
        with self.assertRaises(DududaError):
            validate_ope_sample_binding(
                decision,
                replace(
                    sample,
                    behavior_distribution=ope_sample("other").behavior_distribution,
                    behavior_propensity=Decimal("0.5"),
                ),
            )

    def test_invalid_propensity_reward_prediction_and_duplicates_fail_closed(
        self,
    ) -> None:
        base = ope_sample("base")
        cases = (
            (replace(base, reward=None), ope_policy()),
            (
                replace(
                    base,
                    feedback_disposition=BanditFeedbackDisposition.CENSORED,
                    reward=None,
                ),
                ope_policy(),
            ),
            (replace(base, logged_action_prediction=None), ope_policy()),
            (
                ope_sample(
                    "low",
                    behavior=("0.05", "0.95"),
                    evaluation=("0.5", "0.5"),
                ),
                ope_policy(),
            ),
            (
                ope_sample(
                    "heavy",
                    behavior=("0.01", "0.99"),
                    evaluation=("0.5", "0.5"),
                ),
                ope_policy(floor="0.001", maximum_weight="10"),
            ),
        )
        for sample, policy in cases:
            with self.subTest(sample=sample.sample_id), self.assertRaises(DududaError):
                evaluate_ope((sample,), policy)

        duplicate = replace(base, sample_id="duplicate", decision_id="same")
        with self.assertRaises(DududaError):
            evaluate_ope(
                (
                    duplicate,
                    replace(duplicate, sample_id="duplicate-2"),
                ),
                ope_policy(),
            )

    def test_zero_snips_denominator_fails_closed(self) -> None:
        sample = ope_sample(
            "zero-weight",
            evaluation=("0", "1"),
        )
        with self.assertRaises(DududaError):
            evaluate_ope((sample,), ope_policy())


if __name__ == "__main__":
    unittest.main()
