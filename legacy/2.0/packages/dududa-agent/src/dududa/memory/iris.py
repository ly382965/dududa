from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString, JsonValue, freeze_json
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext, ServiceCallContext

from .models import (
    MemoryDeleteCommand,
    MemoryDeleteReceipt,
    MemoryQuery,
    MemoryRecord,
    MemoryRepositoryArchive,
    MemoryRepositorySnapshot,
    MemoryRestoreCommand,
    MemoryRestoreReceipt,
    MemorySubmissionReceipt,
    MemoryTombstoneCheckpoint,
    MemoryType,
    MemoryWriteCommand,
    Page,
    PageRequest,
    ScopeSelector,
)
from .repository import (
    InMemoryMemoryRepository,
    _await_memory_operation,
    _matches_selector,
    _validate_memory_call,
)
from .serialization import record_from_dict, record_to_dict


@dataclass(frozen=True, slots=True)
class IrisExactFilter:
    platform: str
    bot_id: str
    persona_id: str
    conversation_id: str | None
    group_id: str | None
    user_id: str | None
    memory_types: frozenset[MemoryType]
    safe_user_profile_only: bool


@dataclass(frozen=True, slots=True)
class IrisSearchPage:
    records: tuple[Mapping[str, JsonValue], ...]
    next_offset: int | None
    backend_revision: str


