"""Deterministic answer-profile contracts and policy."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dududa.domain.content import ResponseProfileValidationResult

    from .budget import project_response_reservation
    from .contracts import (
        AnswerProfile,
        DetailPreferenceEvidence,
        ResponsePlan,
        ResponseProfileLimits,
        ResponseProfilePreference,
        ResponseProfileSelectionRequest,
    )
    from .counting import (
        UnicodeVisibleTokenCounter,
        estimate_delivery_parts,
        visible_character_count,
    )
    from .digests import (
        detail_preference_evidence_digest,
        response_plan_digest,
        response_profile_preference_digest,
        response_profile_selection_request_digest,
    )
    from .evidence import detect_detail_preference
    from .policy import (
        DeterministicResponseProfilePolicy,
        ResponseProfilePolicyConfig,
        pilot_response_profile_policy_config,
    )
    from .validation import DeterministicResponseProfileValidator

__all__ = [
    "AnswerProfile",
    "DetailPreferenceEvidence",
    "DeterministicResponseProfilePolicy",
    "DeterministicResponseProfileValidator",
    "ResponsePlan",
    "ResponseProfileLimits",
    "ResponseProfilePolicyConfig",
    "ResponseProfilePreference",
    "ResponseProfileSelectionRequest",
    "ResponseProfileValidationResult",
    "UnicodeVisibleTokenCounter",
    "detail_preference_evidence_digest",
    "detect_detail_preference",
    "estimate_delivery_parts",
    "pilot_response_profile_policy_config",
    "project_response_reservation",
    "response_plan_digest",
    "response_profile_preference_digest",
    "response_profile_selection_request_digest",
    "visible_character_count",
]

_EXPORT_MODULES = {
    "AnswerProfile": ".contracts",
    "DetailPreferenceEvidence": ".contracts",
    "ResponsePlan": ".contracts",
    "ResponseProfileLimits": ".contracts",
    "ResponseProfilePreference": ".contracts",
    "ResponseProfileSelectionRequest": ".contracts",
    "DeterministicResponseProfilePolicy": ".policy",
    "ResponseProfilePolicyConfig": ".policy",
    "pilot_response_profile_policy_config": ".policy",
    "UnicodeVisibleTokenCounter": ".counting",
    "estimate_delivery_parts": ".counting",
    "visible_character_count": ".counting",
    "detail_preference_evidence_digest": ".digests",
    "response_plan_digest": ".digests",
    "response_profile_preference_digest": ".digests",
    "response_profile_selection_request_digest": ".digests",
    "detect_detail_preference": ".evidence",
    "project_response_reservation": ".budget",
    "DeterministicResponseProfileValidator": ".validation",
    "ResponseProfileValidationResult": "dududa.domain.content",
}


def __getattr__(name: str) -> object:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
