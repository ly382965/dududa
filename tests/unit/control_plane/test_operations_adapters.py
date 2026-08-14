from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.control_plane.operations import (
    OperationalScope,
    OperationalStatus,
    OperationalSurface,
)
from dududa.control_plane.operations_adapters import (
    CapabilityCatalogOperationalAdapter,
    McpCapabilityOperationalProjectionProvider,
    McpRegistryOperationalAdapter,
    ModelRouterOperationalProjectionProvider,
)
from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.mcp import McpRegistrySnapshot, mcp_registry_digest
from dududa.models.contracts import ModelTier
from dududa.ports.context import (
    NeverCancelled,
    ServiceCallContext,
    ServicePrincipal,
)

from tests.unit.capabilities.test_registry import catalog_fixture
from tests.unit.mcp.helpers import server_definition
from tests.unit.models.helpers import endpoint
from tests.unit.models.test_policy import _snapshot as model_snapshot
from tests.unit.models.test_registry import _operational as operational_snapshot

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


class SnapshotRegistry:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot

    def acquire_snapshot(self):
        return self.snapshot


class OperationalAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.scope = OperationalScope(1, "qq", "bot-1", "group-1")
        self.call = ServiceCallContext(
            "operations-query",
            ServicePrincipal("tests", "control-plane", frozenset({"query"})),
            "control_plane.operations.query",
            TraceContext("trace-operations"),
            NOW + timedelta(minutes=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "policy-v1",
        )

    async def test_model_adapter_preserves_scope_and_snapshot_revision(self) -> None:
        descriptor = endpoint("sonnet-a", ModelTier.SONNET)
        routing = model_snapshot(
            (
                endpoint("haiku-a", ModelTier.HAIKU),
                descriptor,
                endpoint("opus-a", ModelTier.OPUS),
            )
        )
        operational = operational_snapshot(descriptor, snapshot_id="model-ops-1")
        provider = ModelRouterOperationalProjectionProvider(
            SnapshotRegistry(routing),
            SnapshotRegistry(operational),
        )

        projection = await provider.project(self.scope, call=self.call)

        self.assertEqual(projection.surface, OperationalSurface.MODEL_ROUTER)
        self.assertEqual(projection.scope, self.scope)
        self.assertEqual(projection.revision, "snapshot-1|model-ops-1")
        self.assertEqual(projection.status, OperationalStatus.READY)
        facts = {item.fact_id: item for item in projection.facts}
        self.assertEqual(
            facts["model.provider:provider-a"].revision,
            "health:model-ops-1",
        )
        self.assertEqual(
            facts["model.provider:provider-a"].status,
            OperationalStatus.READY,
        )

    async def test_mcp_and_capability_adapters_degrade_without_cached_health(
        self,
    ) -> None:
        server = server_definition("icourse")
        mcp = McpRegistrySnapshot(
            1,
            "mcp-registry:one",
            "mcp-registry-v1",
            mcp_registry_digest((server,)),
            (server,),
            NOW,
        )
        capabilities, _, _ = catalog_fixture()
        mcp_registry = SnapshotRegistry(mcp)
        capability_registry = SnapshotRegistry(capabilities)

        mcp_fragment = McpRegistryOperationalAdapter(mcp_registry).adapt()
        capability_fragment = CapabilityCatalogOperationalAdapter(
            capability_registry
        ).adapt()
        provider = McpCapabilityOperationalProjectionProvider(
            mcp_registry,
            capability_registry,
        )
        projection = await provider.project(self.scope, call=self.call)

        self.assertEqual(mcp_fragment.status, OperationalStatus.DEGRADED)
        self.assertEqual(
            mcp_fragment.reason_codes,
            ("mcp_health_not_cached",),
        )
        self.assertEqual(capability_fragment.status, OperationalStatus.DEGRADED)
        self.assertEqual(
            capability_fragment.reason_codes,
            ("capability_health_not_cached",),
        )
        self.assertEqual(projection.surface, OperationalSurface.MCP_CAPABILITY)
        self.assertEqual(projection.scope, self.scope)
        self.assertEqual(
            projection.revision,
            f"{mcp.snapshot_id}|{capabilities.snapshot_id}",
        )
        self.assertEqual(projection.status, OperationalStatus.DEGRADED)
        self.assertEqual(
            set(projection.reason_codes),
            {"mcp_health_not_cached", "capability_health_not_cached"},
        )


if __name__ == "__main__":
    unittest.main()
