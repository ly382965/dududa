from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import math
import os
import re
import sys
from contextlib import AsyncExitStack
from typing import Any
from urllib.parse import urlsplit

import httpx2
from mcp import Client, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 2_097_152
MAX_IN_FLIGHT = 64
MAX_CONTENT_BYTES = 1_048_576
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PROCESS_NONCE = re.compile(r"^[a-f0-9]{32}$")
_METHODS = frozenset({"open", "discover", "call", "cancel", "close"})


class WorkerProtocolError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Worker:
    def __init__(
        self,
        *,
        client_factory: Any = Client,
        stdio_transport_factory: Any = stdio_client,
        http_client_factory: Any = httpx2.AsyncClient,
        http_transport_factory: Any = streamable_http_client,
    ) -> None:
        self._client: Client | None = None
        self._stack: AsyncExitStack | None = None
        self._client_factory = client_factory
        self._stdio_transport_factory = stdio_transport_factory
        self._http_client_factory = http_client_factory
        self._http_transport_factory = http_transport_factory
        self._write_lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closing = False

    async def run(self) -> int:
        try:
            while not self._closing:
                line = await asyncio.to_thread(
                    sys.stdin.buffer.readline, MAX_LINE_BYTES + 1
                )
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    return 2
                try:
                    request = _parse_request(line)
                except WorkerProtocolError:
                    return 2
                request_id = request["id"]
                method = request["method"]
                if method == "cancel":
                    await self._cancel_request(request)
                    continue
                if method == "close":
                    await self._close_request(request)
                    break
                if request_id in self._tasks or len(self._tasks) >= MAX_IN_FLIGHT:
                    await self._write_error(
                        request_id,
                        "protocol",
                        "request_capacity_rejected",
                        method,
                        "not_dispatched",
                    )
                    continue
                task = asyncio.create_task(self._execute(request))
                self._tasks[request_id] = task
        finally:
            self._closing = True
            await self._cancel_active()
            await self._close_client()
        return 0

    async def _execute(self, request: dict[str, Any]) -> None:
        request_id = request["id"]
        method = request["method"]
        try:
            if method == "open":
                result = await self._open(request["params"])
            elif method == "discover":
                result = await self._discover(request["params"])
            elif method == "call":
                result = await self._call(request["params"])
            else:
                raise WorkerProtocolError("unknown_method")
            await self._write(
                {"v": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": result}
            )
        except asyncio.CancelledError:
            await self._write_error(
                request_id,
                "cancelled",
                "worker_request_cancelled",
                method,
                "unknown" if method == "call" else "not_dispatched",
            )
        except WorkerProtocolError as exc:
            await self._write_error(
                request_id,
                "protocol",
                exc.code,
                method,
                "unknown" if method == "call" else "not_dispatched",
            )
        except BaseException:
            await self._write_error(
                request_id,
                "unavailable",
                f"{method}_operation_failed",
                method,
                "unknown" if method == "call" else "not_dispatched",
            )
        finally:
            self._tasks.pop(request_id, None)

    async def _open(self, params: object) -> dict[str, object]:
        if self._client is not None:
            raise WorkerProtocolError("session_already_open")
        document = _object(params, "open_params")
        _exact(
            document,
            {
                "transport",
                "protocol_mode",
                "endpoint",
                "process_control",
                "read_timeout_seconds",
            },
        )
        transport_kind = _string(document["transport"], "transport")
        protocol_mode = _string(document["protocol_mode"], "protocol_mode")
        if protocol_mode not in {"auto", "legacy"}:
            raise WorkerProtocolError("invalid_protocol_mode")
        read_timeout = _positive_number(
            document["read_timeout_seconds"], "read_timeout_seconds"
        )
        stack = AsyncExitStack()
        try:
            if transport_kind == "stdio":
                transport = self._stdio_transport_factory(
                    _stdio_parameters(
                        document["endpoint"],
                        document["process_control"],
                    ),
                    errlog=sys.stderr,
                )
            elif transport_kind == "streamable_http":
                if document["process_control"] is not None:
                    raise WorkerProtocolError("invalid_process_control")
                endpoint = _http_endpoint(document["endpoint"])
                http_client = self._http_client_factory(
                    headers=endpoint["headers"],
                    follow_redirects=False,
                    trust_env=False,
                )
                await stack.enter_async_context(http_client)
                transport = self._http_transport_factory(
                    endpoint["url"],
                    http_client=http_client,
                    terminate_on_close=True,
                )
            else:
                raise WorkerProtocolError("unsupported_transport")
            client = self._client_factory(
                transport,
                mode=protocol_mode,
                read_timeout_seconds=read_timeout,
                cache=None,
            )
            await client.__aenter__()
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._client = client
        return {"protocol_version": client.protocol_version}

    async def _discover(self, params: object) -> dict[str, object]:
        _exact(_object(params, "discover_params"), set())
        client = self._require_client()
        result = await client.list_tools(cache_mode="bypass")
        tools = []
        for tool in result.tools:
            encoded = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            tools.append(
                {
                    "name": encoded.get("name"),
                    "description": encoded.get("description", ""),
                    "input_schema": encoded.get("inputSchema"),
                    "output_schema": encoded.get("outputSchema"),
                    "annotations": encoded.get("annotations") or {},
                }
            )
        return {"tools": tools}

    async def _call(self, params: object) -> dict[str, object]:
        document = _object(params, "call_params")
        _exact(document, {"tool_name", "arguments"})
        tool_name = _string(document["tool_name"], "tool_name")
        arguments = document["arguments"]
        if not isinstance(arguments, dict):
            raise WorkerProtocolError("invalid_tool_arguments")
        result = await self._require_client().call_tool(tool_name, arguments)
        structured = result.structured_content
        content = tuple(_normalize_content(item) for item in result.content)
        return {
            "is_error": bool(result.is_error),
            "structured_content": structured,
            "content": content,
        }

    async def _cancel_request(self, request: dict[str, Any]) -> None:
        params = _object(request["params"], "cancel_params")
        _exact(params, {"target_id"})
        target_id = _request_id(params["target_id"])
        task = self._tasks.get(target_id)
        if task is not None:
            task.cancel()
        await self._write(
            {
                "v": PROTOCOL_VERSION,
                "id": request["id"],
                "ok": True,
                "result": {"cancelled": task is not None},
            }
        )

    async def _close_request(self, request: dict[str, Any]) -> None:
        _exact(_object(request["params"], "close_params"), set())
        self._closing = True
        await self._cancel_active()
        await self._close_client()
        await self._write(
            {
                "v": PROTOCOL_VERSION,
                "id": request["id"],
                "ok": True,
                "result": {"closed": True},
            }
        )

    async def _cancel_active(self) -> None:
        current = asyncio.current_task()
        tasks = tuple(task for task in self._tasks.values() if task is not current)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _close_client(self) -> None:
        client = self._client
        stack = self._stack
        self._client = None
        self._stack = None
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except BaseException:
                pass
        if stack is not None:
            try:
                await stack.aclose()
            except BaseException:
                pass

    def _require_client(self) -> Client:
        if self._client is None:
            raise WorkerProtocolError("session_not_open")
        return self._client

    async def _write_error(
        self,
        request_id: str,
        kind: str,
        code: str,
        phase: str,
        dispatch_state: str,
    ) -> None:
        await self._write(
            {
                "v": PROTOCOL_VERSION,
                "id": request_id,
                "ok": False,
                "error": {
                    "kind": kind,
                    "code": code,
                    "phase": phase,
                    "dispatch_state": dispatch_state,
                },
            }
        )

    async def _write(self, value: dict[str, object]) -> None:
        payload = (
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        if len(payload) > MAX_LINE_BYTES:
            raise WorkerProtocolError("response_too_large")
        async with self._write_lock:
            write_task = asyncio.create_task(asyncio.to_thread(_write_all, payload))
            cancelled = False
            while not write_task.done():
                try:
                    await asyncio.shield(write_task)
                except asyncio.CancelledError:
                    cancelled = True
            write_task.result()
            if cancelled:
                raise asyncio.CancelledError()


def _parse_request(line: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            line,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise WorkerProtocolError("invalid_json") from exc
    document = _object(value, "request")
    _exact(document, {"v", "id", "method", "params"})
    if type(document["v"]) is not int or document["v"] != PROTOCOL_VERSION:
        raise WorkerProtocolError("unsupported_protocol_version")
    request_id = _request_id(document["id"])
    method = _string(document["method"], "method")
    if method not in _METHODS:
        raise WorkerProtocolError("unknown_method")
    return {
        "v": PROTOCOL_VERSION,
        "id": request_id,
        "method": method,
        "params": document["params"],
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _stdio_parameters(
    value: object,
    process_control: object,
) -> StdioServerParameters:
    document = _object(value, "stdio_endpoint")
    _exact(document, {"command", "args", "cwd", "env"})
    command = _absolute(_string(document["command"], "command"))
    cwd = _absolute(_string(document["cwd"], "cwd"))
    args = document["args"]
    env = document["env"]
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise WorkerProtocolError("invalid_stdio_args")
    if not isinstance(env, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in env.items()
    ):
        raise WorkerProtocolError("invalid_stdio_environment")
    control = _object(process_control, "process_control")
    _exact(control, {"path", "nonce"})
    path = _absolute(_string(control["path"], "process_control_path"))
    nonce = _string(control["nonce"], "process_control_nonce")
    if _PROCESS_NONCE.fullmatch(nonce) is None:
        raise WorkerProtocolError("invalid_process_control_nonce")
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "dududa_unified_mcp_worker.stdio_guard",
            path,
            nonce,
            command,
            *args,
        ],
        cwd=cwd,
        env=env,
    )


def _http_endpoint(value: object) -> dict[str, Any]:
    document = _object(value, "http_endpoint")
    _exact(document, {"url", "headers"})
    url = _string(document["url"], "url")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise WorkerProtocolError("invalid_http_url")
    headers = document["headers"]
    if not isinstance(headers, dict) or any(
        not isinstance(key, str)
        or not isinstance(item, str)
        or any(character in key for character in "\r\n:")
        or any(character in item for character in "\r\n")
        for key, item in headers.items()
    ):
        raise WorkerProtocolError("invalid_http_headers")
    return {"url": url, "headers": headers}


def _normalize_content(item: object) -> dict[str, object | None]:
    if not hasattr(item, "model_dump"):
        raise WorkerProtocolError("unsupported_content")
    value = item.model_dump(mode="json", by_alias=True, exclude_none=True)
    kind = value.get("type")
    if kind == "text":
        text = _string(value.get("text"), "content_text", allow_empty=True)
        return {
            "kind": "text",
            "text": text,
            "mime_type": value.get("mimeType"),
            "uri": None,
            "data_digest": None,
            "data_base64": None,
            "size_bytes": len(text.encode("utf-8")),
        }
    if kind == "image":
        return _binary_content("image", value.get("data"), value.get("mimeType"), None)
    if kind in {"resource_link", "resourceLink"}:
        return {
            "kind": "resource",
            "text": None,
            "mime_type": value.get("mimeType"),
            "uri": _string(value.get("uri"), "resource_uri"),
            "data_digest": None,
            "data_base64": None,
            "size_bytes": 0,
        }
    if kind == "resource":
        resource = _object(value.get("resource"), "embedded_resource")
        uri = _string(resource.get("uri"), "resource_uri")
        mime = resource.get("mimeType")
        if "text" in resource:
            text = _string(resource["text"], "resource_text", allow_empty=True)
            return {
                "kind": "embedded_resource",
                "text": text,
                "mime_type": mime,
                "uri": uri,
                "data_digest": None,
                "data_base64": None,
                "size_bytes": len(text.encode("utf-8")),
            }
        return _binary_content("embedded_resource", resource.get("blob"), mime, uri)
    raise WorkerProtocolError("unsupported_content")


def _binary_content(
    kind: str, data: object, mime: object, uri: str | None
) -> dict[str, object | None]:
    encoded = _string(data, "binary_content")
    mime_type = _string(mime, "mime_type")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise WorkerProtocolError("invalid_binary_content") from exc
    if not decoded or len(decoded) > MAX_CONTENT_BYTES:
        raise WorkerProtocolError("binary_content_out_of_bounds")
    return {
        "kind": kind,
        "text": None,
        "mime_type": mime_type,
        "uri": uri,
        "data_digest": f"sha-256:{hashlib.sha256(decoded).hexdigest()}",
        "data_base64": encoded,
        "size_bytes": len(decoded),
    }


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise WorkerProtocolError(f"invalid_{field}")
    return value


def _exact(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise WorkerProtocolError("invalid_fields")


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value.encode("utf-8")) > 1_048_576
    ):
        raise WorkerProtocolError(f"invalid_{field}")
    return value


def _request_id(value: object) -> str:
    result = _string(value, "request_id")
    if _REQUEST_ID.fullmatch(result) is None:
        raise WorkerProtocolError("invalid_request_id")
    return result


def _absolute(value: str) -> str:
    if not os.path.isabs(value):
        raise WorkerProtocolError("path_not_absolute")
    return value


def _positive_number(value: object, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise WorkerProtocolError(f"invalid_{field}")
    return float(value)


def _write_all(payload: bytes) -> None:
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
