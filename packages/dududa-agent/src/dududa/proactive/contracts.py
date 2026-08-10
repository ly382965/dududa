from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TypeAlias
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dududa._compat import StrEnum
from dududa.contracts.binding import NegotiatedBindingReceipt
from dududa.contracts.canonical import canonical_digest
from dududa.domain.content import Citation, ValidatedFinalResponse
from dududa.domain.identity import Actor, ActorRef, ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    Sensitivity,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.responses.contracts import AnswerProfile
from dududa.security.digests import scope_digest

from .digests import proactive_delivery_idempotency_key, seal_proactive_contract

_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_REVISION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_REASON_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")


class ProactiveTriggerKind(StrEnum):
    CONVERSATION_PROBE = "conversation_probe"
    SCHEDULED_DIGEST = "scheduled_digest"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKED = "revoked"


class ProactiveRunMode(StrEnum):
    OFF = "off"
    COLLECT = "collect"
    SHADOW = "shadow"
    PREVIEW = "preview"
    CANARY = "canary"


DeliveryRunMode: TypeAlias = ProactiveRunMode
PreviewRunMode: TypeAlias = ProactiveRunMode


class SourceCategory(StrEnum):
    CAMPUS = "campus"
    INDUSTRY = "industry"
    ARXIV = "arxiv"


class ProactiveTargetPolicyStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKED = "revoked"


class ProactiveGrantKind(StrEnum):
    OPERATOR_ENABLE_TARGET = "operator_enable_target"
    GROUP_POLICY_ENABLE = "group_policy_enable"
    SUBSCRIPTION_OWNER = "subscription_owner"


class ScheduleOccurrenceOrigin(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL_CANARY = "manual_canary"


class ProactiveDisposition(StrEnum):
    DENIED = "denied"
    COLLECTED = "collected"
    SHADOWED = "shadowed"
    PREVIEWED = "previewed"
    PREPARED = "prepared"
    DELIVERED = "delivered"
    FAILED = "failed"


class DispatchState(StrEnum):
    PREPARED = "prepared"
    ATTEMPTED = "attempted"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DispatchPrepareDisposition(StrEnum):
    CREATED = "created"
    EXISTING = "existing"
    CONFLICT = "conflict"


class QuotaKind(StrEnum):
    GLOBAL = "global"
    SCOPE = "scope"


@dataclass(frozen=True, slots=True)
class LocalTimeWindow:
    start: time
    end: time

    def __post_init__(self) -> None:
        for field_name in ("start", "end"):
            value = getattr(self, field_name)
            if not isinstance(value, time) or value.tzinfo is not None:
                raise validation_error("invalid_local_time_window", field_name)
        if self.start == self.end:
            raise validation_error("empty_local_time_window")

    @classmethod
    def from_strings(cls, start: str, end: str) -> LocalTimeWindow:
        try:
            return cls(time.fromisoformat(start), time.fromisoformat(end))
        except (TypeError, ValueError):
            raise validation_error("invalid_local_time_window") from None

    def contains(self, value: time) -> bool:
        if not isinstance(value, time) or value.tzinfo is not None:
            raise validation_error("invalid_local_time_value")
        if self.start < self.end:
            return self.start <= value < self.end
        return value >= self.start or value < self.end


@dataclass(frozen=True, slots=True)
class ProactiveAuthorizationGrantRef:
    schema_version: int
    grant_id: str
    revision: int
    authorization_decision_digest: DigestString
    policy_revision: str
    grant_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.grant_id, "grant_id")
        _positive(self.revision, "grant_revision")
        _digest(self.authorization_decision_digest, "authorization_decision_digest")
        _revision(self.policy_revision, "grant_policy_revision")
        _digest(self.grant_digest, "grant_digest")


