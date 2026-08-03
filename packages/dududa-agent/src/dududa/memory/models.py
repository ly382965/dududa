from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Generic, TypeVar

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.delivery import DeliveryStatus
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    Sensitivity,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error
from dududa.security.models import (
    AuthorizationDecision,
    ConfirmationGrant,
    ConfirmationRequirement,
)


class MemoryType(StrEnum):
    USER_PROFILE = "user_profile"
    GROUP_MEMORY = "group_memory"
    EPISODIC = "episodic"
    EXPLICIT_USER_MEMORY = "explicit_user_memory"


class MemorySource(StrEnum):
    EXPLICIT_USER_REQUEST = "explicit_user_request"
    OBSERVED_USER_STATEMENT = "observed_user_statement"
    CONVERSATION_SUMMARY = "conversation_summary"
    TOOL_RESULT = "tool_result"
    ADMIN_MIGRATION = "administrator_migration"
    LEGACY_IMPORT = "legacy_import"


class Visibility(StrEnum):
    CURRENT_CONVERSATION = "current_conversation"
    CURRENT_GROUP = "current_group"
    SAFE_USER_PROFILE = "safe_user_profile"


class SelectorMode(StrEnum):
    CURRENT_CONVERSATION = "current_conversation"
    CURRENT_GROUP = "current_group"
    SAFE_USER_PROFILE = "safe_user_profile"


class DeliveryDependency(StrEnum):
    NONE = "none"
    SUCCESS_REQUIRED = "success_required"


class MemoryWriteAction(StrEnum):
    REJECT = "reject"
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DEFER_FOR_CONFLICT_RESOLUTION = "defer_for_conflict_resolution"


class MemorySubmissionStatus(StrEnum):
    REJECTED = "rejected"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DEFERRED = "deferred"
    QUEUED = "queued"
    PERSISTED = "persisted"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    reference_id: str
    source_type: str
    source_id: str
    source_user_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("reference_id", "source_type", "source_id"):
            require_non_empty(str(getattr(self, name)), name)


@dataclass(frozen=True, slots=True)
class MemoryScope:
    schema_version: int
    platform: str
    bot_id: str
    conversation_type: ConversationType
    conversation_id: str
    group_id: str | None
    user_id: str | None
    persona_id: str
    memory_type: MemoryType

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("platform", "bot_id", "conversation_id", "persona_id"):
            require_non_empty(str(getattr(self, name)), name)
        if self.group_id is not None:
            require_non_empty(self.group_id, "group_id")
        if self.user_id is not None:
            require_non_empty(self.user_id, "user_id")
        if not isinstance(self.conversation_type, ConversationType):
            raise validation_error("invalid_conversation_type")
        if not isinstance(self.memory_type, MemoryType):
            raise validation_error("invalid_memory_type")
        if self.conversation_type is ConversationType.GROUP:
            if not self.group_id or self.group_id != self.conversation_id:
                raise validation_error("invalid_group_memory_scope")
        elif self.group_id is not None:
            raise validation_error("non_group_memory_forbids_group_id")
        if (
            self.conversation_type is ConversationType.PRIVATE
            and self.conversation_id.strip().lower() == "private"
        ):
            raise validation_error("ambiguous_private_conversation_id")
        if self.memory_type in {
            MemoryType.USER_PROFILE,
            MemoryType.EXPLICIT_USER_MEMORY,
        }:
            if not self.user_id:
                raise validation_error("user_owned_memory_requires_user")
        if self.memory_type is MemoryType.GROUP_MEMORY:
            if self.conversation_type is not ConversationType.GROUP:
                raise validation_error("group_memory_requires_group_scope")
            if self.user_id is not None:
                raise validation_error("group_memory_forbids_user_owner")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    schema_version: int
    memory_id: str
    scope: MemoryScope
    content: str
    source: MemorySource
    created_at: datetime
    updated_at: datetime
    confidence: float
    expires_at: datetime | None
    sensitivity: Sensitivity
    visibility: Visibility
    evidence: tuple[EvidenceReference, ...]
    content_hash: DigestString
    version: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.memory_id, "memory_id")
        require_non_empty(self.content, "memory_content")
        require_non_empty(str(self.content_hash), "content_hash")
        expected_content_hash = canonical_digest(
            {"content": self.content},
            domain="memory:content:v1",
        )
        if self.content_hash != expected_content_hash:
            raise validation_error("memory_content_hash_mismatch")
        if not isinstance(self.source, MemorySource):
            raise validation_error("invalid_memory_source")
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_sensitivity")
        if not isinstance(self.visibility, Visibility):
            raise validation_error("invalid_memory_visibility")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise validation_error("memory_updated_before_created")
        if self.expires_at is not None:
            require_aware(self.expires_at, "expires_at")
            if self.expires_at <= self.created_at:
                raise validation_error("memory_expiry_not_future")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise validation_error("invalid_memory_confidence")
        if type(self.version) is not int or self.version < 1:
            raise validation_error("invalid_memory_version")
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    schema_version: int
    text: str
    locale: str
    reference_time: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.locale, "locale")
        require_aware(self.reference_time, "reference_time")


