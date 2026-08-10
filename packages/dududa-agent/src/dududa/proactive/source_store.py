from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from dududa.domain.primitives import DigestString
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext

from .source_contracts import (
    SourceCursor,
    SourceDedupDisposition,
    SourceDedupReceipt,
    SourceItemIdentity,
    SourcePolicySnapshot,
    SourceStateCommitPlan,
    SourceStateCommitReceipt,
)


class InMemorySourcePolicyRegistry:
    def __init__(
        self,
        snapshots: Iterable[SourcePolicySnapshot],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        values: dict[str, SourcePolicySnapshot] = {}
        for snapshot in snapshots:
            if not isinstance(snapshot, SourcePolicySnapshot):
                raise validation_error("invalid_source_policy_snapshot")
            if snapshot.policy_id in values:
                raise validation_error("duplicate_source_policy_id")
            values[snapshot.policy_id] = snapshot
        if not values:
            raise validation_error("empty_source_policy_registry")
        self._snapshots = values
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def resolve(
        self,
        policy_id: str,
        *,
        expected_digest: DigestString,
    ) -> SourcePolicySnapshot:
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise validation_error("invalid_source_policy_id")
        if not isinstance(expected_digest, str) or not expected_digest.strip():
            raise validation_error("invalid_source_policy_digest")
        snapshot = self._snapshots.get(policy_id)
        if snapshot is None:
            raise _conflict("source_policy_not_found")
        if snapshot.policy_digest != expected_digest:
            raise _conflict("source_policy_digest_mismatch")
        now = _utc(self._clock(), "source_policy_now")
        if not snapshot.acquired_at <= now < snapshot.valid_until:
            raise _conflict("source_policy_snapshot_stale")
        return snapshot


@dataclass(frozen=True, slots=True)
class _ItemRecord:
    identity: SourceItemIdentity
    ledger_revision: int


class InMemorySourceStateStore:
    """Atomic reference store for cursor and item-ledger state."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cursors: dict[tuple[str, str], SourceCursor] = {}
        self._items: dict[tuple[str, str], _ItemRecord] = {}
        self._lock = threading.RLock()

    async def load_cursor(
        self,
        subscription_id: str,
        source_id: str,
        *,
        call: PortCallContext,
    ) -> SourceCursor | None:
        _non_empty(subscription_id, "source_cursor_subscription_id")
        _non_empty(source_id, "source_cursor_source_id")
        now = _utc(self._clock(), "source_state_now")
        _validate_call(call, now)
        with self._lock:
            _validate_call(call, _utc(self._clock(), "source_state_now"))
            return self._cursors.get((subscription_id, source_id))

    async def commit_fetch(
        self,
        plan: SourceStateCommitPlan,
        *,
        call: PortCallContext,
    ) -> SourceStateCommitReceipt:
        if not isinstance(plan, SourceStateCommitPlan):
            raise validation_error("invalid_source_state_commit_plan")
        now = _utc(self._clock(), "source_state_now")
        _validate_call(call, now)
        if plan.planned_at > now:
            raise validation_error("source_state_plan_from_future")

        with self._lock:
            _validate_call(call, _utc(self._clock(), "source_state_now"))
            cursors = dict(self._cursors)
            items = dict(self._items)
            next_cursors: list[SourceCursor] = []
            receipts: list[SourceDedupReceipt] = []

            for mutation in plan.mutations:
                cursor_key = (mutation.subscription_id, mutation.source_id)
                current_cursor = cursors.get(cursor_key)
                _apply_cursor_mutation(
                    current_cursor,
                    mutation.expected_cursor_digest,
                    mutation.next_cursor,
                )
                cursors[cursor_key] = mutation.next_cursor
                next_cursors.append(mutation.next_cursor)

                for identity in mutation.identities:
                    item_key = (
                        mutation.subscription_id,
                        str(identity.stable_key_digest),
                    )
                    current_item = items.get(item_key)
                    record, receipt = _classify_item(
                        mutation.subscription_id,
                        identity,
                        current_item,
                        notify_revisions=mutation.notify_revisions,
                        at=mutation.observed_at,
                    )
                    items[item_key] = record
                    receipts.append(receipt)

            committed_at = _utc(self._clock(), "source_state_now")
            _validate_call(call, committed_at)
            result = SourceStateCommitReceipt(
                schema_version=1,
                plan=plan,
                next_cursors=tuple(next_cursors),
                dedup_receipts=tuple(receipts),
                committed_at=committed_at,
            )
            self._cursors = cursors
            self._items = items
            return result


def _apply_cursor_mutation(
    current: SourceCursor | None,
    expected_digest: DigestString | None,
    next_cursor: SourceCursor,
) -> None:
    if current is None:
        if expected_digest is not None or next_cursor.revision != 1:
            raise _conflict("source_cursor_create_conflict")
        return
    if expected_digest != current.cursor_digest:
        raise _conflict("source_cursor_cas_conflict")
    if next_cursor == current:
        return
    if (
        next_cursor.revision != current.revision + 1
        or next_cursor.observed_at < current.observed_at
    ):
        raise _conflict("source_cursor_cas_conflict")


def _classify_item(
    subscription_id: str,
    identity: SourceItemIdentity,
    current: _ItemRecord | None,
    *,
    notify_revisions: bool,
    at: datetime,
) -> tuple[_ItemRecord, SourceDedupReceipt]:
    if current is None:
        record = _ItemRecord(identity, 1)
        disposition = SourceDedupDisposition.NEW
        previous = None
    elif current.identity.revision_key_digest == identity.revision_key_digest:
        record = current
        disposition = SourceDedupDisposition.DUPLICATE
        previous = current.identity.revision_key_digest
    else:
        record = _ItemRecord(identity, current.ledger_revision + 1)
        disposition = (
            SourceDedupDisposition.REVISION_EMIT
            if notify_revisions
            else SourceDedupDisposition.REVISION_HELD
        )
        previous = current.identity.revision_key_digest
    return record, SourceDedupReceipt(
        schema_version=1,
        subscription_id=subscription_id,
        identity=identity,
        disposition=disposition,
        previous_revision_key_digest=previous,
        ledger_revision=record.ledger_revision,
        recorded_at=at,
    )


def _validate_call(call: PortCallContext, now: datetime) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_source_port_call")
    if call.cancellation.is_cancelled:
        raise error(
            "source_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if call.deadline <= now:
        raise error(
            "source_call_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


def _utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_source_datetime", field_name)
    return value.astimezone(timezone.utc)


def _non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_source_string", field_name)
    return value


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


__all__ = ["InMemorySourcePolicyRegistry", "InMemorySourceStateStore"]
