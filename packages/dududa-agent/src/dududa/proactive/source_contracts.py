from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from dududa._compat import StrEnum
from dududa.domain.primitives import (
    DigestString,
    JsonValue,
    PrivacyLevel,
    freeze_json,
    require_aware,
    require_non_empty,
)
from dududa.errors import validation_error

from .contracts import SourceBatch, SourceCategory, SourceFailure
from .digests import seal_proactive_contract

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_HOST = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)


class SourceIdentityRule(StrEnum):
    EXTERNAL_ID = "external_id"
    ARXIV_BASE_ID = "arxiv_base_id"
    CANONICAL_URL = "canonical_url"


class SourceFetchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NO_NEW_ITEMS = "no_new_items"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceFetchOriginKind(StrEnum):
    SCHEDULED_TRIGGER = "scheduled_trigger"
    PREVIEW_REQUEST = "preview_request"


class SourceDedupDisposition(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"
    REVISION_HELD = "revision_held"
    REVISION_EMIT = "revision_emit"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    schema_version: int
    source_id: str
    category: SourceCategory
    capability_id: str
    capability_definition_digest: DigestString
    allowed_hosts: frozenset[str]
    allowed_path_prefixes: tuple[str, ...]
    identity_rule: SourceIdentityRule
    maximum_age: timedelta
    maximum_items: int
    maximum_payload_bytes: int
    require_published_at: bool
    notify_revisions: bool
    schema_revision: str
    result_mapping_revision: str
    definition_revision: str
    definition_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.source_id, "source_id")
        if not isinstance(self.category, SourceCategory):
            raise validation_error("invalid_source_definition_category")
        _identifier(self.capability_id, "source_capability_id")
        _digest(
            self.capability_definition_digest,
            "source_capability_definition_digest",
        )
        hosts = frozenset(self.allowed_hosts)
        if not hosts or any(
            not isinstance(value, str)
            or value != value.lower()
            or _HOST.fullmatch(value) is None
            for value in hosts
        ):
            raise validation_error("invalid_source_allowed_hosts")
        paths = tuple(self.allowed_path_prefixes)
        if (
            not paths
            or paths != tuple(sorted(set(paths)))
            or any(
                not isinstance(value, str)
                or not value.startswith("/")
                or "?" in value
                or "#" in value
                or "%" in value
                or "\\" in value
                or "//" in value
                or any(segment in {".", ".."} for segment in value.split("/"))
                for value in paths
            )
        ):
            raise validation_error("invalid_source_allowed_paths")
        if not isinstance(self.identity_rule, SourceIdentityRule):
            raise validation_error("invalid_source_identity_rule")
        if not isinstance(self.maximum_age, timedelta) or not (
            timedelta(minutes=1) <= self.maximum_age <= timedelta(days=365)
        ):
            raise validation_error("invalid_source_maximum_age")
        if type(self.maximum_items) is not int or not 1 <= self.maximum_items <= 100:
            raise validation_error("invalid_source_maximum_items")
        if type(self.maximum_payload_bytes) is not int or not (
            1_024 <= self.maximum_payload_bytes <= 1_048_576
        ):
            raise validation_error("invalid_source_payload_limit")
        if (
            type(self.require_published_at) is not bool
            or type(self.notify_revisions) is not bool
        ):
            raise validation_error("invalid_source_definition_boolean")
        for field_name in (
            "schema_revision",
            "result_mapping_revision",
            "definition_revision",
        ):
            _revision(getattr(self, field_name), field_name)
        object.__setattr__(self, "allowed_hosts", hosts)
        object.__setattr__(self, "allowed_path_prefixes", paths)
        seal_proactive_contract(self, "definition_digest")