@dataclass(frozen=True, slots=True)
class ProactiveAuthorizationGrant:
    schema_version: int
    grant_id: str
    revision: int
    grant_kind: ProactiveGrantKind
    issuer_ref: ActorRef
    issuer_actor_digest: DigestString
    target_scope_digest: DigestString
    action: str
    allowed_trigger_kinds: frozenset[ProactiveTriggerKind]
    allowed_categories: frozenset[SourceCategory]
    authorization_decision_digest: DigestString
    policy_revision: str
    issued_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    grant_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.grant_id, "grant_id")
        _positive(self.revision, "grant_revision")
        if not isinstance(self.grant_kind, ProactiveGrantKind):
            raise validation_error("invalid_proactive_grant_kind")
        if not isinstance(self.issuer_ref, ActorRef):
            raise validation_error("invalid_proactive_grant_issuer")
        _digest(self.issuer_actor_digest, "issuer_actor_digest")
        _digest(self.target_scope_digest, "target_scope_digest")
        if self.action != "message.send.proactive":
            raise validation_error("invalid_proactive_grant_action")
        trigger_kinds = _enum_set(
            self.allowed_trigger_kinds,
            ProactiveTriggerKind,
            "allowed_trigger_kinds",
            required=True,
        )
        categories = _enum_set(
            self.allowed_categories,
            SourceCategory,
            "allowed_categories",
            required=False,
        )
        if ProactiveTriggerKind.SCHEDULED_DIGEST in trigger_kinds and not categories:
            raise validation_error("digest_grant_requires_categories")
        _digest(self.authorization_decision_digest, "authorization_decision_digest")
        _revision(self.policy_revision, "grant_policy_revision")
        _aware(self.issued_at, "grant_issued_at")
        _optional_aware(self.expires_at, "grant_expires_at")
        _optional_aware(self.revoked_at, "grant_revoked_at")
        if self.expires_at is not None and self.expires_at <= self.issued_at:
            raise validation_error("invalid_proactive_grant_expiry")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise validation_error("invalid_proactive_grant_revocation")
        object.__setattr__(self, "allowed_trigger_kinds", trigger_kinds)
        object.__setattr__(self, "allowed_categories", categories)
        seal_proactive_contract(self, "grant_digest")

    def as_ref(self) -> ProactiveAuthorizationGrantRef:
        return ProactiveAuthorizationGrantRef(
            1,
            self.grant_id,
            self.revision,
            self.authorization_decision_digest,
            self.policy_revision,
            self.grant_digest,
        )


@dataclass(frozen=True, slots=True)
class ProactiveTargetPolicyRef:
    schema_version: int
    target_policy_id: str
    revision: int
    target_scope_digest: DigestString
    target_policy_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.target_policy_id, "target_policy_id")
        _positive(self.revision, "target_policy_revision")
        _digest(self.target_scope_digest, "target_scope_digest")
        _digest(self.target_policy_digest, "target_policy_digest")


@dataclass(frozen=True, slots=True)
class ProactiveTargetPolicy:
    schema_version: int
    target_policy_id: str
    revision: int
    status: ProactiveTargetPolicyStatus
    target_scope: ConversationScope
    operator_authorization_grant_ref: ProactiveAuthorizationGrantRef
    group_policy_grant_ref: ProactiveAuthorizationGrantRef
    allowed_trigger_kinds: frozenset[ProactiveTriggerKind]
    policy_revision: str
    activated_at: datetime
    expires_at: datetime | None
    target_policy_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.target_policy_id, "target_policy_id")
        _positive(self.revision, "target_policy_revision")
        if not isinstance(self.status, ProactiveTargetPolicyStatus):
            raise validation_error("invalid_proactive_target_status")
        _group_scope(self.target_scope)
        if not isinstance(
            self.operator_authorization_grant_ref,
            ProactiveAuthorizationGrantRef,
        ) or not isinstance(
            self.group_policy_grant_ref,
            ProactiveAuthorizationGrantRef,
        ):
            raise validation_error("invalid_proactive_target_grant_ref")
        if (
            self.operator_authorization_grant_ref.grant_id
            == self.group_policy_grant_ref.grant_id
        ):
            raise validation_error("proactive_target_grants_not_distinct")
        kinds = _enum_set(
            self.allowed_trigger_kinds,
            ProactiveTriggerKind,
            "allowed_trigger_kinds",
            required=True,
        )
        _revision(self.policy_revision, "target_policy_revision_name")
        _aware(self.activated_at, "target_policy_activated_at")
        _optional_aware(self.expires_at, "target_policy_expires_at")
        if self.expires_at is not None and self.expires_at <= self.activated_at:
            raise validation_error("invalid_target_policy_expiry")
        object.__setattr__(self, "allowed_trigger_kinds", kinds)
        seal_proactive_contract(self, "target_policy_digest")

    def as_ref(self) -> ProactiveTargetPolicyRef:
        return ProactiveTargetPolicyRef(
            1,
            self.target_policy_id,
            self.revision,
            scope_digest(self.target_scope),
            self.target_policy_digest,
        )


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    schema_version: int
    timezone: str
    local_time: time
    weekdays: frozenset[int]
    quiet_hours: tuple[LocalTimeWindow, ...]
    misfire_grace: timedelta
    schedule_revision: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.timezone, "schedule_timezone")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise validation_error("invalid_schedule_timezone") from None
        if not isinstance(self.local_time, time) or self.local_time.tzinfo is not None:
            raise validation_error("invalid_schedule_local_time")
        weekdays = frozenset(self.weekdays)
        if not weekdays or any(
            type(value) is not int or value not in range(7) for value in weekdays
        ):
            raise validation_error("invalid_schedule_weekdays")
        windows = tuple(self.quiet_hours)
        if len(windows) != len(set(windows)) or any(
            not isinstance(value, LocalTimeWindow) for value in windows
        ):
            raise validation_error("invalid_schedule_quiet_hours")
        if not isinstance(self.misfire_grace, timedelta) or not (
            timedelta(0) < self.misfire_grace <= timedelta(days=7)
        ):
            raise validation_error("invalid_schedule_misfire_grace")
        _revision(self.schedule_revision, "schedule_revision")
        object.__setattr__(self, "weekdays", weekdays)
        object.__setattr__(self, "quiet_hours", windows)


