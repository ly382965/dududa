from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dududa.contracts.canonical import canonical_digest
from dududa.domain.identity import ConversationScope
from dududa.domain.primitives import DigestString
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext
from dududa.security.digests import scope_digest

from .contracts import ProactiveQuotaLease, QuotaKind


class InMemoryProactiveQuotaLedger:
    """Atomically reserves one global and one exact-Scope quota unit."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._lock = asyncio.Lock()
        self._counts: dict[tuple[str, int, str | None], int] = {}
        self._reservations: dict[DigestString, _Reservation] = {}

    async def reserve(
        self,
        request_digest: DigestString,
        scope: ConversationScope,
        *,
        global_limit: int,
        scope_limit: int,
        window: timedelta,
        policy_revision: str,
        call: ServiceCallContext,
    ) -> tuple[ProactiveQuotaLease, ProactiveQuotaLease]:
        _digest(request_digest, "quota_request_digest")
        if not isinstance(scope, ConversationScope):
            raise validation_error("invalid_proactive_quota_scope")
        for field_name, value in (
            ("global_limit", global_limit),
            ("scope_limit", scope_limit),
        ):
            if type(value) is not int or value < 1:
                raise validation_error("invalid_proactive_quota_limit", field_name)
        if not isinstance(window, timedelta) or not (
            timedelta(minutes=1) <= window <= timedelta(days=366)
        ):
            raise validation_error("invalid_proactive_quota_window")
        if not isinstance(policy_revision, str) or not policy_revision.strip():
            raise validation_error("invalid_proactive_quota_revision")
        now = self._now()
        _validate_call(call, now)
        window_us = _microseconds(window)
        bucket = _epoch_microseconds(now) // window_us
        scope_hash = scope_digest(scope)
        request_projection = canonical_digest(
            {
                "request_digest": request_digest,
                "scope_digest": scope_hash,
                "global_limit": global_limit,
                "scope_limit": scope_limit,
                "window": window,
                "bucket": bucket,
                "policy_revision": policy_revision,
            },
            domain="proactive:quota-request:v1",
        )
        async with self._lock:
            now = self._now()
            _validate_call(call, now)
            existing = self._reservations.get(request_digest)
            if existing is not None:
                if existing.request_projection != request_projection:
                    raise _conflict("proactive_quota_request_conflict")
                return existing.leases
            global_key = (policy_revision, bucket, None)
            scope_key = (policy_revision, bucket, str(scope_hash))
            global_allowed = self._counts.get(global_key, 0) < global_limit
            scope_allowed = self._counts.get(scope_key, 0) < scope_limit
            allowed = global_allowed and scope_allowed
            expires_at = _bucket_expiry(bucket, window_us)
            global_lease = self._lease(
                QuotaKind.GLOBAL,
                request_digest,
                None,
                allowed,
                policy_revision,
                now,
                expires_at,
                "quota_reserved" if allowed else "global_quota_exhausted",
            )
            scope_lease = self._lease(
                QuotaKind.SCOPE,
                request_digest,
                scope_hash,
                allowed,
                policy_revision,
                now,
                expires_at,
                "quota_reserved" if allowed else "scope_quota_exhausted",
            )
            leases = (global_lease, scope_lease)
            if allowed:
                self._counts[global_key] = self._counts.get(global_key, 0) + 1
                self._counts[scope_key] = self._counts.get(scope_key, 0) + 1
            self._reservations[request_digest] = _Reservation(
                request_projection,
                leases,
                global_key,
                scope_key,
                "reserved" if allowed else "denied",
            )
            return leases

    async def commit(
        self,
        leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease],
        *,
        call: ServiceCallContext,
    ) -> None:
        await self._settle(leases, release=False, call=call)

    async def release(
        self,
        leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease],
        *,
        call: ServiceCallContext,
    ) -> None:
        await self._settle(leases, release=True, call=call)

    async def _settle(
        self,
        leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease],
        *,
        release: bool,
        call: ServiceCallContext,
    ) -> None:
        if (
            not isinstance(leases, tuple)
            or len(leases) != 2
            or {value.kind for value in leases} != {QuotaKind.GLOBAL, QuotaKind.SCOPE}
            or leases[0].request_digest != leases[1].request_digest
        ):
            raise validation_error("invalid_proactive_quota_lease_pair")
        now = self._now()
        _validate_call(call, now)
        async with self._lock:
            reservation = self._reservations.get(leases[0].request_digest)
            if reservation is None or set(reservation.leases) != set(leases):
                raise validation_error("unknown_proactive_quota_lease")
            if reservation.state in {"committed", "released", "denied"}:
                if (release and reservation.state == "released") or (
                    not release and reservation.state == "committed"
                ):
                    return
                if reservation.state == "denied":
                    return
                raise _conflict("proactive_quota_settlement_conflict")
            if release:
                for key in (reservation.global_key, reservation.scope_key):
                    count = self._counts.get(key, 0)
                    if count < 1:
                        raise _conflict("proactive_quota_count_underflow")
                    if count == 1:
                        self._counts.pop(key, None)
                    else:
                        self._counts[key] = count - 1
                reservation.state = "released"
            else:
                reservation.state = "committed"

    def _lease(
        self,
        kind: QuotaKind,
        request_digest: DigestString,
        scope_hash: DigestString | None,
        allowed: bool,
        policy_revision: str,
        now: datetime,
        expires_at: datetime,
        reason: str,
    ) -> ProactiveQuotaLease:
        return ProactiveQuotaLease(
            1,
            f"quota-lease:{self._new_id()}",
            kind,
            request_digest,
            scope_hash,
            allowed,
            1,
            policy_revision,
            now,
            expires_at,
            (reason,),
        )

    def _now(self) -> datetime:
        try:
            return _aware(self._clock(), "proactive_quota_clock")
        except Exception as exc:
            if getattr(exc, "info", None) is not None:
                raise
            raise error(
                "proactive_quota_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None

    def _new_id(self) -> str:
        try:
            value = self._id_factory()
        except Exception:  # noqa: BLE001 - factory failures are sanitized.
            raise error(
                "proactive_quota_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if not isinstance(value, str) or not value.strip():
            raise validation_error("invalid_proactive_quota_id")
        return value


@dataclass(slots=True)
class _Reservation:
    request_projection: DigestString
    leases: tuple[ProactiveQuotaLease, ProactiveQuotaLease]
    global_key: tuple[str, int, str | None]
    scope_key: tuple[str, int, str | None]
    state: str


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


def _microseconds(value: timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


def _epoch_microseconds(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value.astimezone(timezone.utc) - epoch
    return _microseconds(delta)


def _bucket_expiry(bucket: int, window_us: int) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return epoch + timedelta(microseconds=(bucket + 1) * window_us)


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


__all__ = ["InMemoryProactiveQuotaLedger"]
