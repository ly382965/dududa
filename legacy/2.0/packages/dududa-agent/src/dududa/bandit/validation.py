from __future__ import annotations

from decimal import Decimal, localcontext

from dududa.errors import validation_error

from .contracts import (
    BanditDecision,
    BanditExecutionDisposition,
    BanditExecutionReceipt,
    BanditFeedback,
    BanditFeedbackDisposition,
    BanditOpePolicy,
    BanditOpeSample,
    BanditOpeValidationIssue,
    BanditOpeValidationReport,
    BanditPolicyRef,
)
from .digests import bandit_decision_digest, bandit_execution_receipt_digest


def validate_execution_receipt(
    decision: BanditDecision,
    receipt: BanditExecutionReceipt,
) -> None:
    if not isinstance(decision, BanditDecision) or not isinstance(
        receipt, BanditExecutionReceipt
    ):
        raise validation_error("invalid_bandit_execution_binding")
    if (
        receipt.decision_id != decision.decision_id
        or receipt.decision_digest != bandit_decision_digest(decision)
        or receipt.action_id != decision.chosen_action_id
        or receipt.recorded_at < decision.decided_at
    ):
        raise validation_error("bandit_execution_decision_mismatch")
    if receipt.disposition is BanditExecutionDisposition.EXECUTED:
        selected = _action(decision, decision.chosen_action_id)
        if receipt.executed_endpoint != selected.endpoint:
            raise validation_error("bandit_execution_action_substituted")
        if receipt.admission_result is None:
            raise validation_error("bandit_execution_admission_missing")
        request = receipt.admission_result.request
        if (
            request.provider_id != selected.endpoint.provider_id
            or request.endpoint_id != selected.endpoint.endpoint_id
            or request.endpoint_descriptor_digest
            != selected.endpoint.endpoint_descriptor_digest
        ):
            raise validation_error("bandit_execution_admission_substituted")
        if receipt.executed_at is None or receipt.executed_at < decision.decided_at:
            raise validation_error("bandit_execution_time_mismatch")


def validate_feedback(
    decision: BanditDecision,
    receipt: BanditExecutionReceipt,
    feedback: BanditFeedback,
    reward_policy: BanditPolicyRef,
) -> None:
    validate_execution_receipt(decision, receipt)
    if receipt.disposition is not BanditExecutionDisposition.EXECUTED:
        raise validation_error("bandit_feedback_for_unexecuted_decision")
    if not isinstance(reward_policy, BanditPolicyRef):
        raise validation_error("invalid_bandit_reward_policy")
    if (
        feedback.decision_id != decision.decision_id
        or feedback.decision_digest != bandit_decision_digest(decision)
        or feedback.execution_receipt_id != receipt.receipt_id
        or feedback.execution_receipt_digest != bandit_execution_receipt_digest(receipt)
        or feedback.action_id != receipt.action_id
    ):
        raise validation_error("bandit_feedback_execution_mismatch")
    if feedback.reward_policy != reward_policy:
        raise validation_error("bandit_feedback_reward_policy_mismatch")
    if (
        receipt.executed_at is None
        or feedback.observation_started_at < receipt.executed_at
    ):
        raise validation_error("bandit_feedback_window_precedes_execution")