@dataclass(frozen=True, slots=True)
class ProactiveSubscription:
    schema_version: int
    subscription_id: str
    revision: int
    status: SubscriptionStatus
    owner_ref: ActorRef
    authorization_grant_ref: ProactiveAuthorizationGrantRef
    target_scope: ConversationScope
    target_policy_ref: ProactiveTargetPolicyRef
    categories: frozenset[SourceCategory]
    source_policy_id: str
    schedule: ScheduleSpec
    answer_profile: AnswerProfile
    maximum_items: int
    maximum_age: timedelta
    created_at: datetime
    updated_at: datetime
    subscription_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.subscription_id, "subscription_id")
        _positive(self.revision, "subscription_revision")
        if not isinstance(self.status, SubscriptionStatus):
            raise validation_error("invalid_subscription_status")
        if not isinstance(self.owner_ref, ActorRef):
            raise validation_error("invalid_subscription_owner")
        _group_scope(self.target_scope)
        if (
            self.owner_ref.platform != self.target_scope.platform
            or self.owner_ref.bot_id != self.target_scope.bot_id
        ):
            raise validation_error("subscription_owner_scope_mismatch")
        if not isinstance(
            self.authorization_grant_ref, ProactiveAuthorizationGrantRef
        ) or not isinstance(self.target_policy_ref, ProactiveTargetPolicyRef):
            raise validation_error("invalid_subscription_policy_ref")
        if self.target_policy_ref.target_scope_digest != scope_digest(
            self.target_scope
        ):
            raise validation_error("subscription_target_scope_mismatch")
        categories = _enum_set(
            self.categories,
            SourceCategory,
            "subscription_categories",
            required=True,
        )
        _identifier(self.source_policy_id, "source_policy_id")
        if not isinstance(self.schedule, ScheduleSpec):
            raise validation_error("invalid_subscription_schedule")
        if not isinstance(self.answer_profile, AnswerProfile):
            raise validation_error("invalid_subscription_answer_profile")
        if type(self.maximum_items) is not int or not 1 <= self.maximum_items <= 100:
            raise validation_error("invalid_subscription_item_limit")
        if not isinstance(self.maximum_age, timedelta) or not (
            timedelta(minutes=1) <= self.maximum_age <= timedelta(days=365)
        ):
            raise validation_error("invalid_subscription_maximum_age")
        _aware(self.created_at, "subscription_created_at")
        _aware(self.updated_at, "subscription_updated_at")
        if self.updated_at < self.created_at:
            raise validation_error("invalid_subscription_update_time")
        object.__setattr__(self, "categories", categories)
        seal_proactive_contract(self, "subscription_digest")


@dataclass(frozen=True, slots=True)
class ScheduleOccurrence:
    schema_version: int
    occurrence_id: str
    subscription_id: str
    subscription_revision: int
    origin: ScheduleOccurrenceOrigin
    local_date: date
    scheduled_for: datetime
    eligible_until: datetime
    occurrence_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.occurrence_id, "occurrence_id")
        _identifier(self.subscription_id, "subscription_id")
        _positive(self.subscription_revision, "subscription_revision")
        if not isinstance(self.origin, ScheduleOccurrenceOrigin):
            raise validation_error("invalid_occurrence_origin")
        if not isinstance(self.local_date, date) or isinstance(
            self.local_date, datetime
        ):
            raise validation_error("invalid_occurrence_local_date")
        _aware(self.scheduled_for, "occurrence_scheduled_for")
        _aware(self.eligible_until, "occurrence_eligible_until")
        if self.eligible_until <= self.scheduled_for:
            raise validation_error("invalid_occurrence_eligibility")
        seal_proactive_contract(self, "occurrence_digest")


@dataclass(frozen=True, slots=True)
class ConversationOpportunitySnapshot:
    schema_version: int
    opportunity_id: str
    scope: ConversationScope
    target_policy_ref: ProactiveTargetPolicyRef
    topic_refs: tuple[str, ...]
    topic_summary: str
    sensitivity: Sensitivity
    last_human_activity_at: datetime
    last_bot_activity_at: datetime | None
    expires_at: datetime
    producer_revision: ComponentRevision
    snapshot_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.opportunity_id, "opportunity_id")
        _group_scope(self.scope)
        if not isinstance(self.target_policy_ref, ProactiveTargetPolicyRef):
            raise validation_error("invalid_opportunity_target_policy_ref")
        if self.target_policy_ref.target_scope_digest != scope_digest(self.scope):
            raise validation_error("opportunity_target_scope_mismatch")
        refs = _strings(self.topic_refs, "topic_refs", required=True, maximum=64)
        _bounded_text(self.topic_summary, "topic_summary", maximum=4096)
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_opportunity_sensitivity")
        _aware(self.last_human_activity_at, "last_human_activity_at")
        _optional_aware(self.last_bot_activity_at, "last_bot_activity_at")
        _aware(self.expires_at, "opportunity_expires_at")
        if self.expires_at <= self.last_human_activity_at:
            raise validation_error("invalid_opportunity_expiry")
        if (
            self.last_bot_activity_at is not None
            and self.last_bot_activity_at > self.expires_at
        ):
            raise validation_error("invalid_opportunity_bot_activity")
        if not isinstance(self.producer_revision, ComponentRevision):
            raise validation_error("invalid_opportunity_producer_revision")
        object.__setattr__(self, "topic_refs", refs)
        seal_proactive_contract(self, "snapshot_digest")


