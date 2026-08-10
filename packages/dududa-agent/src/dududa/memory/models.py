from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
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


class MemoryRetrievalStrategy(StrEnum):
    NO_MEMORY = "no_memory"
    RECENCY = "recency"
    CJK_BM25 = "cjk_bm25"


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
        if (
            self.memory_type
            in {
                MemoryType.USER_PROFILE,
                MemoryType.EXPLICIT_USER_MEMORY,
            }
            and not self.user_id
        ):
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
    state_revision: int
    selector_digests: tuple[DigestString, ...]
    request_digest: DigestString
    as_of: datetime
    expires_at: datetime
    integrity_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("snapshot_id", "repository_revision"):
            require_non_empty(str(getattr(self, name)), name)
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise validation_error("invalid_memory_state_revision")
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
class IndexableMemoryProjection:
    schema_version: int
    memory_id: str
    text: str
    content_digest: DigestString
    scope_digest: DigestString
    sensitivity: Sensitivity
    visibility: Visibility
    updated_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.memory_id, "memory_id")
        require_non_empty(self.text, "memory_projection_text")
        require_non_empty(str(self.content_digest), "content_digest")
        require_non_empty(str(self.scope_digest), "scope_digest")
        if not isinstance(self.sensitivity, Sensitivity):
            raise validation_error("invalid_sensitivity")
        if not isinstance(self.visibility, Visibility):
            raise validation_error("invalid_memory_visibility")
        require_aware(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True)
class MemoryRankRequest:
    schema_version: int
    request_digest: DigestString
    query: str
    projections: tuple[IndexableMemoryProjection, ...]
    limit: int
    state_revision: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.request_digest), "request_digest")
        require_non_empty(self.query, "memory_rank_query")
        projections = tuple(self.projections)
        if (
            not projections
            or len(projections) > 400
            or any(
                not isinstance(item, IndexableMemoryProjection) for item in projections
            )
            or len({item.memory_id for item in projections}) != len(projections)
        ):
            raise validation_error("invalid_memory_rank_projections")
        if type(self.limit) is not int or not 1 <= self.limit <= len(projections):
            raise validation_error("invalid_memory_rank_limit")
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise validation_error("invalid_memory_state_revision")
        object.__setattr__(self, "projections", projections)


@dataclass(frozen=True, slots=True)
class MemoryRankScore:
    schema_version: int
    memory_id: str
    content_digest: DigestString
    scope_digest: DigestString
    score: Decimal
    ranker_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.memory_id, "memory_id")
        require_non_empty(str(self.content_digest), "content_digest")
        require_non_empty(str(self.scope_digest), "scope_digest")
        if (
            not isinstance(self.score, Decimal)
            or not self.score.is_finite()
            or self.score < 0
        ):
            raise validation_error("invalid_memory_rank_score")