@dataclass(frozen=True, slots=True)
class PageRequest:
    schema_version: int
    cursor: str | None
    limit: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise validation_error("invalid_page_limit")


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    schema_version: int
    items: tuple[T, ...]
    next_cursor: str | None
    snapshot_revision: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.snapshot_revision, "snapshot_revision")
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True, slots=True)
class ScopeSelector:
    schema_version: int
    selector_id: str
    request_digest: DigestString
    mode: SelectorMode
    policy_revision: str
    purpose: str
    actor_ref: str
    current_scope_digest: DigestString
    platform: str
    bot_id: str
    persona_id: str
    conversation_id: str | None
    group_id: str | None
    user_id: str | None
    memory_types: frozenset[MemoryType]
    issued_at: datetime
    expires_at: datetime
    integrity_proof: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in (
            "selector_id",
            "policy_revision",
            "purpose",
            "actor_ref",
            "platform",
            "bot_id",
            "persona_id",
            "integrity_proof",
        ):
            require_non_empty(str(getattr(self, name)), name)
        for name in ("request_digest", "current_scope_digest"):
            require_non_empty(str(getattr(self, name)), name)
        if not isinstance(self.mode, SelectorMode):
            raise validation_error("invalid_selector_mode")
        types = frozenset(self.memory_types)
        if not types or any(not isinstance(item, MemoryType) for item in types):
            raise validation_error("invalid_selector_memory_types")
        require_aware(self.issued_at, "issued_at")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise validation_error("invalid_selector_expiry")
        if self.mode is SelectorMode.CURRENT_CONVERSATION:
            if not self.conversation_id:
                raise validation_error("conversation_selector_requires_conversation")
        elif self.mode is SelectorMode.CURRENT_GROUP:
            if not self.group_id or self.conversation_id != self.group_id:
                raise validation_error("group_selector_requires_exact_group")
        elif self.mode is SelectorMode.SAFE_USER_PROFILE:
            if not self.user_id or types != {MemoryType.USER_PROFILE}:
                raise validation_error("safe_profile_selector_invalid")
            if self.conversation_id is not None or self.group_id is not None:
                raise validation_error("safe_profile_selector_forbids_conversation")
        object.__setattr__(self, "memory_types", types)