@dataclass(frozen=True, slots=True)
class ProactiveTrigger:
    schema_version: int
    trigger_id: str
    kind: ProactiveTriggerKind
    target_scope: ConversationScope
    occurrence: ScheduleOccurrence | None
    opportunity: ConversationOpportunitySnapshot | None
    target_policy_ref: ProactiveTargetPolicyRef
    created_at: datetime
    expires_at: datetime
    trigger_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.trigger_id, "trigger_id")
        if not isinstance(self.kind, ProactiveTriggerKind):
            raise validation_error("invalid_proactive_trigger_kind")
        _group_scope(self.target_scope)
        if not isinstance(self.target_policy_ref, ProactiveTargetPolicyRef):
            raise validation_error("invalid_trigger_target_policy_ref")
        if self.target_policy_ref.target_scope_digest != scope_digest(
            self.target_scope
        ):
            raise validation_error("trigger_target_scope_mismatch")
        if self.kind is ProactiveTriggerKind.SCHEDULED_DIGEST:
            if (
                not isinstance(self.occurrence, ScheduleOccurrence)
                or self.opportunity is not None
            ):
                raise validation_error("scheduled_trigger_requires_occurrence")
        elif (
            not isinstance(self.opportunity, ConversationOpportunitySnapshot)
            or self.occurrence is not None
        ):
            raise validation_error("probe_trigger_requires_opportunity")
        if self.opportunity is not None and (
            self.opportunity.scope != self.target_scope
            or self.opportunity.target_policy_ref != self.target_policy_ref
        ):
            raise validation_error("opportunity_trigger_binding_mismatch")
        _aware(self.created_at, "trigger_created_at")
        _aware(self.expires_at, "trigger_expires_at")
        if self.expires_at <= self.created_at:
            raise validation_error("invalid_trigger_expiry")
        if (
            self.occurrence is not None
            and self.expires_at > self.occurrence.eligible_until
        ):
            raise validation_error("trigger_exceeds_occurrence_eligibility")
        if (
            self.opportunity is not None
            and self.expires_at > self.opportunity.expires_at
        ):
            raise validation_error("trigger_exceeds_opportunity_expiry")
        seal_proactive_contract(self, "trigger_digest")

    @property
    def source_digest(self) -> DigestString:
        if self.occurrence is not None:
            return self.occurrence.occurrence_digest
        assert self.opportunity is not None
        return self.opportunity.snapshot_digest


@dataclass(frozen=True, slots=True)
class InitiatedRunRequest:
    schema_version: int
    run_id: str
    trigger: ProactiveTrigger
    target_policy_ref: ProactiveTargetPolicyRef
    mode: DeliveryRunMode
    config_snapshot_id: str
    source_policy_revision: str
    response_policy_revision: str
    start_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.run_id, "proactive_run_id")
        if not isinstance(self.trigger, ProactiveTrigger) or not isinstance(
            self.target_policy_ref, ProactiveTargetPolicyRef
        ):
            raise validation_error("invalid_initiated_run_input")
        if self.target_policy_ref != self.trigger.target_policy_ref:
            raise validation_error("initiated_run_target_policy_mismatch")
        if (
            not isinstance(self.mode, ProactiveRunMode)
            or self.mode is ProactiveRunMode.PREVIEW
        ):
            raise validation_error("invalid_initiated_run_mode")
        _identifier(self.config_snapshot_id, "config_snapshot_id")
        _revision(self.source_policy_revision, "source_policy_revision")
        _revision(self.response_policy_revision, "response_policy_revision")
        seal_proactive_contract(self, "start_digest")