@dataclass(frozen=True, slots=True)
class MemoryRetrievalRequest:
    schema_version: int
    query_id: str
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    query: MemoryQuery
    memory_types: frozenset[MemoryType]
    strategy: MemoryRetrievalStrategy
    limit: int
    candidate_limit_per_type: int
    candidate_limit_total: int
    as_of: datetime
    allow_recency_degrade: bool = True

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.query_id, "query_id")
        require_non_empty(str(self.request_digest), "request_digest")
        require_aware(self.as_of, "as_of")
        memory_types = frozenset(self.memory_types)
        if not memory_types or any(
            not isinstance(item, MemoryType) for item in memory_types
        ):
            raise validation_error("invalid_retrieval_memory_types")
        if not isinstance(self.strategy, MemoryRetrievalStrategy):
            raise validation_error("invalid_memory_retrieval_strategy")
        if (
            self.actor.platform != self.conversation_scope.platform
            or self.actor.bot_id != self.conversation_scope.bot_id
        ):
            raise validation_error("memory_retrieval_identity_scope_mismatch")
        if self.query.reference_time != self.as_of:
            raise validation_error("memory_retrieval_time_mismatch")
        values = (
            self.limit,
            self.candidate_limit_per_type,
            self.candidate_limit_total,
        )
        if (
            any(type(value) is not int or value < 1 for value in values)
            or self.limit > 100
            or self.candidate_limit_per_type > 100
            or self.candidate_limit_total > 400
            or self.limit > self.candidate_limit_total
            or self.candidate_limit_per_type > self.candidate_limit_total
            or type(self.allow_recency_degrade) is not bool
        ):
            raise validation_error("invalid_memory_retrieval_limits")
        object.__setattr__(self, "memory_types", memory_types)


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    schema_version: int
    record: MemoryRecord
    rank: int
    score: Decimal | None
    strategy: MemoryRetrievalStrategy
    ranker_revision: ComponentRevision | None

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if type(self.rank) is not int or self.rank < 1:
            raise validation_error("invalid_memory_match_rank")
        if not isinstance(self.strategy, MemoryRetrievalStrategy):
            raise validation_error("invalid_memory_retrieval_strategy")
        if self.score is not None and (
            not isinstance(self.score, Decimal)
            or not self.score.is_finite()
            or self.score < 0
        ):
            raise validation_error("invalid_memory_rank_score")
        if self.strategy is MemoryRetrievalStrategy.CJK_BM25:
            if self.score is None or self.ranker_revision is None:
                raise validation_error("bm25_memory_match_missing_rank_evidence")
        elif self.score is not None or self.ranker_revision is not None:
            raise validation_error("non_bm25_memory_match_has_rank_evidence")


