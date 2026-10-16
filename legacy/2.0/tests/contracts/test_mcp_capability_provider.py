from __future__ import annotations

import itertools
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from astrbot_plugin_dududa_core.adapters.mcp_schema import (
    JsonSchemaCapabilityValidator,
    JsonSchemaMcpValidator,
)
from dududa.capabilities import (
    CapabilityExecutionContext,
    McpCapabilityProvider,
    ProviderInvocation,
    ToolExecutionStatus,
    load_capability_catalog_snapshot,
    provider_invocation_digest,
)
from dududa.capabilities.authorization import (
    CapabilityAuthorizationPurpose,
    build_capability_authorization_request,
)
from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.mcp import ManagedUnifiedMcpClient, McpTimeoutPolicy
from dududa.ports.context import (
    NeverCancelled,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.ports.mcp import UnifiedMcpClient

from tests.contracts.test_unified_mcp_worker import (
    _StaticRegistry,
    factory,
    icourse_definition,
    icourse_fixture_server,
    native_definition,
)
from tests.unit.capabilities.test_contracts import NOW
from tests.unit.capabilities.test_executor import execution_call
from tests.unit.capabilities.test_retrieval import authorization_for, request_for
from tests.unit.mcp.helpers import replace_server_definition

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_DEFINITIONS = ROOT / "configs" / "capabilities" / "definitions"
PRODUCTION_MAPPINGS = ROOT / "configs" / "capabilities" / "mappings"
FAKE_DEFINITIONS = ROOT / "tests" / "fixtures" / "capabilities" / "definitions"
FAKE_MAPPINGS = ROOT / "tests" / "fixtures" / "capabilities" / "mappings"


def service_call() -> ServiceCallContext:
    return ServiceCallContext(
        operation_id="mcp-capability-provider-contract",
        principal=ServicePrincipal(
            service_id="test",
            instance_id="capability-provider",
            roles=frozenset({"mcp-transport"}),
        ),
        operation_kind="mcp_capability_provider_contract",
        trace=TraceContext("trace-mcp-capability-provider-contract"),
        deadline=NOW + timedelta(minutes=2),
        cancellation=NeverCancelled(),
        budget=RuntimeBudget(0, 16, 4, 0, 0, Decimal(100)),
        policy_snapshot_id="policy-v1",
    )


class RecordingUnifiedClient:
    def __init__(self, delegate: UnifiedMcpClient) -> None:
        self.delegate = delegate
        self.discover_calls: list[tuple[str, bool, object]] = []
        self.tool_calls: list[tuple[str, str, object, object]] = []
        self.closed = False

    async def discover(self, server_id, *, refresh=False, call):
        self.discover_calls.append((server_id, refresh, call))
        return await self.delegate.discover(server_id, refresh=refresh, call=call)

    async def call_tool(self, server_id, tool_name, arguments, *, call):
        self.tool_calls.append((server_id, tool_name, arguments, call))
        return await self.delegate.call_tool(
            server_id,
            tool_name,
            arguments,
            call=call,
        )

    async def health(self, server_id, *, call):
        return await self.delegate.health(server_id, call=call)

    async def close(self) -> None:
        self.closed = True
        await self.delegate.close()


async def _invocation(snapshot, capability_id: str, arguments, suffix: str):
    definition = next(
        item for item in snapshot.definitions if item.capability_id == capability_id
    )
    mapping = next(
        item for item in snapshot.mcp_mappings if item.capability_id == capability_id
    )
    source = request_for(definition)
    policy = authorization_for(snapshot.definitions)
    authorizations = []
    for permission in sorted(definition.required_permissions):
        request = build_capability_authorization_request(
            definition,
            source.actor,
            source.conversation_scope,
            snapshot,
            permission=permission,
            purpose=CapabilityAuthorizationPurpose.EXECUTION,
            policy_snapshot_id="policy-v1",
        )
        authorizations.append(await policy.decide(request, call=execution_call()))
    values = {
        "schema_version": 1,
        "invocation_id": f"provider-contract-{suffix}",
        "logical_operation_id": f"provider-contract-operation-{suffix}",
        "capability_id": capability_id,
        "definition_digest": definition.definition_digest,
        "provider": definition.provider,
        "mapping_digest": mapping.mapping_digest,
        "arguments": arguments,
        "idempotency_key": f"provider-contract-key-{suffix}",
        "attempt": 1,
        "context": CapabilityExecutionContext(
            1,
            source.actor,
            source.conversation_scope,
            source.data_classification,
        ),
        "authorizations": tuple(authorizations),
    }
    return ProviderInvocation(
        invocation_digest=provider_invocation_digest(values),
        **values,
    )


def _snapshot(definitions: Path, mappings: Path, suffix: str):
    return load_capability_catalog_snapshot(
        definitions,
        mappings,
        snapshot_id=f"capability-catalog:{suffix}",
        acquired_at=NOW,
    )


def _provider(snapshot, client):
    descriptor = snapshot.provider_descriptors[0]
    return McpCapabilityProvider.from_catalog(
        snapshot,
        descriptor,
        client,
        JsonSchemaCapabilityValidator(),
        clock=lambda: NOW,
    )


class McpCapabilityProviderContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_fake_uses_formal_config_and_generic_provider(self) -> None:
        with TemporaryDirectory() as temporary:
            snapshot = _snapshot(FAKE_DEFINITIONS, FAKE_MAPPINGS, "fake")
            journal = Path(temporary) / "fake.jsonl"
            definition = replace_server_definition(
                native_definition(journal),
                server_id="fake-b",
                config_revision="fake-b-v1",
            )
            managed = ManagedUnifiedMcpClient(
                _StaticRegistry(definition),
                factory(),
                JsonSchemaMcpValidator(),
                wall_clock=lambda: NOW,
                id_factory=lambda: "fake-provider-contract",
            )
            client = RecordingUnifiedClient(managed)
            self.assertIsInstance(client, UnifiedMcpClient)
            provider = _provider(snapshot, client)
            try:
                health = await provider.health(call=service_call())
                request = await _invocation(
                    snapshot,
                    "fixture.echo.read.v1",
                    {"value": "fixture", "operation": "read"},
                    "fake",
                )
                result = await provider.invoke(request, call=execution_call())

                self.assertEqual(health.status.value, "healthy")
                self.assertIs(result.status, ToolExecutionStatus.SUCCEEDED)
                self.assertEqual(result.data, {"value": "fixture"})
                self.assertTrue(result.untrusted)
                self.assertEqual(
                    tuple((item[0], item[1]) for item in client.tool_calls),
                    (("fake-b", "echo"),),
                )
                self.assertEqual(
                    client.tool_calls[0][2],
                    {"operation": "read", "value": "fixture"},
                )
                await provider.close()
                self.assertFalse(client.closed)
            finally:
                await client.close()

    async def test_icourse_five_capabilities_share_contract_and_project(
        self,
    ) -> None:
        with (
            TemporaryDirectory() as temporary,
            icourse_fixture_server() as base_url,
        ):
            database = Path(temporary) / "icourse.sqlite3"
            snapshot = _snapshot(
                PRODUCTION_DEFINITIONS,
                PRODUCTION_MAPPINGS,
                "icourse",
            )
            definition = replace_server_definition(
                icourse_definition(database, base_url=base_url),
                timeouts=McpTimeoutPolicy(
                    connect=timedelta(seconds=10),
                    discovery=timedelta(seconds=10),
                    call=timedelta(seconds=10),
                    maximum_call=timedelta(seconds=30),
                    close=timedelta(seconds=5),
                ),
            )
            identifiers = (f"icourse-provider-{item}" for item in itertools.count())
            managed = ManagedUnifiedMcpClient(
                _StaticRegistry(definition),
                factory(),
                JsonSchemaMcpValidator(),
                wall_clock=lambda: NOW,
                id_factory=lambda: next(identifiers),
            )
            client = RecordingUnifiedClient(managed)
            provider = _provider(snapshot, client)
            cases = (
                (
                    "icourse.public-query.v2",
                    {
                        "query": "Database",
                        "goal": "查询评课社区 Database 课程",
                        "operation": "course",
                        "limit": 20,
                    },
                    "public-query-course",
                ),
                (
                    "icourse.public-query.v2",
                    {
                        "query": "Database",
                        "goal": "搜索 Database 公开点评",
                        "operation": "review",
                        "limit": 20,
                    },
                    "public-query-review",
                ),
                (
                    "icourse.public-query.v2",
                    {
                        "query": "Teacher Fixture",
                        "goal": "查询 Teacher Fixture 老师",
                        "operation": "teacher",
                        "limit": 20,
                    },
                    "public-query-teacher",
                ),
                (
                    "icourse.public-query.v2",
                    {
                        "query": "评课社区排行榜",
                        "goal": "查询评课社区排行榜",
                        "operation": "ranking",
                        "limit": 20,
                    },
                    "public-query-ranking",
                ),
                (
                    "icourse.public-query.v2",
                    {
                        "query": "评课社区统计",
                        "goal": "查询评课社区站点统计",
                        "operation": "stats",
                        "limit": 20,
                    },
                    "public-query-stats",
                ),
                ("icourse.stats.read.v1", {}, "stats"),
                (
                    "icourse.courses.search.v1",
                    {"query": "Database"},
                    "search",
                ),
                (
                    "icourse.course.get.v1",
                    {"course_id": 7, "refresh": False},
                    "course",
                ),
                ("icourse.reviews.get.v1", {"course_id": 7}, "reviews"),
            )
            results = []
            try:
                health = await provider.health(call=service_call())
                for capability_id, arguments, suffix in cases:
                    request = await _invocation(
                        snapshot,
                        capability_id,
                        arguments,
                        suffix,
                    )
                    result = await provider.invoke(request, call=execution_call())
                    self.assertIs(result.status, ToolExecutionStatus.SUCCEEDED)
                    self.assertTrue(result.untrusted)
                    self.assertEqual(result.usage.tool_steps, 1)
                    self.assertEqual(len(result.source_refs), 1)
                    results.append(result)

                missing = await _invocation(
                    snapshot,
                    "icourse.course.get.v1",
                    {"course_id": 999, "refresh": False},
                    "missing",
                )
                missing_result = await provider.invoke(
                    missing,
                    call=execution_call(),
                )
                self.assertIs(missing_result.status, ToolExecutionStatus.FAILED)

                self.assertEqual(len(health.capabilities), 5)
                self.assertEqual(
                    tuple(item[1] for item in client.tool_calls),
                    (
                        "icourse_public_query",
                        "icourse_public_query",
                        "icourse_public_query",
                        "icourse_public_query",
                        "icourse_public_query",
                        "icourse_stats",
                        "search_courses",
                        "get_course",
                        "get_reviews",
                        "get_course",
                    ),
                )
                self.assertIs(client.tool_calls[7][2]["refresh"], False)
                rendered = repr((results, missing_result))
                for forbidden in (
                    str(database),
                    "db_path",
                    "html-secret-sentinel",
                    "introduction-html-sentinel",
                    "summary-html-sentinel",
                    "private-source-hash-sentinel",
                    "teacher-homepage-sentinel",
                    "image-sentinel",
                    "source-sentinel",
                    "course_not_found_in_cache",
                ):
                    self.assertNotIn(forbidden, rendered)
                self.assertIn("remains untrusted data", rendered)
                await provider.close()
                self.assertFalse(client.closed)
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