@dataclass(frozen=True, slots=True)
class ProactivePreviewRequest:
    schema_version: int
    preview_id: str
    mode: PreviewRunMode
    requested_by: Actor
    action: str
    subscription_id: str
    subscription_revision: int
    target_scope: ConversationScope
    target_policy_ref: ProactiveTargetPolicyRef
    config_snapshot_id: str
    source_policy_revision: str
    response_policy_revision: str
    request_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.preview_id, "preview_id")
        if self.mode is not ProactiveRunMode.PREVIEW:
            raise validation_error("invalid_preview_mode")
        if not isinstance(self.requested_by, Actor):
            raise validation_error("invalid_preview_actor")
        if self.action != "proactive.subscription.preview":
            raise validation_error("invalid_proactive_preview_action")
        _identifier(self.subscription_id, "subscription_id")
        _positive(self.subscription_revision, "subscription_revision")
        _group_scope(self.target_scope)
        if (
            self.requested_by.platform != self.target_scope.platform
            or self.requested_by.bot_id != self.target_scope.bot_id
        ):
            raise validation_error("preview_actor_scope_mismatch")
        if not isinstance(self.target_policy_ref, ProactiveTargetPolicyRef) or (
            self.target_policy_ref.target_scope_digest
            != scope_digest(self.target_scope)
        ):
            raise validation_error("preview_target_policy_mismatch")
        _identifier(self.config_snapshot_id, "config_snapshot_id")
        _revision(self.source_policy_revision, "source_policy_revision")
        _revision(self.response_policy_revision, "response_policy_revision")
        seal_proactive_contract(self, "request_digest")


@dataclass(frozen=True, slots=True)
class ProactivePreviewResult:
    schema_version: int
    preview_id: str
    mode: PreviewRunMode
    disposition: ProactiveDisposition
    request_digest: DigestString
    target_scope_digest: DigestString
    authorization_decision_digest: DigestString
    final_response: ValidatedFinalResponse | None
    validated_response_digest: DigestString | None
    response_plan_digest: DigestString | None
    source_batch_digest: DigestString | None
    reason_codes: tuple[str, ...]
    completed_at: datetime
    result_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.preview_id, "preview_id")
        if self.mode is not ProactiveRunMode.PREVIEW:
            raise validation_error("invalid_preview_mode")
        if self.disposition not in {
            ProactiveDisposition.PREVIEWED,
            ProactiveDisposition.DENIED,
            ProactiveDisposition.FAILED,
        }:
            raise validation_error("invalid_preview_disposition")
        for field_name in (
            "request_digest",
            "target_scope_digest",
            "authorization_decision_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        if self.final_response is None:
            if (
                self.validated_response_digest is not None
                or self.response_plan_digest is not None
            ):
                raise validation_error("preview_response_binding_without_response")
        else:
            if not isinstance(self.final_response, ValidatedFinalResponse):
                raise validation_error("invalid_preview_final_response")
            actual = canonical_digest(
                self.final_response.response,
                domain="response:final:v1",
            )
            if self.validated_response_digest != actual:
                raise validation_error("preview_response_digest_mismatch")
            if (
                self.response_plan_digest
                != self.final_response.response.render_metadata.response_plan_digest
            ):
                raise validation_error("preview_response_plan_mismatch")
        _optional_digest(self.source_batch_digest, "source_batch_digest")
        reasons = _reason_codes(self.reason_codes)
        _aware(self.completed_at, "preview_completed_at")
        object.__setattr__(self, "reason_codes", reasons)
        seal_proactive_contract(self, "result_digest")


@dataclass(frozen=True, slots=True)
class SourceFailure:
    source_id: str
    error_code: str
    retryable: bool

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _reason_code(self.error_code, "source_error_code")
        if type(self.retryable) is not bool:
            raise validation_error("invalid_source_failure_retryable")


@dataclass(frozen=True, slots=True)
class SourceItem:
    schema_version: int
    source_id: str
    external_id: str | None
    category: SourceCategory
    title: str
    summary: str
    canonical_url: str
    published_at: datetime | None
    observed_at: datetime
    source_revision: str
    citations: tuple[Citation, ...]
    warnings: tuple[str, ...]
    content_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.source_id, "source_id")
        if self.external_id is not None:
            _identifier(self.external_id, "external_id")
        if not isinstance(self.category, SourceCategory):
            raise validation_error("invalid_source_category")
        _bounded_text(self.title, "source_title", maximum=512)
        _bounded_text(self.summary, "source_summary", maximum=8192)
        parsed = urlsplit(self.canonical_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise validation_error("invalid_source_canonical_url")
        _optional_aware(self.published_at, "source_published_at")
        _aware(self.observed_at, "source_observed_at")
        if self.published_at is not None and self.published_at > self.observed_at:
            raise validation_error("source_published_after_observation")
        _revision(self.source_revision, "source_revision")
        citations = tuple(self.citations)
        if not citations or any(not isinstance(value, Citation) for value in citations):
            raise validation_error("source_item_requires_citation")
        if len({value.citation_id for value in citations}) != len(citations):
            raise validation_error("duplicate_source_citation")
        warnings = _reason_codes(self.warnings)
        object.__setattr__(self, "citations", citations)
        object.__setattr__(self, "warnings", warnings)
        seal_proactive_contract(self, "content_digest")


@dataclass(frozen=True, slots=True)
class SourceBatch:
    schema_version: int
    batch_id: str
    items: tuple[SourceItem, ...]
    succeeded_sources: tuple[str, ...]
    failed_sources: tuple[SourceFailure, ...]
    source_snapshot_revision: str
    observed_at: datetime
    batch_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.batch_id, "source_batch_id")
        items = tuple(self.items)
        if any(not isinstance(value, SourceItem) for value in items):
            raise validation_error("invalid_source_batch_item")
        if len({value.content_digest for value in items}) != len(items):
            raise validation_error("duplicate_source_batch_item")
        succeeded = _strings(
            self.succeeded_sources,
            "succeeded_sources",
            required=False,
            maximum=512,
        )
        failures = tuple(self.failed_sources)
        if any(not isinstance(value, SourceFailure) for value in failures):
            raise validation_error("invalid_source_failure")
        failed_ids = tuple(value.source_id for value in failures)
        if len(failed_ids) != len(set(failed_ids)) or set(succeeded) & set(failed_ids):
            raise validation_error("source_batch_status_conflict")
        if not succeeded and not failures:
            raise validation_error("empty_source_batch_status")
        _revision(self.source_snapshot_revision, "source_snapshot_revision")
        _aware(self.observed_at, "source_batch_observed_at")
        if any(value.observed_at > self.observed_at for value in items):
            raise validation_error("source_item_after_batch_observation")
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "succeeded_sources", succeeded)
        object.__setattr__(self, "failed_sources", failures)
        seal_proactive_contract(self, "batch_digest")


