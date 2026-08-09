from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.contracts.canonical import canonical_json_bytes
from dududa.domain.primitives import DigestString, JsonValue
from dududa.mcp.contracts import (
    McpCallContext,
    McpContentBlock,
    McpContentKind,
    McpDispatchState,
    McpHttpEndpoint,
    McpSecretTarget,
    McpServerDefinition,
    McpStdioEndpoint,
    McpToolDescriptor,
    McpTransportFailureKind,
    McpTransportPhase,
    McpTransportToolResult,
)
from dududa.ports.mcp import (
    McpCallerContext,
    McpEnvironmentProvider,
    McpSecretResolver,
    McpTransportError,
)

_PROTOCOL_VERSION = 1
_MAX_LINE_BYTES = 2_097_152
_WORKER_MODULE = "dududa_unified_mcp_worker"
_PROCESS_RECORD_MAX_BYTES = 4096


@dataclass(slots=True)
class _ServerProcessControl:
    temporary_directory: object
    record_path: Path
    nonce: str
    process_group_id: int | None = None

    @classmethod
    def create(cls) -> _ServerProcessControl:
        temporary = TemporaryDirectory(prefix="dududa-mcp-process-")
        directory = Path(temporary.name)
        return cls(
            temporary_directory=temporary,
            record_path=directory / "server.json",
            nonce=secrets.token_hex(16),
        )

    def payload(self) -> dict[str, str]:
        return {"path": str(self.record_path), "nonce": self.nonce}

    async def capture(self, timeout: float) -> int | None:
        if self.process_group_id is not None:
            return self.process_group_id
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, timeout)
        while True:
            try:
                payload = self.record_path.read_bytes()
            except FileNotFoundError:
                payload = b""
            except OSError:
                payload = b""
            if payload:
                group = _parse_process_record(payload, self.nonce)
                if group is not None:
                    self.process_group_id = group
                    return group
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.01, remaining))

    def cleanup(self) -> None:
        cleanup = getattr(self.temporary_directory, "cleanup", None)
        if callable(cleanup):
            cleanup()


def _parse_process_record(payload: bytes, nonce: str) -> int | None:
    if len(payload) > _PROCESS_RECORD_MAX_BYTES:
        return None
    try:
        document = _strict_json(payload)
        value = _object(document, "process_record")
        _exact_fields(value, {"v", "nonce", "pid", "pgid"}, "process_record")
        pid = value["pid"]
        pgid = value["pgid"]
        if (
            value["v"] != 1
            or value["nonce"] != nonce
            or type(pid) is not int
            or type(pgid) is not int
            or pid <= 1
            or pgid != pid
        ):
            return None
        return pgid
    except BaseException:
        return None


@dataclass(slots=True)
class _PendingRequest:
    future: asyncio.Future[object]
    phase: McpTransportPhase
    dispatch_state: McpDispatchState