@dataclass(frozen=True, slots=True)
class MemoryRepositorySnapshot:
    schema_version: int
    snapshot_id: str
    repository_revision: str
    selector_digests: tuple[DigestString, ...]
    request_digest: DigestString
    as_of: datetime
    expires_at: datetime
    integrity_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("snapshot_id", "repository_revision"):
            require_non_empty(str(getattr(self, name)), name)
        for name in ("request_digest", "integrity_digest"):
            require_non_empty(str(getattr(self, name)), name)
        digests = tuple(self.selector_digests)
        if not digests:
            raise validation_error("empty_memory_snapshot_selectors")
        require_aware(self.as_of, "as_of")
        require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.as_of:
            raise validation_error("invalid_memory_snapshot_expiry")
        object.__setattr__(self, "selector_digests", digests)


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    schema_version: int
    candidate_id: str
    producer: ComponentRevision
    proposed_content: str
    source: MemorySource
    proposed_type: MemoryType
    proposed_scope: MemoryScope
    confidence: float
    sensitivity_hint: Sensitivity
    evidence: tuple[EvidenceReference, ...]
    proposed_ttl: timedelta | None
    delivery_dependency: DeliveryDependency

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.candidate_id, "candidate_id")
        require_non_empty(self.proposed_content, "proposed_content")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise validation_error("invalid_memory_confidence")
        if self.proposed_ttl is not None and self.proposed_ttl <= timedelta(0):
            raise validation_error("invalid_memory_ttl")
        if not isinstance(self.delivery_dependency, DeliveryDependency):
            raise validation_error("invalid_delivery_dependency")
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class MemoryWriteRequest:
    schema_version: int
    request_digest: DigestString
    candidate: MemoryCandidate
    actor: Actor
    conversation_scope: ConversationScope
    delivery_status: DeliveryStatus
    delivery_id: str | None
    delivery_receipt_digest: DigestString | None
    confirmation: ConfirmationGrant | None
    authorization: AuthorizationDecision
    idempotency_key: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.request_digest), "request_digest")
        require_non_empty(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, slots=True)
class MemoryWriteDecision:
    schema_version: int
    decision_id: str
    request_digest: DigestString
    candidate_id: str
    candidate_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    delivery_id: str | None
    delivery_status: DeliveryStatus
    delivery_receipt_digest: DigestString | None
    confirmation_digest: DigestString | None
    authorization_digest: DigestString
    idempotency_key: str
    action: MemoryWriteAction
    reason_codes: tuple[str, ...]
    normalized_record: MemoryRecord | None
    expected_record_version: int | None
    confirmation: ConfirmationRequirement | None
    policy_revision: str
    gate_revision: ComponentRevision
    decision_expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in (
            "decision_id",
            "candidate_id",
            "idempotency_key",
            "policy_revision",
        ):
            require_non_empty(str(getattr(self, name)), name)
        require_aware(self.decision_expires_at, "decision_expires_at")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        if self.action is MemoryWriteAction.ALLOW and self.normalized_record is None:
            raise validation_error("allowed_memory_decision_requires_record")
        if (
            self.action is not MemoryWriteAction.ALLOW
            and self.normalized_record is not None
        ):
            raise validation_error("rejected_memory_decision_has_record")


@dataclass(frozen=True, slots=True)
class MemoryWriteCommand:
    schema_version: int
    command_id: str
    request_digest: DigestString
    decision: MemoryWriteDecision
    actor: Actor
    conversation_scope: ConversationScope
    delivery_id: str | None
    delivery_status: DeliveryStatus
    delivery_receipt_digest: DigestString | None
    confirmation: ConfirmationGrant | None
    authorization: AuthorizationDecision
    idempotency_key: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.command_id, "command_id")
        require_non_empty(str(self.request_digest), "request_digest")
        require_non_empty(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, slots=True)
class MemorySubmissionReceipt:
    schema_version: int
    command_id: str
    decision_id: str
    candidate_id: str
    idempotency_key: str
    status: MemorySubmissionStatus
    memory_id: str | None
    outbox_event_id: str | None
    policy_revision: str
    producer: ComponentRevision
    writer_revision: ComponentRevision | None
    reason_codes: tuple[str, ...]
    recorded_at: datetime


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")
