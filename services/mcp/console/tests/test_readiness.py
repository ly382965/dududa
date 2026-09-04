from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from dududa.mcp import ConfigMcpServerRegistry, McpHealthStatus
from dududa_mcp_console.server import McpConsoleRuntime
from dududa_mcp_console.runtime_servers import RuntimeServerOverlay
from test_runtime_servers import _definition, _http_request


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repository = root / "registry"
        self.repository.mkdir()
        self.doc = _definition()
        self.write_definition()
        runtime = object.__new__(McpConsoleRuntime)
        runtime._server_overlay = RuntimeServerOverlay(self.repository, root / "overlay")
        runtime._registry = ConfigMcpServerRegistry(runtime._server_overlay.registry_directory)
        runtime._definitions = {}
        runtime._schemas = {}
        runtime._mappings = {"test": SimpleNamespace(server_id="repository-server", tool_name="news_list")}
        runtime._checks = {}
        runtime._secrets = SimpleNamespace(is_configured=lambda reference: False)
        runtime._client = SimpleNamespace(
            health=AsyncMock(return_value=SimpleNamespace(status=McpHealthStatus.INITIALIZING)),
            discover=AsyncMock(return_value=SimpleNamespace(tools=(SimpleNamespace(name="news_list"),))),
            call_tool=AsyncMock(),
        )
        self.runtime = runtime

    def write_definition(self):
        (self.repository / "repository-server.json").write_text(json.dumps(self.doc))

    async def test_catalog_is_unverified_and_does_not_connect(self):
        catalog = await self.runtime.catalog()
        self.assertEqual(catalog["servers"][0]["readiness"], "unverified")
        self.assertIsNone(catalog["servers"][0]["checkedAt"])
        self.runtime._client.discover.assert_not_called()

    async def test_registered_connection_check_discovers_without_tool_call(self):
        self.runtime._client.health.return_value.status = McpHealthStatus.HEALTHY
        result = await self.runtime.check_server({"serverId": "repository-server"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["server"]["readiness"], "healthy")
        self.assertIsNotNone(result["server"]["checkedAt"])
        self.runtime._client.discover.assert_awaited_once()
        self.runtime._client.call_tool.assert_not_called()

    async def test_unknown_or_extra_fields_rejected_before_discovery(self):
        for request in ({"serverId": "unknown"}, {"serverId": "repository-server", "url": "https://example.com"}):
            with self.assertRaises(ValueError):
                await self.runtime.check_server(request)
        self.runtime._client.discover.assert_not_called()

    async def test_disabled_does_not_connect(self):
        definition = self.runtime._registry.acquire_snapshot().definitions[0]
        from tests.unit.mcp.helpers import replace_server_definition
        disabled = replace_server_definition(definition, enabled=False)
        self.runtime._registry = SimpleNamespace(acquire_snapshot=lambda: SimpleNamespace(definitions=(disabled,)))
        result = await self.runtime.check_server({"serverId": "repository-server"})
        self.assertEqual(result["server"]["readiness"], "disabled")
        self.runtime._client.discover.assert_not_called()

    async def test_failure_and_timeout_do_not_leak_upstream_details(self):
        for error in (RuntimeError("secret-token-do-not-expose"), TimeoutError()):
            self.runtime._client.discover.side_effect = error
            result = await self.runtime.check_server({"serverId": "repository-server"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["server"]["readiness"], "error")
            self.assertNotIn("secret-token", json.dumps(result))

    async def test_missing_expected_tool_is_not_healthy(self):
        self.runtime._client.discover.return_value = SimpleNamespace(tools=())
        result = await self.runtime.check_server({"serverId": "repository-server"})
        self.assertFalse(result["ok"])

    async def test_missing_secret_does_not_connect(self):
        self.doc["secret_refs"] = [{"secret_id": "test-key", "target": "header", "target_name": "Authorization"}]
        self.write_definition()
        self.runtime._registry = ConfigMcpServerRegistry(self.repository)
        result = await self.runtime.check_server({"serverId": "repository-server"})
        self.assertEqual(result["server"]["readiness"], "missing_secret")
        self.runtime._client.discover.assert_not_called()

    async def test_http_check_requires_exact_request(self):
        status, body = await _http_request(self.runtime, "POST", "/v1/servers/check", {"serverId": "unknown"})
        self.assertIn("400", status)
        self.assertEqual(body["error"], "unknown_mcp_server_id")


if __name__ == "__main__":
    unittest.main()
