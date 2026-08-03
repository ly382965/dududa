from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import TypeVar
import uuid

from dududa.errors import validation_error
from dududa.ports.context import PortCallContext, ServiceCallContext

from .contracts import (
    AdmissionDisposition,
    EndpointAdmissionRequest,
    EndpointAdmissionResult,
    EndpointCapacityLease,
    EndpointCapacityReceipt,
    EndpointLoadSnapshot,
    EndpointTrafficPolicy,
    ModelUsage,
    StaleSnapshotPolicy,
)
from .registry import (
    InMemoryModelOperationalStateRegistry,
    InMemoryModelRoutingRegistry,
)


CallContext = PortCallContext | ServiceCallContext
_T = TypeVar("_T")


@dataclass(slots=True)
class _WindowCharge:
    recorded_at: datetime
    tokens: int


@dataclass(slots=True)
class _PoolState:
    active: dict[str, EndpointCapacityLease] = field(default_factory=dict)
    window: dict[str, _WindowCharge] = field(default_factory=dict)
    waiters: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class InMemoryModelAdmissionController:
    """Atomic shared-quota admission with conservative unknown-usage charging."""

    def __init__(
        self,
        routing_registry: InMemoryModelRoutingRegistry,
        operational_registry: InMemoryModelOperationalStateRegistry,
        *,
        admission_revision: str,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(admission_revision, str) or not admission_revision.strip():
            raise ValueError("admission_revision must be non-empty")
        self._routing_registry = routing_registry
        self._operational_registry = operational_registry
        self._admission_revision = admission_revision
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._states: dict[str, _PoolState] = {}
        self._reservation_requests: dict[str, EndpointAdmissionRequest] = {}
        self._results: dict[str, EndpointAdmissionResult] = {}
        self._pending: dict[str, asyncio.Event] = {}
        self._pending_errors: dict[str, BaseException] = {}
        self._leases: dict[str, EndpointCapacityLease] = {}
        self._receipts: dict[str, EndpointCapacityReceipt] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        request: EndpointAdmissionRequest,
        *,
        call: CallContext,
    ) -> EndpointAdmissionResult:
        if not isinstance(request, EndpointAdmissionRequest):
            raise validation_error("invalid_endpoint_admission_request")
        owner = False
        pending: asyncio.Event
        async with self._lock:
            previous = self._reservation_requests.get(request.reservation_id)
            if previous is not None and previous != request:
                raise validation_error("admission_reservation_id_conflict")
            result = self._results.get(request.reservation_id)
            if result is not None:
                return result
            previous_error = self._pending_errors.get(request.reservation_id)
            if previous_error is not None:
                raise previous_error
            pending = self._pending.get(request.reservation_id)  # type: ignore[assignment]
            if pending is None:
                pending = asyncio.Event()
                self._pending[request.reservation_id] = pending
                self._reservation_requests[request.reservation_id] = request
                owner = True
        if not owner:
            await self._wait_for_pending(pending, call)
            async with self._lock:
                error_value = self._pending_errors.get(request.reservation_id)
                if error_value is not None:
                    raise error_value
                return self._results[request.reservation_id]

        try:
            result = await self._reserve_new(request, call)
        except BaseException as exc:
            async with self._lock:
                self._pending_errors[request.reservation_id] = exc
                self._pending.pop(request.reservation_id).set()
            raise
        async with self._lock:
            self._results[request.reservation_id] = result
            self._pending.pop(request.reservation_id).set()
        return result

    async def settle(
        self,
        lease: EndpointCapacityLease,
        usage: ModelUsage | None,
        *,
        call: CallContext,
    ) -> EndpointCapacityReceipt:
        del call
        return await _await_cleanup(
            self._finalize(
                lease,
                AdmissionDisposition.SETTLED,
                usage,
            )
        )

    async def release(
        self,
        lease: EndpointCapacityLease,
        *,
        call: CallContext,
    ) -> EndpointCapacityReceipt:
        del call
        return await _await_cleanup(
            self._finalize(
                lease,
                AdmissionDisposition.RELEASED,
                None,
            )
        )

    async def _reserve_new(
        self,
        request: EndpointAdmissionRequest,
        call: CallContext,
    ) -> EndpointAdmissionResult:
        now = self._now()
        if request.expires_at > call.deadline:
            raise validation_error("capacity_lease_exceeds_call_deadline")
        snapshot = self._operational_registry.snapshot_by_id(
            request.operational_snapshot_id,
            expected_digest=request.operational_snapshot_digest,
        )
        endpoint = self._routing_registry.resolve_endpoint_revision(
            request.provider_id,
            request.endpoint_id,
            request.endpoint_descriptor_digest,
        )
        policy = endpoint.traffic_policy
        if (
            request.quota_pool_id != endpoint.quota_pool_id
            or request.traffic_policy_id != policy.policy_id
            or request.traffic_policy_revision != policy.policy_revision
        ):
            raise validation_error("admission_traffic_policy_mismatch")
        load = _load_for(snapshot.endpoint_load, request)
        queued = False
        try:
            while True:
                now = self._now()
                reason = _preflight_reason(request, load, policy, call, now)
                if reason is not None:
                    return self._rejected(request, reason, now)
                async with self._lock:
                    state = self._states.setdefault(request.quota_pool_id, _PoolState())
                    self._expire_locked(state, now)
                    if queued:
                        if state.waiters <= 0:
                            raise validation_error(
                                "admission_waiter_accounting_mismatch"
                            )
                        state.waiters -= 1
                        queued = False
                    rate_reason = _rate_reason(state, load, policy, request, now)
                    if rate_reason is not None:
                        return self._rejected(request, rate_reason, now)
                    if load.in_flight + len(state.active) < policy.max_concurrency:
                        lease = EndpointCapacityLease(
                            schema_version=1,
                            lease_id=self._new_id("capacity"),
                            request=request,
                            admission_revision=self._admission_revision,
                            issued_at=now,
                        )
                        state.active[lease.lease_id] = lease
                        state.window[lease.lease_id] = _WindowCharge(
                            recorded_at=now,
                            tokens=_reserved_tokens(request),
                        )
                        self._leases[lease.lease_id] = lease
                        return EndpointAdmissionResult(
                            schema_version=1,
                            request=request,
                            disposition=AdmissionDisposition.RESERVED,
                            lease=lease,
                            admission_revision=self._admission_revision,
                            reason_codes=("capacity_reserved",),
                            decided_at=now,
                        )
                    if (
                        policy.max_queue_depth == 0
                        or load.queue_depth + state.waiters >= policy.max_queue_depth
                    ):
                        return self._rejected(
                            request,
                            "queue_capacity_exhausted",
                            now,
                        )
                    state.waiters += 1
                    queued = True
                    changed = state.changed
                    wake_at = min(
                        call.deadline,
                        request.expires_at,
                        *(lease.request.expires_at for lease in state.active.values()),
                    )
                wait_reason = await _wait_for_change(
                    changed,
                    call,
                    now,
                    deadline=wake_at,
                )
                if wait_reason == "admission_cancelled":
                    return self._rejected(request, wait_reason, self._now())
        finally:
            if queued:
                await _await_cleanup(self._remove_waiter(request.quota_pool_id))

    async def _remove_waiter(self, quota_pool_id: str) -> None:
        async with self._lock:
            state = self._states[quota_pool_id]
            if state.waiters <= 0:
                raise validation_error("admission_waiter_accounting_mismatch")
            state.waiters -= 1

    async def _finalize(
        self,
        lease: EndpointCapacityLease,
        disposition: AdmissionDisposition,
        usage: ModelUsage | None,
    ) -> EndpointCapacityReceipt:
        if not isinstance(lease, EndpointCapacityLease):
            raise validation_error("invalid_endpoint_capacity_lease")
        now = self._now()
        async with self._lock:
            state = self._states.get(lease.request.quota_pool_id)
            stored = self._leases.get(lease.lease_id)
            if state is None or stored != lease:
                raise validation_error("unknown_or_tampered_capacity_lease")
            self._expire_locked(state, now)
            existing = self._receipts.get(lease.lease_id)
            if existing is not None:
                if existing.disposition is disposition:
                    return existing
                raise validation_error("capacity_lease_already_finalized")
            if disposition is AdmissionDisposition.SETTLED:
                charged = _charged_usage(lease.request, usage)
                reason_codes = (
                    ("reservation_ceiling_charged",)
                    if usage is None
                    else ("reported_usage_charged",)
                )
                state.window[lease.lease_id].tokens = charged.total_tokens
            elif disposition is AdmissionDisposition.RELEASED:
                charged = None
                reason_codes = ("capacity_released",)
                state.window.pop(lease.lease_id, None)
            else:
                raise validation_error("invalid_capacity_final_disposition")
            state.active.pop(lease.lease_id, None)
            receipt = EndpointCapacityReceipt(
                schema_version=1,
                lease_id=lease.lease_id,
                disposition=disposition,
                usage=charged,
                reason_codes=reason_codes,
                recorded_at=now,
            )
            self._receipts[lease.lease_id] = receipt
            _notify(state)
            return receipt

    def _expire_locked(self, state: _PoolState, now: datetime) -> None:
        expired = tuple(
            lease for lease in state.active.values() if lease.request.expires_at <= now
        )
        for lease in expired:
            charged = _ceiling_usage(lease.request)
            state.active.pop(lease.lease_id, None)
            state.window[lease.lease_id].tokens = charged.total_tokens
            self._receipts[lease.lease_id] = EndpointCapacityReceipt(
                schema_version=1,
                lease_id=lease.lease_id,
                disposition=AdmissionDisposition.SETTLED,
                usage=charged,
                reason_codes=("expired_lease_ceiling_charged",),
                recorded_at=now,
            )
        if expired:
            _notify(state)

    async def _wait_for_pending(
        self,
        pending: asyncio.Event,
        call: CallContext,
    ) -> None:
        reason = await _wait_for_change(pending, call, self._now())
        if reason is not None:
            if reason == "admission_wait_timeout":
                reason = "admission_deadline_exceeded"
            raise validation_error(reason)

    def _rejected(
        self,
        request: EndpointAdmissionRequest,
        reason: str,
        now: datetime,
    ) -> EndpointAdmissionResult:
        return EndpointAdmissionResult(
            schema_version=1,
            request=request,
            disposition=AdmissionDisposition.REJECTED,
            lease=None,
            admission_revision=self._admission_revision,
            reason_codes=(reason,),
            decided_at=now,
        )

    def _new_id(self, prefix: str) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value.strip():
            raise ValueError("id_factory returned an empty identifier")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock returned a naive datetime")
        return value