@dataclass(frozen=True, slots=True)
class ProactivePolicyDecision:
    schema_version: int
    decision_id: str
    trigger_digest: DigestString
    target_policy_ref: ProactiveTargetPolicyRef
    allowed: bool
    target_scope_digest: DigestString
    answer_profile: AnswerProfile
    maximum_items: int
    authorization_decision_digest: DigestString
    interaction_lease_id: str | None
    reason_codes: tuple[str, ...]
    policy_revision: str
    decided_at: datetime
    expires_at: datetime
    decision_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.decision_id, "proactive_decision_id")
        _digest(self.trigger_digest, "trigger_digest")
        if not isinstance(self.target_policy_ref, ProactiveTargetPolicyRef):
            raise validation_error("invalid_policy_target_ref")
        if type(self.allowed) is not bool:
            raise validation_error("invalid_proactive_policy_allowed")
        _digest(self.target_scope_digest, "target_scope_digest")
        if self.target_scope_digest != self.target_policy_ref.target_scope_digest:
            raise validation_error("policy_target_scope_mismatch")
        if not isinstance(self.answer_profile, AnswerProfile):
            raise validation_error("invalid_policy_answer_profile")
        if type(self.maximum_items) is not int or not 0 <= self.maximum_items <= 100:
            raise validation_error("invalid_policy_item_limit")
        _digest(self.authorization_decision_digest, "authorization_decision_digest")
        if self.interaction_lease_id is not None:
            _identifier(self.interaction_lease_id, "interaction_lease_id")
        reasons = _reason_codes(self.reason_codes)
        if not reasons:
            raise validation_error("empty_proactive_policy_reason_codes")
        _revision(self.policy_revision, "proactive_policy_revision")
        _aware(self.decided_at, "policy_decided_at")
        _aware(self.expires_at, "policy_expires_at")
        if self.expires_at <= self.decided_at:
            raise validation_error("invalid_policy_expiry")
        object.__setattr__(self, "reason_codes", reasons)
        seal_proactive_contract(self, "decision_digest")


