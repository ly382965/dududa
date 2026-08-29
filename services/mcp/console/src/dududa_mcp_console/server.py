from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import tomllib
from dududa.capabilities import load_capability_catalog_snapshot
from dududa.contracts.canonical import canonical_json_bytes, canonical_schema_digest
from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.errors import DududaError
from dududa.mcp import (
    ConfigMcpServerRegistry,
    ManagedUnifiedMcpClient,
    McpCallContext,
    McpHttpEndpoint,
    McpOperationSemantics,
    McpStdioEndpoint,
    SubprocessMcpV2SessionFactory,
    mcp_tool_request_digest,
)
from dududa.ports.context import NeverCancelled, ServiceCallContext, ServicePrincipal
from jsonschema.validators import validator_for

from .runtime_servers import RuntimeServerOverlay

SERVER_NAMES = {
    "icourse": "评课社区",
    "ustc-academic": "教务处",
    "ustc-curriculum": "培养方案",
    "ustc-young": "二课",
}
MAX_BODY_BYTES = 65_536


class EnvironmentSecretResolver:
    _CREDENTIAL_KEYS: ClassVar[dict[str, str]] = {
        "ustc-cas-username": "username",
        "ustc-cas-password": "password",
    }

    def __init__(self, credentials_file: Path | None = None) -> None:
        configured_path = os.getenv("USTC_CAS_CREDENTIALS_FILE", "")
        self._credentials_file = credentials_file or (Path(configured_path) if configured_path else None)

    def is_configured(self, reference) -> bool:
        return bool(self._value(reference))

    async def resolve(self, reference, *, call) -> str:
        value = self._value(reference)
        if not value:
            raise RuntimeError("required secret is not configured")
        return value

    def _value(self, reference) -> str:
        value = os.getenv(reference.target_name, "")
        if value:
            return value
        key = self._CREDENTIAL_KEYS.get(reference.secret_id)
        if key is None or self._credentials_file is None:
            return ""
        try:
            document = tomllib.loads(self._credentials_file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return ""
        value = document.get(key)
        return value if isinstance(value, str) and value else ""


class EnvironmentProvider:
    def select(self, allowlist: frozenset[str]) -> Mapping[str, str]:
        return {name: os.environ[name] for name in allowlist if name in os.environ}


class JsonSchemaValidator:
    def check_schema(self, schema, *, schema_id: str) -> None:
        document = json.loads(canonical_json_bytes(schema))
        validator_for(document).check_schema(document)

    def validate(self, value, schema, *, schema_id: str):
        document = json.loads(canonical_json_bytes(schema))
        instance = json.loads(canonical_json_bytes(value))
        validator = validator_for(document)(document)
        error = next(validator.iter_errors(instance), None)
        if error is not None:
            raise ValueError(f"schema_validation_failed:{error.json_path}")
        return value


class McpConsoleRuntime:
    def __init__(
        self,
        registry_directory: Path,
        definitions_directory: Path,
        mappings_directory: Path,
        worker_python: Path,
        overlay_directory: Path,
    ) -> None:
        self._server_overlay = RuntimeServerOverlay(
            registry_directory,
            overlay_directory,
        )
        self._registry = ConfigMcpServerRegistry(self._server_overlay.registry_directory)
        self._catalog = load_capability_catalog_snapshot(
            definitions_directory,
            mappings_directory,
            snapshot_id=f"mcp-console:{uuid.uuid4().hex}",
            acquired_at=datetime.now(timezone.utc),
        )
        self._secrets = EnvironmentSecretResolver()
        factory = SubprocessMcpV2SessionFactory(
            worker_python,
            self._secrets,
            EnvironmentProvider(),
        )
        self._client = ManagedUnifiedMcpClient(self._registry, factory, JsonSchemaValidator())
        self._definitions = {item.capability_id: item for item in self._catalog.definitions}
        self._mappings = {item.capability_id: item for item in self._catalog.mcp_mappings if item.enabled}
        self._schemas = {
            (item.schema_ref.schema_id, item.schema_ref.schema_version): item
            for item in self._catalog.schema_documents
        }
        self._install_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.close()

    async def catalog(self) -> dict[str, Any]:
        registry = self._registry.acquire_snapshot()
        servers = []
        by_id = {item.server_id: item for item in registry.definitions}
        for server_id, definition in sorted(by_id.items()):
            missing = [ref.target_name for ref in definition.secret_refs if not self._secrets.is_configured(ref)]
            auth = "not_required" if not definition.secret_refs else ("configured" if not missing else "missing_secret")
            health = await self._client.health(server_id, call=self._service_call("catalog-health"))
            servers.append(
                {
                    "id": server_id,
                    "displayName": SERVER_NAMES.get(
                        server_id,
                        self._server_overlay.display_name(server_id),
                    ),
                    "enabled": definition.enabled,
                    "available": definition.enabled and not missing,
                    "authentication": auth,
                    "health": health.status.value,
                    "reason": _missing_secret_reason(definition) if missing else None,
                    "capabilityCount": sum(1 for item in self._mappings.values() if item.server_id == server_id),
                }
            )
        capabilities = []
        for capability_id, mapping in sorted(self._mappings.items()):
            definition = self._definitions.get(capability_id)
            server = by_id.get(mapping.server_id)
            if definition is None or server is None or not definition.enabled:
                continue
            missing = [ref.target_name for ref in server.secret_refs if not self._secrets.is_configured(ref)]
            input_document = self._schema(definition.input_schema)
            capabilities.append(
                {
                    "id": capability_id,
                    "serverId": mapping.server_id,
                    "toolName": mapping.tool_name,
                    "name": definition.name,
                    "description": definition.description,
                    "category": definition.category,
                    "privacy": definition.privacy_level.value,
                    "allowedContexts": sorted(item.value for item in definition.allowed_contexts),
                    "inputSchema": _plain(input_document.document),
                    "available": server.enabled and not missing,
                    "authentication": "not_required" if not server.secret_refs else ("configured" if not missing else "missing_secret"),
                    "unavailableReason": _missing_secret_reason(server) if missing else None,
                }
            )
        return {"schemaVersion": 1, "servers": servers, "capabilities": capabilities}

    async def runtime_servers(self) -> dict[str, Any]:
        snapshot = self._registry.acquire_snapshot()
        servers = []
        for definition in sorted(snapshot.definitions, key=lambda item: item.server_id):
            servers.append(await self._runtime_server_projection(definition))
        return {
            "schemaVersion": 1,
            "servers": servers,
        }

    async def install_server(self, request: Mapping[str, Any]) -> dict[str, Any]:
        async with self._install_lock:
            document = self._server_overlay.install(request)
            server_id = str(document["server_id"])
            try:
                snapshot = await self._registry.reload(
                    call=self._service_call("runtime-server-reload")
                )
            except Exception:
                self._server_overlay.rollback(server_id)
                raise
            definition = self._registry.resolve_server(snapshot, server_id)
            projection = await self._runtime_server_projection(definition)
            try:
                schema = await self._client.discover(
                    server_id,
                    refresh=True,
                    call=self._service_call("runtime-server-discovery"),
                )
            except DududaError as exc:  # Discovery failure leaves a visible, repairable config.
                code = getattr(getattr(exc, "info", None), "code", "mcp_discovery_failed")
                return {
                    "schemaVersion": 1,
                    "ok": True,
                    "serverId": server_id,
                    "displayName": projection["displayName"],
                    "status": "warning",
                    "message": "MCP Server 已接入，但工具发现暂不可用",
                    "server": projection,
                    "discovery": {"status": "unavailable", "error": code, "tools": []},
                    "capabilityGranted": False,
                }
            return {
                "schemaVersion": 1,
                "ok": True,
                "serverId": server_id,
                "displayName": projection["displayName"],
                "status": "ok",
                "message": "MCP Server 已接入并完成工具发现",
                "server": await self._runtime_server_projection(definition),
                "discovery": {
                    "status": "ok",
                    "tools": [
                        {"name": item.name, "description": item.description}
                        for item in schema.tools
                    ],
                },
                "capabilityGranted": False,
            }

    async def _runtime_server_projection(self, definition) -> dict[str, Any]:
        missing = [
            reference.target_name
            for reference in definition.secret_refs
            if not self._secrets.is_configured(reference)
        ]
        health = await self._client.health(
            definition.server_id,
            call=self._service_call("runtime-server-health"),
        )
        endpoint: dict[str, Any]
        if isinstance(definition.endpoint, McpStdioEndpoint):
            endpoint = {
                "command": definition.endpoint.command,
                "args": list(definition.endpoint.args),
                "cwd": definition.endpoint.cwd,
                "envAllowlist": sorted(definition.endpoint.env_allowlist),
            }
        elif isinstance(definition.endpoint, McpHttpEndpoint):
            endpoint = {
                "url": definition.endpoint.url,
                "allowedHosts": sorted(definition.endpoint.allowed_hosts),
            }
        else:  # pragma: no cover - Core definition validation makes this unreachable.
            raise TypeError("unsupported_mcp_endpoint")
        return {
            "id": definition.server_id,
            "displayName": SERVER_NAMES.get(
                definition.server_id,
                self._server_overlay.display_name(definition.server_id),
            ),
            "origin": self._server_overlay.origin(definition.server_id),
            "enabled": definition.enabled,
            "transport": definition.transport.value,
            "protocolMode": definition.protocol_mode.value,
            "endpoint": endpoint,
            "authentication": (
                "not_required"
                if not definition.secret_refs
                else ("configured" if not missing else "missing_secret")
            ),
            "available": definition.enabled and not missing,
            "reason": _missing_secret_reason(definition) if missing else None,
            "health": health.status.value,
            "configRevision": definition.config_revision,
            "allowedTools": sorted(definition.allowed_tools),
            "deniedTools": sorted(definition.denied_tools),
            "secretRefs": [
                {
                    "secretId": item.secret_id,
                    "target": item.target.value,
                    "targetName": item.target_name,
                    "configured": self._secrets.is_configured(item),
                }
                for item in definition.secret_refs
            ],
            "capabilityCount": sum(
                1 for item in self._mappings.values() if item.server_id == definition.server_id
            ),
            "capabilityGranted": False,
        }

    async def invoke(self, capability_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        definition = self._definitions.get(capability_id)
        mapping = self._mappings.get(capability_id)
        if definition is None or mapping is None:
            raise ValueError("unknown_capability_id")
        if mapping.semantics is not McpOperationSemantics.READ_ONLY:
            raise ValueError("console_only_supports_read_only_capabilities")
        registry = self._registry.acquire_snapshot()
        server = self._registry.resolve_server(registry, mapping.server_id)
        if any(not self._secrets.is_configured(reference) for reference in server.secret_refs):
            raise RuntimeError("需要配置 USTC CAS")
        input_document = self._schema(definition.input_schema)
        input_validator = validator_for(input_document.document)(input_document.document)
        payload = dict(arguments)
        for key, value in mapping.fixed_arguments.items():
            if key in payload and payload[key] != value:
                raise ValueError(f"fixed_argument_mismatch:{key}")
            payload[key] = _plain(value)
        input_error = next(input_validator.iter_errors(payload), None)
        if input_error is not None:
            raise ValueError(f"invalid_capability_arguments:{input_error.json_path}")
        caller = self._service_call("invoke")
        schema = await self._client.discover(mapping.server_id, call=caller)
        tool = next((item for item in schema.tools if item.name == mapping.tool_name), None)
        if tool is None:
            raise RuntimeError("configured_mcp_tool_missing")
        actual_input = canonical_schema_digest(
            tool.input_schema,
            schema_id=f"mcp.{mapping.server_id}.{mapping.tool_name}.input",
            schema_version=1,
        )
        actual_output = None if tool.output_schema is None else canonical_schema_digest(
            tool.output_schema,
            schema_id=f"mcp.{mapping.server_id}.{mapping.tool_name}.output",
            schema_version=1,
        )
        if actual_input != mapping.expected_input_schema_digest or actual_output != mapping.expected_output_schema_digest:
            raise RuntimeError("configured_mcp_tool_schema_drifted")
        request_digest = mcp_tool_request_digest(
            mapping.server_id,
            mapping.tool_name,
            payload,
            schema,
            mapping.semantics,
            None,
        )
        call = McpCallContext(
            schema_version=1,
            caller=caller,
            schema_snapshot_id=schema.snapshot_id,
            schema_snapshot_digest=schema.snapshot_digest,
            request_digest=request_digest,
            semantics=mapping.semantics,
        )
        result = await self._client.call_tool(mapping.server_id, mapping.tool_name, payload, call=call)
        data = _plain(result.structured_content)
        if data is not None:
            output_document = self._schema(definition.output_schema)
            data = _project_to_schema(data, output_document.document)
            output_error = next(
                validator_for(output_document.document)(output_document.document).iter_errors(data),
                None,
            )
            if output_error is not None:
                raise RuntimeError("mcp_capability_output_schema_mismatch")
        content = [block.text for block in result.content if block.text is not None]
        source_url = data.get("source_url") if isinstance(data, dict) else None
        fetched = data.get("fetched_at") if isinstance(data, dict) else None
        return {
            "ok": not result.is_error,
            "capabilityId": capability_id,
            "serverId": mapping.server_id,
            "toolName": mapping.tool_name,
            "data": data,
            "content": content,
            "sourceUrl": source_url,
            "fetchedAt": fetched,
            "generation": result.generation,
        }

    def _schema(self, reference):
        document = self._schemas.get((reference.schema_id, reference.schema_version))
        if document is None or document.schema_ref.digest != reference.digest:
            raise RuntimeError("capability_schema_missing")
        return document

    @staticmethod
    def _service_call(kind: str) -> ServiceCallContext:
        suffix = uuid.uuid4().hex
        return ServiceCallContext(
            operation_id=f"mcp-console-{suffix}",
            principal=ServicePrincipal("dududa-web", "mcp-console", frozenset({"super_admin", "mcp-transport"})),
            operation_kind=f"mcp_console_{kind}",
            trace=TraceContext(f"trace-mcp-console-{suffix}"),
            deadline=datetime.now(timezone.utc) + timedelta(minutes=2),
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(0, 32, 4, 0, 0, Decimal(100)),
            policy_snapshot_id="mcp-console-read-only-v1",
        )


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _missing_secret_reason(definition) -> str:
    secret_ids = {item.secret_id for item in definition.secret_refs}
    if secret_ids and secret_ids <= {"ustc-cas-username", "ustc-cas-password"}:
        return "需要配置 USTC CAS"
    return "需要配置引用的 Secret"


def _project_to_schema(value: Any, schema: Mapping[str, Any]) -> Any:
    kind = schema.get("type")
    kinds = {kind} if isinstance(kind, str) else set(kind) if isinstance(kind, (list, tuple)) else set()
    if isinstance(value, dict) and ("object" in kinds or not kinds):
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            return {
                name: _project_to_schema(value[name], child)
                for name, child in properties.items()
                if name in value and isinstance(child, Mapping)
            }
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list) and ("array" in kinds or not kinds):
        items = schema.get("items")
        if isinstance(items, Mapping):
            return [_project_to_schema(item, items) for item in value]
        return [_plain(item) for item in value]
    return _plain(value)


async def _response(writer: asyncio.StreamWriter, status: int, body: object) -> None:
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    reasons = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 413: "Content Too Large", 500: "Internal Server Error", 503: "Service Unavailable"}
    writer.write(
        f"HTTP/1.1 {status} {reasons.get(status, 'Error')}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {len(payload)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode("ascii") + payload
    )
    await writer.drain()


