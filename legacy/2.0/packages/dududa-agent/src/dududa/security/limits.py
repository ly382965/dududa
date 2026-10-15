from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping
import uuid

from dududa.domain.primitives import ComponentRevision, DigestString, ResourceUsage
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext, ServiceCallContext

from .digests import (
    actor_digest,
    budget_reservation_request_digest,
    interaction_limit_request_digest,
    resource_digest,
    scope_digest,
    usage_digest,
)
from .models import (
    BudgetDisposition,
    BudgetLease,
    BudgetReceipt,
    BudgetReservationRequest,
    InteractionLease,
    InteractionLeaseReceipt,
    InteractionLimitRequest,
    LeaseDisposition,
)


class InMemoryInteractionLimiter:
    def __init__(
        self,
        limits: Mapping[str, int],
        *,
        policy_revision: str,
        lease_ttl: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if (
            not policy_revision.strip()
            or lease_ttl <= timedelta(0)
            or any(
                not isinstance(key, str)
                or not key.strip()
                or type(value) is not int
                or value < 0
                for key, value in limits.items()
            )
        ):
            raise ValueError("invalid interaction limit")
        self._limits = MappingProxyType(dict(limits))
        self._policy_revision = policy_revision
        self._lease_ttl = lease_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._leases: dict[str, InteractionLease] = {}
        self._keys: dict[str, str] = {}
        self._states: dict[str, LeaseDisposition | None] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        request: InteractionLimitRequest,
        *,
        call: PortCallContext,
    ) -> InteractionLease:
        if interaction_limit_request_digest(request) != request.request_digest:
            raise _limit_error("interaction_request_digest_mismatch")
        now = self._clock()
        _validate_call(call, now, _limit_error)
        async with self._lock:
            self._expire(now)
            existing_id = self._keys.get(request.idempotency_key)
            if existing_id is not None:
                existing = self._leases[existing_id]
                if existing.request_digest != request.request_digest:
                    raise _limit_error("interaction_idempotency_conflict")
                return existing
            limit = self._limits.get(str(request.action), 0)
            scope_key = _interaction_scope_key(request)
            reserved = sum(
                lease.units
                for lease_id, lease in self._leases.items()
                if _lease_scope_key(lease) == scope_key
                and self._states.get(lease_id) is not LeaseDisposition.RELEASED
                and lease.expires_at > now
                and lease.allowed
            )
            allowed = reserved + request.units <= limit
            lease = InteractionLease(
                schema_version=1,
                lease_id=self._id_factory(),
                allowed=allowed,
                request_digest=request.request_digest,
                actor_digest=actor_digest(request.actor),
                scope_digest=scope_digest(request.conversation_scope),
                action=request.action,
                units=request.units,
                idempotency_key=request.idempotency_key,
                policy_revision=self._policy_revision,
                reason_codes=("reserved",) if allowed else ("limit_exceeded",),
                reserved_at=now,
                expires_at=now + self._lease_ttl,
            )
            self._leases[lease.lease_id] = lease
            self._keys[request.idempotency_key] = lease.lease_id
            self._states[lease.lease_id] = None
            return lease

    async def commit(
        self,
        lease: InteractionLease,
        *,
        call: PortCallContext,
    ) -> InteractionLeaseReceipt:
        return await self._finish(lease, LeaseDisposition.COMMITTED, call)

    async def release(
        self,
        lease: InteractionLease,
        *,
        call: PortCallContext,
    ) -> InteractionLeaseReceipt:
        return await self._finish(lease, LeaseDisposition.RELEASED, call)

    async def _finish(
        self,
        lease: InteractionLease,
        disposition: LeaseDisposition,
        call: PortCallContext,
    ) -> InteractionLeaseReceipt:
        now = self._clock()
        _validate_call(call, now, _limit_error)
        async with self._lock:
            self._expire(now)
            stored = self._leases.get(lease.lease_id)
            if stored != lease:
                raise _limit_error("unknown_or_tampered_interaction_lease")
            if not lease.allowed and disposition is LeaseDisposition.COMMITTED:
                raise _limit_error("denied_interaction_lease_cannot_commit")
            current = self._states[lease.lease_id]
            if current is LeaseDisposition.COMMITTED:
                result = LeaseDisposition.ALREADY_COMMITTED
            elif current is LeaseDisposition.RELEASED:
                result = LeaseDisposition.ALREADY_RELEASED
            else:
                self._states[lease.lease_id] = disposition
                result = disposition
        return InteractionLeaseReceipt(
            1,
            lease.lease_id,
            lease.idempotency_key,
            result,
            ComponentRevision(
                "security.interaction-limiter",
                "1",
                self._policy_revision,
                DigestString("builtin"),
            ),
            now,
        )

    def _expire(self, now: datetime) -> None:
        for lease_id, lease in self._leases.items():
            if (
                self._states.get(lease_id) is not LeaseDisposition.RELEASED
                and lease.expires_at <= now
            ):
                self._states[lease_id] = LeaseDisposition.RELEASED