def _load_for(
    loads: tuple[EndpointLoadSnapshot, ...],
    request: EndpointAdmissionRequest,
) -> EndpointLoadSnapshot:
    for load in loads:
        if (
            load.provider_id == request.provider_id
            and load.endpoint_id == request.endpoint_id
        ):
            if (
                load.endpoint_descriptor_digest != request.endpoint_descriptor_digest
                or load.quota_pool_id != request.quota_pool_id
                or load.traffic_policy_id != request.traffic_policy_id
                or load.traffic_policy_revision != request.traffic_policy_revision
            ):
                raise validation_error("admission_load_binding_mismatch")
            return load
    raise validation_error("admission_load_observation_missing")


def _preflight_reason(
    request: EndpointAdmissionRequest,
    load: EndpointLoadSnapshot,
    policy: EndpointTrafficPolicy,
    call: CallContext,
    now: datetime,
) -> str | None:
    if call.cancellation.is_cancelled:
        return "admission_cancelled"
    if now >= call.deadline or now >= request.expires_at:
        return "admission_deadline_exceeded"
    if load.checked_at > now:
        return "load_observation_from_future"
    age = (now - load.checked_at).total_seconds()
    if (
        age > policy.max_snapshot_age_seconds
        and policy.stale_snapshot_policy is StaleSnapshotPolicy.EXCLUDE
    ):
        return "load_snapshot_stale"
    if load.sample_count < policy.minimum_samples:
        return "load_samples_insufficient"
    if load.cooldown_until is not None and load.cooldown_until > now:
        return "endpoint_cooldown_active"
    if policy.max_p95_latency_ms is not None:
        if load.p95_latency_ms is None:
            return "p95_latency_missing"
        if load.p95_latency_ms > policy.max_p95_latency_ms:
            return "p95_latency_exceeded"
    if load.rate_429 > policy.max_429_rate:
        return "rate_429_exceeded"
    if load.error_rate > policy.max_error_rate:
        return "error_rate_exceeded"
    if load.queue_depth > policy.max_queue_depth:
        return "observed_queue_exceeded"
    if load.p95_latency_ms is not None and (
        now + timedelta(milliseconds=load.p95_latency_ms) >= call.deadline
    ):
        return "deadline_capacity_insufficient"
    return None


