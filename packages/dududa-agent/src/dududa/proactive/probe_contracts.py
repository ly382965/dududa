from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from dududa._compat import StrEnum
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    Sensitivity,
    require_aware,
)
from dududa.errors import validation_error
from dududa.responses.contracts import ResponseProfileLimits
from dududa.security.digests import scope_digest

from .contracts import (
    ConversationOpportunitySnapshot,
    ProactiveDisposition,
    ProactiveRunMode,
    ProactiveTargetPolicyRef,
)
from .digests import seal_proactive_contract

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class ProbeHardBlocker(StrEnum):
    ACTIVE_HUMAN_DIALOGUE = "active_human_dialogue"
    DIRECTED_QUESTION = "directed_question"
    CONFLICT_ESCALATION = "conflict_escalation"
    SAFETY_EVENT = "safety_event"
    PERSONAL_TARGET = "personal_target"
    PERSONAL_MEMORY_REQUIRED = "personal_memory_required"
    PENDING_DELIVERY = "pending_delivery"
    UNRESOLVED_PROBE = "unresolved_probe"


class ProbeDetectionStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class ProbeStateClaimDisposition(StrEnum):
    ACQUIRED = "acquired"
    DUPLICATE = "duplicate"
    ACTIVE = "active"
    COOLDOWN = "cooldown"


class ProbeOutcomeKind(StrEnum):
    ENGAGED = "engaged"
    NO_OBSERVED_RESPONSE = "no_observed_response"


@dataclass(frozen=True, slots=True)
class ProbeConversationWindow:
    schema_version: int
    window_id: str
    scope: ConversationScope
    target_policy_ref: ProactiveTargetPolicyRef
    topic_refs: tuple[str, ...]
    topic_summary: str
    sensitivity: Sensitivity
    last_human_activity_at: datetime
    last_bot_activity_at: datetime | None
    observed_at: datetime
    hard_blockers: frozenset[ProbeHardBlocker]
    projection_revision: ComponentRevision
    window_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.window_id, "probe_window_id")
        _group_scope(self.scope)
        if not isinstance(self.target_policy_ref, ProactiveTargetPolicyRef):
            raise validation_error("invalid_probe_target_policy_ref")
        if self.target_policy_ref.target_scope_digest != scope_digest(self.scope):
            raise validation_error("probe_window_target_scope_mismatch")
        refs = _strings(self.topic_refs, "probe_topic_refs", maximum=32)
        _bounded_text(self.topic_summary, "probe_topic_summary", maximum=160)
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_probe_sensitivity")
        for field_name in (
            "last_human_activity_at",
            "observed_at",
        ):
            require_aware(getattr(self, field_name), field_name)
        if self.last_human_activity_at > self.observed_at:
            raise validation_error("probe_human_activity_from_future")
        if self.last_bot_activity_at is not None:
            require_aware(self.last_bot_activity_at, "last_bot_activity_at")
            if self.last_bot_activity_at > self.observed_at:
                raise validation_error("probe_bot_activity_from_future")
        blockers = frozenset(self.hard_blockers)
        if any(not isinstance(value, ProbeHardBlocker) for value in blockers):
            raise validation_error("invalid_probe_hard_blocker")
        if not isinstance(self.projection_revision, ComponentRevision):
            raise validation_error("invalid_probe_projection_revision")
        object.__setattr__(self, "topic_refs", refs)
        object.__setattr__(self, "hard_blockers", blockers)
        seal_proactive_contract(self, "window_digest")


