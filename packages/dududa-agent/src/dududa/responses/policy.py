from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    require_aware,
    require_non_empty,
)
from dududa.domain.task import TaskComplexityLevel, TaskReasoningDepth
from dududa.errors import validation_error
from dududa.perception.contracts import SocialAction

from .contracts import (
    AnswerProfile,
    ResponsePlan,
    ResponseProfileLimits,
    ResponseProfileSelectionRequest,
    profile_at_most,
)
from .digests import (
    detail_preference_evidence_digest,
    response_profile_preference_digest,
    response_profile_selection_request_digest,
)


@dataclass(frozen=True, slots=True)
class ResponseProfilePolicyConfig:
    schema_version: int
    profile_limits: Mapping[AnswerProfile, ResponseProfileLimits]
    complexity_defaults: Mapping[TaskComplexityLevel, AnswerProfile]
    conversation_caps: Mapping[ConversationType, AnswerProfile]
    delivery_part_character_limit: int
    policy_revision: str
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        limits = dict(self.profile_limits)
        defaults = dict(self.complexity_defaults)
        caps = dict(self.conversation_caps)
        if set(limits) != set(AnswerProfile) or any(
            not isinstance(profile, AnswerProfile)
            or not isinstance(limit, ResponseProfileLimits)
            for profile, limit in limits.items()
        ):
            raise validation_error("invalid_response_profile_limits")
        if set(defaults) != set(TaskComplexityLevel) or any(
            not isinstance(level, TaskComplexityLevel)
            or not isinstance(profile, AnswerProfile)
            for level, profile in defaults.items()
        ):
            raise validation_error("invalid_response_complexity_defaults")
        if set(caps) != set(ConversationType) or any(
            not isinstance(kind, ConversationType)
            or not isinstance(profile, AnswerProfile)
            for kind, profile in caps.items()
        ):
            raise validation_error("invalid_response_conversation_caps")
        if (
            type(self.delivery_part_character_limit) is not int
            or self.delivery_part_character_limit < 1
        ):
            raise validation_error("invalid_delivery_part_character_limit")
        require_non_empty(self.policy_revision, "response_policy_revision")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_response_policy_component_revision")
        object.__setattr__(self, "profile_limits", MappingProxyType(limits))
        object.__setattr__(self, "complexity_defaults", MappingProxyType(defaults))
        object.__setattr__(self, "conversation_caps", MappingProxyType(caps))