def _rate_reason(
    state: _PoolState,
    load: EndpointLoadSnapshot,
    policy: EndpointTrafficPolicy,
    request: EndpointAdmissionRequest,
    now: datetime,
) -> str | None:
    cutoff = now - timedelta(seconds=policy.observation_window_seconds)
    for lease_id, charge in tuple(state.window.items()):
        if charge.recorded_at <= cutoff and lease_id not in state.active:
            state.window.pop(lease_id, None)
    local_requests = len(state.window)
    local_tokens = sum(charge.tokens for charge in state.window.values())
    if (
        policy.rpm_limit is not None
        and load.requests_per_minute + local_requests + 1 > policy.rpm_limit
    ):
        return "rpm_capacity_exhausted"
    if (
        policy.tpm_limit is not None
        and load.tokens_per_minute + local_tokens + _reserved_tokens(request)
        > policy.tpm_limit
    ):
        return "tpm_capacity_exhausted"
    return None


def _charged_usage(
    request: EndpointAdmissionRequest,
    usage: ModelUsage | None,
) -> ModelUsage:
    if usage is None:
        return _ceiling_usage(request)
    charged = usage
    if usage.cost_units is None and request.reserved_cost_units is not None:
        charged = replace(usage, cost_units=request.reserved_cost_units)
    if (
        charged.input_tokens > request.reserved_input_tokens
        or charged.generated_tokens > request.reserved_generated_tokens
        or (
            charged.reasoning_tokens is not None
            and charged.reasoning_tokens > request.reserved_reasoning_tokens
        )
        or (
            request.reserved_cost_units is not None
            and (
                charged.cost_units is None
                or charged.cost_units > request.reserved_cost_units
            )
        )
    ):
        raise validation_error("model_usage_exceeds_capacity_reservation")
    return charged


