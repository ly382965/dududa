from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import PortCallContext

from .contracts import (
    MAX_TOOL_ATTEMPTS,
    ToolExecutionStatus,
    ToolInvocationClaim,
    ToolInvocationClaimRequest,
    ToolInvocationDisposition,
    ToolInvocationReceipt,
    ToolObservation,
)
from .digests import tool_invocation_claim_digest, tool_invocation_receipt_digest


@dataclass(slots=True)
class _InvocationRecord:
    owner: ToolInvocationClaim
    changed: asyncio.Event
    receipt: ToolInvocationReceipt | None = None
    retain_until: datetime | None = None


class InMemoryToolInvocationLedger:
    """Capacity-bounded single-flight ownership for governed Provider calls."""

    def __init__(
        self,
        *,
        maximum_records: int = 1_024,
        maximum_history: int = 8_192,
        terminal_retention: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if type(maximum_records) is not int or maximum_records < 1:
            raise ValueError("maximum_records must be positive")
        if (
            type(maximum_history) is not int
            or maximum_history < maximum_records * MAX_TOOL_ATTEMPTS
        ):
            raise ValueError("maximum_history must cover every active attempt")
        if not isinstance(
            terminal_retention, timedelta
        ) or terminal_retention <= timedelta(0):
            raise ValueError("terminal_retention must be positive")
        self._maximum_records = maximum_records
        self._maximum_history = maximum_history
        self._terminal_retention = terminal_retention
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._records: OrderedDict[str, _InvocationRecord] = OrderedDict()
        self._history: OrderedDict[str, ToolInvocationReceipt] = OrderedDict()
        self._history_by_request: dict[tuple[str, str], str] = {}
        self._seen_by_key: dict[str, set[str]] = {}
        self._sealed_until: OrderedDict[str, datetime] = OrderedDict()
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        request: ToolInvocationClaimRequest,
        *,
        call: PortCallContext,
    ) -> ToolInvocationClaim:
        if not isinstance(request, ToolInvocationClaimRequest):
            raise validation_error("invalid_tool_invocation_claim_request")
        now = self._now()
        _validate_active_call(call, now)
        if request.expires_at <= now:
            raise validation_error("tool_invocation_claim_expired")
        if request.expires_at > call.deadline:
            raise validation_error("tool_invocation_claim_exceeds_call_deadline")
        async with self._lock:
            now = self._now()
            _validate_active_call(call, now)
            if request.expires_at <= now:
                raise validation_error("tool_invocation_claim_expired")
            if request.expires_at > call.deadline:
                raise validation_error("tool_invocation_claim_exceeds_call_deadline")
            self._collect_expired(now)
            record = self._records.get(request.idempotency_key)
            historical = self._historical_receipt(request)
            disposition, receipt = self._disposition(
                record,
                historical,
                request,
                sealed=request.idempotency_key in self._sealed_until,
            )
            claim = self._claim(request, disposition, receipt, now)
            if disposition is ToolInvocationDisposition.ACQUIRED:
                if record is None and len(self._records) >= self._maximum_records:
                    raise _capacity("tool_invocation_ledger_capacity_exhausted")
                if record is not None:
                    record.changed.set()
                self._records[request.idempotency_key] = _InvocationRecord(
                    owner=claim,
                    changed=asyncio.Event(),
                )
                self._seen_by_key.setdefault(request.idempotency_key, set()).add(
                    str(request.execution_request_digest)
                )
                self._records.move_to_end(request.idempotency_key)
            return claim

    async def complete(
        self,
        claim: ToolInvocationClaim,
        observation: ToolObservation,
        *,
        call: PortCallContext,
    ) -> ToolInvocationReceipt:
        if not isinstance(claim, ToolInvocationClaim):
            raise validation_error("invalid_tool_invocation_claim")
        if not isinstance(observation, ToolObservation):
            raise validation_error("invalid_tool_invocation_observation")
        _validate_call_type(call)
        now = self._now()
        async with self._lock:
            record = self._records.get(claim.idempotency_key)
            if record is None or record.owner != claim:
                raise _conflict("tool_invocation_claim_not_owned")
            if claim.disposition is not ToolInvocationDisposition.ACQUIRED:
                raise _conflict("tool_invocation_claim_not_acquired")
            if record.receipt is not None:
                if record.receipt.observation == observation:
                    return record.receipt
                raise _conflict("tool_invocation_already_completed")
            if observation.idempotency_key != claim.idempotency_key:
                raise _conflict("tool_invocation_observation_key_mismatch")
            if observation.execution_request_digest != claim.execution_request_digest:
                raise _conflict("tool_invocation_observation_execution_mismatch")
            if observation.attempt != claim.attempt:
                raise _conflict("tool_invocation_observation_attempt_mismatch")
            values = {
                "schema_version": 1,
                "claim_id": claim.claim_id,
                "claim_request_digest": claim.claim_request_digest,
                "idempotency_key": claim.idempotency_key,
                "execution_request_digest": claim.execution_request_digest,
                "observation": observation,
                "completed_at": now,
            }
            receipt = ToolInvocationReceipt(
                receipt_digest=tool_invocation_receipt_digest(values),
                **values,
            )
            record.receipt = receipt
            record.retain_until = max(
                claim.expires_at,
                now + self._terminal_retention,
            )
            record.changed.set()
            self._records.move_to_end(claim.idempotency_key)
            self._remember(receipt)
            return receipt

    async def wait(
        self,
        claim: ToolInvocationClaim,
        *,
        call: PortCallContext,
    ) -> ToolInvocationReceipt | None:
        if not isinstance(claim, ToolInvocationClaim):
            raise validation_error("invalid_tool_invocation_claim")
        while True:
            now = self._now()
            _validate_active_call(call, now)
            async with self._lock:
                receipt = self._receipt_for_claim(claim)
                if receipt is not None:
                    return receipt
                if claim.disposition is ToolInvocationDisposition.CONFLICT:
                    return None
                record = self._records.get(claim.idempotency_key)
                if record is None:
                    raise _conflict("tool_invocation_claim_unknown")
                if (
                    record.owner.execution_request_digest
                    != claim.execution_request_digest
                ):
                    raise _conflict("tool_invocation_claim_generation_conflict")
                if claim.disposition is ToolInvocationDisposition.ACQUIRED:
                    if record.owner != claim:
                        raise _conflict("tool_invocation_claim_not_owned")
                elif (
                    claim.disposition is not ToolInvocationDisposition.DUPLICATE_PENDING
                ):
                    raise _conflict("tool_invocation_claim_invalid_wait")
                changed = record.changed
                wake_at = min(call.deadline, record.owner.expires_at)
                if wake_at <= now:
                    return None
            changed_before_expiry = await _wait_for_change(
                changed,
                call,
                now,
                wake_at=wake_at,
            )
            if not changed_before_expiry:
                return None

    def _disposition(
        self,
        record: _InvocationRecord | None,
        historical: ToolInvocationReceipt | None,
        request: ToolInvocationClaimRequest,
        *,
        sealed: bool,
    ) -> tuple[ToolInvocationDisposition, ToolInvocationReceipt | None]:
        if historical is not None:
            return ToolInvocationDisposition.DUPLICATE_COMPLETED, historical
        if sealed:
            return ToolInvocationDisposition.CONFLICT, None
        if record is None:
            return ToolInvocationDisposition.ACQUIRED, None
        if record.receipt is None:
            if (
                record.owner.execution_request_digest
                == request.execution_request_digest
            ):
                return ToolInvocationDisposition.DUPLICATE_PENDING, None
            return ToolInvocationDisposition.CONFLICT, None
        if (
            _is_known_retryable_failure(record.receipt.observation)
            and record.owner.execution_request_digest
            != request.execution_request_digest
            and request.maximum_attempts == record.owner.maximum_attempts
            and request.attempt == record.owner.attempt + 1
            and request.attempt <= request.maximum_attempts
            and len(self._seen_by_key.get(request.idempotency_key, ()))
            < request.maximum_attempts
        ):
            return ToolInvocationDisposition.ACQUIRED, None
        return ToolInvocationDisposition.DUPLICATE_COMPLETED, record.receipt

    def _historical_receipt(
        self,
        request: ToolInvocationClaimRequest,
    ) -> ToolInvocationReceipt | None:
        digest = self._history_by_request.get(
            (request.idempotency_key, str(request.execution_request_digest))
        )
        return self._history.get(digest) if digest is not None else None

    def _claim(
        self,
        request: ToolInvocationClaimRequest,
        disposition: ToolInvocationDisposition,
        receipt: ToolInvocationReceipt | None,
        now: datetime,
    ) -> ToolInvocationClaim:
        values = {
            "schema_version": 1,
            "claim_id": self._new_id("tool-claim"),
            "claim_request_digest": request.request_digest,
            "idempotency_key": request.idempotency_key,
            "execution_request_digest": request.execution_request_digest,
            "attempt": request.attempt,
            "maximum_attempts": request.maximum_attempts,
            "disposition": disposition,
            "terminal_receipt_digest": (
                receipt.receipt_digest if receipt is not None else None
            ),
            "claimed_at": now,
            "expires_at": request.expires_at,
        }
        return ToolInvocationClaim(
            claim_digest=tool_invocation_claim_digest(values),
            **values,
        )

    def _receipt_for_claim(
        self,
        claim: ToolInvocationClaim,
    ) -> ToolInvocationReceipt | None:
        if claim.terminal_receipt_digest is not None:
            receipt = self._history.get(str(claim.terminal_receipt_digest))
            if receipt is None or receipt.idempotency_key != claim.idempotency_key:
                raise _conflict("tool_invocation_terminal_receipt_unknown")
            return receipt
        digest = self._history_by_request.get(
            (claim.idempotency_key, str(claim.execution_request_digest))
        )
        if digest is not None:
            receipt = self._history.get(digest)
            if receipt is not None:
                return receipt
        record = self._records.get(claim.idempotency_key)
        if (
            record is not None
            and record.receipt is not None
            and record.owner.execution_request_digest == claim.execution_request_digest
        ):
            return record.receipt
        return None

    def _remember(self, receipt: ToolInvocationReceipt) -> None:
        digest = str(receipt.receipt_digest)
        request_key = (
            receipt.idempotency_key,
            str(receipt.execution_request_digest),
        )
        self._history[digest] = receipt
        self._history.move_to_end(digest)
        self._history_by_request[request_key] = digest
        while len(self._history) > self._maximum_history:
            forgotten_digest, forgotten = self._history.popitem(last=False)
            forgotten_key = (
                forgotten.idempotency_key,
                str(forgotten.execution_request_digest),
            )
            if self._history_by_request.get(forgotten_key) == forgotten_digest:
                del self._history_by_request[forgotten_key]

    def _collect_expired(self, now: datetime) -> None:
        expired_seals = tuple(
            key for key, retain_until in self._sealed_until.items() if retain_until <= now
        )
        for key in expired_seals:
            del self._sealed_until[key]
            self._seen_by_key.pop(key, None)

        expired_terminals = tuple(
            key
            for key, record in self._records.items()
            if record.receipt is not None
            and record.retain_until is not None
            and record.retain_until <= now
        )
        for key in expired_terminals:
            del self._records[key]
            self._seen_by_key.pop(key, None)
            forgotten = tuple(
                (digest, receipt)
                for digest, receipt in self._history.items()
                if receipt.idempotency_key == key
            )
            for digest, receipt in forgotten:
                del self._history[digest]
                request_key = (key, str(receipt.execution_request_digest))
                if self._history_by_request.get(request_key) == digest:
                    del self._history_by_request[request_key]

        available_seals = self._maximum_history - len(self._sealed_until)
        if available_seals <= 0:
            return
        expired_pending = tuple(
            (key, record)
            for key, record in self._records.items()
            if record.receipt is None and record.owner.expires_at <= now
        )[:available_seals]
        for key, record in expired_pending:
            record.changed.set()
            del self._records[key]
            self._sealed_until[key] = now + self._terminal_retention

    def _new_id(self, prefix: str) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "tool_invocation_ledger_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_tool_invocation_ledger_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - clock failures are sanitized.
            raise error(
                "tool_invocation_ledger_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_tool_invocation_ledger_clock")
        return value