@dataclass(frozen=True, slots=True)
class SourcePolicySnapshot:
    schema_version: int
    policy_id: str
    policy_revision: str
    definitions: tuple[SourceDefinition, ...]
    acquired_at: datetime
    valid_until: datetime
    policy_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.policy_id, "source_policy_id")
        _revision(self.policy_revision, "source_policy_revision")
        definitions = tuple(self.definitions)
        if any(not isinstance(value, SourceDefinition) for value in definitions):
            raise validation_error("invalid_source_policy_definition")
        source_ids = tuple(value.source_id for value in definitions)
        if (
            not source_ids
            or source_ids != tuple(sorted(source_ids))
            or len(source_ids) != len(set(source_ids))
        ):
            raise validation_error("invalid_source_policy_definition_order")
        capability_ids = tuple(value.capability_id for value in definitions)
        if len(capability_ids) != len(set(capability_ids)):
            raise validation_error("duplicate_source_policy_capability")
        _aware(self.acquired_at, "source_policy_acquired_at")
        _aware(self.valid_until, "source_policy_valid_until")
        if (
            not self.acquired_at
            < self.valid_until
            <= self.acquired_at + timedelta(days=365)
        ):
            raise validation_error("invalid_source_policy_validity")
        object.__setattr__(self, "definitions", definitions)
        seal_proactive_contract(self, "policy_digest")

    def definition(self, source_id: str) -> SourceDefinition:
        matches = tuple(
            item for item in self.definitions if item.source_id == source_id
        )
        if len(matches) != 1:
            raise validation_error("source_definition_not_found")
        return matches[0]


@dataclass(frozen=True, slots=True)
class SourceCursor:
    schema_version: int
    subscription_id: str
    source_id: str
    token: str
    source_snapshot_revision: str
    revision: int
    observed_at: datetime
    cursor_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.subscription_id, "source_cursor_subscription_id")
        _identifier(self.source_id, "source_cursor_source_id")
        _bounded_string(self.token, "source_cursor_token", maximum=2_048)
        _revision(self.source_snapshot_revision, "source_snapshot_revision")
        _positive(self.revision, "source_cursor_revision")
        _aware(self.observed_at, "source_cursor_observed_at")
        seal_proactive_contract(self, "cursor_digest")


