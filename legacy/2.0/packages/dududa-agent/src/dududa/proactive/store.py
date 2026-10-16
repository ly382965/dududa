from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext

from .contracts import (
    DispatchClaim,
    DispatchLedgerRecord,
    DispatchState,
    PreparedDispatch,
)


class InMemoryProactiveDispatchStore:
    """Atomic Fake store whose recovery authority is the first prepared payload."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        maximum_records: int = 10_000,
    ) -> None:
        if type(maximum_records) is not int or maximum_records < 1:
            raise validation_error("invalid_proactive_dispatch_capacity")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._maximum_records = maximum_records
        self._lock = asyncio.Lock()
        self._records: dict[DigestString, DispatchLedgerRecord] = {}
        self._dispatch_ids: dict[str, DigestString] = {}
        self._claims: dict[str, DispatchClaim] = {}

    async def prepare(
        self,
        dispatch: PreparedDispatch,
        *,
        call: ServiceCallContext,
    ) -> PreparedDispatch:
        if not isinstance(dispatch, PreparedDispatch):
            raise validation_error("invalid_prepared_dispatch")
        now = self._now()
        _validate_call(call, now)
        if dispatch.expires_at <= now:
            raise validation_error("prepared_dispatch_expired")
        async with self._lock:
            now = self._now()
            _validate_call(call, now)
            existing = self._records.get(dispatch.trigger_digest)
            if existing is not None:
                if _same_business_dispatch(existing.prepared, dispatch):
                    return existing.prepared
                raise _conflict("proactive_dispatch_trigger_conflict")
            bound_trigger = self._dispatch_ids.get(dispatch.dispatch_id)
            if bound_trigger is not None:
                raise _conflict("proactive_dispatch_id_conflict")
            if len(self._records) >= self._maximum_records:
                raise error(
                    "proactive_dispatch_capacity_exhausted",
                    ErrorCategory.BUDGET,
                    "service.capacity_exhausted",
                )
            self._records[dispatch.trigger_digest] = DispatchLedgerRecord(
                1,
                dispatch,
                DispatchState.PREPARED,
                1,
                0,
                None,
                None,
                now,
            )
            self._dispatch_ids[dispatch.dispatch_id] = dispatch.trigger_digest
            return dispatch

    async def load_for_trigger(
        self,
        trigger_digest: DigestString,
        *,
        call: ServiceCallContext,
    ) -> PreparedDispatch | None:
        record = await self.load_record(trigger_digest, call=call)
        return record.prepared if record is not None else None

    async def load_record(
        self,
        trigger_digest: DigestString,
        *,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord | None:
        _digest(trigger_digest, "trigger_digest")
        now = self._now()
        _validate_call(call, now)
        async with self._lock:
            now = self._now()
            _validate_call(call, now)
            return self._records.get(trigger_digest)

    async def record_attempt(
        self,
        trigger_digest: DigestString,
        *,
        expected_revision: int,
        delivery_request_digest: DigestString,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord:
        _digest(delivery_request_digest, "delivery_request_digest")
        return await self._transition(
            trigger_digest,
            expected_revision=expected_revision,
            next_state=DispatchState.ATTEMPTED,
            delivery_request_digest=delivery_request_digest,
            delivery_receipt_digest=None,
            call=call,
        )

    async def record_outcome(
        self,
        trigger_digest: DigestString,
        *,
        expected_revision: int,
        state: DispatchState,
        delivery_request_digest: DigestString,
        delivery_receipt_digest: DigestString,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord:
        if state not in {
            DispatchState.PARTIAL,
            DispatchState.UNKNOWN,
            DispatchState.SUCCEEDED,
            DispatchState.FAILED,
        }:
            raise validation_error("invalid_dispatch_outcome_state")
        _digest(delivery_request_digest, "delivery_request_digest")
        _digest(delivery_receipt_digest, "delivery_receipt_digest")
        return await self._transition(
            trigger_digest,
            expected_revision=expected_revision,
            next_state=state,
            delivery_request_digest=delivery_request_digest,
            delivery_receipt_digest=delivery_receipt_digest,
            call=call,
        )

    async def recover(
        self,
        trigger_digest: DigestString,
        *,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord | None:
        _digest(trigger_digest, "trigger_digest")
        now = self._now()
        _validate_call(call, now)
        async with self._lock:
            now = self._now()
            _validate_call(call, now)
            record = self._records.get(trigger_digest)
            if record is None or record.state is not DispatchState.ATTEMPTED:
                return record
            # A crash after send-start has an unknown external outcome. The original
            # payload and key remain authoritative; recovery never creates another.
            receipt_digest = canonical_digest(
                {
                    "prepared_dispatch_digest": record.prepared.prepared_dispatch_digest,
                    "delivery_request_digest": record.delivery_request_digest,
                    "outcome": "unknown_after_recovery",
                },
                domain="proactive:recovered-unknown-receipt:v1",
            )
            recovered = DispatchLedgerRecord(
                1,
                record.prepared,
                DispatchState.UNKNOWN,
                record.revision + 1,
                record.attempt,
                record.delivery_request_digest,
                receipt_digest,
                now,
            )
            self._records[trigger_digest] = recovered
            return recovered

    async def claim(
        self,
        trigger_digest: DigestString,
        *,
        worker_id: str,
        ttl: timedelta,
        call: ServiceCallContext,
    ) -> DispatchClaim:
        _digest(trigger_digest, "trigger_digest")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise validation_error("invalid_dispatch_worker_id")
        if not isinstance(ttl, timedelta) or not (
            timedelta(milliseconds=1) <= ttl <= timedelta(hours=1)
        ):
            raise validation_error("invalid_dispatch_claim_ttl")
        now = self._now()
        _validate_call(call, now)
        async with self._lock:
            now = self._now()
            _validate_call(call, now)
            record = self._records.get(trigger_digest)
            if record is None:
                raise validation_error("proactive_dispatch_not_found")
            existing = self._claims.get(record.prepared.dispatch_id)
            if existing is not None and existing.expires_at > now:
                if existing.worker_id == worker_id:
                    return existing
                raise _conflict("proactive_dispatch_claim_conflict")
            revision = existing.lease_revision + 1 if existing is not None else 1
            claim = DispatchClaim(
                1,
                f"dispatch-claim:{self._new_id()}",
                record.prepared.dispatch_id,
                record.prepared.prepared_dispatch_digest,
                worker_id,
                revision,
                now,
                min(now + ttl, record.prepared.expires_at),
            )
            self._claims[record.prepared.dispatch_id] = claim
            return claim

    async def _transition(
        self,
        trigger_digest: DigestString,
        *,
        expected_revision: int,
        next_state: DispatchState,
        delivery_request_digest: DigestString,
        delivery_receipt_digest: DigestString | None,
        call: ServiceCallContext,
    ) -> DispatchLedgerRecord:
        _digest(trigger_digest, "trigger_digest")
        if type(expected_revision) is not int or expected_revision < 1:
            raise validation_error("invalid_dispatch_expected_revision")
        now = self._now()
        _validate_call(call, now)
        async with self._lock:
            now = self._now()
            _validate_call(call, now)
            record = self._records.get(trigger_digest)
            if record is None:
                raise validation_error("proactive_dispatch_not_found")
            if record.revision != expected_revision:
                if (
                    record.state is next_state
                    and record.delivery_request_digest == delivery_request_digest
                    and record.delivery_receipt_digest == delivery_receipt_digest
                ):
                    return record
                raise _conflict("proactive_dispatch_revision_conflict")
            if record.state in {
                DispatchState.PARTIAL,
                DispatchState.UNKNOWN,
                DispatchState.SUCCEEDED,
                DispatchState.FAILED,
                DispatchState.CANCELLED,
            }:
                raise _conflict("proactive_dispatch_terminal_state")
            if (
                record.state is DispatchState.ATTEMPTED
                and next_state is DispatchState.ATTEMPTED
            ):
                if record.delivery_request_digest == delivery_request_digest:
                    return record
                raise _conflict("proactive_dispatch_attempt_conflict")
            attempt = record.attempt + (record.state is DispatchState.PREPARED)
            updated = DispatchLedgerRecord(
                1,
                record.prepared,
                next_state,
                record.revision + 1,
                attempt,
                delivery_request_digest,
                delivery_receipt_digest,
                now,
            )
            self._records[trigger_digest] = updated
            return updated

    def _now(self) -> datetime:
        try:
            return _aware(self._clock(), "proactive_dispatch_clock")
        except Exception as exc:
            if getattr(exc, "info", None) is not None:
                raise
            raise error(
                "proactive_dispatch_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None

    def _new_id(self) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "proactive_dispatch_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if not isinstance(value, str) or not value.strip():
            raise validation_error("invalid_proactive_dispatch_id")
        return value


def _same_business_dispatch(left: PreparedDispatch, right: PreparedDispatch) -> bool:
    return (
        left.trigger_kind is right.trigger_kind
        and left.trigger_digest == right.trigger_digest
        and left.trigger_source_digest == right.trigger_source_digest
        and left.target_policy_ref == right.target_policy_ref
        and left.policy_decision_digest == right.policy_decision_digest
        and left.source_batch_digest == right.source_batch_digest
        and left.item_set_digest == right.item_set_digest
        and left.response_plan_digest == right.response_plan_digest
        and left.validated_response_digest == right.validated_response_digest
        and left.target_scope == right.target_scope
        and left.idempotency_key == right.idempotency_key
    )


def _validate_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_proactive_service_call")
    if call.cancellation.is_cancelled:
        raise error(
            "proactive_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if call.deadline <= now:
        raise error(
            "proactive_call_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_proactive_digest", field_name)
    return value


def _aware(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise validation_error("invalid_proactive_datetime", field_name)
    return value


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


__all__ = [
    "DispatchLedgerRecord",
    "InMemoryProactiveDispatchStore",
]
