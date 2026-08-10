from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.security.digests import (
    actor_digest,
    authorization_decision_digest,
    scope_digest,
)
from dududa.security.models import AuthorizationEffect

from .digests import selector_digest
from .models import (
    MemoryQuery,
    MemoryRecord,
    MemoryRepositorySnapshot,
    MemorySubmissionReceipt,
    MemorySubmissionStatus,
    MemoryWriteAction,
    MemoryWriteCommand,
    Page,
    PageRequest,
    ScopeSelector,
    SelectorMode,
    Visibility,
)


class InMemoryMemoryRepository:
    def __init__(
        self,
        selector_verifier: object,
        *,
        write_decision_verifier: object | None = None,
        repository_revision: str = "memory-repository-v1",
        trusted_gate_component_ids: frozenset[str] = frozenset(
            {"memory.explicit-write-gate"}
        ),
        cursor_secret: bytes = b"dududa-memory-cursor-secret-v1",
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._selector_verifier = selector_verifier
        self._write_decision_verifier = write_decision_verifier
        self._repository_revision = repository_revision
        self._trusted_gate_component_ids = trusted_gate_component_ids
        self._cursor_secret = bytes(cursor_secret)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._records: dict[str, MemoryRecord] = {}
        self._state_revision = 0
        self._snapshots: dict[str, MemoryRepositorySnapshot] = {}
        self._idempotency: dict[str, tuple[DigestString, MemorySubmissionReceipt]] = {}
        self._consumed_decisions: set[str] = set()
        self._writer_revision = ComponentRevision(
            "memory.repository",
            "1",
            repository_revision,
            DigestString("builtin"),
        )
        self._lock = asyncio.Lock()

    def seed(self, records: Iterable[MemoryRecord]) -> None:
        for record in records:
            if record.memory_id in self._records:
                raise ValueError("duplicate memory id")
            self._records[record.memory_id] = record

    async def open_snapshot(
        self,
        selectors: tuple[ScopeSelector, ...],
        *,
        request_digest: DigestString,
        as_of: datetime,
        call: PortCallContext,
    ) -> MemoryRepositorySnapshot:
        now = self._clock()
        _validate_memory_call(call, now)
        if not selectors or as_of.tzinfo is None or as_of > now:
            raise _memory_error("invalid_memory_snapshot_request")
        selector_digests: list[DigestString] = []
        for selector in selectors:
            if not self._verify_selector(selector, request_digest):
                raise _memory_error("invalid_scope_selector")
            selector_digests.append(selector_digest(selector))
        expires_at = min(
            min(item.expires_at for item in selectors), now + timedelta(minutes=5)
        )
        snapshot_id = self._id_factory()
        unsigned = {
            "snapshot_id": snapshot_id,
            "repository_revision": self._repository_revision,
            "state_revision": self._state_revision,
            "selector_digests": tuple(selector_digests),
            "request_digest": request_digest,
            "as_of": as_of,
            "expires_at": expires_at,
        }
        snapshot = MemoryRepositorySnapshot(
            1,
            snapshot_id,
            self._repository_revision,
            self._state_revision,
            tuple(selector_digests),
            request_digest,
            as_of,
            expires_at,
            canonical_digest(unsigned, domain="memory:repository-snapshot:v1"),
        )
        await _acquire_memory_lock(self._lock, call, self._clock)
        try:
            _validate_memory_call(call, self._clock())
            self._snapshots[snapshot_id] = snapshot
        finally:
            self._lock.release()
        return snapshot

    async def get(
        self,
        snapshot: MemoryRepositorySnapshot,
        memory_id: str,
        selector: ScopeSelector,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> MemoryRecord | None:
        _validate_memory_call(call, self._clock())
        self._validate_read(snapshot, selector, request_digest)
        record = self._records.get(memory_id)
        if record is None or not _matches_selector(record, selector, snapshot.as_of):
            return None
        return record

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
        _validate_memory_call(call, self._clock())
        self._validate_read(snapshot, selector, request_digest)
        if not 1 <= candidate_limit <= 100:
            raise _memory_error("invalid_memory_candidate_limit")
        query_digest = canonical_digest(query, domain="memory:query:v1")
        offset = self._decode_cursor(cursor, snapshot, selector, query_digest)
        text = query.text.casefold().strip()
        eligible = [
            record
            for record in self._records.values()
            if _matches_selector(record, selector, query.reference_time)
            and (not text or text in record.content.casefold())
        ]
        eligible.sort(key=lambda item: (item.updated_at, item.memory_id), reverse=True)
        page_items = tuple(eligible[offset : offset + candidate_limit])
        next_offset = offset + len(page_items)
        next_cursor = None
        if next_offset < len(eligible):
            next_cursor = self._encode_cursor(
                next_offset, snapshot, selector, query_digest
            )
        return Page(1, page_items, next_cursor, snapshot.repository_revision)

    async def list(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        page: PageRequest,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> Page[MemoryRecord]:
        query = MemoryQuery(1, "", "und", snapshot.as_of)
        return await self.retrieve(
            snapshot,
            selector,
            query,
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
        now = self._clock()
        _validate_memory_call(call, now)
        decision = command.decision
        command_digest = canonical_digest(command, domain="memory:write-command:v1")
        await _acquire_memory_lock(self._lock, call, self._clock)
        try:
            now = self._clock()
            _validate_memory_call(call, now)
            existing = self._idempotency.get(command.idempotency_key)
            if existing is not None:
                if existing[0] != command_digest:
                    raise _memory_error("memory_write_idempotency_conflict")
                return existing[1]
            self._validate_write(command, now)
            if decision.decision_id in self._consumed_decisions:
                raise _memory_error("memory_write_decision_consumed")
            record = decision.normalized_record
            if record is None:
                raise _memory_error("memory_write_record_missing")
            current = self._records.get(record.memory_id)
            if current is None:
                if decision.expected_record_version is not None:
                    raise _memory_error("memory_expected_version_conflict")
            elif decision.expected_record_version != current.version:
                raise _memory_error("memory_expected_version_conflict")
            self._records[record.memory_id] = record
            self._consumed_decisions.add(decision.decision_id)
            receipt = MemorySubmissionReceipt(
                1,
                command.command_id,
                decision.decision_id,
                decision.candidate_id,
                command.idempotency_key,
                MemorySubmissionStatus.PERSISTED,
                record.memory_id,
                None,
                decision.policy_revision,
                decision.gate_revision,
                self._writer_revision,
                (),
                now,
            )
            self._idempotency[command.idempotency_key] = (command_digest, receipt)
            try:
                await self._after_write_locked()
            except BaseException:
                if current is None:
                    self._records.pop(record.memory_id, None)
                else:
                    self._records[record.memory_id] = current
                self._consumed_decisions.discard(decision.decision_id)
                self._idempotency.pop(command.idempotency_key, None)
                raise
            return receipt
        finally:
            self._lock.release()

    async def _after_write_locked(self) -> None:
        return None

    def _validate_read(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        request_digest: DigestString,
    ) -> None:
        now = self._clock()
        stored = self._snapshots.get(snapshot.snapshot_id)
        selector_hash = selector_digest(selector)
        if (
            stored != snapshot
            or snapshot.repository_revision != self._repository_revision
            or snapshot.request_digest != request_digest
            or snapshot.expires_at <= now
            or selector_hash not in snapshot.selector_digests
            or not self._verify_selector(selector, request_digest)
        ):
            raise _memory_error("invalid_or_mixed_memory_snapshot")

    def _validate_write(self, command: MemoryWriteCommand, now: datetime) -> None:
        decision = command.decision
        authorization = command.authorization
        if (
            decision.action is not MemoryWriteAction.ALLOW
            or decision.normalized_record is None
            or decision.decision_expires_at <= now
            or decision.gate_revision.component_id
            not in self._trusted_gate_component_ids
            or not self._verify_write_decision(decision, now)
        ):
            raise _memory_error("memory_write_decision_invalid")
        if (
            command.request_digest != decision.request_digest
            or command.idempotency_key != decision.idempotency_key
            or command.delivery_id != decision.delivery_id
            or command.delivery_status is not decision.delivery_status
            or command.delivery_receipt_digest != decision.delivery_receipt_digest
        ):
            raise _memory_error("memory_write_evidence_mismatch")
        actor_hash = actor_digest(command.actor)
        conversation_hash = scope_digest(command.conversation_scope)
        if (
            decision.actor_digest != actor_hash
            or decision.scope_digest != conversation_hash
        ):
            raise _memory_error("memory_write_scope_mismatch")
        if (
            authorization.effect is not AuthorizationEffect.ALLOW
            or str(authorization.action) != "memory.write"
            or authorization.actor_digest != actor_hash
            or authorization.scope_digest != conversation_hash
            or authorization.expires_at <= now
            or authorization_decision_digest(authorization)
            != decision.authorization_digest
        ):
            raise _memory_error("memory_write_authorization_invalid")
        confirmation_digest = (
            canonical_digest(
                command.confirmation, domain="security:confirmation-grant:v1"
            )
            if command.confirmation is not None
            else None
        )
        if confirmation_digest != decision.confirmation_digest:
            raise _memory_error("memory_write_confirmation_mismatch")
        record_scope = decision.normalized_record.scope
        if (
            record_scope.platform != command.conversation_scope.platform
            or record_scope.bot_id != command.conversation_scope.bot_id
            or record_scope.conversation_id
            != command.conversation_scope.conversation_id
            or record_scope.group_id != command.conversation_scope.group_id
            or record_scope.persona_id != command.conversation_scope.persona_id
            or (
                record_scope.user_id is not None
                and record_scope.user_id != command.actor.user_id
            )
        ):
            raise _memory_error("memory_write_record_scope_mismatch")

    def _verify_write_decision(
        self,
        decision: object,
        now: datetime,
    ) -> bool:
        verifier = self._write_decision_verifier
        if verifier is None:
            return False
        try:
            return bool(verifier.verify_decision(decision, at=now))
        except Exception:  # noqa: BLE001 - verifier failures fail closed
            return False

    def _verify_selector(
        self, selector: ScopeSelector, request_digest: DigestString
    ) -> bool:
        try:
            return bool(
                self._selector_verifier.verify(
                    selector,
                    expected_request_digest=request_digest,
                )
            )
        except Exception:  # noqa: BLE001 - verifier failures fail closed
            return False

    def _encode_cursor(
        self,
        offset: int,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        query_digest: DigestString,
    ) -> str:
        body = f"{offset}:{snapshot.snapshot_id}:{selector_digest(selector)}:{query_digest}"
        signature = hmac.new(
            self._cursor_secret, body.encode(), hashlib.sha256
        ).hexdigest()
        return f"{offset}:{signature}"

    def _decode_cursor(
        self,
        cursor: str | None,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        query_digest: DigestString,
    ) -> int:
        if cursor is None:
            return 0
        try:
            raw_offset, signature = cursor.split(":", 1)
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise _memory_error("invalid_memory_cursor") from None
        expected = self._encode_cursor(offset, snapshot, selector, query_digest).split(
            ":", 1
        )[1]
        if offset < 0 or not hmac.compare_digest(signature, expected):
            raise _memory_error("invalid_memory_cursor")
        return offset


def _matches_selector(
    record: MemoryRecord, selector: ScopeSelector, as_of: datetime
) -> bool:
    scope = record.scope
    if record.expires_at is not None and record.expires_at <= as_of:
        return False
    if (
        scope.platform != selector.platform
        or scope.bot_id != selector.bot_id
        or scope.persona_id != selector.persona_id
        or scope.memory_type not in selector.memory_types
    ):
        return False
    if selector.mode is SelectorMode.SAFE_USER_PROFILE:
        return (
            scope.user_id == selector.user_id
            and record.visibility is Visibility.SAFE_USER_PROFILE
        )
    if (
        scope.conversation_id != selector.conversation_id
        or scope.group_id != selector.group_id
    ):
        return False
    if scope.user_id is not None and scope.user_id != selector.user_id:
        return False
    if record.visibility is Visibility.CURRENT_CONVERSATION:
        return selector.mode is SelectorMode.CURRENT_CONVERSATION
    if record.visibility is Visibility.CURRENT_GROUP:
        return scope.group_id is not None and selector.mode in {
            SelectorMode.CURRENT_CONVERSATION,
            SelectorMode.CURRENT_GROUP,
        }
    return False


def _memory_error(code: str):
    return error(code, ErrorCategory.AUTHORIZATION, "memory.unavailable")


_T = TypeVar("_T")


async def _await_memory_operation(
    operation: Awaitable[_T],
    call: PortCallContext | ServiceCallContext,
    clock: Callable[[], datetime],
) -> _T:
    operation_task = asyncio.ensure_future(operation)
    cancellation_task = asyncio.ensure_future(call.cancellation.wait())
    tasks = (operation_task, cancellation_task)
    try:
        now = clock()
        _validate_memory_call(call, now)
        done, _ = await asyncio.wait(
            tasks,
            timeout=(call.deadline - now).total_seconds(),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            return operation_task.result()
        raise _memory_error("memory_call_cancelled_or_expired")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)


async def _acquire_memory_lock(
    lock: asyncio.Lock,
    call: PortCallContext | ServiceCallContext,
    clock: Callable[[], datetime],
) -> None:
    await _await_memory_operation(lock.acquire(), call, clock)


def _validate_memory_call(
    call: PortCallContext | ServiceCallContext,
    now: datetime,
) -> None:
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise _memory_error("memory_call_cancelled_or_expired")
