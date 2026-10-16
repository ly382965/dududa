from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest

from dududa.domain.primitives import (
    DigestString,
    PrivacyLevel,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.models.contracts import (
    EndpointHealthStatus,
    EndpointLoadSnapshot,
    LoadCounterScope,
    ModelEndpointHealth,
    ModelEndpointRef,
    ModelInputModality,
    ModelOperationalSnapshot,
    ModelOutputModality,
    ModelProviderDescriptor,
    ModelProviderHealth,
    ModelRole,
    ModelTier,
    StructuredOutputSupport,
)
from dududa.models.digests import routing_catalog_digest
from dududa.models.policy import (
    ModelCapabilitiesRequirement,
    ModelCatalogUpdate,
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

    async def generate(self, request, *, call):  # pragma: no cover - registry only
        raise AssertionError("not invoked")

    async def health(self, *, call):  # pragma: no cover - registry only
        raise AssertionError("not invoked")

    async def close(self) -> None:
        return None


def _policy(descriptors) -> ModelRoutePolicy:
    refs = tuple(
        ModelEndpointRef(
            schema_version=1,
            provider_id="provider-a",
            endpoint_id=item.endpoint_id,
            model_id=item.model_id,
            endpoint_descriptor_digest=item.descriptor_digest,
            tier=item.tier,
            priority=index,
        )
        for index, item in enumerate(descriptors, 1)
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
            max_retries_per_endpoint=1,
            max_same_tier_failovers=0,
            max_tier_hops=0,
            max_total_attempts=2,
            max_schema_repairs=0,
            retryable_failure_kinds=frozenset(),
            deterministic_fallback_id="direct-chat-unavailable",
        ),
        tier_fallback_edges=(),
        policy_revision="route-v1",
    )


def _operational(descriptor, *, snapshot_id: str, checked_at=NOW):
    endpoint_health = ModelEndpointHealth(
        schema_version=1,
        endpoint_id=descriptor.endpoint_id,
        endpoint_descriptor_digest=descriptor.descriptor_digest,
        status=EndpointHealthStatus.HEALTHY,
        reason_codes=(),
    )
    health = ModelProviderHealth(
        schema_version=1,
        provider_id="provider-a",
        status=EndpointHealthStatus.HEALTHY,
        endpoints=(endpoint_health,),
        snapshot_revision=f"health:{snapshot_id}",
        checked_at=checked_at,
        reason_codes=(),
    )
    load = EndpointLoadSnapshot(
        schema_version=1,
        provider_id="provider-a",
        endpoint_id=descriptor.endpoint_id,
        endpoint_descriptor_digest=descriptor.descriptor_digest,
        quota_pool_id=descriptor.quota_pool_id,
        traffic_policy_id=descriptor.traffic_policy.policy_id,
        traffic_policy_revision=descriptor.traffic_policy.policy_revision,
        counter_scope=LoadCounterScope.EXTERNAL_TO_ADMISSION_CONTROLLER,
        in_flight=0,
        requests_per_minute=0,
        tokens_per_minute=0,
        queue_depth=0,
        p95_latency_ms=100,
        rate_429=0,
        error_rate=0,
        sample_count=descriptor.traffic_policy.minimum_samples,
        cooldown_until=None,
        checked_at=checked_at,
        snapshot_revision=f"load:{snapshot_id}",
    )
    return ModelOperationalSnapshot(
        schema_version=1,
        snapshot_id=snapshot_id,
        provider_health=(health,),
        endpoint_load=(load,),
        acquired_at=checked_at,
    )


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.descriptor = endpoint("sonnet-a", ModelTier.SONNET)
        self.provider_descriptor = ModelProviderDescriptor(
            schema_version=1,
            provider_id="provider-a",
            revision=revision("provider-a"),
            endpoints=(self.descriptor,),
        )
        self.provider = _Provider(self.provider_descriptor)
        self.policy = _policy((self.descriptor,))
        self.ids = iter(("initial", "publish-1", "publish-2", "publish-3"))
        self.registry = InMemoryModelRoutingRegistry(
            (self.provider,),
            (self.policy,),
            clock=lambda: NOW,
            id_factory=lambda: next(self.ids),
        )
        self.call = ServiceCallContext(
            operation_id="catalog-update",
            principal=ServicePrincipal(
                "test",
                "registry",
                frozenset({"model-catalog"}),
            ),
            operation_kind="model_catalog_update",
            trace=TraceContext("trace-registry"),
            deadline=NOW + timedelta(minutes=1),
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(0, 0, 0, 0, 0, Decimal("0")),
            policy_snapshot_id="policy-v1",
        )

    async def test_catalog_publish_is_atomic_and_resolves_exact_revision(self) -> None:
        initial = self.registry.acquire_snapshot()
        resolved = self.registry.resolve_provider(
            initial,
            "provider-a",
            self.provider_descriptor.revision,
        )
        self.assertIs(resolved, self.provider)

        unknown = replace(
            initial.route_policies[0].candidate_endpoints[0],
            endpoint_id="missing-endpoint",
        )
        invalid_policy = replace(
            initial.route_policies[0],
            candidate_endpoints=(unknown,),
        )
        invalid_update = ModelCatalogUpdate(
            schema_version=1,
            expected_revision=initial.catalog_revision,
            provider_descriptors=initial.provider_descriptors,
            route_policies=(invalid_policy,),
        )
        with self.assertRaises(DududaError):
            await self.registry.publish(invalid_update, call=self.call)
        self.assertIs(self.registry.acquire_snapshot(), initial)

        conflict = ModelCatalogUpdate(
            schema_version=1,
            expected_revision="stale-revision",
            provider_descriptors=initial.provider_descriptors,
            route_policies=initial.route_policies,
        )
        with self.assertRaises(DududaError):
            await self.registry.publish(conflict, call=self.call)
        self.assertIs(self.registry.acquire_snapshot(), initial)

        valid = ModelCatalogUpdate(
            schema_version=1,
            expected_revision=initial.catalog_revision,
            provider_descriptors=initial.provider_descriptors,
            route_policies=initial.route_policies,
        )
        receipt = await self.registry.publish(valid, call=self.call)
        published = self.registry.acquire_snapshot()
        self.assertEqual(receipt.snapshot_id, published.snapshot_id)
        self.assertEqual(
            published.catalog_revision,
            str(
                routing_catalog_digest(
                    published.provider_descriptors,
                    published.route_policies,
                )
            ),
        )
        self.assertEqual(self.registry.snapshot_by_id(initial.snapshot_id), initial)

    async def test_operational_publish_binds_endpoint_and_keeps_last_good(self) -> None:
        initial = _operational(self.descriptor, snapshot_id="operational-1")
        operational = InMemoryModelOperationalStateRegistry(
            self.registry,
            initial,
            clock=lambda: NOW + timedelta(seconds=1),
        )
        invalid_load = replace(
            initial.endpoint_load[0],
            endpoint_descriptor_digest=DigestString("stale-descriptor"),
        )
        invalid = replace(
            initial,
            snapshot_id="operational-invalid",
            endpoint_load=(invalid_load,),
        )
        with self.assertRaises(DududaError):
            await operational.publish(invalid, call=self.call)
        self.assertIs(operational.acquire_snapshot(), initial)

        next_snapshot = _operational(
            self.descriptor,
            snapshot_id="operational-2",
            checked_at=NOW + timedelta(seconds=1),
        )
        await operational.publish(next_snapshot, call=self.call)
        self.assertIs(operational.acquire_snapshot(), next_snapshot)
        self.assertEqual(
            operational.snapshot_by_id(initial.snapshot_id),
            initial,
        )


if __name__ == "__main__":
    unittest.main()