def _ceiling_usage(request: EndpointAdmissionRequest) -> ModelUsage:
    return ModelUsage(
        schema_version=1,
        input_tokens=request.reserved_input_tokens,
        generated_tokens=request.reserved_generated_tokens,
        reasoning_tokens=request.reserved_reasoning_tokens,
        cached_input_tokens=None,
        cost_units=request.reserved_cost_units,
    )


def _reserved_tokens(request: EndpointAdmissionRequest) -> int:
    return request.reserved_input_tokens + request.reserved_generated_tokens


def _notify(state: _PoolState) -> None:
    previous = state.changed
    state.changed = asyncio.Event()
    previous.set()


async def _wait_for_change(
    changed: asyncio.Event,
    call: CallContext,
    now: datetime,
    *,
    deadline: datetime | None = None,
) -> str | None:
    wait_deadline = min(call.deadline, deadline or call.deadline)
    remaining = max(0.0, (wait_deadline - now).total_seconds())
    changed_task = asyncio.create_task(changed.wait())
    cancelled_task = asyncio.create_task(call.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (changed_task, cancelled_task),
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled_task in done:
            return "admission_cancelled"
        if changed_task in done:
            return None
        return "admission_wait_timeout"
    finally:
        for task in (changed_task, cancelled_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(changed_task, cancelled_task, return_exceptions=True)


async def _await_cleanup(awaitable: Awaitable[_T]) -> _T:
    task = asyncio.create_task(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            continue
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result
