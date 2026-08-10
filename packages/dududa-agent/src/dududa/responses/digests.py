from __future__ import annotations

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString

from .contracts import (
    DetailPreferenceEvidence,
    ResponsePlan,
    ResponseProfilePreference,
    ResponseProfileSelectionRequest,
)


def detail_preference_evidence_digest(
    evidence: DetailPreferenceEvidence,
) -> DigestString:
    return canonical_digest(evidence, domain="response:detail-evidence:v1")


def response_profile_preference_digest(
    preference: ResponseProfilePreference,
) -> DigestString:
    return canonical_digest(preference, domain="response:profile-preference:v1")


def response_profile_selection_request_digest(
    request: ResponseProfileSelectionRequest,
) -> DigestString:
    return canonical_digest(request, domain="response:profile-selection-request:v1")


def response_plan_digest(plan: ResponsePlan) -> DigestString:
    return canonical_digest(plan, domain="response:plan:v1")


__all__ = [
    "detail_preference_evidence_digest",
    "response_plan_digest",
    "response_profile_preference_digest",
    "response_profile_selection_request_digest",
]