@dataclass(frozen=True, slots=True)
class PreparedDispatch:
    schema_version: int
    dispatch_id: str
    trigger_kind: ProactiveTriggerKind
    trigger_digest: DigestString
    trigger_source_digest: DigestString
    target_policy_ref: ProactiveTargetPolicyRef
    policy_decision_digest: DigestString
    source_batch_digest: DigestString | None
    item_set_digest: DigestString | None
    response_plan_digest: DigestString
    validated_response_digest: DigestString
    validated_response: ValidatedFinalResponse
    target_scope: ConversationScope
    idempotency_key: str
    adapter_binding: NegotiatedBindingReceipt
    prepared_at: datetime
    expires_at: datetime
    prepared_dispatch_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.dispatch_id, "dispatch_id")
        if not isinstance(self.trigger_kind, ProactiveTriggerKind):
            raise validation_error("invalid_dispatch_trigger_kind")
        for field_name in (
            "trigger_digest",
            "trigger_source_digest",
            "policy_decision_digest",
            "response_plan_digest",
            "validated_response_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        _optional_digest(self.source_batch_digest, "source_batch_digest")
        _optional_digest(self.item_set_digest, "item_set_digest")
        if not isinstance(self.target_policy_ref, ProactiveTargetPolicyRef):
            raise validation_error("invalid_dispatch_target_policy_ref")
        _group_scope(self.target_scope)
        if self.target_policy_ref.target_scope_digest != scope_digest(
            self.target_scope
        ):
            raise validation_error("dispatch_target_scope_mismatch")
        if not isinstance(self.validated_response, ValidatedFinalResponse):
            raise validation_error("invalid_dispatch_response")
        actual_response_digest = canonical_digest(
            self.validated_response.response,
            domain="response:final:v1",
        )
        if self.validated_response_digest != actual_response_digest:
            raise validation_error("dispatch_response_digest_mismatch")
        if (
            self.response_plan_digest
            != self.validated_response.response.render_metadata.response_plan_digest
        ):
            raise validation_error("dispatch_response_plan_mismatch")
        expected_key = proactive_delivery_idempotency_key(
            trigger_kind=self.trigger_kind,
            trigger_source_digest=self.trigger_source_digest,
            target_scope=self.target_scope,
            item_set_digest=self.item_set_digest,
            validated_response_digest=self.validated_response_digest,
        )
        if self.idempotency_key != expected_key:
            raise validation_error("proactive_dispatch_idempotency_mismatch")
        if not isinstance(self.adapter_binding, NegotiatedBindingReceipt):
            raise validation_error("invalid_dispatch_adapter_binding")
        _aware(self.prepared_at, "dispatch_prepared_at")
        _aware(self.expires_at, "dispatch_expires_at")
        if self.expires_at <= self.prepared_at:
            raise validation_error("invalid_dispatch_expiry")
        seal_proactive_contract(self, "prepared_dispatch_digest")


@dataclass(frozen=True, slots=True)
class DispatchClaim:
    schema_version: int
    claim_id: str
    dispatch_id: str
    dispatch_digest: DigestString
    worker_id: str
    lease_revision: int
    claimed_at: datetime
    expires_at: datetime
    claim_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.claim_id, "dispatch_claim_id")
        _identifier(self.dispatch_id, "dispatch_id")
        _digest(self.dispatch_digest, "dispatch_digest")
        _identifier(self.worker_id, "dispatch_worker_id")
        _positive(self.lease_revision, "dispatch_lease_revision")
        _aware(self.claimed_at, "dispatch_claimed_at")
        _aware(self.expires_at, "dispatch_claim_expires_at")
        if self.expires_at <= self.claimed_at:
            raise validation_error("invalid_dispatch_claim_expiry")
        seal_proactive_contract(self, "claim_digest")


@dataclass(frozen=True, slots=True)
class ProactiveRunReceipt:
    schema_version: int
    run_id: str
    trigger_id: str
    mode: DeliveryRunMode
    disposition: ProactiveDisposition
    policy_decision_digest: DigestString | None
    source_batch_digest: DigestString | None
    prepared_dispatch_digest: DigestString | None
    delivery_receipt_digest: DigestString | None
    reason_codes: tuple[str, ...]
    completed_at: datetime
    receipt_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.run_id, "proactive_run_id")
        _identifier(self.trigger_id, "trigger_id")
        if (
            not isinstance(self.mode, ProactiveRunMode)
            or self.mode is ProactiveRunMode.PREVIEW
        ):
            raise validation_error("invalid_proactive_receipt_mode")
        if not isinstance(self.disposition, ProactiveDisposition):
            raise validation_error("invalid_proactive_disposition")
        for field_name in (
            "policy_decision_digest",
            "source_batch_digest",
            "prepared_dispatch_digest",
            "delivery_receipt_digest",
        ):
            _optional_digest(getattr(self, field_name), field_name)
        reasons = _reason_codes(self.reason_codes)
        if not reasons:
            raise validation_error("empty_proactive_receipt_reason_codes")
        _aware(self.completed_at, "proactive_receipt_completed_at")
        object.__setattr__(self, "reason_codes", reasons)
        seal_proactive_contract(self, "receipt_digest")


@dataclass(frozen=True, slots=True)
class ProactiveQuotaLease:
    schema_version: int
    lease_id: str
    kind: QuotaKind
    request_digest: DigestString
    scope_digest: DigestString | None
    allowed: bool
    units: int
    policy_revision: str
    reserved_at: datetime
    expires_at: datetime
    reason_codes: tuple[str, ...]
    lease_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.lease_id, "quota_lease_id")
        if not isinstance(self.kind, QuotaKind):
            raise validation_error("invalid_quota_kind")
        _digest(self.request_digest, "quota_request_digest")
        if self.kind is QuotaKind.SCOPE:
            _digest(self.scope_digest, "quota_scope_digest")
        elif self.scope_digest is not None:
            raise validation_error("global_quota_forbids_scope")
        if type(self.allowed) is not bool:
            raise validation_error("invalid_quota_allowed")
        _positive(self.units, "quota_units")
        _revision(self.policy_revision, "quota_policy_revision")
        _aware(self.reserved_at, "quota_reserved_at")
        _aware(self.expires_at, "quota_expires_at")
        if self.expires_at <= self.reserved_at:
            raise validation_error("invalid_quota_expiry")
        reasons = _reason_codes(self.reason_codes)
        object.__setattr__(self, "reason_codes", reasons)
        seal_proactive_contract(self, "lease_digest")


