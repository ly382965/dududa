from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dududa._compat import StrEnum
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    require_aware,
    require_non_empty,
)
from dududa.domain.task import (
    TaskComplexityLevel,
    TaskReasoningDepth,
)
from dududa.errors import validation_error
from dududa.perception.contracts import SocialAction


class AnswerProfile(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


_PROFILE_ORDER = {
    AnswerProfile.SHORT: 0,
    AnswerProfile.MEDIUM: 1,
    AnswerProfile.LONG: 2,
}


@dataclass(frozen=True, slots=True)
class ResponseProfileLimits:
    schema_version: int
    visible_token_units: int
    visible_characters: int
    delivery_parts: int
    generated_tokens: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in (
            "visible_token_units",
            "visible_characters",
            "delivery_parts",
            "generated_tokens",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise validation_error("invalid_response_profile_limit", name)
        if self.visible_token_units > self.generated_tokens:
            raise validation_error("visible_tokens_exceed_generated_tokens")


@dataclass(frozen=True, slots=True)
class DetailPreferenceEvidence:
    schema_version: int
    message_ref: str
    requested_profile: AnswerProfile | None
    reason_codes: tuple[str, ...]
    detector_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.message_ref, "detail_evidence_message_ref")
        if self.requested_profile is not None and not isinstance(
            self.requested_profile, AnswerProfile
        ):
            raise validation_error("invalid_requested_answer_profile")
        object.__setattr__(
            self,
            "reason_codes",
            _reason_codes(self.reason_codes, "detail_evidence_reason_codes"),
        )
        if not isinstance(self.detector_revision, ComponentRevision):
            raise validation_error("invalid_detail_detector_revision")


@dataclass(frozen=True, slots=True)
class ResponseProfilePreference:
    schema_version: int
    preferred_profile: AnswerProfile
    actor_digest: DigestString
    scope_digest: DigestString
    persona_id: str
    revision: int
    source_revision: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.preferred_profile, AnswerProfile):
            raise validation_error("invalid_preferred_answer_profile")
        for name in ("actor_digest", "scope_digest"):
            require_non_empty(str(getattr(self, name)), name)
        require_non_empty(self.persona_id, "preference_persona_id")
        require_non_empty(self.source_revision, "preference_source_revision")
        if type(self.revision) is not int or self.revision < 1:
            raise validation_error("invalid_response_preference_revision")
        require_aware(self.issued_at, "preference_issued_at")
        require_aware(self.expires_at, "preference_expires_at")
        if self.expires_at <= self.issued_at:
            raise validation_error("invalid_response_preference_expiry")