@dataclass(frozen=True, slots=True)
class ProbePolicySnapshot:
    schema_version: int
    snapshot_id: str
    response_policy_revision: str
    persona_catalog_snapshot_id: str
    persona_catalog_digest: DigestString
    persona_id: str
    persona_version: str | None
    minimum_silence: timedelta
    maximum_topic_age: timedelta
    opportunity_ttl: timedelta
    response_attribution_window: timedelta
    recent_bot_cooldown: timedelta
    shadow_cooldown: timedelta
    no_response_cooldown: timedelta
    short_limits: ResponseProfileLimits
    delivery_part_character_limit: int
    detector_revision: ComponentRevision
    composer_revision: ComponentRevision
    policy_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "snapshot_id",
            "persona_catalog_snapshot_id",
            "persona_id",
        ):
            _identifier(getattr(self, field_name), field_name)
        _revision(self.response_policy_revision, "response_policy_revision")
        _digest(self.persona_catalog_digest, "persona_catalog_digest")
        if self.persona_version is not None:
            _revision(self.persona_version, "persona_version")
        _duration(
            self.minimum_silence,
            "probe_minimum_silence",
            minimum=timedelta(seconds=1),
            maximum=timedelta(days=1),
        )
        _duration(
            self.maximum_topic_age,
            "probe_maximum_topic_age",
            minimum=self.minimum_silence,
            maximum=timedelta(days=30),
        )
        if self.maximum_topic_age <= self.minimum_silence:
            raise validation_error("probe_topic_age_must_exceed_minimum_silence")
        _duration(
            self.opportunity_ttl,
            "probe_opportunity_ttl",
            minimum=timedelta(seconds=1),
            maximum=self.maximum_topic_age,
        )
        _duration(
            self.response_attribution_window,
            "probe_response_attribution_window",
            minimum=self.opportunity_ttl,
            maximum=timedelta(days=7),
        )
        _duration(
            self.recent_bot_cooldown,
            "probe_recent_bot_cooldown",
            minimum=timedelta(seconds=1),
            maximum=timedelta(days=30),
        )
        _duration(
            self.shadow_cooldown,
            "probe_shadow_cooldown",
            minimum=self.opportunity_ttl,
            maximum=timedelta(days=30),
        )
        _duration(
            self.no_response_cooldown,
            "probe_no_response_cooldown",
            minimum=self.shadow_cooldown,
            maximum=timedelta(days=366),
        )
        if self.no_response_cooldown <= self.shadow_cooldown:
            raise validation_error("probe_no_response_cooldown_must_be_longer")
        if not isinstance(self.short_limits, ResponseProfileLimits):
            raise validation_error("invalid_probe_short_limits")
        if type(self.delivery_part_character_limit) is not int or not (
            1 <= self.delivery_part_character_limit <= 10_000
        ):
            raise validation_error("invalid_probe_part_character_limit")
        for field_name in ("detector_revision", "composer_revision"):
            if not isinstance(getattr(self, field_name), ComponentRevision):
                raise validation_error("invalid_probe_component_revision", field_name)
        seal_proactive_contract(self, "policy_digest")


@dataclass(frozen=True, slots=True)
class ProbeDetectionResult:
    schema_version: int
    window_digest: DigestString
    status: ProbeDetectionStatus
    opportunity: ConversationOpportunitySnapshot | None
    reason_codes: tuple[str, ...]
    evaluated_at: datetime
    result_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.window_digest, "probe_window_digest")
        if not isinstance(self.status, ProbeDetectionStatus):
            raise validation_error("invalid_probe_detection_status")
        if self.status is ProbeDetectionStatus.ELIGIBLE:
            if not isinstance(self.opportunity, ConversationOpportunitySnapshot):
                raise validation_error("eligible_probe_requires_opportunity")
        elif self.opportunity is not None:
            raise validation_error("ineligible_probe_has_opportunity")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        require_aware(self.evaluated_at, "probe_detection_evaluated_at")
        seal_proactive_contract(self, "result_digest")


@dataclass(frozen=True, slots=True)
class ProbeStateSnapshot:
    schema_version: int
    namespace: str
    scope_digest: DigestString
    revision: int
    last_opportunity_digest: DigestString | None
    active_until: datetime | None
    cooldown_until: datetime | None
    last_outcome: ProbeOutcomeKind | None
    last_attribution_digest: DigestString | None
    updated_at: datetime
    state_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.namespace, "probe_state_namespace")
        _digest(self.scope_digest, "probe_state_scope_digest")
        if type(self.revision) is not int or self.revision < 1:
            raise validation_error("invalid_probe_state_revision")
        if self.last_opportunity_digest is not None:
            _digest(self.last_opportunity_digest, "last_opportunity_digest")
        require_aware(self.updated_at, "probe_state_updated_at")
        for field_name in ("active_until", "cooldown_until"):
            value = getattr(self, field_name)
            if value is not None:
                require_aware(value, field_name)
                if value <= self.updated_at:
                    raise validation_error("invalid_probe_state_boundary", field_name)
        if self.last_outcome is not None and not isinstance(
            self.last_outcome,
            ProbeOutcomeKind,
        ):
            raise validation_error("invalid_probe_state_outcome")
        if self.last_outcome is not None and self.last_opportunity_digest is None:
            raise validation_error("probe_outcome_without_opportunity")
        if (self.last_outcome is None) != (self.last_attribution_digest is None):
            raise validation_error("incomplete_probe_outcome_evidence")
        if self.last_attribution_digest is not None:
            _digest(self.last_attribution_digest, "last_attribution_digest")
        seal_proactive_contract(self, "state_digest")