def validate_target_policy_ref(
    policy: ProactiveTargetPolicy,
    reference: ProactiveTargetPolicyRef,
) -> ProactiveTargetPolicy:
    if not isinstance(policy, ProactiveTargetPolicy) or not isinstance(
        reference, ProactiveTargetPolicyRef
    ):
        raise validation_error("invalid_target_policy_ref_input")
    if policy.as_ref() != reference:
        raise validation_error("target_policy_ref_mismatch")
    return policy


def validate_grant_ref(
    grant: ProactiveAuthorizationGrant,
    reference: ProactiveAuthorizationGrantRef,
    *,
    expected_kind: ProactiveGrantKind,
) -> ProactiveAuthorizationGrant:
    if (
        not isinstance(grant, ProactiveAuthorizationGrant)
        or not isinstance(reference, ProactiveAuthorizationGrantRef)
        or not isinstance(expected_kind, ProactiveGrantKind)
    ):
        raise validation_error("invalid_grant_ref_input")
    if grant.grant_kind is not expected_kind or grant.as_ref() != reference:
        raise validation_error("proactive_grant_ref_mismatch")
    return grant


def _v1(value: object) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise validation_error("invalid_proactive_identifier", field_name)
    return value


def _revision(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise validation_error("invalid_proactive_revision", field_name)
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise validation_error("invalid_proactive_digest", field_name)
    return value


def _optional_digest(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _digest(value, field_name)


def _positive(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise validation_error("invalid_proactive_positive_integer", field_name)
    return value


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise validation_error("invalid_proactive_datetime", field_name)
    require_aware(value, field_name)
    return value


def _optional_aware(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _aware(value, field_name)


def _group_scope(value: object) -> ConversationScope:
    if not isinstance(value, ConversationScope) or (
        value.conversation_type is not ConversationType.GROUP
    ):
        raise validation_error("proactive_target_requires_group_scope")
    return value


def _enum_set(
    values: object,
    item_type: type[StrEnum],
    field_name: str,
    *,
    required: bool,
) -> frozenset:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_proactive_enum_set", field_name)
    try:
        result = frozenset(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_proactive_enum_set", field_name) from None
    if (required and not result) or any(
        not isinstance(value, item_type) for value in result
    ):
        raise validation_error("invalid_proactive_enum_set", field_name)
    return result


def _strings(
    values: object,
    field_name: str,
    *,
    required: bool,
    maximum: int,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_proactive_strings", field_name)
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_proactive_strings", field_name) from None
    if (
        (required and not result)
        or len(result) > maximum
        or len(result) != len(set(result))
        or any(
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > 512
            for value in result
        )
    ):
        raise validation_error("invalid_proactive_strings", field_name)
    return result


def _reason_code(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _REASON_RE.fullmatch(value) is None:
        raise validation_error("invalid_proactive_reason_code", field_name)
    return value


def _reason_codes(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_proactive_reason_codes")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_proactive_reason_codes") from None
    if len(result) != len(set(result)):
        raise validation_error("duplicate_proactive_reason_code")
    for value in result:
        _reason_code(value, "reason_codes")
    return tuple(sorted(result))


def _bounded_text(value: object, field_name: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
    ):
        raise validation_error("invalid_proactive_text", field_name)
    return value


__all__ = [
    "ConversationOpportunitySnapshot",
    "DeliveryRunMode",
    "DispatchClaim",
    "DispatchPrepareDisposition",
    "DispatchState",
    "InitiatedRunRequest",
    "LocalTimeWindow",
    "PreparedDispatch",
    "PreviewRunMode",
    "ProactiveAuthorizationGrant",
    "ProactiveAuthorizationGrantRef",
    "ProactiveDisposition",
    "ProactiveGrantKind",
    "ProactivePolicyDecision",
    "ProactivePreviewRequest",
    "ProactivePreviewResult",
    "ProactiveQuotaLease",
    "ProactiveRunMode",
    "ProactiveRunReceipt",
    "ProactiveSubscription",
    "ProactiveTargetPolicy",
    "ProactiveTargetPolicyRef",
    "ProactiveTargetPolicyStatus",
    "ProactiveTrigger",
    "ProactiveTriggerKind",
    "QuotaKind",
    "ScheduleOccurrence",
    "ScheduleOccurrenceOrigin",
    "ScheduleSpec",
    "SourceBatch",
    "SourceCategory",
    "SourceFailure",
    "SourceItem",
    "SubscriptionStatus",
    "validate_grant_ref",
    "validate_target_policy_ref",
]
