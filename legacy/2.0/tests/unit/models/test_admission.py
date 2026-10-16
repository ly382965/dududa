from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import itertools
import time
import unittest

from dududa.domain.primitives import (
    DigestString,
    PrivacyLevel,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.models.admission import InMemoryModelAdmissionController
from dududa.models.contracts import (
    AdmissionDisposition,
    EndpointAdmissionRequest,
    EndpointHealthStatus,
    EndpointLoadSnapshot,
    LoadCounterScope,
    EndpointTrafficPolicy,
    ModelEndpointHealth,
    ModelEndpointRef,
    ModelInputModality,
    ModelInvocationEstimate,
    ModelOperationalSnapshot,
    ModelOutputModality,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRole,
    ModelTier,
    ModelUsage,
    StaleSnapshotPolicy,
    StructuredOutputSupport,
)
from dududa.models.digests import (
    model_endpoint_descriptor_digest,
    model_invocation_estimate_digest,
    model_operational_snapshot_digest,
)
from dududa.models.policy import (
    ModelCapabilitiesRequirement,
    ModelFallbackPolicy,
    ModelRoutePolicy,
)
from dududa.models.registry import (
    InMemoryModelOperationalStateRegistry,
    InMemoryModelRoutingRegistry,
)
from dududa.ports.context import NeverCancelled, ServiceCallContext, ServicePrincipal

from .helpers import NOW, endpoint, revision


class _Provider:
    def __init__(self, descriptor: ModelProviderDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> ModelProviderDescriptor:
        return self._descriptor

    async def generate(self, request, *, call):  # pragma: no cover
        raise AssertionError("not invoked")

    async def health(self, *, call):  # pragma: no cover
        raise AssertionError("not invoked")

    async def close(self) -> None:
        return None


def _traffic_policy(
    *,
    max_concurrency: int = 1,
    rpm_limit: int | None = 20,
    tpm_limit: int | None = 10_000,
    max_queue_depth: int = 1,
) -> EndpointTrafficPolicy:
    return EndpointTrafficPolicy(
        schema_version=1,
        policy_id="shared-pool",
        policy_revision="traffic-v1",
        max_concurrency=max_concurrency,
        rpm_limit=rpm_limit,
        tpm_limit=tpm_limit,
        max_queue_depth=max_queue_depth,
        max_p95_latency_ms=1_000,
        max_429_rate=0.1,
        max_error_rate=0.2,
        observation_window_seconds=60,
        minimum_samples=2,
        cooldown_seconds=30,
        max_snapshot_age_seconds=10,
        stale_snapshot_policy=StaleSnapshotPolicy.EXCLUDE,
    )


def _with_policy(endpoint_value, policy: EndpointTrafficPolicy):
    changed = replace(endpoint_value, traffic_policy=policy)
    return replace(
        changed,
        descriptor_digest=model_endpoint_descriptor_digest(changed),
    )


def _route_policy(descriptors) -> ModelRoutePolicy:
    refs = tuple(
        ModelEndpointRef(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=value.endpoint_id,
            model_id=value.model_id,
            endpoint_descriptor_digest=value.descriptor_digest,
            tier=value.tier,
            priority=index,
        )
        for index, value in enumerate(descriptors, 1)
    )
    return ModelRoutePolicy(
        schema_version=1,
        policy_id="direct-chat",
        role=ModelRole.DIRECT_CHAT,
        default_tier=ModelTier.SONNET,
        allowed_tiers=frozenset({ModelTier.SONNET}),
        candidate_endpoints=refs,
        requirements=ModelCapabilitiesRequirement(
            schema_version=1,
            input_modalities=frozenset({ModelInputModality.TEXT}),
            output_modalities=frozenset({ModelOutputModality.TEXT}),
            minimum_native_structured_output=StructuredOutputSupport.NONE,
            requires_schema_validation=False,
            minimum_context_tokens=1_024,
            minimum_output_tokens=64,
            reasoning_profile_id="balanced",
        ),
        allowed_data_classes=frozenset({PrivacyLevel.CONVERSATION}),
        fallback=ModelFallbackPolicy(
            schema_version=1,
            max_retries_per_endpoint=0,
            max_same_tier_failovers=1,
            max_tier_hops=0,
            max_total_attempts=2,
            max_schema_repairs=0,
            retryable_failure_kinds=frozenset(),
            deterministic_fallback_id="unavailable",
        ),
        tier_fallback_edges=(),
        policy_revision="route-v1",
    )


def _operational(descriptors, *, checked_at=NOW, sample_count: int = 2):
    health_items = tuple(
        ModelEndpointHealth(
            schema_version=1,
            endpoint_id=value.endpoint_id,
            endpoint_descriptor_digest=value.descriptor_digest,
            status=EndpointHealthStatus.HEALTHY,
            reason_codes=(),
        )
        for value in descriptors
    )
    health = ModelProviderHealth(
        schema_version=1,
        provider_id="provider-a",
        status=EndpointHealthStatus.HEALTHY,
        endpoints=health_items,
        snapshot_revision="health-v1",
        checked_at=checked_at,
        reason_codes=(),
    )
    loads = tuple(
        EndpointLoadSnapshot(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=value.endpoint_id,
            endpoint_descriptor_digest=value.descriptor_digest,
            quota_pool_id=value.quota_pool_id,
            traffic_policy_id=value.traffic_policy.policy_id,
            traffic_policy_revision=value.traffic_policy.policy_revision,
            counter_scope=LoadCounterScope.EXTERNAL_TO_ADMISSION_CONTROLLER,
            in_flight=0,
            requests_per_minute=0,
            tokens_per_minute=0,
            queue_depth=0,
            p95_latency_ms=100,
            rate_429=0,
            error_rate=0,
            sample_count=sample_count,
            cooldown_until=None,
            checked_at=checked_at,
            snapshot_revision=f"load:{value.endpoint_id}",
        )
        for value in descriptors
    )
    return ModelOperationalSnapshot(
        schema_version=1,
        snapshot_id="operational-v1",
        provider_health=(health,),
        endpoint_load=loads,
        acquired_at=checked_at,
    )


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        policy = _traffic_policy()
        self.endpoints = tuple(
            _with_policy(endpoint(name, ModelTier.SONNET), policy)
            for name in ("sonnet-a", "sonnet-b")
        )
        provider_descriptor = ModelProviderDescriptor(
            schema_version=1,
            provider_id="provider-a",
            revision=revision("provider-a"),
            endpoints=self.endpoints,
        )
        self.routing = InMemoryModelRoutingRegistry(
            (_Provider(provider_descriptor),),
            (_route_policy(self.endpoints),),
            clock=lambda: NOW,
            id_factory=lambda: "catalog-1",
        )
        self.operational_snapshot = _operational(self.endpoints)
        self.operational = InMemoryModelOperationalStateRegistry(
            self.routing,
            self.operational_snapshot,
            clock=lambda: NOW,
        )
        self.ids = iter(("lease-1", "lease-2", "lease-3", "lease-4"))
        self.controller = InMemoryModelAdmissionController(
            self.routing,
            self.operational,
            admission_revision="admission-v1",
            clock=lambda: NOW,
            id_factory=lambda: next(self.ids),
        )
        self.call = ServiceCallContext(
            operation_id="admission",
            principal=ServicePrincipal(
                "test",
                "admission",
                frozenset({"model-admission"}),
            ),
            operation_kind="model_admission",
            trace=TraceContext("trace-admission"),
            deadline=NOW + timedelta(seconds=30),
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(10, 0, 10, 10_000, 10_000, Decimal(100)),
            policy_snapshot_id="policy-v1",
        )

    def request(
        self,
        endpoint_index: int,
        reservation_id: str,
        *,
        input_tokens: int = 100,
        generated_tokens: int = 50,
    ) -> EndpointAdmissionRequest:
        descriptor = self.endpoints[endpoint_index]
        estimate = ModelInvocationEstimate(
            schema_version=1,
            model_request_digest=DigestString(f"request:{reservation_id}"),
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            reasoning_profile_id="balanced",
            input_tokens_upper_bound=input_tokens,
            generated_tokens_upper_bound=generated_tokens,
            reasoning_tokens_upper_bound=min(25, generated_tokens),
            total_context_tokens_upper_bound=input_tokens + generated_tokens,
            cost_units_upper_bound=Decimal("0.5"),
            estimator_revision=revision("estimator"),
        )
        return EndpointAdmissionRequest(
            schema_version=1,
            reservation_id=reservation_id,
            model_request_id=f"model:{reservation_id}",
            model_request_digest=estimate.model_request_digest,
            provider_id="provider-a",
            endpoint_id=descriptor.endpoint_id,
            endpoint_descriptor_digest=descriptor.descriptor_digest,
            quota_pool_id=descriptor.quota_pool_id,
            traffic_policy_id=descriptor.traffic_policy.policy_id,
            traffic_policy_revision=descriptor.traffic_policy.policy_revision,
            operational_snapshot_id=self.operational_snapshot.snapshot_id,
            operational_snapshot_digest=model_operational_snapshot_digest(
                self.operational_snapshot
            ),
            invocation_estimate_digest=model_invocation_estimate_digest(estimate),
            invocation_estimate=estimate,
            reserved_input_tokens=input_tokens,
            reserved_generated_tokens=generated_tokens,
            reserved_reasoning_tokens=min(25, generated_tokens),
            reserved_cost_units=Decimal("0.5"),
            expires_at=NOW + timedelta(seconds=20),
        )

    async def test_unknown_usage_charges_ceiling_and_is_idempotent(self) -> None:
        result = await self.controller.reserve(
            self.request(0, "reservation-1"),
            call=self.call,
        )
        duplicate = await self.controller.reserve(result.request, call=self.call)
        self.assertEqual(result, duplicate)
        self.assertEqual(result.disposition, AdmissionDisposition.RESERVED)
        receipt = await self.controller.settle(result.lease, None, call=self.call)  # type: ignore[arg-type]
        again = await self.controller.settle(result.lease, None, call=self.call)  # type: ignore[arg-type]
        self.assertEqual(receipt, again)
        self.assertEqual(receipt.usage.input_tokens, 100)  # type: ignore[union-attr]
        self.assertEqual(receipt.usage.generated_tokens, 50)  # type: ignore[union-attr]
        self.assertEqual(receipt.usage.reasoning_tokens, 25)  # type: ignore[union-attr]

    async def test_settlement_finishes_before_native_cancellation_propagates(
        self,
    ) -> None:
        result = await self.controller.reserve(
            self.request(0, "reservation-settle-cancel"),
            call=self.call,
        )
        await self.controller._lock.acquire()
        settling = asyncio.create_task(
            self.controller.settle(result.lease, None, call=self.call)  # type: ignore[arg-type]
        )
        await asyncio.sleep(0)
        settling.cancel()
        self.controller._lock.release()
        with self.assertRaises(asyncio.CancelledError):
            await settling

        receipt = self.controller._receipts[result.lease.lease_id]  # type: ignore[union-attr]
        self.assertEqual(receipt.disposition, AdmissionDisposition.SETTLED)
        state = self.controller._states[self.endpoints[0].quota_pool_id]
        self.assertEqual(state.active, {})

    async def test_shared_pool_concurrency_queue_and_release(self) -> None:
        first = await self.controller.reserve(
            self.request(0, "reservation-first"),
            call=self.call,
        )
        waiting = asyncio.create_task(
            self.controller.reserve(
                self.request(1, "reservation-waiting"),
                call=self.call,
            )
        )
        await asyncio.sleep(0)
        rejected = await self.controller.reserve(
            self.request(1, "reservation-overflow"),
            call=self.call,
        )
        self.assertEqual(rejected.disposition, AdmissionDisposition.REJECTED)
        self.assertEqual(rejected.reason_codes, ("queue_capacity_exhausted",))

        release = await self.controller.release(first.lease, call=self.call)  # type: ignore[arg-type]
        self.assertEqual(release.disposition, AdmissionDisposition.RELEASED)
        admitted = await asyncio.wait_for(waiting, timeout=1)
        self.assertEqual(admitted.disposition, AdmissionDisposition.RESERVED)
        await self.controller.release(admitted.lease, call=self.call)  # type: ignore[arg-type]

    async def test_native_waiter_cancellation_cannot_leak_queue_capacity(self) -> None:
        first = await self.controller.reserve(
            self.request(0, "reservation-cancel-first"),
            call=self.call,
        )
        waiting = asyncio.create_task(
            self.controller.reserve(
                self.request(1, "reservation-cancel-waiting"),
                call=self.call,
            )
        )
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        state = self.controller._states[self.endpoints[0].quota_pool_id]
        self.assertEqual(state.waiters, 0)

        await self.controller.release(first.lease, call=self.call)  # type: ignore[arg-type]
        admitted = await self.controller.reserve(
            self.request(1, "reservation-after-cancel"),
            call=self.call,
        )
        self.assertEqual(admitted.disposition, AdmissionDisposition.RESERVED)
        await self.controller.release(admitted.lease, call=self.call)  # type: ignore[arg-type]

    async def test_waiter_rechecks_snapshot_staleness_after_wake(self) -> None:
        now = [NOW]
        ids = (f"stale-wait-{index}" for index in itertools.count(1))
        controller = InMemoryModelAdmissionController(
            self.routing,
            self.operational,
            admission_revision="admission-stale-wait-v1",
            clock=lambda: now[0],
            id_factory=lambda: next(ids),
        )
        first = await controller.reserve(
            self.request(0, "reservation-stale-wait-first"),
            call=self.call,
        )
        waiting = asyncio.create_task(
            controller.reserve(
                self.request(1, "reservation-stale-after-wake"),
                call=self.call,
            )
        )
        await asyncio.sleep(0)

        now[0] = NOW + timedelta(seconds=11)
        await controller.release(first.lease, call=self.call)  # type: ignore[arg-type]
        rejected = await asyncio.wait_for(waiting, timeout=1)

        self.assertEqual(rejected.disposition, AdmissionDisposition.REJECTED)
        self.assertEqual(rejected.reason_codes, ("load_snapshot_stale",))
        state = controller._states[self.endpoints[0].quota_pool_id]
        self.assertEqual(state.waiters, 0)
        self.assertEqual(state.active, {})

    async def test_expired_active_lease_wakes_waiter_and_charges_ceiling(self) -> None:
        started = time.monotonic()

        def advancing_clock():
            return NOW + timedelta(seconds=time.monotonic() - started)

        ids = (f"expiring-{index}" for index in itertools.count(1))
        controller = InMemoryModelAdmissionController(
            self.routing,
            self.operational,
            admission_revision="admission-expiry-v1",
            clock=advancing_clock,
            id_factory=lambda: next(ids),
        )
        call = replace(self.call, deadline=NOW + timedelta(seconds=1))
        first_request = replace(
            self.request(0, "reservation-expiring"),
            expires_at=NOW + timedelta(milliseconds=30),
        )
        first = await controller.reserve(first_request, call=call)
        waiting_request = replace(
            self.request(1, "reservation-after-expiry"),
            expires_at=NOW + timedelta(milliseconds=500),
        )
        waiting = asyncio.create_task(controller.reserve(waiting_request, call=call))
        admitted = await asyncio.wait_for(waiting, timeout=0.5)

        self.assertEqual(admitted.disposition, AdmissionDisposition.RESERVED)
        expired_receipt = controller._receipts[first.lease.lease_id]  # type: ignore[union-attr]
        self.assertEqual(
            expired_receipt.reason_codes,
            ("expired_lease_ceiling_charged",),
        )
        await controller.release(admitted.lease, call=call)  # type: ignore[arg-type]

    async def test_local_window_accumulates_rpm_and_tpm_without_double_counting(
        self,
    ) -> None:
        rpm_ids = (f"rpm-{index}" for index in itertools.count(1))
        rpm_controller = InMemoryModelAdmissionController(
            self.routing,
            self.operational,
            admission_revision="admission-rpm-v1",
            clock=lambda: NOW,
            id_factory=lambda: next(rpm_ids),
        )
        for index in range(20):
            admitted = await rpm_controller.reserve(
                self.request(0, f"reservation-rpm-{index}"),
                call=self.call,
            )
            await rpm_controller.settle(admitted.lease, None, call=self.call)  # type: ignore[arg-type]
        rpm_rejected = await rpm_controller.reserve(
            self.request(0, "reservation-rpm-overflow"),
            call=self.call,
        )
        self.assertEqual(rpm_rejected.reason_codes, ("rpm_capacity_exhausted",))

        tpm_ids = (f"tpm-{index}" for index in itertools.count(1))
        tpm_controller = InMemoryModelAdmissionController(
            self.routing,
            self.operational,
            admission_revision="admission-tpm-v1",
            clock=lambda: NOW,
            id_factory=lambda: next(tpm_ids),
        )
        first = await tpm_controller.reserve(
            self.request(
                0,
                "reservation-tpm-first",
                input_tokens=5_950,
                generated_tokens=50,
            ),
            call=self.call,
        )
        await tpm_controller.settle(first.lease, None, call=self.call)  # type: ignore[arg-type]
        tpm_rejected = await tpm_controller.reserve(
            self.request(
                0,
                "reservation-tpm-overflow",
                input_tokens=4_450,
                generated_tokens=50,
            ),
            call=self.call,
        )
        self.assertEqual(tpm_rejected.reason_codes, ("tpm_capacity_exhausted",))

    async def test_tpm_and_stale_load_fail_closed(self) -> None:
        too_large = await self.controller.reserve(
            self.request(0, "reservation-too-large", input_tokens=9_980),
            call=self.call,
        )
        self.assertEqual(too_large.disposition, AdmissionDisposition.REJECTED)
        self.assertEqual(too_large.reason_codes, ("tpm_capacity_exhausted",))

        stale_snapshot = _operational(
            self.endpoints,
            checked_at=NOW - timedelta(seconds=20),
        )
        stale_snapshot = replace(stale_snapshot, snapshot_id="operational-stale")
        stale_registry = InMemoryModelOperationalStateRegistry(
            self.routing,
            stale_snapshot,
            clock=lambda: NOW,
        )
        stale_controller = InMemoryModelAdmissionController(
            self.routing,
            stale_registry,
            admission_revision="admission-v1",
            clock=lambda: NOW,
        )
        stale_request = replace(
            self.request(0, "reservation-stale"),
            operational_snapshot_id=stale_snapshot.snapshot_id,
            operational_snapshot_digest=model_operational_snapshot_digest(
                stale_snapshot
            ),
        )
        rejected = await stale_controller.reserve(stale_request, call=self.call)
        self.assertEqual(rejected.reason_codes, ("load_snapshot_stale",))

    async def test_operational_threshold_matrix_fails_closed(self) -> None:
        cases = (
            (
                "minimum_samples",
                lambda loads: (replace(loads[0], sample_count=1), loads[1]),
                "load_samples_insufficient",
            ),
            (
                "cooldown",
                lambda loads: (
                    replace(loads[0], cooldown_until=NOW + timedelta(seconds=1)),
                    loads[1],
                ),
                "endpoint_cooldown_active",
            ),
            (
                "p95",
                lambda loads: (replace(loads[0], p95_latency_ms=1_001), loads[1]),
                "p95_latency_exceeded",
            ),
            (
                "missing_p95",
                lambda loads: (replace(loads[0], p95_latency_ms=None), loads[1]),
                "p95_latency_missing",
            ),
            (
                "429_rate",
                lambda loads: (replace(loads[0], rate_429=0.2), loads[1]),
                "rate_429_exceeded",
            ),
            (
                "error_rate",
                lambda loads: (replace(loads[0], error_rate=0.3), loads[1]),
                "error_rate_exceeded",
            ),
            (
                "rpm",
                lambda loads: tuple(
                    replace(item, requests_per_minute=20) for item in loads
                ),
                "rpm_capacity_exhausted",
            ),
        )
        for index, (name, mutate, expected) in enumerate(cases, 1):
            with self.subTest(case=name):
                snapshot = replace(
                    self.operational_snapshot,
                    snapshot_id=f"operational-{name}",
                    endpoint_load=tuple(
                        mutate(self.operational_snapshot.endpoint_load)
                    ),
                )
                registry = InMemoryModelOperationalStateRegistry(
                    self.routing,
                    snapshot,
                    clock=lambda: NOW,
                )
                controller = InMemoryModelAdmissionController(
                    self.routing,
                    registry,
                    admission_revision="admission-v1",
                    clock=lambda: NOW,
                )
                request = replace(
                    self.request(0, f"reservation-threshold-{index}"),
                    operational_snapshot_id=snapshot.snapshot_id,
                    operational_snapshot_digest=model_operational_snapshot_digest(
                        snapshot
                    ),
                )
                result = await controller.reserve(request, call=self.call)
                self.assertEqual(result.disposition, AdmissionDisposition.REJECTED)
                self.assertEqual(result.reason_codes, (expected,))

    async def test_reported_usage_cannot_exceed_reservation(self) -> None:
        result = await self.controller.reserve(
            self.request(0, "reservation-usage"),
            call=self.call,
        )
        excessive = ModelUsage(
            schema_version=1,
            input_tokens=101,
            generated_tokens=50,
            reasoning_tokens=25,
            cached_input_tokens=None,
            cost_units=Decimal("0.5"),
        )
        with self.assertRaises(DududaError):
            await self.controller.settle(
                result.lease,  # type: ignore[arg-type]
                excessive,
                call=self.call,
            )
        receipt = await self.controller.settle(
            result.lease,  # type: ignore[arg-type]
            None,
            call=self.call,
        )
        self.assertEqual(
            receipt.reason_codes,
            ("reservation_ceiling_charged",),
        )


if __name__ == "__main__":
    unittest.main()