class IrisBackend(Protocol):
    @property
    def supports_exact_scope(self) -> bool: ...

    async def search_exact(
        self,
        exact_filter: IrisExactFilter,
        *,
        query: str,
        as_of: datetime,
        limit: int,
        offset: int,
    ) -> IrisSearchPage: ...

    async def get_exact(
        self,
        memory_id: str,
        exact_filter: IrisExactFilter,
        *,
        as_of: datetime,
    ) -> Mapping[str, JsonValue] | None: ...

    async def upsert_scoped(
        self,
        record: Mapping[str, JsonValue],
        exact_filter: IrisExactFilter,
        *,
        expected_version: int | None,
        idempotency_key: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class QuarantinedMemory:
    quarantine_id: str
    backend_record_digest: DigestString
    reason_code: str
    observed_at: datetime
    raw_record: JsonValue


class InMemoryMemoryQuarantine:
    def __init__(self) -> None:
        self.records: list[QuarantinedMemory] = []

    async def add(
        self,
        raw_record: Mapping[str, JsonValue],
        *,
        reason_code: str,
        observed_at: datetime,
    ) -> None:
        frozen = freeze_json(dict(raw_record))
        digest = canonical_digest(frozen, domain="memory:quarantine-record:v1")
        if any(item.backend_record_digest == digest for item in self.records):
            return
        self.records.append(
            QuarantinedMemory(
                f"quarantine-{len(self.records) + 1}",
                digest,
                reason_code,
                observed_at,
                frozen,
            )
        )


class IrisMemoryRepository(InMemoryMemoryRepository):
    """Fail-closed Iris adapter with no unscoped-search path."""

    def __init__(
        self,
        backend: IrisBackend,
        selector_verifier: object,
        *,
        quarantine: InMemoryMemoryQuarantine | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            selector_verifier,
            repository_revision="memory-iris-v1",
            **kwargs,
        )
        self._backend = backend
        self.quarantine = quarantine or InMemoryMemoryQuarantine()
        self._pending_write: ContextVar[
            tuple[
                str,
                int | None,
                str,
                PortCallContext | ServiceCallContext,
            ]
            | None
        ] = ContextVar(
            "iris_pending_write",
            default=None,
        )

    async def open_snapshot(
        self,
        selectors: tuple[ScopeSelector, ...],
        *,
        request_digest: DigestString,
        as_of: datetime,
        call: PortCallContext,
    ) -> MemoryRepositorySnapshot:
        self._require_exact_scope()
        return await super().open_snapshot(
            selectors,
            request_digest=request_digest,
            as_of=as_of,
            call=call,
        )

    async def get(
        self,
        snapshot: MemoryRepositorySnapshot,
        memory_id: str,
        selector: ScopeSelector,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> MemoryRecord | None:
        self._require_exact_scope()
        _validate_memory_call(call, self._clock())
        self._validate_read(snapshot, selector, request_digest)
        raw = await _await_memory_operation(
            self._backend.get_exact(
                memory_id,
                _exact_filter(selector),
                as_of=snapshot.as_of,
            ),
            call,
            self._clock,
        )
        if raw is None:
            return None
        return await self._decode_scoped(raw, selector, snapshot.as_of, call)

    async def retrieve(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        query: MemoryQuery,
        *,
        candidate_limit: int,
        cursor: str | None,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> Page[MemoryRecord]:
        self._require_exact_scope()
        _validate_memory_call(call, self._clock())
        self._validate_read(snapshot, selector, request_digest)
        if not 1 <= candidate_limit <= 100:
            raise _iris_error("invalid_memory_candidate_limit")
        if query.reference_time != snapshot.as_of:
            raise _iris_error("memory_query_snapshot_time_mismatch")
        query_digest = canonical_digest(query, domain="memory:query:v1")
        offset = self._decode_cursor(cursor, snapshot, selector, query_digest)
        backend_page = await _await_memory_operation(
            self._backend.search_exact(
                _exact_filter(selector),
                query=query.text,
                as_of=query.reference_time,
                limit=candidate_limit,
                offset=offset,
            ),
            call,
            self._clock,
        )
        if len(backend_page.records) > candidate_limit:
            raise _iris_error("iris_backend_ignored_candidate_limit")
        records: list[MemoryRecord] = []
        for raw in backend_page.records:
            record = await self._decode_scoped(
                raw,
                selector,
                query.reference_time,
                call,
            )
            if record is not None:
                records.append(record)
        next_cursor = None
        if backend_page.next_offset is not None:
            next_cursor = self._encode_cursor(
                backend_page.next_offset,
                snapshot,
                selector,
                query_digest,
            )
        return Page(1, tuple(records), next_cursor, snapshot.repository_revision)

    async def list(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        page: PageRequest,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> Page[MemoryRecord]:
        return await self.retrieve(
            snapshot,
            selector,
            MemoryQuery(1, "", "und", snapshot.as_of),
            candidate_limit=page.limit,
            cursor=page.cursor,
            request_digest=request_digest,
            call=call,
        )

    async def commit_write(
        self,
        command: MemoryWriteCommand,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> MemorySubmissionReceipt:
        self._require_exact_scope()
        record = command.decision.normalized_record
        if record is None:
            raise _iris_error("memory_write_record_missing")
        token = self._pending_write.set(
            (
                record.memory_id,
                command.decision.expected_record_version,
                command.idempotency_key,
                call,
            )
        )
        try:
            return await super().commit_write(command, call=call)
        finally:
            self._pending_write.reset(token)

    async def commit_delete(
        self,
        command: MemoryDeleteCommand,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> MemoryDeleteReceipt:
        del command, call
        raise _iris_error("iris_delete_unsupported")

    async def export_tombstone_checkpoint(
        self,
        *,
        call: ServiceCallContext,
    ) -> MemoryTombstoneCheckpoint:
        del call
        raise _iris_error("iris_archive_unsupported")

    async def export_archive(
        self,
        *,
        call: ServiceCallContext,
    ) -> MemoryRepositoryArchive:
        del call
        raise _iris_error("iris_archive_unsupported")

    async def restore(
        self,
        command: MemoryRestoreCommand,
        *,
        call: ServiceCallContext,
    ) -> MemoryRestoreReceipt:
        del command, call
        raise _iris_error("iris_restore_unsupported")

    async def _after_write_locked(self) -> None:
        pending = self._pending_write.get()
        if pending is None:
            raise _iris_error("iris_write_context_missing")
        memory_id, expected_version, idempotency_key, call = pending
        record = self._records[memory_id]
        selector = IrisExactFilter(
            record.scope.platform,
            record.scope.bot_id,
            record.scope.persona_id,
            record.scope.conversation_id,
            record.scope.group_id,
            record.scope.user_id,
            frozenset({record.scope.memory_type}),
            False,
        )
        await _await_memory_operation(
            self._backend.upsert_scoped(
                record_to_dict(record),
                selector,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            ),
            call,
            self._clock,
        )

    async def _decode_scoped(
        self,
        raw: Mapping[str, JsonValue],
        selector: ScopeSelector,
        as_of: datetime,
        call: PortCallContext,
    ) -> MemoryRecord | None:
        _validate_memory_call(call, self._clock())
        try:
            record = record_from_dict(raw)
        except Exception:  # noqa: BLE001 - malformed backend data is quarantined
            await self.quarantine.add(
                raw,
                reason_code="missing_or_invalid_scope_metadata",
                observed_at=self._clock(),
            )
            return None
        if not _matches_selector(record, selector, as_of):
            raise _iris_error("iris_returned_out_of_scope_record")
        return record

    def _require_exact_scope(self) -> None:
        if not self._backend.supports_exact_scope:
            raise _iris_error("iris_exact_scope_unsupported")


def _exact_filter(selector: ScopeSelector) -> IrisExactFilter:
    return IrisExactFilter(
        selector.platform,
        selector.bot_id,
        selector.persona_id,
        selector.conversation_id,
        selector.group_id,
        selector.user_id,
        selector.memory_types,
        selector.mode.value == "safe_user_profile",
    )


def _iris_error(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "memory.iris_unavailable")
