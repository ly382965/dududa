from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest

from dududa.domain.primitives import DigestString, RuntimeBudget, TraceContext
from dududa.errors import DududaError
from dududa.models.admission import InMemoryModelAdmissionController
from dududa.models.contracts import (
    AdmissionDisposition,
    EndpointAdmissionRequest,
    EndpointHealthStatus,
    ModelFailureKind,
    ModelEndpointHealth,
    ModelInvocationEstimate,
    ModelOperationalSnapshot,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRole,
    ModelTier,
)
from dududa.models.errors import ModelInvocationError
from dududa.models.digests import (
    model_invocation_estimate_digest,
    model_operational_snapshot_digest,
)
from dududa.models.health import BoundedModelHealthPublisher, ModelHealthEvidence
from dududa.models.policy import ModelCatalogUpdate
from dududa.models.registry import (
    InMemoryModelOperationalStateRegistry,
    InMemoryModelRoutingRegistry,
)
from dududa.ports.context import NeverCancelled, ServiceCallContext, ServicePrincipal

from .helpers import NOW, endpoint, revision
from .test_registry import _Provider, _operational, _policy
from .test_router import (
    RouterFixture,
    _operational as _router_operational,
    _policy as _router_policy,
    _request,
    _tier_decision,
)


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self):
        return self.now


class BoundedModelHealthPublisherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.endpoint = endpoint("sonnet-a", ModelTier.SONNET)
        self.provider_descriptor = ModelProviderDescriptor(
            schema_version=1,
            provider_id="provider-a",
            revision=revision("provider-a"),
            endpoints=(self.endpoint,),
        )
        self.routing = InMemoryModelRoutingRegistry(
            (_Provider(self.provider_descriptor),),
            (_policy((self.endpoint,)),),
            clock=self.clock,
            id_factory=lambda: "routing",
        )
        self.initial = _operational(
            self.endpoint,
            snapshot_id="operational-initial",
        )
        self.operational = InMemoryModelOperationalStateRegistry(
            self.routing,
            self.initial,
            clock=self.clock,
        )
        ids = iter(("healthy", "stale", "failed", "missing"))
        self.publisher = BoundedModelHealthPublisher(
            self.routing,
            self.operational,
            clock=self.clock,
            id_factory=lambda: next(ids),
        )
        self.call = ServiceCallContext(
            operation_id="health-publish",
            principal=ServicePrincipal(
                "test",
                "health-publisher",
                frozenset({"model-health"}),
            ),
            operation_kind="model_health_publish",
            trace=TraceContext("trace-health"),
            deadline=NOW + timedelta(minutes=1),
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            policy_snapshot_id="policy-v1",
        )

    def _evidence(
        self,
        status: EndpointHealthStatus = EndpointHealthStatus.HEALTHY,
    ) -> ModelHealthEvidence:
        health = ModelProviderHealth(
            schema_version=1,
            provider_id="provider-a",
            status=status,
            endpoints=(
                ModelEndpointHealth(
                    schema_version=1,
                    endpoint_id=self.endpoint.endpoint_id,
                    endpoint_descriptor_digest=self.endpoint.descriptor_digest,
                    status=status,
                    reason_codes=(),
                ),
            ),
            snapshot_revision="probe-v1",
            checked_at=NOW,
            reason_codes=(),
        )
        return ModelHealthEvidence(
            schema_version=1,
            provider_revision=self.provider_descriptor.revision,
            health=health,
            expires_at=NOW + timedelta(seconds=5),
            evidence_revision="evidence-v1",
        )

    async def test_healthy_evidence_expires_to_unknown(self) -> None:
        healthy = await self.publisher.publish(
            (self._evidence(),),
            self.initial.endpoint_load,
            call=self.call,
        )
        self.assertIs(
            healthy.provider_health[0].status,
            EndpointHealthStatus.HEALTHY,
        )

        self.clock.now = NOW + timedelta(seconds=6)
        stale = await self.publisher.publish(
            (self._evidence(),),
            self.initial.endpoint_load,
            call=self.call,
        )
        self.assertIs(
            stale.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(
            stale.provider_health[0].reason_codes,
            ("health_evidence_stale",),
        )

    async def test_failed_or_missing_probe_is_unknown(self) -> None:
        failed = await self.publisher.publish(
            (self._evidence(EndpointHealthStatus.UNAVAILABLE),),
            self.initial.endpoint_load,
            call=self.call,
        )
        self.assertEqual(failed.provider_health[0].reason_codes, ("health_probe_failed",))

        missing = await self.publisher.publish(
            (),
            self.initial.endpoint_load,
            call=self.call,
        )
        self.assertEqual(
            missing.provider_health[0].reason_codes,
            ("health_evidence_missing",),
        )

    async def test_descriptor_drift_fails_closed(self) -> None:
        evidence = self._evidence()
        forged = replace(
            evidence,
            health=replace(
                evidence.health,
                endpoints=(
                    replace(
                        evidence.health.endpoints[0],
                        endpoint_descriptor_digest="forged-digest",
                    ),
                ),
            ),
        )
        with self.assertRaises(DududaError) as captured:
            await self.publisher.publish(
                (forged,),
                self.initial.endpoint_load,
                call=self.call,
            )
        self.assertEqual(
            captured.exception.info.code,
            "health_endpoint_descriptor_mismatch",
        )

    async def test_router_keeps_unknown_health_fail_closed(self) -> None:
        def unknown_operational(descriptors):
            snapshot = _router_operational(descriptors)
            provider = snapshot.provider_health[0]
            return replace(
                snapshot,
                provider_health=(
                    replace(
                        provider,
                        status=EndpointHealthStatus.UNKNOWN,
                        endpoints=tuple(
                            replace(item, status=EndpointHealthStatus.UNKNOWN)
                            for item in provider.endpoints
                        ),
                        reason_codes=("health_evidence_stale",),
                    ),
                ),
            )

        fixture = RouterFixture(
            (self.endpoint,),
            (
                _router_policy(
                    ModelRole.DIRECT_CHAT,
                    (self.endpoint,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            operational_factory=unknown_operational,
        )
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="health-unknown"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )
        self.assertIs(captured.exception.failure_kind, ModelFailureKind.ROUTE_NOT_FOUND)
        self.assertEqual(fixture.provider.calls, [])
        self.assertEqual(
            captured.exception.route_decision.rejected_endpoints[0].reason_codes,
            ("provider_health_unavailable",),
        )

    async def test_router_rechecks_health_expiry_without_another_publish(self) -> None:
        fixture = RouterFixture(
            (self.endpoint,),
            (
                _router_policy(
                    ModelRole.DIRECT_CHAT,
                    (self.endpoint,),
                    schema=False,
                    profile="balanced",
                ),
            ),
            (),
            clock=self.clock,
        )
        publisher = BoundedModelHealthPublisher(
            fixture.routing,
            fixture.operational,
            clock=self.clock,
            id_factory=lambda: "expiring",
        )
        await publisher.publish(
            (self._evidence(),),
            fixture.operational_snapshot.endpoint_load,
            call=fixture.call,
        )
        fixture.router._operational_registry = publisher

        self.clock.now = NOW + timedelta(seconds=6)
        projected = publisher.acquire_snapshot()
        self.assertIs(
            projected.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(
            projected.provider_health[0].reason_codes,
            ("health_evidence_stale",),
        )
        self.assertEqual(
            publisher.snapshot_by_id(
                projected.snapshot_id,
                expected_digest=model_operational_snapshot_digest(projected),
            ),
            projected,
        )
        fixture.admission._operational_registry = publisher
        with self.assertRaises(ModelInvocationError) as captured:
            await fixture.router.invoke(
                _request(ModelRole.DIRECT_CHAT, request_id="health-expired"),
                _tier_decision(ModelTier.SONNET),
                call=fixture.call,
            )

        self.assertEqual(fixture.provider.calls, [])
        self.assertEqual(
            captured.exception.route_decision.rejected_endpoints[0].reason_codes,
            ("provider_health_unavailable",),
        )

    async def test_catalog_revision_change_invalidates_published_health(self) -> None:
        await self.publisher.publish(
            (self._evidence(),),
            self.initial.endpoint_load,
            call=self.call,
        )
        current = self.routing.acquire_snapshot()
        changed = replace(
            self.provider_descriptor,
            revision=revision("provider-a-v2"),
        )
        self.routing.register_provider(_Provider(changed))
        await self.routing.publish(
            ModelCatalogUpdate(
                schema_version=1,
                expected_revision=current.catalog_revision,
                provider_descriptors=(changed,),
                route_policies=current.route_policies,
            ),
            call=self.call,
        )

        projected = self.publisher.acquire_snapshot()

        self.assertIs(
            projected.provider_health[0].status,
            EndpointHealthStatus.UNKNOWN,
        )
        self.assertEqual(
            projected.provider_health[0].reason_codes,
            ("health_catalog_changed",),
        )

    async def test_partial_expiry_snapshot_is_resolvable_by_admission(self) -> None:
        endpoint_b = endpoint("sonnet-b", ModelTier.SONNET)
        descriptor_b = ModelProviderDescriptor(
            schema_version=1,
            provider_id="provider-b",
            revision=revision("provider-b"),
            endpoints=(endpoint_b,),
        )
        routing = InMemoryModelRoutingRegistry(
            (_Provider(self.provider_descriptor), _Provider(descriptor_b)),
            (_policy((self.endpoint,)),),
            clock=self.clock,
            id_factory=lambda: "multi-routing",
        )
        health_b = ModelProviderHealth(
            schema_version=1,
            provider_id="provider-b",
            status=EndpointHealthStatus.HEALTHY,
            endpoints=(
                ModelEndpointHealth(
                    schema_version=1,
                    endpoint_id=endpoint_b.endpoint_id,
                    endpoint_descriptor_digest=endpoint_b.descriptor_digest,
                    status=EndpointHealthStatus.HEALTHY,
                    reason_codes=(),
                ),
            ),
            snapshot_revision="probe-b",
            checked_at=NOW,
            reason_codes=(),
        )
        load_a = self.initial.endpoint_load[0]
        load_b = replace(
            load_a,
            provider_id="provider-b",
            endpoint_id=endpoint_b.endpoint_id,
            endpoint_descriptor_digest=endpoint_b.descriptor_digest,
            quota_pool_id=endpoint_b.quota_pool_id,
            traffic_policy_id=endpoint_b.traffic_policy.policy_id,
            traffic_policy_revision=endpoint_b.traffic_policy.policy_revision,
            snapshot_revision="load:provider-b",
        )
        initial = ModelOperationalSnapshot(
            schema_version=1,
            snapshot_id="multi-operational",
            provider_health=(self._evidence().health, health_b),
            endpoint_load=(load_a, load_b),
            acquired_at=NOW,
        )
        operational = InMemoryModelOperationalStateRegistry(
            routing,
            initial,
            clock=self.clock,
        )
        publisher = BoundedModelHealthPublisher(
            routing,
            operational,
            clock=self.clock,
            id_factory=lambda: "multi-health",
        )
        evidence_b = ModelHealthEvidence(
            schema_version=1,
            provider_revision=descriptor_b.revision,
            health=health_b,
            expires_at=NOW + timedelta(seconds=30),
            evidence_revision="evidence-b",
        )
        await publisher.publish(
            (self._evidence(), evidence_b),
            initial.endpoint_load,
            call=self.call,
        )

        self.clock.now = NOW + timedelta(seconds=6)
        projected = publisher.acquire_snapshot()
        self.assertEqual(
            tuple(item.status for item in projected.provider_health),
            (EndpointHealthStatus.UNKNOWN, EndpointHealthStatus.HEALTHY),
        )
        controller = InMemoryModelAdmissionController(
            routing,
            publisher,
            admission_revision="admission-v1",
            clock=self.clock,
            id_factory=lambda: "lease-b",
        )
        estimate = ModelInvocationEstimate(
            schema_version=1,
            model_request_digest=DigestString("request:provider-b"),
            endpoint_descriptor_digest=endpoint_b.descriptor_digest,
            reasoning_profile_id="balanced",
            input_tokens_upper_bound=100,
            generated_tokens_upper_bound=50,
            reasoning_tokens_upper_bound=25,
            total_context_tokens_upper_bound=150,
            cost_units_upper_bound=Decimal("0.5"),
            estimator_revision=revision("estimator"),
        )
        request = EndpointAdmissionRequest(
            schema_version=1,
            reservation_id="reservation-b",
            model_request_id="model:provider-b",
            model_request_digest=estimate.model_request_digest,
            provider_id="provider-b",
            endpoint_id=endpoint_b.endpoint_id,
            endpoint_descriptor_digest=endpoint_b.descriptor_digest,
            quota_pool_id=endpoint_b.quota_pool_id,
            traffic_policy_id=endpoint_b.traffic_policy.policy_id,
            traffic_policy_revision=endpoint_b.traffic_policy.policy_revision,
            operational_snapshot_id=projected.snapshot_id,
            operational_snapshot_digest=model_operational_snapshot_digest(projected),
            invocation_estimate_digest=model_invocation_estimate_digest(estimate),
            invocation_estimate=estimate,
            reserved_input_tokens=100,
            reserved_generated_tokens=50,
            reserved_reasoning_tokens=25,
            reserved_cost_units=Decimal("0.5"),
            expires_at=self.clock.now + timedelta(seconds=10),
        )

        result = await controller.reserve(request, call=self.call)

        self.assertIs(result.disposition, AdmissionDisposition.RESERVED)

    def test_v1_operational_digest_golden_is_unchanged(self) -> None:
        snapshot = _router_operational((self.endpoint,))

        self.assertEqual(
            str(model_operational_snapshot_digest(snapshot)),
            "dududa-c14n-v1:model:operational-snapshot:v1:sha-256:"
            "8d12d7ea8171fbcec2793ad44a77083418ed760772100a77a4d2310651deac7b",
        )


if __name__ == "__main__":
    unittest.main()