@dataclass(frozen=True, slots=True)
class ProbeStateClaimReceipt:
    schema_version: int
    namespace: str
    scope_digest: DigestString
    opportunity_digest: DigestString
    disposition: ProbeStateClaimDisposition
    previous_revision: int | None
    current_revision: int | None
    state_digest: DigestString | None
    completed_at: datetime
    receipt_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.namespace, "probe_claim_namespace")
        for field_name in ("scope_digest", "opportunity_digest"):
            _digest(getattr(self, field_name), field_name)
        if not isinstance(self.disposition, ProbeStateClaimDisposition):
            raise validation_error("invalid_probe_claim_disposition")
        for field_name in ("previous_revision", "current_revision"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value < 1):
                raise validation_error("invalid_probe_claim_revision", field_name)
        if self.disposition is ProbeStateClaimDisposition.ACQUIRED:
            if self.current_revision is None or self.state_digest is None:
                raise validation_error("acquired_probe_claim_missing_state")
            if self.previous_revision is not None and (
                self.current_revision != self.previous_revision + 1
            ):
                raise validation_error("invalid_probe_claim_revision_step")
        elif self.current_revision != self.previous_revision:
            raise validation_error("denied_probe_claim_changed_revision")
        if self.state_digest is not None:
            _digest(self.state_digest, "probe_claim_state_digest")
        require_aware(self.completed_at, "probe_claim_completed_at")
        seal_proactive_contract(self, "receipt_digest")

    @property
    def acquired(self) -> bool:
        return self.disposition is ProbeStateClaimDisposition.ACQUIRED


@dataclass(frozen=True, slots=True)
class ProbeOutcomeObservation:
    schema_version: int
    observation_id: str
    namespace: str
    scope_digest: DigestString
    opportunity_digest: DigestString
    attribution_digest: DigestString
    expected_revision: int
    outcome: ProbeOutcomeKind
    observed_at: datetime
    observation_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in ("observation_id", "namespace"):
            _identifier(getattr(self, field_name), field_name)
        for field_name in (
            "scope_digest",
            "opportunity_digest",
            "attribution_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise validation_error("invalid_probe_outcome_revision")
        if not isinstance(self.outcome, ProbeOutcomeKind):
            raise validation_error("invalid_probe_outcome")
        require_aware(self.observed_at, "probe_outcome_observed_at")
        seal_proactive_contract(self, "observation_digest")


@dataclass(frozen=True, slots=True)
class ProbeShadowRequest:
    schema_version: int
    request_id: str
    window: ProbeConversationWindow
    mode: ProactiveRunMode
    config_snapshot_id: str
    response_policy_revision: str
    request_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.request_id, "probe_shadow_request_id")
        if not isinstance(self.window, ProbeConversationWindow):
            raise validation_error("invalid_probe_shadow_window")
        if (
            not isinstance(self.mode, ProactiveRunMode)
            or self.mode is ProactiveRunMode.PREVIEW
        ):
            raise validation_error("invalid_probe_shadow_mode")
        _identifier(self.config_snapshot_id, "probe_config_snapshot_id")
        _revision(self.response_policy_revision, "response_policy_revision")
        seal_proactive_contract(self, "request_digest")