@dataclass(frozen=True, slots=True)
class SourceCapabilityObservation:
    schema_version: int
    source_id: str
    capability_id: str
    capability_definition_digest: DigestString
    provider_id: str
    provider_generation: int
    provider_result_digest: DigestString
    schema_revision: str
    result_mapping_revision: str
    source_snapshot_revision: str
    next_cursor_token: str
    data: Mapping[str, JsonValue]
    sensitivity: PrivacyLevel
    observed_at: datetime
    truncated: bool
    observation_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in ("source_id", "capability_id", "provider_id"):
            _identifier(getattr(self, field_name), field_name)
        _digest(
            self.capability_definition_digest,
            "source_capability_definition_digest",
        )
        _positive(self.provider_generation, "source_provider_generation")
        _digest(self.provider_result_digest, "source_provider_result_digest")
        for field_name in (
            "schema_revision",
            "result_mapping_revision",
            "source_snapshot_revision",
        ):
            _revision(getattr(self, field_name), field_name)
        _bounded_string(
            self.next_cursor_token,
            "source_next_cursor_token",
            maximum=2_048,
        )
        if not isinstance(self.data, Mapping):
            raise validation_error("invalid_source_observation_data")
        data = freeze_json(dict(self.data))
        if not isinstance(data, Mapping):
            raise validation_error("invalid_source_observation_data")
        if self.sensitivity is not PrivacyLevel.PUBLIC:
            raise validation_error("source_observation_not_public")
        _aware(self.observed_at, "source_observation_time")
        if type(self.truncated) is not bool or self.truncated:
            raise validation_error("source_observation_truncated")
        object.__setattr__(self, "data", data)
        seal_proactive_contract(self, "observation_digest")


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    schema_version: int
    source_id: str
    capability_id: str
    capability_definition_digest: DigestString
    provider_id: str
    provider_generation: int
    provider_result_digest: DigestString
    policy_digest: DigestString
    schema_revision: str
    result_mapping_revision: str
    observed_at: datetime
    provenance_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in ("source_id", "capability_id", "provider_id"):
            _identifier(getattr(self, field_name), field_name)
        for field_name in (
            "capability_definition_digest",
            "provider_result_digest",
            "policy_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        _positive(self.provider_generation, "source_provider_generation")
        _revision(self.schema_revision, "source_schema_revision")
        _revision(self.result_mapping_revision, "source_result_mapping_revision")
        _aware(self.observed_at, "source_provenance_observed_at")
        seal_proactive_contract(self, "provenance_digest")


@dataclass(frozen=True, slots=True)
class SourceItemIdentity:
    schema_version: int
    source_id: str
    external_identity: str
    stable_key_digest: DigestString
    revision_key_digest: DigestString
    revision_content_digest: DigestString
    content_digest: DigestString
    identity_rule_revision: str
    identity_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.source_id, "source_identity_source_id")
        _bounded_string(
            self.external_identity,
            "source_external_identity",
            maximum=2_048,
        )
        for field_name in (
            "stable_key_digest",
            "revision_key_digest",
            "revision_content_digest",
            "content_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        _revision(self.identity_rule_revision, "source_identity_rule_revision")
        seal_proactive_contract(self, "identity_digest")


@dataclass(frozen=True, slots=True)
class SourceFetchRequest:
    schema_version: int
    request_id: str
    subscription_id: str
    subscription_revision: int
    origin_kind: SourceFetchOriginKind
    origin_digest: DigestString
    source_policy_id: str
    source_policy_digest: DigestString
    source_ids: tuple[str, ...]
    categories: frozenset[SourceCategory]
    maximum_age: timedelta
    maximum_items: int
    requested_at: datetime
    request_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in ("request_id", "subscription_id", "source_policy_id"):
            _identifier(getattr(self, field_name), field_name)
        _positive(self.subscription_revision, "source_subscription_revision")
        if not isinstance(self.origin_kind, SourceFetchOriginKind):
            raise validation_error("invalid_source_fetch_origin_kind")
        _digest(self.origin_digest, "source_fetch_origin_digest")
        _digest(self.source_policy_digest, "source_policy_digest")
        source_ids = tuple(self.source_ids)
        if (
            not source_ids
            or any(
                not isinstance(value, str)
                or _IDENTIFIER.fullmatch(value) is None
                for value in source_ids
            )
            or source_ids != tuple(sorted(set(source_ids)))
        ):
            raise validation_error("invalid_source_request_sources")
        categories = frozenset(self.categories)
        if not categories or any(
            not isinstance(value, SourceCategory) for value in categories
        ):
            raise validation_error("invalid_source_request_categories")
        if not isinstance(self.maximum_age, timedelta) or not (
            timedelta(minutes=1) <= self.maximum_age <= timedelta(days=365)
        ):
            raise validation_error("invalid_source_request_age")
        if type(self.maximum_items) is not int or not 1 <= self.maximum_items <= 100:
            raise validation_error("invalid_source_request_item_limit")
        _aware(self.requested_at, "source_request_time")
        object.__setattr__(self, "source_ids", source_ids)
        object.__setattr__(self, "categories", categories)
        seal_proactive_contract(self, "request_digest")


@dataclass(frozen=True, slots=True)
class SourceDedupReceipt:
    schema_version: int
    subscription_id: str
    identity: SourceItemIdentity
    disposition: SourceDedupDisposition
    previous_revision_key_digest: DigestString | None
    ledger_revision: int
    recorded_at: datetime
    receipt_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.subscription_id, "source_dedup_subscription_id")
        if not isinstance(self.identity, SourceItemIdentity):
            raise validation_error("invalid_source_dedup_identity")
        if not isinstance(self.disposition, SourceDedupDisposition):
            raise validation_error("invalid_source_dedup_disposition")
        if self.previous_revision_key_digest is not None:
            _digest(
                self.previous_revision_key_digest,
                "source_previous_revision_key_digest",
            )
        if self.disposition is SourceDedupDisposition.NEW:
            if (
                self.previous_revision_key_digest is not None
                or self.ledger_revision != 1
            ):
                raise validation_error("invalid_new_source_dedup_receipt")
        elif self.previous_revision_key_digest is None:
            raise validation_error("source_dedup_receipt_missing_previous_revision")
        _positive(self.ledger_revision, "source_dedup_ledger_revision")
        _aware(self.recorded_at, "source_dedup_recorded_at")
        seal_proactive_contract(self, "receipt_digest")

    @property
    def should_emit(self) -> bool:
        return self.disposition in {
            SourceDedupDisposition.NEW,
            SourceDedupDisposition.REVISION_EMIT,
        }