async def _handle(runtime: McpConsoleRuntime, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        header = await reader.readuntil(b"\r\n\r\n")
        if len(header) > 32_768:
            await _response(writer, 413, {"error": "request_headers_too_large"})
            return
        lines = header.decode("iso-8859-1").split("\r\n")
        method, path, _version = lines[0].split(" ", 2)
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.casefold()] = value.strip()
        size = int(headers.get("content-length", "0"))
        if size < 0 or size > MAX_BODY_BYTES:
            await _response(writer, 413, {"error": "request_body_too_large"})
            return
        body = await reader.readexactly(size) if size else b""
        if method == "GET" and path == "/health":
            await _response(writer, 200, {"ok": True})
        elif method == "GET" and path == "/v1/catalog":
            await _response(writer, 200, await runtime.catalog())
        elif method == "GET" and path == "/v1/servers/runtime":
            await _response(writer, 200, await runtime.runtime_servers())
        elif method == "POST" and path == "/v1/servers/install":
            value = json.loads(body or b"{}")
            if not isinstance(value, dict):
                raise ValueError("invalid_mcp_server_install_request")
            await _response(writer, 200, await runtime.install_server(value))
        elif method == "POST" and path == "/v1/invoke":
            value = json.loads(body or b"{}")
            if not isinstance(value, dict) or not isinstance(value.get("capabilityId"), str) or not isinstance(value.get("arguments", {}), dict):
                raise ValueError("invalid_invoke_request")
            await _response(writer, 200, await runtime.invoke(value["capabilityId"], value.get("arguments", {})))
        elif path in {
            "/health",
            "/v1/catalog",
            "/v1/invoke",
            "/v1/servers/runtime",
            "/v1/servers/install",
        }:
            await _response(writer, 405, {"error": "method_not_allowed"})
        else:
            await _response(writer, 404, {"error": "not_found"})
    except (ValueError, json.JSONDecodeError) as exc:
        await _response(writer, 400, {"error": str(exc)})
    except RuntimeError as exc:
        await _response(writer, 503, {"error": str(exc)})
    except Exception:  # noqa: BLE001 - HTTP boundary returns a sanitized error.
        await _response(writer, 500, {"error": "mcp_console_internal_error"})
    finally:
        writer.close()
        await writer.wait_closed()


