from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dududa.mcp import ConfigMcpServerRegistry, McpHealthStatus
from dududa_mcp_console.runtime_servers import RuntimeServerOverlay
from dududa_mcp_console.server import McpConsoleRuntime, _handle


def _definition(server_id: str = "repository-server") -> dict[str, object]:
    return {
        "schema_version": 1,
        "server_id": server_id,
        "enabled": True,
        "transport": "streamable_http",
        "protocol_mode": "auto",
        "endpoint": {
            "url": "https://mcp.example.edu/mcp",
            "allowed_hosts": ["mcp.example.edu"],
        },
        "secret_refs": [],
        "allowed_tools": ["news_list"],
        "denied_tools": [],
        "timeouts_seconds": {
            "connect": 10,
            "discovery": 10,
            "call": 30,
            "maximum_call": 60,
            "close": 5,
        },
        "retry": {"maximum_attempts": 1, "base_delay_ms": 100},
        "circuit": {
            "failure_threshold": 3,
            "failure_window_seconds": 60,
            "open_duration_seconds": 30,
        },
        "maximum_concurrency": 1,
        "schema_ttl_seconds": 300,
        "config_revision": "repository-v1",
    }


def _request(server_id: str = "campus-news") -> dict[str, object]:
    return {
        "serverId": server_id,
        "displayName": "校园资讯",
        "enabled": True,
        "transport": "streamable_http",
        "protocolMode": "auto",
        "endpoint": {
            "url": "https://news-mcp.example.edu/mcp",
            "allowedHosts": ["news-mcp.example.edu"],
        },
        "secretRefs": [],
        "allowedTools": ["news_list"],
        "deniedTools": [],
        "timeoutsSeconds": {
            "connect": 10,
            "discovery": 10,
            "call": 30,
            "maximumCall": 60,
            "close": 5,
        },
        "retry": {"maximumAttempts": 1, "baseDelayMs": 100},
        "circuit": {
            "failureThreshold": 3,
            "failureWindowSeconds": 60,
            "openDurationSeconds": 30,
        },
        "maximumConcurrency": 1,
        "schemaTtlSeconds": 300,
        "configRevision": "webui-v1",
    }


def _write_repository(directory: Path) -> None:
    directory.mkdir()
    (directory / "repository-server.json").write_text(
        json.dumps(_definition()),
        encoding="utf-8",
    )


class RuntimeServerOverlayTests(unittest.TestCase):
    def test_frontend_definition_is_persisted_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            _write_repository(repository)
            overlay = RuntimeServerOverlay(
                repository,
                root / "overlay",
                revision_factory=lambda: "generated",
            )

            installed = overlay.install(_request())
            registry = ConfigMcpServerRegistry(overlay.registry_directory)
            snapshot = registry.acquire_snapshot()

            self.assertEqual(installed["config_revision"], "webui-v1")
            self.assertEqual(
                tuple(item.server_id for item in snapshot.definitions),
                ("campus-news", "repository-server"),
            )
            self.assertEqual(overlay.origin("campus-news"), "runtime")
            self.assertEqual(overlay.origin("repository-server"), "repository")
            self.assertEqual(overlay.display_name("campus-news"), "校园资讯")
            self.assertFalse((repository / "campus-news.json").exists())

    def test_unknown_plaintext_secret_field_and_repository_replacement_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            _write_repository(repository)
            overlay = RuntimeServerOverlay(repository, root / "overlay")

            plaintext = {**_request(), "secretValue": "do-not-accept"}
            with self.assertRaisesRegex(ValueError, "invalid_mcp_server_install_fields"):
                overlay.install(plaintext)
            with self.assertRaisesRegex(
                ValueError,
                "repository_mcp_server_cannot_be_replaced",
            ):
                overlay.install(_request("repository-server"))
            with self.assertRaisesRegex(ValueError, "invalid_mcp_server_id"):
                overlay.install(_request(".hidden"))
            self.assertFalse((overlay.installed_directory / ".hidden.json").exists())


class _FakeClient:
    def __init__(self) -> None:
        self.discoveries: list[tuple[str, bool]] = []

    async def health(self, server_id: str, *, call):
        return SimpleNamespace(status=McpHealthStatus.INITIALIZING)

    async def discover(self, server_id: str, *, refresh: bool, call):
        self.discoveries.append((server_id, refresh))
        return SimpleNamespace(
            tools=(SimpleNamespace(name="news_list", description="列出校园资讯"),)
        )


class RuntimeInstallTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_reloads_registry_discovers_tools_and_grants_no_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            _write_repository(repository)
            overlay = RuntimeServerOverlay(repository, root / "overlay")
            runtime = object.__new__(McpConsoleRuntime)
            runtime._server_overlay = overlay
            runtime._registry = ConfigMcpServerRegistry(overlay.registry_directory)
            runtime._client = _FakeClient()
            runtime._secrets = SimpleNamespace(is_configured=lambda reference: False)
            runtime._mappings = {}
            runtime._install_lock = asyncio.Lock()

            result = await runtime.install_server(_request())

            self.assertTrue(result["ok"])
            self.assertEqual(result["serverId"], "campus-news")
            self.assertEqual(result["displayName"], "校园资讯")
            self.assertFalse(result["capabilityGranted"])
            self.assertEqual(result["discovery"]["tools"][0]["name"], "news_list")
            self.assertEqual(runtime._client.discoveries, [("campus-news", True)])
            self.assertEqual(
                tuple(
                    item.server_id
                    for item in runtime._registry.acquire_snapshot().definitions
                ),
                ("campus-news", "repository-server"),
            )


class _RouteRuntime:
    def __init__(self) -> None:
        self.installed: dict[str, object] | None = None

    async def runtime_servers(self):
        return {"schemaVersion": 1, "servers": [{"id": "repository-server"}]}

    async def install_server(self, request):
        self.installed = request
        return {
            "ok": True,
            "serverId": request["serverId"],
            "displayName": request.get("displayName", request["serverId"]),
            "capabilityGranted": False,
            "message": "ok",
        }


async def _http_request(runtime, method: str, path: str, body: object | None = None):
    server = await asyncio.start_server(
        lambda reader, writer: _handle(runtime, reader, writer),
        "127.0.0.1",
        0,
    )
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    writer.write(
        (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1\r\nContent-Length: {len(payload)}\r\n\r\n"
        ).encode("ascii")
        + payload
    )
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()
    status_line = response.split(b"\r\n", 1)[0].decode("ascii")
    value = json.loads(response.split(b"\r\n\r\n", 1)[1])
    return status_line, value


class RuntimeServerRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_list_and_install_routes(self) -> None:
        runtime = _RouteRuntime()
        status, catalog = await _http_request(
            runtime,
            "GET",
            "/v1/servers/runtime",
        )
        self.assertIn("200", status)
        self.assertEqual(catalog["servers"][0]["id"], "repository-server")

        status, result = await _http_request(
            runtime,
            "POST",
            "/v1/servers/install",
            _request(),
        )
        self.assertIn("200", status)
        self.assertFalse(result["capabilityGranted"])
        self.assertEqual(runtime.installed["configRevision"], "webui-v1")


if __name__ == "__main__":
    unittest.main()