class SubprocessMcpV2SessionFactory:
    def __init__(
        self,
        worker_python: Path,
        secret_resolver: McpSecretResolver,
        environment_provider: McpEnvironmentProvider,
        *,
        worker_module: str = _WORKER_MODULE,
        worker_environment: Mapping[str, str] | None = None,
    ) -> None:
        python = Path(worker_python)
        if not python.is_absolute():
            raise ValueError("worker_python must be absolute")
        if not isinstance(secret_resolver, McpSecretResolver):
            raise TypeError("secret_resolver must implement McpSecretResolver")
        if not isinstance(environment_provider, McpEnvironmentProvider):
            raise TypeError(
                "environment_provider must implement McpEnvironmentProvider"
            )
        if not isinstance(worker_module, str) or not worker_module.strip():
            raise ValueError("worker_module must be non-empty")
        environment = dict(worker_environment or {})
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or "\x00" in key
            or "\x00" in value
            for key, value in environment.items()
        ):
            raise ValueError("invalid worker environment")
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        self._worker_python = python
        self._secret_resolver = secret_resolver
        self._environment_provider = environment_provider
        self._worker_module = worker_module
        self._worker_environment = environment

    async def open(
        self,
        definition: McpServerDefinition,
        generation: int,
        *,
        call: McpCallerContext,
    ) -> SubprocessMcpV2Session:
        endpoint_failure = False
        try:
            endpoint = await self._endpoint_payload(definition, call)
        except asyncio.CancelledError:
            raise
        except BaseException:
            endpoint_failure = True
        if endpoint_failure:
            raise McpTransportError(
                McpTransportFailureKind.UNAVAILABLE,
                "connection_material_unavailable",
                phase=McpTransportPhase.CONNECT,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
        process_control = (
            _ServerProcessControl.create()
            if isinstance(definition.endpoint, McpStdioEndpoint)
            else None
        )
        process = None
        spawn_cancelled = False
        try:
            process = await asyncio.create_subprocess_exec(
                str(self._worker_python),
                "-m",
                self._worker_module,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._worker_environment,
                start_new_session=os.name == "posix",
                limit=_MAX_LINE_BYTES + 1,
            )
        except asyncio.CancelledError:
            spawn_cancelled = True
        except BaseException:
            pass
        if process is None:
            if process_control is not None:
                process_control.cleanup()
            if spawn_cancelled:
                raise asyncio.CancelledError()
            raise McpTransportError(
                McpTransportFailureKind.UNAVAILABLE,
                "worker_start_failed",
                phase=McpTransportPhase.CONNECT,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
        session = SubprocessMcpV2Session(
            definition.server_id,
            generation,
            process,
            process_control=process_control,
            close_timeout_seconds=definition.timeouts.close.total_seconds(),
        )
        try:
            await session.initialize(
                {
                    "transport": definition.transport.value,
                    "protocol_mode": definition.protocol_mode.value,
                    "endpoint": endpoint,
                    "process_control": (
                        None if process_control is None else process_control.payload()
                    ),
                    "read_timeout_seconds": definition.timeouts.maximum_call.total_seconds(),
                }
            )
        except BaseException:
            try:
                await session.abort()
            except BaseException:
                pass
            raise
        return session

    async def _endpoint_payload(
        self,
        definition: McpServerDefinition,
        call: McpCallerContext,
    ) -> dict[str, object]:
        secrets: dict[tuple[McpSecretTarget, str], str] = {}
        for reference in definition.secret_refs:
            value = await self._secret_resolver.resolve(reference, call=call)
            if not isinstance(value, str) or not value or "\x00" in value:
                raise McpTransportError(
                    McpTransportFailureKind.UNAVAILABLE,
                    "secret_resolution_failed",
                    phase=McpTransportPhase.CONNECT,
                    dispatch_state=McpDispatchState.NOT_DISPATCHED,
                )
            secrets[(reference.target, reference.target_name)] = value
        endpoint = definition.endpoint
        if isinstance(endpoint, McpStdioEndpoint):
            selected = dict(self._environment_provider.select(endpoint.env_allowlist))
            if set(selected) - set(endpoint.env_allowlist) or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or "\x00" in key
                or "\x00" in value
                for key, value in selected.items()
            ):
                raise McpTransportError(
                    McpTransportFailureKind.INTERNAL,
                    "environment_provider_violation",
                    phase=McpTransportPhase.CONNECT,
                    dispatch_state=McpDispatchState.NOT_DISPATCHED,
                )
            for (target, name), value in secrets.items():
                if target is not McpSecretTarget.ENV or name in selected:
                    raise McpTransportError(
                        McpTransportFailureKind.INTERNAL,
                        "secret_target_conflict",
                        phase=McpTransportPhase.CONNECT,
                        dispatch_state=McpDispatchState.NOT_DISPATCHED,
                    )
                selected[name] = value
            return {
                "command": endpoint.command,
                "args": list(endpoint.args),
                "cwd": endpoint.cwd,
                "env": selected,
            }
        if not isinstance(endpoint, McpHttpEndpoint):
            raise McpTransportError(
                McpTransportFailureKind.INTERNAL,
                "endpoint_type_invalid",
                phase=McpTransportPhase.CONNECT,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
        headers: dict[str, str] = {}
        for (target, name), value in secrets.items():
            if target is not McpSecretTarget.HEADER or name.lower() in {
                item.lower() for item in headers
            }:
                raise McpTransportError(
                    McpTransportFailureKind.INTERNAL,
                    "secret_target_conflict",
                    phase=McpTransportPhase.CONNECT,
                    dispatch_state=McpDispatchState.NOT_DISPATCHED,
                )
            headers[name] = value
        return {"url": endpoint.url, "headers": headers}


class SubprocessMcpV2Session:
    def __init__(
        self,
        server_id: str,
        generation: int,
        process: asyncio.subprocess.Process,
        *,
        process_control: _ServerProcessControl | None = None,
        close_timeout_seconds: float = 5.0,
    ) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise ValueError("worker process pipes are required")
        self._server_id = server_id
        self._generation = generation
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._stderr = process.stderr
        self._process_control = process_control
        self._close_timeout_seconds = max(0.1, float(close_timeout_seconds))
        self._pending: dict[str, _PendingRequest] = {}
        self._auxiliary_tasks: set[asyncio.Task[object]] = set()
        self._counter = 0
        self._write_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._closing = False
        self._closed = False
        self._terminal = False
        self._reader_task = asyncio.create_task(self._read_responses())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def is_closed(self) -> bool:
        return (
            self._closing
            or self._closed
            or self._terminal
            or self._process.returncode is not None
        )

    async def initialize(self, payload: Mapping[str, object]) -> None:
        await self._request(
            "open",
            payload,
            phase=McpTransportPhase.CONNECT,
            dispatch_state=McpDispatchState.NOT_DISPATCHED,
        )

    async def discover(
        self,
        *,
        call: McpCallerContext,
    ) -> tuple[McpToolDescriptor, ...]:
        result = await self._request(
            "discover",
            {},
            phase=McpTransportPhase.DISCOVERY,
            dispatch_state=McpDispatchState.NOT_DISPATCHED,
        )
        document = _object(result, "discovery_result")
        _exact_fields(document, {"tools"}, "discovery_result")
        raw_tools = document["tools"]
        if not isinstance(raw_tools, list):
            raise _protocol_error("invalid_tool_list", McpTransportPhase.DISCOVERY)
        try:
            return tuple(
                McpToolDescriptor(
                    schema_version=1,
                    name=_string(item, "name"),
                    description=_string(item, "description", allow_empty=True),
                    input_schema=_mapping(item, "input_schema"),
                    output_schema=(
                        None
                        if _field(item, "output_schema") is None
                        else _mapping(item, "output_schema")
                    ),
                    annotations=_mapping(item, "annotations"),
                )
                for item in raw_tools
            )
        except McpTransportError:
            raise
        except BaseException as exc:
            raise _protocol_error(
                "invalid_tool_descriptor", McpTransportPhase.DISCOVERY
            ) from exc

    async def call_tool(
        self,
        tool_name: str,
        arguments: JsonValue,
        *,
        call: McpCallContext,
    ) -> McpTransportToolResult:
        result = await self._request(
            "call",
            {"tool_name": tool_name, "arguments": _plain_json(arguments)},
            phase=McpTransportPhase.CALL,
            dispatch_state=McpDispatchState.UNKNOWN,
        )
        document = _object(result, "call_result")
        _exact_fields(
            document,
            {"is_error", "structured_content", "content"},
            "call_result",
        )
        if type(document["is_error"]) is not bool or not isinstance(
            document["content"], list
        ):
            raise _protocol_error("invalid_call_result", McpTransportPhase.CALL)
        try:
            content = tuple(_content_block(item) for item in document["content"])
            structured = document["structured_content"]
            total_size = sum(item.size_bytes for item in content) + (
                0 if structured is None else len(canonical_json_bytes(structured))
            )
            return McpTransportToolResult(
                schema_version=1,
                is_error=document["is_error"],
                structured_content=structured,
                content=content,
                total_size_bytes=total_size,
            )
        except McpTransportError:
            raise
        except BaseException as exc:
            raise _protocol_error(
                "invalid_call_result", McpTransportPhase.CALL
            ) from exc

    async def close(self) -> None:
        await self._shutdown(graceful=True)

    async def abort(self) -> None:
        await self._shutdown(graceful=False)

    async def _shutdown(self, *, graceful: bool) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            self._fail_all(
                McpTransportError(
                    McpTransportFailureKind.CLOSED,
                    "worker_session_closing",
                    phase=McpTransportPhase.CLOSE,
                    dispatch_state=McpDispatchState.NOT_DISPATCHED,
                )
            )
            close_failure: McpTransportError | None = None
            cancelled = False
            try:
                if graceful and self._process.returncode is None:
                    graceful_timeout = min(
                        0.5,
                        max(0.05, self._close_timeout_seconds * 0.1),
                    )
                    try:
                        await asyncio.wait_for(
                            self._request(
                                "close",
                                {},
                                phase=McpTransportPhase.CLOSE,
                                dispatch_state=McpDispatchState.NOT_DISPATCHED,
                            ),
                            timeout=graceful_timeout,
                        )
                    except asyncio.CancelledError:
                        cancelled = True
                    except asyncio.TimeoutError:
                        close_failure = McpTransportError(
                            McpTransportFailureKind.TIMEOUT,
                            "worker_close_timeout",
                            phase=McpTransportPhase.CLOSE,
                            dispatch_state=McpDispatchState.NOT_DISPATCHED,
                        )
                    except McpTransportError as failure:
                        close_failure = failure
                    except BaseException:
                        close_failure = McpTransportError(
                            McpTransportFailureKind.INTERNAL,
                            "worker_close_failed",
                            phase=McpTransportPhase.CLOSE,
                            dispatch_state=McpDispatchState.NOT_DISPATCHED,
                        )
            finally:
                cleanup = asyncio.create_task(self._terminate_process())
                settled, cleanup_cancelled = await _settle_task(
                    cleanup,
                    self._close_timeout_seconds,
                )
                cancelled = cancelled or cleanup_cancelled
                cleanup_ok = False
                if settled:
                    try:
                        cleanup_ok = bool(cleanup.result())
                    except BaseException:
                        cleanup_ok = False
                else:
                    cleanup.cancel()
                    await _settle_task(cleanup, 0.25)
                for task in tuple(self._auxiliary_tasks):
                    task.cancel()
                    await _settle_task(task, 0.25)
                await _cancel_and_settle(self._reader_task)
                await _cancel_and_settle(self._stderr_task)
                self._fail_all(
                    McpTransportError(
                        McpTransportFailureKind.CLOSED,
                        "worker_session_closed",
                        phase=McpTransportPhase.CLOSE,
                        dispatch_state=McpDispatchState.NOT_DISPATCHED,
                    )
                )
                if cleanup_ok:
                    self._closed = True
                    close_failure = None
                    if self._process_control is not None:
                        self._process_control.cleanup()
                else:
                    close_failure = McpTransportError(
                        McpTransportFailureKind.UNAVAILABLE,
                        "worker_cleanup_incomplete",
                        phase=McpTransportPhase.CLOSE,
                        dispatch_state=McpDispatchState.NOT_DISPATCHED,
                    )
            if cancelled:
                raise asyncio.CancelledError()
            if close_failure is not None:
                raise close_failure

    async def _request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        phase: McpTransportPhase,
        dispatch_state: McpDispatchState,
    ) -> object:
        if (self.is_closed or self._terminal) and method != "close":
            raise McpTransportError(
                McpTransportFailureKind.CLOSED,
                "worker_session_closed",
                phase=phase,
                dispatch_state=dispatch_state,
            )
        self._counter += 1
        request_id = f"request-{self._counter}"
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _PendingRequest(future, phase, dispatch_state)
        try:
            await self._write(
                {
                    "v": _PROTOCOL_VERSION,
                    "id": request_id,
                    "method": method,
                    "params": dict(params),
                }
            )
            return await future
        except asyncio.CancelledError:
            await self._send_cancel(request_id)
            raise
        finally:
            self._pending.pop(request_id, None)

    async def _send_cancel(self, target_id: str) -> None:
        self._counter += 1
        task = asyncio.create_task(
            self._write(
                {
                    "v": _PROTOCOL_VERSION,
                    "id": f"cancel-{self._counter}",
                    "method": "cancel",
                    "params": {"target_id": target_id},
                }
            )
        )
        self._auxiliary_tasks.add(task)
        task.add_done_callback(self._auxiliary_tasks.discard)
        try:
            settled, _ = await _settle_task(task, 0.25)
            if not settled:
                task.cancel()
                await _settle_task(task, 0.25)
        except BaseException:
            pass

    async def _write(self, message: Mapping[str, object]) -> None:
        try:
            payload = (
                json.dumps(
                    message,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8")
                + b"\n"
            )
        except (TypeError, ValueError) as exc:
            raise _protocol_error(
                "request_serialization_failed", McpTransportPhase.CALL
            ) from exc
        if len(payload) > _MAX_LINE_BYTES:
            raise _protocol_error("request_too_large", McpTransportPhase.CALL)
        async with self._write_lock:
            if self._stdin.is_closing():
                raise McpTransportError(
                    McpTransportFailureKind.UNAVAILABLE,
                    "worker_pipe_closed",
                    phase=McpTransportPhase.CALL,
                    dispatch_state=McpDispatchState.NOT_DISPATCHED,
                )
            self._stdin.write(payload)
            await self._stdin.drain()

    async def _read_responses(self) -> None:
        failure: McpTransportError | None = None
        try:
            while True:
                line = await self._stdout.readline()
                if not line:
                    break
                if len(line) > _MAX_LINE_BYTES:
                    failure = _protocol_error(
                        "response_too_large", McpTransportPhase.CONNECT
                    )
                    break
                response = _strict_json(line)
                self._publish_response(response)
        except asyncio.CancelledError:
            failure = McpTransportError(
                McpTransportFailureKind.CLOSED,
                "worker_reader_cancelled",
                phase=McpTransportPhase.CLOSE,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
        except BaseException:
            failure = _protocol_error(
                "worker_protocol_failed", McpTransportPhase.CONNECT
            )
        if failure is None:
            failure = McpTransportError(
                McpTransportFailureKind.UNAVAILABLE,
                "worker_exited",
                phase=McpTransportPhase.CONNECT,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
        self._terminal = True
        self._fail_all(failure)

    def _publish_response(self, value: object) -> None:
        document = _object(value, "worker_response")
        _exact_fields(
            document,
            {"v", "id", "ok", "result"}
            if document.get("ok") is True
            else {"v", "id", "ok", "error"},
            "worker_response",
        )
        if document["v"] != _PROTOCOL_VERSION or type(document["ok"]) is not bool:
            raise ValueError("invalid worker response")
        request_id = _string(document, "id")
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            return
        if document["ok"]:
            pending.future.set_result(document["result"])
            return
        pending.future.set_exception(_worker_error(document["error"], pending))

    async def _drain_stderr(self) -> None:
        try:
            while await self._stderr.read(8192):
                pass
        except asyncio.CancelledError:
            return
        except BaseException:
            return

    def _fail_all(self, failure: McpTransportError) -> None:
        for pending in tuple(self._pending.values()):
            if pending.future.done():
                continue
            dispatch = pending.dispatch_state
            pending.future.set_exception(
                McpTransportError(
                    failure.failure_kind,
                    failure.code,
                    phase=pending.phase,
                    dispatch_state=dispatch,
                )
            )

    async def _terminate_process(self) -> bool:
        if not self._stdin.is_closing():
            self._stdin.close()
            try:
                await asyncio.wait_for(self._stdin.wait_closed(), timeout=0.1)
            except BaseException:
                pass
        server_group = None
        if self._process_control is not None:
            server_group = await self._process_control.capture(0.05)
        _signal_process_group_id(server_group, signal.SIGTERM)
        _signal_process_group(self._process, signal.SIGTERM)
        if self._process.returncode is None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=0.25)
            except BaseException:
                pass
        if self._process_control is not None and server_group is None:
            server_group = await self._process_control.capture(0.25)
        _signal_process_group_id(server_group, signal.SIGKILL)
        _signal_process_group(self._process, signal.SIGKILL)
        if self._process.returncode is None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=0.5)
            except BaseException:
                pass
        if self._process_control is not None and server_group is None:
            server_group = await self._process_control.capture(0.25)
            _signal_process_group_id(server_group, signal.SIGKILL)
        worker_dead = self._process.returncode is not None
        server_dead = await _wait_process_group_dead(server_group, timeout=0.5)
        return worker_dead and server_dead


def _worker_error(value: object, pending: _PendingRequest) -> McpTransportError:
    document = _object(value, "worker_error")
    _exact_fields(document, {"kind", "code", "phase", "dispatch_state"}, "worker_error")
    _string(document, "code")
    kind = {
        "unavailable": McpTransportFailureKind.UNAVAILABLE,
        "timeout": McpTransportFailureKind.TIMEOUT,
        "cancelled": McpTransportFailureKind.CANCELLED,
        "protocol": McpTransportFailureKind.PROTOCOL,
        "closed": McpTransportFailureKind.CLOSED,
        "internal": McpTransportFailureKind.INTERNAL,
    }.get(_string(document, "kind"))
    dispatch = {
        "not_dispatched": McpDispatchState.NOT_DISPATCHED,
        "dispatched": McpDispatchState.DISPATCHED,
        "unknown": McpDispatchState.UNKNOWN,
    }.get(_string(document, "dispatch_state"))
    expected_phase = {
        McpTransportPhase.CONNECT: "open",
        McpTransportPhase.DISCOVERY: "discover",
        McpTransportPhase.CALL: "call",
        McpTransportPhase.CLOSE: "close",
    }[pending.phase]
    if kind is None or dispatch is None or _string(document, "phase") != expected_phase:
        raise ValueError("invalid worker error classification")
    stable_code = {
        McpTransportFailureKind.UNAVAILABLE: "worker_operation_unavailable",
        McpTransportFailureKind.TIMEOUT: "worker_operation_timeout",
        McpTransportFailureKind.CANCELLED: "worker_operation_cancelled",
        McpTransportFailureKind.PROTOCOL: "worker_protocol_rejected",
        McpTransportFailureKind.CLOSED: "worker_session_closed",
        McpTransportFailureKind.INTERNAL: "worker_internal_failure",
    }[kind]
    return McpTransportError(
        kind,
        stable_code,
        phase=pending.phase,
        dispatch_state=dispatch,
    )


def _content_block(value: object) -> McpContentBlock:
    document = _object(value, "content_block")
    _exact_fields(
        document,
        {
            "kind",
            "text",
            "mime_type",
            "uri",
            "data_digest",
            "data_base64",
            "size_bytes",
        },
        "content_block",
    )
    try:
        return McpContentBlock(
            schema_version=1,
            kind=McpContentKind(_string(document, "kind")),
            text=_optional_string(document["text"]),
            mime_type=_optional_string(document["mime_type"]),
            uri=_optional_string(document["uri"]),
            data_digest=(
                None
                if document["data_digest"] is None
                else DigestString(_string(document, "data_digest"))
            ),
            size_bytes=document["size_bytes"],
            data_base64=_optional_string(document["data_base64"], allow_empty=True),
        )
    except BaseException as exc:
        raise _protocol_error("invalid_content_block", McpTransportPhase.CALL) from exc


def _strict_json(payload: bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        payload,
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"invalid {field}")
    return value


def _exact_fields(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ValueError(f"invalid {field} fields")


def _field(value: object, name: str) -> object:
    document = _object(value, "object")
    if name not in document:
        raise ValueError("missing field")
    return document[name]


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    item = _field(value, name) if isinstance(value, dict) else value
    if not isinstance(item, str) or (not allow_empty and not item):
        raise ValueError(f"invalid {name}")
    return item


def _optional_string(value: object, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    return _string(value, "optional_string", allow_empty=allow_empty)


def _mapping(value: object, name: str) -> Mapping[str, JsonValue]:
    item = _field(value, name)
    if not isinstance(item, dict):
        raise ValueError(f"invalid {name}")
    return item


def _plain_json(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _protocol_error(code: str, phase: McpTransportPhase) -> McpTransportError:
    return McpTransportError(
        McpTransportFailureKind.PROTOCOL,
        code,
        phase=phase,
        dispatch_state=(
            McpDispatchState.UNKNOWN
            if phase is McpTransportPhase.CALL
            else McpDispatchState.NOT_DISPATCHED
        ),
    )


async def _cancel_and_settle(task: asyncio.Task[object]) -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


async def _settle_task(
    task: asyncio.Task[object],
    timeout: float,
) -> tuple[bool, bool]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout)
    cancelled = False
    while not task.done():
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait((task,), timeout=remaining)
        except asyncio.CancelledError:
            cancelled = True
    if task.done():
        _consume_task_exception(task)
    return task.done(), cancelled


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except BaseException:
        pass


def _signal_process_group(
    process: asyncio.subprocess.Process, sig: signal.Signals
) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig is signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass


def _signal_process_group_id(
    process_group_id: int | None,
    sig: signal.Signals,
) -> None:
    if process_group_id is None or os.name != "posix":
        return
    try:
        os.killpg(process_group_id, sig)
    except (ProcessLookupError, PermissionError):
        pass


async def _wait_process_group_dead(
    process_group_id: int | None,
    *,
    timeout: float,
) -> bool:
    if process_group_id is None or os.name != "posix":
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout)
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.01, remaining))