def validate_ope_samples(
    samples: tuple[BanditOpeSample, ...],
    policy: BanditOpePolicy,
) -> BanditOpeValidationReport:
    if not isinstance(policy, BanditOpePolicy):
        raise validation_error("invalid_bandit_ope_policy")
    materialized = tuple(samples)
    if any(not isinstance(sample, BanditOpeSample) for sample in materialized):
        raise validation_error("invalid_bandit_ope_sample")

    issues: list[BanditOpeValidationIssue] = []
    counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    support_ok = 0
    reward_ok = 0
    for sample in materialized:
        counts[sample.sample_id] = counts.get(sample.sample_id, 0) + 1
        decision_counts[sample.decision_id] = (
            decision_counts.get(sample.decision_id, 0) + 1
        )
        sample_issues: set[str] = set()
        sample_support_ok = True
        if sample.behavior_propensity <= 0:
            sample_issues.add("zero_behavior_propensity")
            sample_support_ok = False
        elif sample.behavior_propensity < policy.minimum_behavior_propensity:
            sample_issues.add("behavior_propensity_below_floor")
            sample_support_ok = False
        if sample.evaluation_probability > 0 and sample.behavior_propensity <= 0:
            sample_issues.add("evaluation_action_without_support")
        behavior = {
            item.action_id: item.probability for item in sample.behavior_distribution
        }
        evaluation = {
            item.action_id: item.probability for item in sample.evaluation_distribution
        }
        for action_id, probability in evaluation.items():
            if probability <= 0:
                continue
            behavior_probability = behavior[action_id]
            if behavior_probability <= 0:
                sample_issues.add("evaluation_action_without_support")
                sample_support_ok = False
                continue
            if behavior_probability < policy.minimum_behavior_propensity:
                sample_issues.add("behavior_propensity_below_floor")
                sample_support_ok = False
            with localcontext() as context:
                context.prec = 64
                action_weight = probability / behavior_probability
            if action_weight > policy.maximum_importance_weight:
                sample_issues.add("importance_weight_exceeds_limit")
                sample_support_ok = False
        if sample_support_ok:
            support_ok += 1
        if sample.behavior_propensity > 0:
            with localcontext() as context:
                context.prec = 64
                weight = sample.evaluation_probability / sample.behavior_propensity
            if weight > policy.maximum_importance_weight:
                sample_issues.add("importance_weight_exceeds_limit")
        if (
            sample.feedback_disposition is not BanditFeedbackDisposition.OBSERVED
            or sample.reward is None
        ):
            sample_issues.add("observed_reward_missing")
        else:
            reward_ok += 1
        if sample.logged_action_prediction is None:
            sample_issues.add("logged_action_prediction_missing")
        if sample.evaluation_expected_prediction is None:
            sample_issues.add("evaluation_prediction_missing")
        issues.extend(
            BanditOpeValidationIssue(1, sample.sample_id, reason)
            for reason in sorted(sample_issues)
        )

    for sample in materialized:
        if counts[sample.sample_id] > 1:
            issues.append(
                BanditOpeValidationIssue(1, sample.sample_id, "duplicate_sample_id")
            )
        if decision_counts[sample.decision_id] > 1:
            issues.append(
                BanditOpeValidationIssue(1, sample.sample_id, "duplicate_decision_id")
            )
    if not materialized:
        issues.append(BanditOpeValidationIssue(1, "<dataset>", "empty_sample_set"))

    count = len(materialized)
    denominator = Decimal(count) if count else Decimal(1)
    with localcontext() as context:
        context.prec = 64
        support_coverage = Decimal(support_ok) / denominator
        reward_coverage = Decimal(reward_ok) / denominator
    return BanditOpeValidationReport(
        schema_version=1,
        sample_count=count,
        support_coverage=support_coverage,
        reward_coverage=reward_coverage,
        issues=tuple(
            sorted(
                set(issues),
                key=lambda item: (item.sample_id, item.reason_code),
            )
        ),
    )


def validate_ope_sample_binding(
    decision: BanditDecision,
    sample: BanditOpeSample,
) -> None:
    if not isinstance(decision, BanditDecision) or not isinstance(
        sample,
        BanditOpeSample,
    ):
        raise validation_error("invalid_bandit_ope_binding")
    if (
        sample.decision_id != decision.decision_id
        or sample.decision_digest != bandit_decision_digest(decision)
        or sample.action_id != decision.chosen_action_id
    ):
        raise validation_error("bandit_ope_decision_mismatch")
    behavior = {
        item.action_id: item.probability for item in sample.behavior_distribution
    }
    expected = {item.action_id: item.probability for item in decision.distribution}
    evaluation_ids = {item.action_id for item in sample.evaluation_distribution}
    if behavior != expected or evaluation_ids != set(expected):
        raise validation_error("bandit_ope_distribution_decision_mismatch")


def require_valid_ope_samples(
    samples: tuple[BanditOpeSample, ...],
    policy: BanditOpePolicy,
) -> BanditOpeValidationReport:
    report = validate_ope_samples(samples, policy)
    if not report.valid:
        reasons = tuple(sorted({item.reason_code for item in report.issues}))
        raise validation_error("invalid_bandit_ope_samples", *reasons)
    return report


def _action(decision: BanditDecision, action_id: str):
    matches = tuple(item for item in decision.actions if item.action_id == action_id)
    if len(matches) != 1:
        raise validation_error("bandit_action_not_found")
    return matches[0]


__all__ = [
    "require_valid_ope_samples",
    "validate_execution_receipt",
    "validate_feedback",
    "validate_ope_sample_binding",
    "validate_ope_samples",
]