async def serve(args: argparse.Namespace) -> None:
    runtime = McpConsoleRuntime(
        args.registry,
        args.definitions,
        args.mappings,
        args.worker_python,
        args.runtime_overlay,
    )
    server = await asyncio.start_server(lambda reader, writer: _handle(runtime, reader, writer), args.host, args.port, limit=MAX_BODY_BYTES + 32_768)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    try:
        async with server:
            await stop.wait()
    finally:
        await runtime.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the internal read-only MCP Capability console.")
    parser.add_argument("--host", default=os.getenv("DUDUDA_MCP_CONSOLE_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DUDUDA_MCP_CONSOLE_PORT", "8090")))
    parser.add_argument("--registry", type=Path, default=Path(os.getenv("DUDUDA_MCP_REGISTRY_DIR", "/opt/dududa/config/mcp/servers")))
    parser.add_argument(
        "--runtime-overlay",
        type=Path,
        default=Path(
            os.getenv(
                "DUDUDA_MCP_RUNTIME_OVERLAY_DIR",
                "/var/lib/dududa/mcp/servers",
            )
        ),
    )
    parser.add_argument("--definitions", type=Path, default=Path(os.getenv("DUDUDA_CAPABILITY_DEFINITIONS_DIR", "/opt/dududa/config/capabilities/definitions")))
    parser.add_argument("--mappings", type=Path, default=Path(os.getenv("DUDUDA_CAPABILITY_MAPPINGS_DIR", "/opt/dududa/config/capabilities/mappings")))
    parser.add_argument("--worker-python", type=Path, default=Path(os.getenv("DUDUDA_MCP_WORKER_PYTHON", "/opt/dududa/unified-mcp-worker/.venv/bin/python")))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    asyncio.run(serve(parse_args(argv)))


if __name__ == "__main__":
    main()
