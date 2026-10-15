from __future__ import annotations

import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.mcp import (
    McpHttpEndpoint,
    McpSecretRef,
    McpSecretTarget,
    McpTransportKind,
    SubprocessMcpV2SessionFactory,
)
from dududa.ports.context import (
    NeverCancelled,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.ports.mcp import McpTransportError
from dududa.testing import (
    MappingMcpEnvironmentProvider,
    MappingMcpSecretResolver,
)

from .helpers import NOW, replace_server_definition, server_definition


def service_call() -> ServiceCallContext:
    return ServiceCallContext(
        operation_id="subprocess-v2-test",
        principal=ServicePrincipal(
            service_id="test",
            instance_id="subprocess-v2",
            roles=frozenset({"mcp-transport"}),
        ),
        operation_kind="mcp_transport_test",
        trace=TraceContext("trace-subprocess-v2"),
        deadline=NOW + timedelta(minutes=1),
        cancellation=NeverCancelled(),
        budget=RuntimeBudget(0, 1, 0, 0, 0, Decimal("0")),
        policy_snapshot_id="policy-v1",
    )


def http_definition():
    return replace_server_definition(
        server_definition("http-fixture"),
        transport=McpTransportKind.STREAMABLE_HTTP,
        endpoint=McpHttpEndpoint(
            url="https://mcp.example.test/api",
            allowed_hosts=frozenset({"mcp.example.test"}),
        ),
        secret_refs=(
            McpSecretRef(
                secret_id="fixture-header",
                target=McpSecretTarget.HEADER,
                target_name="Authorization",
            ),
        ),
        config_revision="http-fixture-v1",
    )


class _BrokenSecretResolver:
    async def resolve(self, reference, *, call) -> str:
        raise RuntimeError("resolver-secret-sentinel")


class SubprocessMcpV2FactoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_https_payload_is_built_offline_with_header_secret(self) -> None:
        factory = SubprocessMcpV2SessionFactory(
            Path("/opt/dududa/worker/python"),
            MappingMcpSecretResolver({"fixture-header": "test-secret"}),
            MappingMcpEnvironmentProvider({}),
        )
        payload = await factory._endpoint_payload(
            http_definition(),
            service_call(),
        )
        self.assertEqual(payload["url"], "https://mcp.example.test/api")
        self.assertEqual(payload["headers"], {"Authorization": "test-secret"})

    async def test_secret_resolver_exception_has_no_raw_exception_graph(self) -> None:
        factory = SubprocessMcpV2SessionFactory(
            Path("/opt/dududa/worker/python"),
            _BrokenSecretResolver(),
            MappingMcpEnvironmentProvider({}),
        )
        with self.assertRaises(McpTransportError) as captured:
            await factory.open(http_definition(), 1, call=service_call())
        error = captured.exception
        self.assertNotIn("resolver-secret-sentinel", repr(error))
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)


if __name__ == "__main__":
    unittest.main()