@dataclass(frozen=True, slots=True)
class SourceStateMutation:
    schema_version: int
    subscription_id: str
    source_id: str
    expected_cursor_digest: DigestString | None
    next_cursor: SourceCursor
    identities: tuple[SourceItemIdentity, ...]
    notify_revisions: bool
    observed_at: datetime
    mutation_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.subscription_id, "source_state_subscription_id")
        _identifier(self.source_id, "source_state_source_id")
        if self.expected_cursor_digest is not None:
            _digest(self.expected_cursor_digest, "source_expected_cursor_digest")
        if (
            not isinstance(self.next_cursor, SourceCursor)
            or self.next_cursor.subscription_id != self.subscription_id
            or self.next_cursor.source_id != self.source_id
        ):
            raise validation_error("source_state_cursor_mismatch")
        identities = _typed_tuple(
            self.identities,
            SourceItemIdentity,
            "source_state_identities",
        )
        stable_keys = tuple(item.stable_key_digest for item in identities)
        if any(item.source_id != self.source_id for item in identities) or len(
            stable_keys
        ) != len(set(stable_keys)):
            raise validation_error("source_state_identity_mismatch")
        if type(self.notify_revisions) is not bool:
            raise validation_error("invalid_source_revision_policy")
        _aware(self.observed_at, "source_state_observed_at")
        if self.next_cursor.observed_at > self.observed_at:
            raise validation_error("source_state_observation_mismatch")
        object.__setattr__(self, "identities", identities)
        seal_proactive_contract(self, "mutation_digest")


@dataclass(frozen=True, slots=True)
class SourceStateCommitPlan:
    schema_version: int
    request_digest: DigestString
    subscription_id: str
    mutations: tuple[SourceStateMutation, ...]
    planned_at: datetime
    plan_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.request_digest, "source_fetch_request_digest")
        _identifier(self.subscription_id, "source_state_subscription_id")
        mutations = _typed_tuple(
            self.mutations,
            SourceStateMutation,
            "source_state_mutations",
        )
        source_ids = tuple(item.source_id for item in mutations)
        if (
            not source_ids
            or source_ids != tuple(sorted(source_ids))
            or len(source_ids) != len(set(source_ids))
            or any(item.subscription_id != self.subscription_id for item in mutations)
        ):
            raise validation_error("invalid_source_state_mutation_order")
        _aware(self.planned_at, "source_state_planned_at")
        object.__setattr__(self, "mutations", mutations)
        seal_proactive_contract(self, "plan_digest")


@dataclass(frozen=True, slots=True)
class SourceStateCommitReceipt:
    schema_version: int
    plan: SourceStateCommitPlan
    next_cursors: tuple[SourceCursor, ...]
    dedup_receipts: tuple[SourceDedupReceipt, ...]
    committed_at: datetime
    receipt_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.plan, SourceStateCommitPlan):
            raise validation_error("invalid_source_state_plan")
        cursors = _typed_tuple(
            self.next_cursors,
            SourceCursor,
            "source_state_cursors",
        )
        receipts = _typed_tuple(
            self.dedup_receipts,
            SourceDedupReceipt,
            "source_state_dedup_receipts",
        )
        expected_cursors = tuple(item.next_cursor for item in self.plan.mutations)
        expected_identities = tuple(
            identity
            for mutation in self.plan.mutations
            for identity in mutation.identities
        )
        if (
            cursors != expected_cursors
            or tuple(item.identity for item in receipts) != expected_identities
        ):
            raise validation_error("source_state_commit_evidence_mismatch")
        _aware(self.committed_at, "source_state_committed_at")
        object.__setattr__(self, "next_cursors", cursors)
        object.__setattr__(self, "dedup_receipts", receipts)
        seal_proactive_contract(self, "receipt_digest")