class InMemoryBudgetLedger:
    def __init__(
        self,
        capacity: ResourceUsage,
        *,
        policy_revision: str,
        lease_ttl: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not policy_revision.strip() or lease_ttl <= timedelta(0):
            raise ValueError("invalid budget ledger config")
        self._capacity = capacity
        self._remaining = capacity
        self._policy_revision = policy_revision
        self._lease_ttl = lease_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._leases: dict[str, BudgetLease] = {}
        self._keys: dict[str, str] = {}
        self._receipts: dict[str, BudgetReceipt] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        request: BudgetReservationRequest,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetLease:
        if budget_reservation_request_digest(request) != request.request_digest:
            raise _budget_error("budget_request_digest_mismatch")
        now = self._clock()
        _validate_call(call, now, _budget_error)
        async with self._lock:
            existing_id = self._keys.get(request.idempotency_key)
            if existing_id is not None:
                lease = self._leases[existing_id]
                if lease.request_digest != request.request_digest:
                    raise _budget_error("budget_idempotency_conflict")
                return lease
            if not _fits(request.maximum, self._remaining):
                raise _budget_error("budget_exhausted")
            self._remaining = _subtract(self._remaining, request.maximum)
            lease = BudgetLease(
                1,
                self._id_factory(),
                request.request_digest,
                resource_digest(request.resource),
                request.idempotency_key,
                request.maximum,
                self._policy_revision,
                now,
                now + self._lease_ttl,
            )
            self._leases[lease.lease_id] = lease
            self._keys[lease.idempotency_key] = lease.lease_id
            return lease

    async def settle(
        self,
        lease: BudgetLease,
        usage: ResourceUsage,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetReceipt:
        charged = usage
        if usage.cost_units is None and lease.reserved.cost_units is not None:
            charged = replace(usage, cost_units=lease.reserved.cost_units)
        if not _fits(charged, lease.reserved):
            raise _budget_error("usage_exceeds_reservation")
        return await self._finish(lease, charged, BudgetDisposition.SETTLED, call)

    async def release(
        self,
        lease: BudgetLease,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetReceipt:
        return await self._finish(
            lease,
            _zero_usage(),
            BudgetDisposition.RELEASED,
            call,
        )

    async def _finish(
        self,
        lease: BudgetLease,
        charged: ResourceUsage,
        disposition: BudgetDisposition,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetReceipt:
        now = self._clock()
        _validate_call(call, now, _budget_error)
        async with self._lock:
            stored = self._leases.get(lease.lease_id)
            if stored != lease:
                raise _budget_error("unknown_or_tampered_budget_lease")
            existing = self._receipts.get(lease.lease_id)
            if existing is not None:
                if (
                    existing.usage_digest != usage_digest(charged)
                    or existing.disposition is not disposition
                ):
                    raise _budget_error("budget_settlement_conflict")
                return BudgetReceipt(
                    1,
                    existing.lease_id,
                    existing.request_digest,
                    existing.usage_digest,
                    existing.idempotency_key,
                    BudgetDisposition.DUPLICATE,
                    existing.charged,
                    existing.remaining,
                    now,
                )
            refund = _subtract(lease.reserved, charged)
            self._remaining = _add(self._remaining, refund)
            receipt = BudgetReceipt(
                1,
                lease.lease_id,
                lease.request_digest,
                usage_digest(charged),
                lease.idempotency_key,
                disposition,
                charged,
                self._remaining,
                now,
            )
            self._receipts[lease.lease_id] = receipt
            return receipt


def _interaction_scope_key(request: InteractionLimitRequest) -> tuple[str, str, str]:
    return (
        str(actor_digest(request.actor)),
        str(scope_digest(request.conversation_scope)),
        str(request.action),
    )


def _lease_scope_key(lease: InteractionLease) -> tuple[str, str, str]:
    return (str(lease.actor_digest), str(lease.scope_digest), str(lease.action))


def _values(value: ResourceUsage) -> tuple[int | Decimal | None, ...]:
    return (
        value.model_calls,
        value.tool_steps,
        value.retries,
        value.input_tokens,
        value.output_tokens,
        value.cost_units,
    )


def _fits(needed: ResourceUsage, available: ResourceUsage) -> bool:
    for need, have in zip(_values(needed), _values(available)):
        if need is None:
            continue
        if have is None or need > have:
            return False
    return True


def _subtract(left: ResourceUsage, right: ResourceUsage) -> ResourceUsage:
    return ResourceUsage(
        1,
        left.model_calls - right.model_calls,
        left.tool_steps - right.tool_steps,
        left.retries - right.retries,
        left.input_tokens - right.input_tokens,
        left.output_tokens - right.output_tokens,
        None
        if left.cost_units is None
        else left.cost_units - (right.cost_units or Decimal(0)),
    )


def _add(left: ResourceUsage, right: ResourceUsage) -> ResourceUsage:
    return ResourceUsage(
        1,
        left.model_calls + right.model_calls,
        left.tool_steps + right.tool_steps,
        left.retries + right.retries,
        left.input_tokens + right.input_tokens,
        left.output_tokens + right.output_tokens,
        None
        if left.cost_units is None
        else left.cost_units + (right.cost_units or Decimal(0)),
    )


def _zero_usage() -> ResourceUsage:
    return ResourceUsage(1, 0, 0, 0, 0, 0, Decimal(0))


def _limit_error(code: str):
    return error(code, ErrorCategory.CONFLICT, "security.rate_limited")


def _budget_error(code: str):
    return error(code, ErrorCategory.BUDGET, "runtime.budget_exhausted")


def _validate_call(
    call: PortCallContext | ServiceCallContext,
    now: datetime,
    error_factory: Callable[[str], BaseException],
) -> None:
    if call.cancellation.is_cancelled or call.deadline <= now:
        raise error_factory("security_call_cancelled_or_expired")
