from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString

from .contracts import (
    BanditAction,
    BanditContextEvidence,
    BanditDecision,
    BanditExecutionReceipt,
    BanditFeedback,
    BanditOpePolicy,
    BanditOpeReport,
    BanditOpeSample,
    BanditRouterEvidence,
)


def bandit_action_digest(value: BanditAction) -> DigestString:
    return canonical_digest(value, domain="bandit:action:v1")


def bandit_context_evidence_digest(value: BanditContextEvidence) -> DigestString:
    return canonical_digest(value, domain="bandit:context-evidence:v1")


def bandit_router_evidence_digest(value: BanditRouterEvidence) -> DigestString:
    return canonical_digest(value, domain="bandit:router-evidence:v1")


def bandit_decision_digest(value: BanditDecision) -> DigestString:
    return canonical_digest(value, domain="bandit:decision:v1")


def bandit_execution_receipt_digest(value: BanditExecutionReceipt) -> DigestString:
    return canonical_digest(value, domain="bandit:execution-receipt:v1")


def bandit_feedback_digest(value: BanditFeedback) -> DigestString:
    return canonical_digest(value, domain="bandit:feedback:v1")


def bandit_ope_policy_digest(value: BanditOpePolicy) -> DigestString:
    return canonical_digest(value, domain="bandit:ope-policy:v1")


def bandit_ope_sample_set_digest(
    values: tuple[BanditOpeSample, ...],
) -> DigestString:
    ordered = tuple(sorted(values, key=lambda item: item.sample_id))
    return canonical_digest(ordered, domain="bandit:ope-sample-set:v1")


def bandit_ope_report_digest(value: BanditOpeReport) -> DigestString:
    return canonical_digest(value, domain="bandit:ope-report:v1")


__all__ = [
    "bandit_action_digest",
    "bandit_context_evidence_digest",
    "bandit_decision_digest",
    "bandit_execution_receipt_digest",
    "bandit_feedback_digest",
    "bandit_ope_policy_digest",
    "bandit_ope_report_digest",
    "bandit_ope_sample_set_digest",
    "bandit_router_evidence_digest",
]
