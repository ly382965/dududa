from __future__ import annotations

import itertools
import shutil
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.capabilities import (
    CapabilityEndpointHealth,
    CapabilityHealthSnapshot,
    CapabilityHealthStatus,
    CapabilityProviderHealth,
    CapabilityRunRequest,
    CapabilityRunStatus,
    ConfigCapabilityRegistry,
    DeterministicArgumentBinder,
    DeterministicBoundedCapabilityRuntime,
    DeterministicCapabilityRetriever,
    DeterministicToolPlanner,
    DeterministicToolPlanValidator,
    DeterministicToolResultValidator,
    GovernedToolExecutor,
    InMemoryCapabilityProviderRegistry,
    InMemoryToolInvocationLedger,
    McpCapabilityProvider,
    capability_health_snapshot_digest,
    capability_provider_health_digest,
    capability_run_request_digest,
    load_capability_catalog_snapshot,
)
from dududa.contracts.canonical import canonical_json_bytes, canonical_schema_digest
from dududa.domain.primitives import ResourceUsage
from dududa.errors import DududaError
from dududa.mcp import (
    McpSchemaSnapshot,
    McpToolDescriptor,
    McpToolResult,
    mcp_schema_snapshot_digest,
    mcp_tool_result_digest,
    mcp_tool_schema_facts_digest,
)
from dududa.security.audit import InMemoryAuditSink
from dududa.security.authorization import (
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.limits import InMemoryBudgetLedger, InMemoryInteractionLimiter

from plugins.astrbot_plugin_dududa_core.adapters.mcp_schema import (
    JsonSchemaCapabilityValidator,
)
from tests.unit.capabilities.test_contracts import NOW
from tests.unit.capabilities.test_executor import execution_call
from tests.unit.capabilities.test_registry import call as catalog_call
from tests.unit.capabilities.test_retrieval import (
    StaticHealthRegistry,
    authorization_for,
    request_for,
)

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_CAPABILITIES = ROOT / "config" / "capabilities"
FAKE_CAPABILITIES = ROOT / "tests" / "fixtures" / "capabilities"


class RecordingMixedMcpClient:
    def __init__(self) -> None:
        self.schema_mode = "current"
        self.discover_calls: list[str] = []
        self.tool_calls: list[tuple[str, str, object]] = []
        self.closed = False

    async def discover(self, server_id, *, refresh=False, call):
        self.discover_calls.append(server_id)
        if server_id != "fake-b":
            raise AssertionError("iCourse transport must not be called in this fixture")
        return _fake_schema(self.schema_mode)

    async def call_tool(self, server_id, tool_name, arguments, *, call):
        self.tool_calls.append((server_id, tool_name, arguments))
        structured = {"value": arguments["value"]}
        schema = _fake_schema(self.schema_mode)
        values = {
            "server_id": server_id,
            "tool_name": tool_name,
            "generation": schema.generation,
            "schema_snapshot_id": schema.snapshot_id,
            "schema_snapshot_digest": schema.snapshot_digest,
            "request_digest": call.request_digest,
            "is_error": False,
            "structured_content": structured,
            "content": (),
        }
        return McpToolResult(
            schema_version=1,
            result_digest=mcp_tool_result_digest(**values),
            total_size_bytes=len(canonical_json_bytes(structured)),
            **values,
        )

    async def health(self, server_id, *, call):
        raise NotImplementedError

    async def close(self) -> None:
        self.closed = True


def _fake_schema(mode: str) -> McpSchemaSnapshot:
    name = "unknown" if mode == "unknown-tool" else "echo"
    value_type = "integer" if mode == "schema-drift" else "string"
    tool = McpToolDescriptor(
        schema_version=1,
        name=name,
        description="Local deterministic echo fixture.",
        input_schema={
            "type": "object",
            "properties": {
                "value": {"type": value_type},
                "delay_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                "operation": {"enum": ["read", "crash"]},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {}},
            "required": ["value"],
            "additionalProperties": False,
        },
        annotations={"readOnlyHint": True},
    )
    tools = (tool,)
    definition_digest = canonical_schema_digest(
        {"server": "fake-b"},
        schema_id="fixture.mcp-server.fake-b",
        schema_version=1,
    )
    values = {
        "server_id": "fake-b",
        "config_revision": "fake-b-v1",
        "definition_digest": definition_digest,
        "generation": 1,
        "tools": tools,
    }
    suffix = mode.replace("-", ".")
    return McpSchemaSnapshot(
        schema_version=1,
        snapshot_id=f"mcp-schema:fake-b:{suffix}",
        snapshot_digest=mcp_schema_snapshot_digest(**values),
        schema_facts_digest=mcp_tool_schema_facts_digest(tools),
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        **values,
    )


def _copy_mixed_catalog(root: Path) -> tuple[Path, Path]:
    definitions = root / "definitions"
    mappings = root / "mappings"
    definitions.mkdir()
    mappings.mkdir()
    for source_root, target in (
        (PRODUCTION_CAPABILITIES / "definitions", definitions),
        (PRODUCTION_CAPABILITIES / "mappings", mappings),
        (FAKE_CAPABILITIES / "definitions", definitions),
        (FAKE_CAPABILITIES / "mappings", mappings),
    ):
        for source in source_root.iterdir():
            shutil.copy2(source, target / source.name)
    return definitions, mappings


def _health(catalog) -> CapabilityHealthSnapshot:
    providers = []
    for descriptor in catalog.provider_descriptors:
        endpoints = tuple(
            CapabilityEndpointHealth(
                schema_version=1,
                capability_id=definition.capability_id,
                definition_digest=definition.definition_digest,
                status=CapabilityHealthStatus.HEALTHY,
                reason_codes=("mixed_fixture",),
            )
            for definition in catalog.definitions
            if definition.provider == descriptor.provider
        )
        values = {
            "schema_version": 1,
            "provider": descriptor.provider,
            "status": CapabilityHealthStatus.HEALTHY,
            "capabilities": endpoints,
            "observed_at": NOW,
            "expires_at": NOW + timedelta(minutes=5),
        }
        providers.append(
            CapabilityProviderHealth(
                health_digest=capability_provider_health_digest(values),
                **values,
            )
        )
    values = {
        "schema_version": 1,
        "providers": tuple(providers),
        "observed_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    return CapabilityHealthSnapshot(
        snapshot_id="capability-health:mixed",
        snapshot_digest=capability_health_snapshot_digest(values),
        **values,
    )


class McpCapabilityExtensionContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_catalog_permission_execution_and_revocation(self) -> None:
        with TemporaryDirectory() as temporary:
            definitions, mappings = _copy_mixed_catalog(Path(temporary))
            bootstrap = load_capability_catalog_snapshot(
                definitions,
                mappings,
                snapshot_id="capability-catalog:mixed-bootstrap",
                acquired_at=NOW,
            )
            schemas = JsonSchemaCapabilityValidator()
            client = RecordingMixedMcpClient()
            providers = tuple(
                McpCapabilityProvider.from_catalog(
                    bootstrap,
                    descriptor,
                    client,
                    schemas,
                    clock=lambda: NOW,
                )
                for descriptor in bootstrap.provider_descriptors
            )
            provider_registry = InMemoryCapabilityProviderRegistry(providers)
            registry = ConfigCapabilityRegistry(
                definitions,
                mappings,
                schema_validator=schemas,
                provider_registry=provider_registry,
                clock=lambda: NOW,
                initial_snapshot=bootstrap,
            )
            fake = next(
                item
                for item in bootstrap.definitions
                if item.capability_id == "fixture.echo.read.v1"
            )
            health = StaticHealthRegistry(_health(bootstrap))
            query = request_for(fake)
            denied = RoleAuthorizationPolicy(
                AuthorizationPolicyConfig(
                    policy_revision="policy-v1",
                    role_permissions={"member": frozenset()},
                ),
                clock=lambda: NOW,
            )
            denied_result = await DeterministicCapabilityRetriever(
                registry,
                health,
                denied,
                denied,
                clock=lambda: NOW,
            ).retrieve(query, call=execution_call())
            self.assertEqual(denied_result.candidates, ())
            self.assertNotIn(fake.capability_id, repr(denied_result))
            self.assertEqual(client.tool_calls, [])

            authorization = authorization_for((fake,))
            retriever = DeterministicCapabilityRetriever(
                registry,
                health,
                authorization,
                authorization,
                clock=lambda: NOW,
            )
            plan_ids = itertools.count()
            planner = DeterministicToolPlanner(
                {fake.capability_id: {"value": "fixture"}},
                clock=lambda: NOW,
                id_factory=lambda: f"mixed-plan-{next(plan_ids)}",
            )
            plan_validator = DeterministicToolPlanValidator(registry, schemas)
            executor = GovernedToolExecutor(
                registry,
                provider_registry,
                health,
                schemas,
                plan_validator,
                authorization,
                authorization,
                InMemoryInteractionLimiter(
                    {"capability.invoke": 100},
                    policy_revision="limit-v1",
                    clock=lambda: NOW,
                ),
                InMemoryBudgetLedger(
                    ResourceUsage(
                        1,
                        tool_steps=100,
                        retries=100,
                        cost_units=Decimal(100),
                    ),
                    policy_revision="budget-v1",
                    clock=lambda: NOW,
                ),
                InMemoryAuditSink(clock=lambda: NOW),
                InMemoryToolInvocationLedger(clock=lambda: NOW),
                clock=lambda: NOW,
            )
            runtime_ids = itertools.count()
            runtime = DeterministicBoundedCapabilityRuntime(
                registry,
                retriever,
                planner,
                plan_validator,
                DeterministicArgumentBinder(schemas),
                executor,
                DeterministicToolResultValidator(
                    registry,
                    schemas,
                    plan_validator,
                    clock=lambda: NOW,
                ),
                clock=lambda: NOW,
                id_factory=lambda: f"mixed-runtime-{next(runtime_ids)}",
            )
            run_values = {
                "schema_version": 1,
                "query": query.query,
                "actor": query.actor,
                "conversation_scope": query.conversation_scope,
                "data_classification": query.data_classification,
                "available_input_schemas": query.available_input_schemas,
                "maximum_attempts": 4,
            }
            run_request = CapabilityRunRequest(
                request_digest=capability_run_request_digest(run_values),
                **run_values,
            )

            try:
                completed = await runtime.run(run_request, call=execution_call())
                self.assertIs(completed.status, CapabilityRunStatus.COMPLETED)
                self.assertEqual(completed.observations[0].data, {"value": "fixture"})
                self.assertEqual(
                    client.tool_calls,
                    [("fake-b", "echo", {"operation": "read", "value": "fixture"})],
                )

                fake_mapping = mappings / "fixture.echo.read.v1.json"
                fake_mapping.unlink()
                revoked = await registry.reload(call=catalog_call())
                self.assertFalse(
                    next(
                        item
                        for item in revoked.mcp_mappings
                        if item.capability_id == fake.capability_id
                    ).enabled
                )
                deferred = await runtime.run(run_request, call=execution_call())
                self.assertIs(deferred.status, CapabilityRunStatus.DEFERRED)
                self.assertEqual(len(client.tool_calls), 1)

                fake_definition = definitions / "fixture.echo.read.v1.json"
                fake_definition.unlink()
                removed = await registry.reload(call=catalog_call())
                self.assertNotIn(
                    fake.capability_id,
                    {item.capability_id for item in removed.definitions},
                )
                shutil.copy2(
                    FAKE_CAPABILITIES / "definitions" / fake_definition.name,
                    fake_definition,
                )
                shutil.copy2(
                    FAKE_CAPABILITIES / "mappings" / fake_mapping.name,
                    fake_mapping,
                )
                with self.assertRaises(DududaError) as revived:
                    await registry.reload(call=catalog_call())
                self.assertEqual(
                    revived.exception.info.code,
                    "retired_capability_requires_provider_revision",
                )
                self.assertIs(registry.acquire_snapshot(), removed)
                self.assertEqual(len(client.tool_calls), 1)

                fake_provider = next(
                    item
                    for item in providers
                    if item.descriptor.provider.provider_id == "mcp.fake-b"
                )
                for mode in ("unknown-tool", "schema-drift"):
                    client.schema_mode = mode
                    with self.subTest(mode=mode), self.assertRaises(DududaError):
                        await fake_provider.health(call=execution_call())
                    self.assertEqual(len(client.tool_calls), 1)
            finally:
                await provider_registry.close()
                await client.close()


if __name__ == "__main__":
    unittest.main()