@dataclass(frozen=True, slots=True)
class MemoryConflictGroup:
    schema_version: int
    conflict_id: str
    matches: tuple[MemoryMatch, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(self.conflict_id, "conflict_id")
        matches = tuple(self.matches)
        reasons = tuple(self.reason_codes)
        if len(matches) < 2 or len({item.record.memory_id for item in matches}) != len(
            matches
        ):
            raise validation_error("invalid_memory_conflict_matches")
        _validate_reason_codes(reasons)
        object.__setattr__(self, "matches", matches)
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class MemoryRetrievalResult:
    schema_version: int
    request_digest: DigestString
    strategy: MemoryRetrievalStrategy
    matches: tuple[MemoryMatch, ...]
    conflicts: tuple[MemoryConflictGroup, ...]
    repository_snapshot_id: str | None
    repository_revision: str | None
    state_revision: int | None
    policy_revision: str
    ranker_revision: ComponentRevision | None
    retriever_revision: ComponentRevision
    degraded: bool
    reason_codes: tuple[str, ...]
    result_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        require_non_empty(str(self.request_digest), "request_digest")
        require_non_empty(self.policy_revision, "policy_revision")
        if not isinstance(self.strategy, MemoryRetrievalStrategy):
            raise validation_error("invalid_memory_retrieval_strategy")
        matches = tuple(self.matches)
        conflicts = tuple(self.conflicts)
        reasons = tuple(self.reason_codes)
        if (
            len(matches) > 100
            or len({item.record.memory_id for item in matches}) != len(matches)
            or tuple(item.rank for item in matches) != tuple(range(1, len(matches) + 1))
            or type(self.degraded) is not bool
        ):
            raise validation_error("invalid_memory_retrieval_result")
        _validate_reason_codes(reasons)
        if self.strategy is MemoryRetrievalStrategy.NO_MEMORY:
            if (
                matches
                or conflicts
                or self.repository_snapshot_id is not None
                or self.repository_revision is not None
                or self.state_revision is not None
                or self.ranker_revision is not None
                or self.degraded
            ):
                raise validation_error("invalid_no_memory_result")
        elif (
            self.repository_snapshot_id is None
            or not self.repository_snapshot_id.strip()
            or self.repository_revision is None
            or not self.repository_revision.strip()
            or type(self.state_revision) is not int
            or self.state_revision < 0
        ):
            raise validation_error("memory_result_missing_repository_evidence")
        if self.strategy is MemoryRetrievalStrategy.CJK_BM25 and not self.degraded:
            if self.ranker_revision is None:
                raise validation_error("bm25_result_missing_ranker_revision")
        elif self.ranker_revision is not None:
            raise validation_error("non_bm25_result_has_ranker_revision")
        object.__setattr__(self, "matches", matches)
        object.__setattr__(self, "conflicts", conflicts)
        object.__setattr__(self, "reason_codes", reasons)


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


@dataclass(frozen=True, slots=True)
class MemoryDeleteCommand:
    schema_version: int
    command_id: str
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    memory_id: str
    expected_version: int
    record_digest: DigestString
    authorization: AuthorizationDecision
    confirmation: ConfirmationGrant
    idempotency_key: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("command_id", "memory_id", "idempotency_key"):
            require_non_empty(str(getattr(self, name)), name)
        require_non_empty(str(self.request_digest), "request_digest")
        require_non_empty(str(self.record_digest), "record_digest")
        if type(self.expected_version) is not int or self.expected_version < 1:
            raise validation_error("invalid_memory_expected_version")
        if (
            self.actor.platform != self.conversation_scope.platform
            or self.actor.bot_id != self.conversation_scope.bot_id
        ):
            raise validation_error("memory_delete_identity_scope_mismatch")


@dataclass(frozen=True, slots=True)
class MemoryTombstone:
    schema_version: int
    tombstone_id: str
    memory_id: str
    scope: MemoryScope
    deleted_record_digest: DigestString
    content_hash: DigestString
    deleted_version: int
    delete_command_digest: DigestString
    authorization_digest: DigestString
    confirmation_digest: DigestString
    policy_revision: str
    writer_revision: ComponentRevision
    deleted_at: datetime
    state_revision: int
    integrity_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("tombstone_id", "memory_id", "policy_revision"):
            require_non_empty(str(getattr(self, name)), name)
        for name in (
            "deleted_record_digest",
            "content_hash",
            "delete_command_digest",
            "authorization_digest",
            "confirmation_digest",
            "integrity_digest",
        ):
            require_non_empty(str(getattr(self, name)), name)
        if type(self.deleted_version) is not int or self.deleted_version < 1:
            raise validation_error("invalid_memory_deleted_version")
        if type(self.state_revision) is not int or self.state_revision < 1:
            raise validation_error("invalid_memory_state_revision")
        require_aware(self.deleted_at, "deleted_at")


@dataclass(frozen=True, slots=True)
class MemoryDeleteReceipt:
    schema_version: int
    command_id: str
    request_digest: DigestString
    idempotency_key: str
    memory_id: str
    deleted_version: int
    tombstone_digest: DigestString
    state_revision: int
    policy_revision: str
    writer_revision: ComponentRevision
    completed_at: datetime
    receipt_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("command_id", "idempotency_key", "memory_id", "policy_revision"):
            require_non_empty(str(getattr(self, name)), name)
        for name in ("request_digest", "tombstone_digest", "receipt_digest"):
            require_non_empty(str(getattr(self, name)), name)
        if type(self.deleted_version) is not int or self.deleted_version < 1:
            raise validation_error("invalid_memory_deleted_version")
        if type(self.state_revision) is not int or self.state_revision < 1:
            raise validation_error("invalid_memory_state_revision")
        require_aware(self.completed_at, "completed_at")


@dataclass(frozen=True, slots=True)
class MemoryExportPage:
    schema_version: int
    records: tuple[MemoryRecord, ...]
    next_cursor: str | None
    repository_revision: str
    state_revision: int
    snapshot_id: str
    exported_at: datetime
    export_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        records = tuple(self.records)
        if len({item.memory_id for item in records}) != len(records):
            raise validation_error("duplicate_memory_export_record")
        for name in ("repository_revision", "snapshot_id"):
            require_non_empty(str(getattr(self, name)), name)
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise validation_error("invalid_memory_state_revision")
        require_aware(self.exported_at, "exported_at")
        require_non_empty(str(self.export_digest), "export_digest")
        object.__setattr__(self, "records", records)


@dataclass(frozen=True, slots=True)
class MemoryTombstoneCheckpoint:
    schema_version: int
    checkpoint_id: str
    repository_revision: str
    state_revision: int
    tombstones: tuple[MemoryTombstone, ...]
    created_at: datetime
    checkpoint_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("checkpoint_id", "repository_revision"):
            require_non_empty(str(getattr(self, name)), name)
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise validation_error("invalid_memory_state_revision")
        tombstones = tuple(self.tombstones)
        if len({item.memory_id for item in tombstones}) != len(tombstones) or any(
            item.state_revision > self.state_revision for item in tombstones
        ):
            raise validation_error("invalid_memory_tombstone_checkpoint")
        require_aware(self.created_at, "created_at")
        require_non_empty(str(self.checkpoint_digest), "checkpoint_digest")
        object.__setattr__(self, "tombstones", tombstones)


@dataclass(frozen=True, slots=True)
class MemoryRepositoryArchive:
    schema_version: int
    archive_id: str
    repository_revision: str
    state_revision: int
    records: tuple[MemoryRecord, ...]
    tombstone_checkpoint: MemoryTombstoneCheckpoint
    exported_at: datetime
    archive_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("archive_id", "repository_revision"):
            require_non_empty(str(getattr(self, name)), name)
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise validation_error("invalid_memory_state_revision")
        records = tuple(self.records)
        record_ids = {item.memory_id for item in records}
        tombstone_ids = {
            item.memory_id for item in self.tombstone_checkpoint.tombstones
        }
        if (
            len(record_ids) != len(records)
            or record_ids & tombstone_ids
            or self.tombstone_checkpoint.repository_revision != self.repository_revision
            or self.tombstone_checkpoint.state_revision != self.state_revision
        ):
            raise validation_error("invalid_memory_repository_archive")
        require_aware(self.exported_at, "exported_at")
        require_non_empty(str(self.archive_digest), "archive_digest")
        object.__setattr__(self, "records", records)


@dataclass(frozen=True, slots=True)
class MemoryRestoreCommand:
    schema_version: int
    command_id: str
    request_digest: DigestString
    archive: MemoryRepositoryArchive
    recovery_checkpoint: MemoryTombstoneCheckpoint
    expected_state_revision: int
    required_checkpoint_state_revision: int
    idempotency_key: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("command_id", "idempotency_key"):
            require_non_empty(str(getattr(self, name)), name)
        require_non_empty(str(self.request_digest), "request_digest")
        for name in (
            "expected_state_revision",
            "required_checkpoint_state_revision",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise validation_error("invalid_memory_state_revision", name)
        if (
            self.recovery_checkpoint.state_revision
            < self.required_checkpoint_state_revision
        ):
            raise validation_error("stale_memory_recovery_checkpoint")


@dataclass(frozen=True, slots=True)
class MemoryRestoreReceipt:
    schema_version: int
    command_id: str
    request_digest: DigestString
    idempotency_key: str
    archive_digest: DigestString
    checkpoint_digest: DigestString
    restored_records: int
    suppressed_records: int
    state_revision_before: int
    state_revision_after: int
    writer_revision: ComponentRevision
    completed_at: datetime
    receipt_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for name in ("command_id", "idempotency_key"):
            require_non_empty(str(getattr(self, name)), name)
        for name in (
            "request_digest",
            "archive_digest",
            "checkpoint_digest",
            "receipt_digest",
        ):
            require_non_empty(str(getattr(self, name)), name)
        values = (
            self.restored_records,
            self.suppressed_records,
            self.state_revision_before,
            self.state_revision_after,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise validation_error("invalid_memory_restore_counts")
        if self.state_revision_after <= self.state_revision_before:
            raise validation_error("memory_restore_revision_not_advanced")
        require_aware(self.completed_at, "completed_at")


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _validate_reason_codes(values: tuple[str, ...]) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values) or len(
        values
    ) != len(set(values)):
        raise validation_error("invalid_reason_codes")