@dataclass(frozen=True, slots=True)
class ResponseProfileSelectionRequest:
    schema_version: int
    selection_id: str
    actor_digest: DigestString
    scope_digest: DigestString
    persona_id: str
    conversation_type: ConversationType
    current_message_ref: str
    complexity_level: TaskComplexityLevel
    reasoning_depth: TaskReasoningDepth
    expected_tool_steps: int
    verification_required: bool
    social_action: SocialAction
    assessment_digest: DigestString
    social_decision_digest: DigestString
    detail_evidence: DetailPreferenceEvidence
    persistent_preference: ResponseProfilePreference | None
    available_generated_tokens: int
    maximum_response_characters: int | None
    maximum_delivery_parts: int | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in (
            "selection_id",
            "persona_id",
            "current_message_ref",
        ):
            require_non_empty(getattr(self, name), name)
        for name in (
            "actor_digest",
            "scope_digest",
            "assessment_digest",
            "social_decision_digest",
        ):
            require_non_empty(str(getattr(self, name)), name)
        if not isinstance(self.conversation_type, ConversationType):
            raise validation_error("invalid_response_conversation_type")
        if not isinstance(self.complexity_level, TaskComplexityLevel):
            raise validation_error("invalid_response_complexity_level")
        if not isinstance(self.reasoning_depth, TaskReasoningDepth):
            raise validation_error("invalid_response_reasoning_depth")
        if not isinstance(self.social_action, SocialAction):
            raise validation_error("invalid_response_social_action")
        if type(self.expected_tool_steps) is not int or self.expected_tool_steps < 0:
            raise validation_error("invalid_response_expected_tool_steps")
        if type(self.verification_required) is not bool:
            raise validation_error("invalid_response_verification_flag")
        if not isinstance(self.detail_evidence, DetailPreferenceEvidence):
            raise validation_error("invalid_detail_preference_evidence")
        if self.detail_evidence.message_ref != self.current_message_ref:
            raise validation_error("detail_evidence_message_mismatch")
        if self.persistent_preference is not None and not isinstance(
            self.persistent_preference, ResponseProfilePreference
        ):
            raise validation_error("invalid_response_profile_preference")
        if (
            type(self.available_generated_tokens) is not int
            or self.available_generated_tokens < 1
        ):
            raise validation_error("invalid_available_generated_tokens")
        for name in ("maximum_response_characters", "maximum_delivery_parts"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise validation_error("invalid_response_hard_limit", name)


@dataclass(frozen=True, slots=True)
class ResponsePlan:
    schema_version: int
    plan_id: str
    requested_profile: AnswerProfile | None
    uncapped_profile: AnswerProfile
    selected_profile: AnswerProfile
    visible_token_limit: int
    visible_character_limit: int
    delivery_part_limit: int
    delivery_part_character_limit: int
    generated_token_limit: int
    assessment_digest: DigestString
    social_decision_digest: DigestString
    detail_evidence_digest: DigestString
    persistent_preference_digest: DigestString | None
    policy_digest: DigestString
    policy_revision: str
    selection_fingerprint: DigestString
    reason_codes: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.plan_id, "response_plan_id")
        if self.requested_profile is not None and not isinstance(
            self.requested_profile, AnswerProfile
        ):
            raise validation_error("invalid_requested_answer_profile")
        for name in ("uncapped_profile", "selected_profile"):
            if not isinstance(getattr(self, name), AnswerProfile):
                raise validation_error("invalid_response_plan_profile", name)
        if profile_rank(self.selected_profile) > profile_rank(self.uncapped_profile):
            raise validation_error("selected_profile_exceeds_uncapped_profile")
        for name in (
            "visible_token_limit",
            "visible_character_limit",
            "delivery_part_limit",
            "delivery_part_character_limit",
            "generated_token_limit",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise validation_error("invalid_response_plan_limit", name)
        if self.visible_token_limit > self.generated_token_limit:
            raise validation_error("visible_tokens_exceed_generated_tokens")
        for name in (
            "assessment_digest",
            "social_decision_digest",
            "detail_evidence_digest",
            "policy_digest",
            "selection_fingerprint",
        ):
            require_non_empty(str(getattr(self, name)), name)
        if self.persistent_preference_digest is not None:
            require_non_empty(
                str(self.persistent_preference_digest),
                "persistent_preference_digest",
            )
        require_non_empty(self.policy_revision, "response_policy_revision")
        object.__setattr__(
            self,
            "reason_codes",
            _reason_codes(self.reason_codes, "response_plan_reason_codes"),
        )
        require_aware(self.decided_at, "response_plan_decided_at")


def profile_rank(profile: AnswerProfile) -> int:
    if not isinstance(profile, AnswerProfile):
        raise validation_error("invalid_answer_profile")
    return _PROFILE_ORDER[profile]


def profile_at_most(
    profile: AnswerProfile,
    maximum: AnswerProfile,
) -> AnswerProfile:
    return profile if profile_rank(profile) <= profile_rank(maximum) else maximum


def _reason_codes(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_string_collection", field)
    materialized = tuple(values)
    if not materialized or any(
        not isinstance(value, str) or not value.strip() for value in materialized
    ):
        raise validation_error("invalid_reason_codes", field)
    if len(materialized) != len(set(materialized)):
        raise validation_error("duplicate_identifier", field)
    return materialized


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


__all__ = [
    "AnswerProfile",
    "DetailPreferenceEvidence",
    "ResponsePlan",
    "ResponseProfileLimits",
    "ResponseProfilePreference",
    "ResponseProfileSelectionRequest",
    "profile_at_most",
    "profile_rank",
]