@dataclass(frozen=True, slots=True)
class ProbeShadowMetadata:
    schema_version: int
    request_id: str
    window_digest: DigestString
    target_scope_digest: DigestString
    mode: ProactiveRunMode
    disposition: ProactiveDisposition
    policy_digest: DigestString
    detection_result_digest: DigestString | None
    opportunity_digest: DigestString | None
    state_claim_receipt_digest: DigestString | None
    trigger_digest: DigestString | None
    run_digest: DigestString | None
    response_plan_digest: DigestString | None
    candidate_response_digest: DigestString | None
    persona_catalog_digest: DigestString | None
    persona_source_digest: DigestString | None
    reason_codes: tuple[str, ...]
    completed_at: datetime
    metadata_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.request_id, "probe_shadow_request_id")
        for field_name in (
            "window_digest",
            "target_scope_digest",
            "policy_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        if (
            not isinstance(self.mode, ProactiveRunMode)
            or self.mode is ProactiveRunMode.PREVIEW
        ):
            raise validation_error("invalid_probe_metadata_mode")
        if self.disposition not in {
            ProactiveDisposition.DENIED,
            ProactiveDisposition.COLLECTED,
            ProactiveDisposition.SHADOWED,
            ProactiveDisposition.FAILED,
        }:
            raise validation_error("invalid_probe_metadata_disposition")
        evidence_fields = (
            "detection_result_digest",
            "opportunity_digest",
            "state_claim_receipt_digest",
            "trigger_digest",
            "run_digest",
            "response_plan_digest",
            "candidate_response_digest",
            "persona_catalog_digest",
            "persona_source_digest",
        )
        for field_name in evidence_fields:
            value = getattr(self, field_name)
            if value is not None:
                _digest(value, field_name)
        if (self.trigger_digest is None) != (self.run_digest is None):
            raise validation_error("incomplete_probe_run_evidence")
        if self.opportunity_digest is not None and self.detection_result_digest is None:
            raise validation_error("probe_opportunity_without_detection")
        if self.trigger_digest is not None and self.opportunity_digest is None:
            raise validation_error("probe_run_without_opportunity")
        candidate_fields = (
            self.response_plan_digest,
            self.candidate_response_digest,
            self.persona_catalog_digest,
            self.persona_source_digest,
        )
        if any(value is not None for value in candidate_fields) and not all(
            value is not None for value in candidate_fields
        ):
            raise validation_error("incomplete_probe_candidate_evidence")
        if self.candidate_response_digest is not None and self.run_digest is None:
            raise validation_error("probe_candidate_without_run")
        if self.disposition is ProactiveDisposition.COLLECTED and (
            self.mode is not ProactiveRunMode.COLLECT
            or self.run_digest is None
            or any(value is not None for value in candidate_fields)
        ):
            raise validation_error("invalid_collected_probe_metadata")
        if self.disposition is ProactiveDisposition.SHADOWED and (
            self.mode is not ProactiveRunMode.SHADOW
            or self.candidate_response_digest is None
        ):
            raise validation_error("invalid_shadowed_probe_metadata")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        require_aware(self.completed_at, "probe_shadow_completed_at")
        seal_proactive_contract(self, "metadata_digest")

    @property
    def candidate_built(self) -> bool:
        return self.candidate_response_digest is not None


def _v1(value: object) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise validation_error("invalid_probe_identifier", field_name)
    return value


def _revision(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise validation_error("invalid_probe_revision", field_name)
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise validation_error("invalid_probe_digest", field_name)
    return value


def _group_scope(value: object) -> ConversationScope:
    if not isinstance(value, ConversationScope) or (
        value.conversation_type is not ConversationType.GROUP
    ):
        raise validation_error("probe_requires_group_scope")
    return value


def _strings(values: object, field_name: str, *, maximum: int) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_probe_string_collection", field_name)
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_probe_string_collection", field_name) from None
    if (
        not result
        or len(result) > maximum
        or len(result) != len(set(result))
        or any(
            not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None
            for value in result
        )
    ):
        raise validation_error("invalid_probe_string_collection", field_name)
    return result


def _bounded_text(value: object, field_name: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
    ):
        raise validation_error("invalid_probe_text", field_name)
    return value


def _duration(
    value: object,
    field_name: str,
    *,
    minimum: timedelta,
    maximum: timedelta,
) -> timedelta:
    if not isinstance(value, timedelta) or not minimum <= value <= maximum:
        raise validation_error("invalid_probe_duration", field_name)
    return value


def _reason_codes(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_probe_reason_codes")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_probe_reason_codes") from None
    if (
        not result
        or len(result) > 32
        or len(result) != len(set(result))
        or any(not isinstance(value, str) or not value.strip() for value in result)
    ):
        raise validation_error("invalid_probe_reason_codes")
    return result


__all__ = [
    "ProbeConversationWindow",
    "ProbeDetectionResult",
    "ProbeDetectionStatus",
    "ProbeHardBlocker",
    "ProbeOutcomeKind",
    "ProbeOutcomeObservation",
    "ProbePolicySnapshot",
    "ProbeShadowMetadata",
    "ProbeShadowRequest",
    "ProbeStateClaimDisposition",
    "ProbeStateClaimReceipt",
    "ProbeStateSnapshot",
]