def _validate_call_type(call: PortCallContext) -> None:
    if not isinstance(call, PortCallContext):
        raise validation_error("invalid_tool_invocation_ledger_call")


def _validate_active_call(call: PortCallContext, now: datetime) -> None:
    _validate_call_type(call)
    try:
        cancelled = call.cancellation.is_cancelled
    except Exception:  # noqa: BLE001 - cancellation implementations are untrusted.
        raise error(
            "tool_invocation_cancellation_unavailable",
            ErrorCategory.INTERNAL,
            "service.unavailable",
        ) from None
    if cancelled:
        raise error(
            "tool_invocation_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "tool_invocation_call_expired",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


async def _wait_for_change(
    changed: asyncio.Event,
    call: PortCallContext,
    now: datetime,
    *,
    wake_at: datetime,
) -> bool:
    remaining = max(0.0, (wake_at - now).total_seconds())
    changed_task = asyncio.create_task(changed.wait())
    try:
        cancelled_task = asyncio.create_task(call.cancellation.wait())
    except Exception:  # noqa: BLE001 - cancellation implementations are untrusted.
        changed_task.cancel()
        await asyncio.gather(changed_task, return_exceptions=True)
        raise error(
            "tool_invocation_cancellation_unavailable",
            ErrorCategory.INTERNAL,
            "service.unavailable",
        ) from None
    try:
        done, _ = await asyncio.wait(
            (changed_task, cancelled_task),
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled_task in done:
            try:
                cancelled_task.result()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - raw token failures are hidden.
                raise error(
                    "tool_invocation_cancellation_unavailable",
                    ErrorCategory.INTERNAL,
                    "service.unavailable",
                ) from None
            raise error(
                "tool_invocation_wait_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if changed_task in done:
            return True
        if wake_at >= call.deadline:
            raise error(
                "tool_invocation_wait_timeout",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )
        return False
    finally:
        for task in (changed_task, cancelled_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(changed_task, cancelled_task, return_exceptions=True)


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


def _capacity(code: str):
    return error(code, ErrorCategory.BUDGET, "request.capacity_exhausted")


def _is_known_retryable_failure(observation: ToolObservation) -> bool:
    return bool(
        observation.status is ToolExecutionStatus.FAILED
        and observation.error is not None
        and observation.error.info.retryable
        and not observation.error.info.outcome_unknown
    )


__all__ = ["InMemoryToolInvocationLedger"]
