from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dududa.domain.message import MessageDedupKey
from dududa.domain.primitives import ComponentRevision, require_aware
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext

from .state import (
    RuntimeCheckpoint,
    RuntimeCommitDisposition,
    RuntimeCommitRequest,
    RuntimeCommitResult,
    RuntimeDedupRecord,
    RuntimePhase,
    RuntimeState,
    validate_runtime_state,
)


@dataclass(frozen=True, slots=True)
class InMemoryRuntimeStateStoreConfig:
    schema_version: int
    checkpoint_ttl: timedelta
    tombstone_ttl: timedelta
    maximum_checkpoints: int
    maximum_dedup_records: int
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        for name in ("checkpoint_ttl", "tombstone_ttl"):
            value = getattr(self, name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise validation_error("invalid_runtime_store_ttl", name)
        for name in ("maximum_checkpoints", "maximum_dedup_records"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise validation_error("invalid_runtime_store_capacity", name)
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_runtime_store_revision")


class InMemoryRuntimeStateStore:
    def __init__(
        self,
        config: InMemoryRuntimeStateStoreConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(config, InMemoryRuntimeStateStoreConfig):
            raise TypeError("invalid in-memory Runtime State Store config")
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()
        self._checkpoints: dict[str, RuntimeCheckpoint] = {}
        self._dedup: dict[MessageDedupKey, RuntimeDedupRecord] = {}
        self._run_keys: dict[str, MessageDedupKey] = {}
        self._changed: dict[str, asyncio.Event] = {}

    @property
    def config(self) -> InMemoryRuntimeStateStoreConfig:
        return self._config

    async def commit(
        self,
        request: RuntimeCommitRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeCommitResult:
        if not isinstance(request, RuntimeCommitRequest):
            raise validation_error("invalid_runtime_commit_request")
        now = self._now()
        _validate_port_call(call, request.run_id, now)
        async with self._lock:
            now = self._now()
            _validate_port_call(call, request.run_id, now)
            self._collect_expired(now)
            if request.expected_revision is None:
                return self._create(request, now)
            return self._update(request, now)

    async def load(
        self,
        run_id: str,
        *,
        call: PortCallContext,
    ) -> RuntimeCheckpoint | None:
        now = self._now()
        _validate_port_call(call, run_id, now)
        async with self._lock:
            now = self._now()
            _validate_port_call(call, run_id, now)
            self._collect_expired(now)
            return self._checkpoints.get(run_id)

    async def wait_for_revision(
        self,
        run_id: str,
        after_revision: int,
        *,
        call: PortCallContext,
    ) -> RuntimeCheckpoint | None:
        if type(after_revision) is not int or after_revision < 1:
            raise validation_error("invalid_runtime_wait_revision")
        while True:
            now = self._now()
            _validate_port_call(call, run_id, now)
            async with self._lock:
                now = self._now()
                _validate_port_call(call, run_id, now)
                self._collect_expired(now)
                checkpoint = self._checkpoints.get(run_id)
                if checkpoint is None or checkpoint.revision > after_revision:
                    return checkpoint
                changed = self._changed.setdefault(run_id, asyncio.Event())
                wake_at = min(call.deadline, checkpoint.expires_at)
            await _wait_for_change(changed, call, now, wake_at=wake_at)

    async def lookup_dedup(
        self,
        key: MessageDedupKey,
        *,
        call: PortCallContext,
    ) -> RuntimeDedupRecord | None:
        if not isinstance(key, MessageDedupKey):
            raise validation_error("invalid_runtime_dedup_key")
        now = self._now()
        _validate_unbound_port_call(call, now)
        async with self._lock:
            now = self._now()
            _validate_unbound_port_call(call, now)
            self._collect_expired(now)
            return self._dedup.get(key)

    async def delete(
        self,
        run_id: str,
        expected_revision: int,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> None:
        if type(expected_revision) is not int or expected_revision < 1:
            raise validation_error("invalid_runtime_expected_revision")
        now = self._now()
        _validate_store_call(call, run_id, now)
        async with self._lock:
            now = self._now()
            _validate_store_call(call, run_id, now)
            self._collect_expired(now)
            checkpoint = self._checkpoints.get(run_id)
            if checkpoint is None:
                return
            if checkpoint.revision != expected_revision:
                raise _conflict("runtime_store_delete_revision_conflict")
            del self._checkpoints[run_id]
            self._notify(run_id)

    def _create(
        self,
        request: RuntimeCommitRequest,
        now: datetime,
    ) -> RuntimeCommitResult:
        state = request.next_state
        if state.phase is not RuntimePhase.RECEIVED:
            raise validation_error("runtime_initial_checkpoint_not_received")
        validate_runtime_state(state)
        existing_key = self._run_keys.get(request.run_id)
        existing_record = self._dedup.get(request.message_dedup_key)
        if existing_key is not None and existing_key != request.message_dedup_key:
            raise _conflict("runtime_store_run_id_conflict")
        if existing_record is not None:
            if (
                existing_record.run_id != request.run_id
                or existing_record.start_digest != state.start_digest
            ):
                raise _conflict("runtime_store_dedup_payload_conflict")
            return RuntimeCommitResult(
                1,
                RuntimeCommitDisposition.DUPLICATE,
                self._checkpoints.get(existing_record.run_id),
                existing_record,
            )
        if existing_key is not None:
            raise _conflict("runtime_store_run_tombstone_conflict")
        if len(self._checkpoints) >= self._config.maximum_checkpoints:
            raise _capacity("runtime_store_checkpoint_capacity_exhausted")
        if len(self._dedup) >= self._config.maximum_dedup_records:
            raise _capacity("runtime_store_tombstone_capacity_exhausted")

        checkpoint_expires_at = self._checkpoint_expiry(now, state)
        checkpoint = RuntimeCheckpoint(1, state, 1, checkpoint_expires_at)
        record = RuntimeDedupRecord(
            1,
            request.message_dedup_key,
            request.run_id,
            state.start_digest,
            1,
            _state_outcome(state),
            checkpoint_expires_at + self._config.tombstone_ttl,
        )
        self._checkpoints[request.run_id] = checkpoint
        self._dedup[request.message_dedup_key] = record
        self._run_keys[request.run_id] = request.message_dedup_key
        self._notify(request.run_id)
        return RuntimeCommitResult(
            1,
            RuntimeCommitDisposition.CREATED,
            checkpoint,
            record,
        )

    def _update(
        self,
        request: RuntimeCommitRequest,
        now: datetime,
    ) -> RuntimeCommitResult:
        key = self._run_keys.get(request.run_id)
        if key is None:
            raise _conflict("runtime_store_unknown_run")
        if key != request.message_dedup_key:
            raise _conflict("runtime_store_run_id_conflict")
        record = self._dedup.get(key)
        if record is None or record.start_digest != request.next_state.start_digest:
            raise _conflict("runtime_store_dedup_payload_conflict")
        checkpoint = self._checkpoints.get(request.run_id)
        if checkpoint is None:
            raise _conflict("runtime_store_checkpoint_expired")
        if checkpoint.revision != request.expected_revision:
            if checkpoint.state == request.next_state:
                return RuntimeCommitResult(
                    1,
                    RuntimeCommitDisposition.DUPLICATE,
                    checkpoint,
                    record,
                )
            raise _conflict("runtime_store_cas_conflict")
        if checkpoint.state == request.next_state:
            return RuntimeCommitResult(
                1,
                RuntimeCommitDisposition.DUPLICATE,
                checkpoint,
                record,
            )

        validate_runtime_state(request.next_state, previous=checkpoint.state)
        next_revision = checkpoint.revision + 1
        checkpoint_expires_at = self._checkpoint_expiry(now, request.next_state)
        updated_checkpoint = RuntimeCheckpoint(
            1,
            request.next_state,
            next_revision,
            checkpoint_expires_at,
        )
        updated_record = RuntimeDedupRecord(
            1,
            key,
            request.run_id,
            request.next_state.start_digest,
            next_revision,
            _state_outcome(request.next_state),
            checkpoint_expires_at + self._config.tombstone_ttl,
        )
        self._checkpoints[request.run_id] = updated_checkpoint
        self._dedup[key] = updated_record
        self._notify(request.run_id)
        return RuntimeCommitResult(
            1,
            RuntimeCommitDisposition.UPDATED,
            updated_checkpoint,
            updated_record,
        )

    def _collect_expired(self, now: datetime) -> None:
        expired_runs = tuple(
            run_id
            for run_id, checkpoint in self._checkpoints.items()
            if checkpoint.expires_at <= now
        )
        for run_id in expired_runs:
            del self._checkpoints[run_id]
            self._notify(run_id)

        expired_keys = tuple(
            key for key, record in self._dedup.items() if record.expires_at <= now
        )
        for key in expired_keys:
            record = self._dedup.pop(key)
            if self._run_keys.get(record.run_id) == key:
                del self._run_keys[record.run_id]
            self._notify(record.run_id, retain=False)

    def _notify(self, run_id: str, *, retain: bool = True) -> None:
        previous = self._changed.get(run_id)
        if retain:
            self._changed[run_id] = asyncio.Event()
        else:
            self._changed.pop(run_id, None)
        if previous is not None:
            previous.set()

    def _checkpoint_expiry(self, now: datetime, state: RuntimeState) -> datetime:
        expires_at = now + self._config.checkpoint_ttl
        if state.reconciliation_expires_at is not None:
            expires_at = max(expires_at, state.reconciliation_expires_at)
        return expires_at

    def _now(self) -> datetime:
        now = self._clock()
        require_aware(now, "runtime_store_clock")
        return now


def _state_outcome(state: RuntimeState):
    return state.pending_result.outcome if state.pending_result is not None else None


def _validate_port_call(call: PortCallContext, run_id: str, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_runtime_store_call")
    if call.run_id != run_id:
        raise validation_error("runtime_store_call_run_mismatch")
    _raise_if_stopped(call, now)


def _validate_unbound_port_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_runtime_store_call")
    _raise_if_stopped(call, now)


def _validate_store_call(
    call: PortCallContext | ServiceCallContext,
    run_id: str,
    now: datetime,
) -> None:
    if not isinstance(call, (PortCallContext, ServiceCallContext)):
        raise validation_error("invalid_runtime_store_call")
    if isinstance(call, PortCallContext) and call.run_id != run_id:
        raise validation_error("runtime_store_call_run_mismatch")
    _raise_if_stopped(call, now)


def _raise_if_stopped(
    call: PortCallContext | ServiceCallContext,
    now: datetime,
) -> None:
    if call.cancellation.is_cancelled:
        raise error(
            "runtime_store_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if call.deadline <= now:
        raise error(
            "runtime_store_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


async def _wait_for_change(
    changed: asyncio.Event,
    call: PortCallContext,
    now: datetime,
    *,
    wake_at: datetime,
) -> None:
    remaining = max(0.0, (wake_at - now).total_seconds())
    changed_task = asyncio.create_task(changed.wait())
    cancelled_task = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (changed_task, cancelled_task),
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled_task in done:
            raise error(
                "runtime_store_wait_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if changed_task not in done and wake_at >= call.deadline:
            raise error(
                "runtime_store_wait_timeout",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
    finally:
        for task in (changed_task, cancelled_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(changed_task, cancelled_task, return_exceptions=True)


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


def _capacity(code: str):
    return error(code, ErrorCategory.BUDGET, "request.capacity_exhausted")
