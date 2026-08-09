from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.capabilities.contracts import (
    CapabilityEndpointHealth,
    CapabilityHealthStatus,
    CapabilityProviderHealth,
)
from dududa.capabilities.digests import capability_provider_health_digest
from dududa.capabilities.health import PollingCapabilityHealthRegistry
from dududa.capabilities.registry import (
    InMemoryCapabilityProviderRegistry,
    InMemoryCapabilityRegistry,
)
from dududa.errors import DududaError
from dududa.ports.context import ManualCancellationToken

from tests.unit.capabilities.test_registry import (
    FakeProvider,
    SchemaValidator,
    call,
    catalog_fixture,
)


def bound_providers(catalog, provider):
    providers = InMemoryCapabilityProviderRegistry((provider,))
    InMemoryCapabilityRegistry(
        catalog,
        schema_validator=SchemaValidator(),
        provider_registry=providers,
        clock=lambda: call().deadline - timedelta(seconds=30),
    )
    return providers


def healthy_provider(provider, item) -> CapabilityProviderHealth:
    endpoint = CapabilityEndpointHealth(
        schema_version=1,
        capability_id=item.capability_id,
        definition_digest=item.definition_digest,
        status=CapabilityHealthStatus.HEALTHY,
        reason_codes=("ready",),
    )
    values = {
        "schema_version": 1,
        "provider": provider,
        "status": CapabilityHealthStatus.HEALTHY,
        "capabilities": (endpoint,),
        "observed_at": call().deadline - timedelta(minutes=1),
        "expires_at": call().deadline + timedelta(minutes=1),
    }
    return CapabilityProviderHealth(
        health_digest=capability_provider_health_digest(values),
        **values,
    )


class HealthProvider(FakeProvider):
    def __init__(self, descriptor, result) -> None:
        super().__init__(descriptor)
        self.result = result
        self.health_calls = 0

    async def health(self, *, call):
        self.health_calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class CapabilityHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_provider_is_bound_to_exact_revision_and_definition(
        self,
    ) -> None:
        catalog, item, descriptor = catalog_fixture()
        provider = HealthProvider(
            descriptor,
            healthy_provider(descriptor.provider, item),
        )
        providers = bound_providers(catalog, provider)
        registry = PollingCapabilityHealthRegistry(
            providers,
            clock=lambda: call().deadline - timedelta(seconds=30),
            id_factory=lambda: "one",
        )
        snapshot = await registry.snapshot(catalog, call=call())
        self.assertIs(snapshot.providers[0].status, CapabilityHealthStatus.HEALTHY)
        self.assertEqual(
            snapshot.providers[0].capabilities[0].definition_digest,
            item.definition_digest,
        )
        self.assertEqual(provider.health_calls, 1)

    async def test_probe_failure_becomes_bounded_unavailable_fact(self) -> None:
        catalog, _, descriptor = catalog_fixture()
        provider = HealthProvider(descriptor, RuntimeError("secret payload"))
        providers = bound_providers(catalog, provider)
        registry = PollingCapabilityHealthRegistry(
            providers,
            clock=lambda: call().deadline - timedelta(seconds=30),
            id_factory=lambda: "failure",
        )
        snapshot = await registry.snapshot(catalog, call=call())
        health = snapshot.providers[0]
        self.assertIs(health.status, CapabilityHealthStatus.UNAVAILABLE)
        self.assertEqual(health.capabilities, ())
        self.assertNotIn("secret payload", repr(health))

    async def test_stale_or_surface_drift_is_fail_closed(self) -> None:
        catalog, item, descriptor = catalog_fixture()
        stale = healthy_provider(descriptor.provider, item)
        stale = type(stale)(
            schema_version=1,
            provider=stale.provider,
            status=stale.status,
            capabilities=stale.capabilities,
            observed_at=stale.observed_at - timedelta(minutes=5),
            expires_at=stale.observed_at - timedelta(minutes=1),
            health_digest=capability_provider_health_digest(
                {
                    "schema_version": 1,
                    "provider": stale.provider,
                    "status": stale.status,
                    "capabilities": stale.capabilities,
                    "observed_at": stale.observed_at - timedelta(minutes=5),
                    "expires_at": stale.observed_at - timedelta(minutes=1),
                }
            ),
        )
        provider = HealthProvider(descriptor, stale)
        providers = bound_providers(catalog, provider)
        registry = PollingCapabilityHealthRegistry(
            providers,
            clock=lambda: call().deadline - timedelta(seconds=30),
            id_factory=lambda: "stale",
        )
        snapshot = await registry.snapshot(catalog, call=call())
        self.assertIs(
            snapshot.providers[0].status,
            CapabilityHealthStatus.UNAVAILABLE,
        )

    async def test_expired_call_is_not_converted_to_provider_unavailable(self) -> None:
        catalog, _, descriptor = catalog_fixture()
        provider = HealthProvider(descriptor, RuntimeError("unused"))
        providers = bound_providers(catalog, provider)
        registry = PollingCapabilityHealthRegistry(
            providers,
            clock=lambda: call().deadline,
        )
        with self.assertRaises(DududaError) as raised:
            await registry.snapshot(catalog, call=call())
        self.assertEqual(raised.exception.info.code, "capability_health_call_expired")

    async def test_in_flight_cancellation_stops_a_hung_probe(self) -> None:
        catalog, _, descriptor = catalog_fixture()

        class HungProvider(HealthProvider):
            async def health(self, *, call):
                try:
                    await asyncio.Future()
                finally:
                    self.probe_stopped.set()

        provider = HungProvider(descriptor, None)
        provider.probe_stopped = asyncio.Event()
        providers = bound_providers(catalog, provider)
        registry = PollingCapabilityHealthRegistry(
            providers,
            clock=lambda: call().deadline - timedelta(seconds=30),
        )
        cancellation = ManualCancellationToken()
        operation = asyncio.create_task(
            registry.snapshot(
                catalog,
                call=replace(call(), cancellation=cancellation),
            )
        )
        await asyncio.sleep(0)
        cancellation.cancel()
        with self.assertRaises(DududaError) as raised:
            await operation
        self.assertEqual(
            raised.exception.info.code,
            "capability_health_call_cancelled",
        )
        self.assertTrue(provider.probe_stopped.is_set())


if __name__ == "__main__":
    unittest.main()