@dataclass(frozen=True, slots=True)
class SourceFetchReceipt:
    schema_version: int
    request_digest: DigestString
    status: SourceFetchStatus
    batch: SourceBatch | None
    failures: tuple[SourceFailure, ...]
    provenance: tuple[SourceProvenance, ...]
    identities: tuple[SourceItemIdentity, ...]
    dedup_receipts: tuple[SourceDedupReceipt, ...]
    next_cursors: tuple[SourceCursor, ...]
    reason_codes: tuple[str, ...]
    completed_at: datetime
    receipt_digest: DigestString = ""

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.request_digest, "source_fetch_request_digest")
        if not isinstance(self.status, SourceFetchStatus):
            raise validation_error("invalid_source_fetch_status")
        if self.status in {SourceFetchStatus.FAILED, SourceFetchStatus.CANCELLED}:
            if self.batch is not None:
                raise validation_error("failed_source_fetch_has_batch")
        elif not isinstance(self.batch, SourceBatch):
            raise validation_error("successful_source_fetch_requires_batch")
        failures = _typed_tuple(
            self.failures,
            SourceFailure,
            "source_fetch_failures",
        )
        if self.status is SourceFetchStatus.FAILED and not failures:
            raise validation_error("failed_source_fetch_requires_failure")
        if self.batch is not None and failures != self.batch.failed_sources:
            raise validation_error("source_fetch_failure_evidence_mismatch")
        provenance = _typed_tuple(
            self.provenance,
            SourceProvenance,
            "source_fetch_provenance",
        )
        identities = _typed_tuple(
            self.identities,
            SourceItemIdentity,
            "source_fetch_identities",
        )
        dedup_receipts = _typed_tuple(
            self.dedup_receipts,
            SourceDedupReceipt,
            "source_fetch_dedup_receipts",
        )
        cursors = _typed_tuple(
            self.next_cursors,
            SourceCursor,
            "source_fetch_cursors",
        )
        if self.status in {SourceFetchStatus.FAILED, SourceFetchStatus.CANCELLED} and (
            provenance or identities or dedup_receipts or cursors
        ):
            raise validation_error("terminal_source_fetch_has_state_evidence")
        if self.status is SourceFetchStatus.CANCELLED and failures:
            raise validation_error("cancelled_source_fetch_has_failure")
        if self.batch is not None:
            emitted = tuple(
                item.identity.content_digest
                for item in dedup_receipts
                if item.should_emit
            )
            batch_digests = tuple(item.content_digest for item in self.batch.items)
            receipt_identities = tuple(item.identity for item in dedup_receipts)
            if emitted != batch_digests or identities != receipt_identities:
                raise validation_error("source_fetch_item_evidence_mismatch")
            if self.status is SourceFetchStatus.SUCCEEDED and (
                not self.batch.items or self.batch.failed_sources
            ):
                raise validation_error("invalid_successful_source_fetch")
            if self.status is SourceFetchStatus.PARTIAL and (
                not self.batch.succeeded_sources or not self.batch.failed_sources
            ):
                raise validation_error("invalid_partial_source_fetch")
            if self.status is SourceFetchStatus.NO_NEW_ITEMS and (
                self.batch.items or self.batch.failed_sources
            ):
                raise validation_error("invalid_no_new_source_fetch")
        reasons = _reason_codes(self.reason_codes)
        _aware(self.completed_at, "source_fetch_completed_at")
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "failures", failures)
        object.__setattr__(self, "identities", identities)
        object.__setattr__(self, "dedup_receipts", dedup_receipts)
        object.__setattr__(self, "next_cursors", cursors)
        object.__setattr__(self, "reason_codes", reasons)
        seal_proactive_contract(self, "receipt_digest")


def _v1(value: object) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_schema_version")


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise validation_error("invalid_source_identifier", field_name)
    return value


def _revision(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise validation_error("invalid_source_revision", field_name)
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_source_digest", field_name)
    return value


def _positive(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise validation_error("invalid_source_positive_integer", field_name)
    return value


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise validation_error("invalid_source_datetime", field_name)
    require_aware(value, field_name)
    return value


def _bounded_string(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_source_string", field_name)
    require_non_empty(value, field_name)
    if len(value.encode("utf-8")) > maximum:
        raise validation_error("source_string_too_large", field_name)
    return value


def _typed_tuple(
    values: object,
    expected: type,
    field_name: str,
) -> tuple:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_source_collection", field_name)
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_source_collection", field_name) from None
    if any(not isinstance(value, expected) for value in result):
        raise validation_error("invalid_source_collection", field_name)
    return result


def _reason_codes(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise validation_error("invalid_source_reason_codes")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError:
        raise validation_error("invalid_source_reason_codes") from None
    if (
        len(result) > 32
        or len(result) != len(set(result))
        or any(
            not isinstance(value, str)
            or not value
            or _REVISION.fullmatch(value) is None
            for value in result
        )
    ):
        raise validation_error("invalid_source_reason_codes")
    return result


__all__ = [
    "SourceCapabilityObservation",
    "SourceCursor",
    "SourceDedupDisposition",
    "SourceDedupReceipt",
    "SourceDefinition",
    "SourceFetchOriginKind",
    "SourceFetchReceipt",
    "SourceFetchRequest",
    "SourceFetchStatus",
    "SourceIdentityRule",
    "SourceItemIdentity",
    "SourcePolicySnapshot",
    "SourceProvenance",
    "SourceStateCommitPlan",
    "SourceStateCommitReceipt",
    "SourceStateMutation",
]