class DeterministicResponseProfilePolicy:
    def __init__(
        self,
        config: ResponseProfilePolicyConfig,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(config, ResponseProfilePolicyConfig):
            raise TypeError("invalid Response Profile Policy config")
        self._config = config
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._policy_digest = canonical_digest(
            config,
            domain="response:profile-policy:v1",
        )

    @property
    def config(self) -> ResponseProfilePolicyConfig:
        return self._config

    @property
    def policy_digest(self) -> DigestString:
        return self._policy_digest

    def select(
        self,
        request: ResponseProfileSelectionRequest,
        *,
        now: datetime,
    ) -> ResponsePlan:
        if not isinstance(request, ResponseProfileSelectionRequest):
            raise validation_error("invalid_response_profile_selection_request")
        require_aware(now, "response_profile_policy_time")
        if request.social_action not in {
            SocialAction.DIRECT_REPLY,
            SocialAction.USE_TOOLS,
            SocialAction.ASK_CLARIFICATION,
        }:
            raise validation_error("response_profile_for_non_visible_action")
        reasons = set(request.detail_evidence.reason_codes)
        preference = request.persistent_preference
        preference_digest = None
        usable_preference = None
        if preference is not None:
            _validate_preference_binding(request)
            preference_digest = response_profile_preference_digest(preference)
            if preference.expires_at <= now:
                reasons.add("persistent_preference_expired")
            else:
                usable_preference = preference

        requested = request.detail_evidence.requested_profile
        if request.social_action is SocialAction.ASK_CLARIFICATION:
            uncapped = AnswerProfile.SHORT
            reasons.add("clarification_short_selected")
            if requested is not None and requested is not AnswerProfile.SHORT:
                reasons.add("detail_preference_not_applicable_to_clarification")
        elif requested is not None:
            uncapped = requested
            reasons.add("current_message_preference_selected")
        elif (
            request.complexity_level is TaskComplexityLevel.HIGH
            or request.reasoning_depth is TaskReasoningDepth.DEEP
            or request.verification_required
        ):
            uncapped = AnswerProfile.LONG
            reasons.add("task_requires_long_response")
        elif (
            request.complexity_level is TaskComplexityLevel.MEDIUM
            or request.reasoning_depth is TaskReasoningDepth.MULTI_STEP
            or request.expected_tool_steps > 0
        ):
            uncapped = AnswerProfile.MEDIUM
            reasons.add("task_requires_medium_response")
        elif usable_preference is not None:
            uncapped = usable_preference.preferred_profile
            requested = uncapped
            reasons.add("persistent_preference_selected")
        else:
            uncapped = self._config.complexity_defaults[request.complexity_level]
            reasons.add("configured_complexity_default_selected")

        cap = self._config.conversation_caps[request.conversation_type]
        selected = profile_at_most(uncapped, cap)
        if selected is not uncapped:
            reasons.add("conversation_profile_cap_applied")
        configured = self._config.profile_limits[selected]
        generated_tokens = min(
            configured.generated_tokens,
            request.available_generated_tokens,
        )
        visible_tokens = min(configured.visible_token_units, generated_tokens)
        visible_characters = configured.visible_characters
        if request.maximum_response_characters is not None:
            visible_characters = min(
                visible_characters,
                request.maximum_response_characters,
            )
        delivery_parts = configured.delivery_parts
        if request.maximum_delivery_parts is not None:
            delivery_parts = min(delivery_parts, request.maximum_delivery_parts)
        if generated_tokens < configured.generated_tokens:
            reasons.add("runtime_generated_token_cap_applied")
        if visible_characters < configured.visible_characters:
            reasons.add("response_character_cap_applied")
        if delivery_parts < configured.delivery_parts:
            reasons.add("delivery_part_cap_applied")

        evidence_digest = detail_preference_evidence_digest(request.detail_evidence)
        request_digest = response_profile_selection_request_digest(request)
        fingerprint = canonical_digest(
            {
                "request_digest": request_digest,
                "policy_digest": self._policy_digest,
                "requested_profile": requested,
                "uncapped_profile": uncapped,
                "selected_profile": selected,
                "visible_token_limit": visible_tokens,
                "visible_character_limit": visible_characters,
                "delivery_part_limit": delivery_parts,
                "delivery_part_character_limit": (
                    self._config.delivery_part_character_limit
                ),
                "generated_token_limit": generated_tokens,
                "reason_codes": tuple(sorted(reasons)),
            },
            domain="response:profile-selection-fingerprint:v1",
        )
        return ResponsePlan(
            schema_version=1,
            plan_id=self._id_factory(),
            requested_profile=requested,
            uncapped_profile=uncapped,
            selected_profile=selected,
            visible_token_limit=visible_tokens,
            visible_character_limit=visible_characters,
            delivery_part_limit=delivery_parts,
            delivery_part_character_limit=(self._config.delivery_part_character_limit),
            generated_token_limit=generated_tokens,
            assessment_digest=request.assessment_digest,
            social_decision_digest=request.social_decision_digest,
            detail_evidence_digest=evidence_digest,
            persistent_preference_digest=preference_digest,
            policy_digest=self._policy_digest,
            policy_revision=self._config.policy_revision,
            selection_fingerprint=fingerprint,
            reason_codes=tuple(sorted(reasons)),
            decided_at=now,
        )


def pilot_response_profile_policy_config(
    revision: ComponentRevision,
) -> ResponseProfilePolicyConfig:
    return ResponseProfilePolicyConfig(
        schema_version=1,
        profile_limits={
            AnswerProfile.SHORT: ResponseProfileLimits(1, 128, 180, 1, 128),
            AnswerProfile.MEDIUM: ResponseProfileLimits(1, 512, 720, 2, 512),
            AnswerProfile.LONG: ResponseProfileLimits(1, 1536, 2400, 5, 1536),
        },
        complexity_defaults={
            TaskComplexityLevel.LOW: AnswerProfile.SHORT,
            TaskComplexityLevel.MEDIUM: AnswerProfile.MEDIUM,
            TaskComplexityLevel.HIGH: AnswerProfile.LONG,
        },
        conversation_caps={
            ConversationType.PRIVATE: AnswerProfile.LONG,
            ConversationType.GROUP: AnswerProfile.LONG,
            ConversationType.CHANNEL: AnswerProfile.LONG,
        },
        delivery_part_character_limit=500,
        policy_revision="response-profile-pilot-v1",
        component_revision=revision,
    )


def _validate_preference_binding(
    request: ResponseProfileSelectionRequest,
) -> None:
    preference = request.persistent_preference
    if preference is None:
        return
    if (
        preference.actor_digest != request.actor_digest
        or preference.scope_digest != request.scope_digest
        or preference.persona_id != request.persona_id
    ):
        raise validation_error("response_profile_preference_binding_mismatch")


__all__ = [
    "DeterministicResponseProfilePolicy",
    "ResponseProfilePolicyConfig",
    "pilot_response_profile_policy_config",
]
