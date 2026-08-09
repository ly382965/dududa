from __future__ import annotations

import asyncio
import json
import math
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext

from .contracts import (
    McpCircuitPolicy,
    McpHttpEndpoint,
    McpProtocolMode,
    McpRegistrySnapshot,
    McpRetryPolicy,
    McpSecretRef,
    McpSecretTarget,
    McpServerDefinition,
    McpStdioEndpoint,
    McpTimeoutPolicy,
    McpTransportKind,
)
from .digests import mcp_registry_digest, mcp_server_definition_digest

_DEFINITION_FIELDS = frozenset(
    {
        "schema_version",
        "server_id",
        "enabled",
        "transport",
        "protocol_mode",
        "endpoint",
        "secret_refs",
        "allowed_tools",
        "denied_tools",
        "timeouts_seconds",
        "retry",
        "circuit",
        "maximum_concurrency",
        "schema_ttl_seconds",
        "config_revision",
    }
)
_STDIO_FIELDS = frozenset({"command", "args", "cwd", "env_allowlist"})
_HTTP_FIELDS = frozenset({"url", "allowed_hosts"})
_SECRET_FIELDS = frozenset({"secret_id", "target", "target_name"})
_TIMEOUT_FIELDS = frozenset({"connect", "discovery", "call", "maximum_call", "close"})
_RETRY_FIELDS = frozenset({"maximum_attempts", "base_delay_ms"})
_CIRCUIT_FIELDS = frozenset(
    {"failure_threshold", "failure_window_seconds", "open_duration_seconds"}
)


class ConfigMcpServerRegistry:
    """Strict, atomic, last-known-good MCP Server configuration registry."""

    def __init__(
        self,
        directory: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        history_limit: int = 32,
    ) -> None:
        if type(history_limit) is not int or history_limit < 2:
            raise ValueError("history_limit must be at least two")
        self._directory = Path(directory)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._history_limit = history_limit
        initial = self._load_candidate()
        self._current = initial
        self._history: OrderedDict[str, McpRegistrySnapshot] = OrderedDict(
            ((initial.snapshot_id, initial),)
        )
        self._reload_lock = asyncio.Lock()

    @property
    def directory(self) -> Path:
        return self._directory

    def acquire_snapshot(self) -> McpRegistrySnapshot:
        return self._current

    def resolve_server(
        self,
        snapshot: McpRegistrySnapshot,
        server_id: str,
    ) -> McpServerDefinition:
        stored = self._history.get(snapshot.snapshot_id)
        if stored is None:
            raise validation_error("unknown_mcp_registry_snapshot")
        if stored != snapshot or stored.registry_digest != snapshot.registry_digest:
            raise validation_error("mcp_registry_snapshot_tampered")
        for definition in stored.definitions:
            if definition.server_id == server_id:
                return definition
        raise validation_error("mcp_server_not_found")

    async def reload(
        self,
        *,
        call: ServiceCallContext,
    ) -> McpRegistrySnapshot:
        now = self._now()
        _validate_reload_call(call, now)
        async with self._reload_lock:
            _validate_reload_call(call, self._now())
            candidate = self._load_candidate()
            current = self._current
            if candidate.registry_digest == current.registry_digest:
                return current
            self._current = candidate
            self._history[candidate.snapshot_id] = candidate
            self._history.move_to_end(candidate.snapshot_id)
            while len(self._history) > self._history_limit:
                self._history.popitem(last=False)
            return candidate

    def _load_candidate(self) -> McpRegistrySnapshot:
        unavailable = False
        try:
            entries = sorted(self._directory.iterdir(), key=lambda item: item.name)
        except OSError:
            unavailable = True
        if unavailable:
            raise error(
                "mcp_registry_unavailable",
                ErrorCategory.EXTERNAL,
                "service.unavailable",
                "registry_directory_unreadable",
            )
        unexpected = tuple(
            item.name
            for item in entries
            if not item.name.startswith(".")
            and (item.suffix != ".json" or not item.is_file() or item.is_symlink())
        )
        if unexpected:
            raise validation_error("invalid_mcp_registry_entry")
        paths = tuple(
            item
            for item in entries
            if not item.name.startswith(".") and item.suffix == ".json"
        )
        if not paths or len(paths) > 128:
            raise validation_error("invalid_mcp_registry_file_count")
        definitions = tuple(
            sorted(
                (_load_definition(path) for path in paths),
                key=lambda item: item.server_id,
            )
        )
        ids = tuple(item.server_id for item in definitions)
        if len(ids) != len(set(ids)):
            raise validation_error("duplicate_mcp_server_id")
        digest = mcp_registry_digest(definitions)
        return McpRegistrySnapshot(
            schema_version=1,
            snapshot_id=self._new_id("mcp-registry"),
            registry_revision=str(digest),
            registry_digest=digest,
            definitions=definitions,
            acquired_at=self._now(),
        )

    def _new_id(self, prefix: str) -> str:
        failed = False
        try:
            value = self._id_factory()
        except Exception:
            failed = True
            value = None
        if failed:
            raise error(
                "mcp_registry_id_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            )
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise validation_error("invalid_mcp_registry_id")
        return f"{prefix}:{value}"

    def _now(self) -> datetime:
        failed = False
        try:
            value = self._clock()
        except Exception:
            failed = True
            value = None
        if failed:
            raise error(
                "mcp_registry_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            )
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_mcp_registry_clock")
        return value


def _load_definition(path: Path) -> McpServerDefinition:
    invalid_json = False
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        invalid_json = True
    if invalid_json:
        raise validation_error("invalid_mcp_registry_json")
    document = _object(raw, "mcp_server_definition")
    _exact_fields(document, _DEFINITION_FIELDS, "mcp_server_definition")
    server_id = _string(document["server_id"], "server_id")
    if path.stem != server_id:
        raise validation_error("mcp_server_filename_mismatch")
    invalid_transport = False
    try:
        transport = McpTransportKind(document["transport"])
        protocol_mode = McpProtocolMode(document["protocol_mode"])
    except (TypeError, ValueError):
        invalid_transport = True
    if invalid_transport:
        raise validation_error("invalid_mcp_transport_configuration")
    endpoint = _parse_endpoint(document["endpoint"], transport)
    secret_refs = tuple(
        _parse_secret(item) for item in _array(document["secret_refs"], "secret_refs")
    )
    timeouts = _parse_timeouts(document["timeouts_seconds"])
    retry = _parse_retry(document["retry"])
    circuit = _parse_circuit(document["circuit"])
    values = {
        "schema_version": _integer(document["schema_version"], "schema_version"),
        "server_id": server_id,
        "enabled": _boolean(document["enabled"], "enabled"),
        "transport": transport,
        "protocol_mode": protocol_mode,
        "endpoint": endpoint,
        "secret_refs": secret_refs,
        "allowed_tools": frozenset(
            _string_array(document["allowed_tools"], "allowed_tools")
        ),
        "denied_tools": frozenset(
            _string_array(document["denied_tools"], "denied_tools")
        ),
        "timeouts": timeouts,
        "retry": retry,
        "circuit": circuit,
        "maximum_concurrency": _integer(
            document["maximum_concurrency"], "maximum_concurrency"
        ),
        "schema_ttl": timedelta(
            seconds=_number(document["schema_ttl_seconds"], "schema_ttl_seconds")
        ),
        "config_revision": _string(document["config_revision"], "config_revision"),
    }
    return McpServerDefinition(
        **values,
        definition_digest=mcp_server_definition_digest(values),
    )


def _parse_endpoint(
    value: object, transport: McpTransportKind
) -> McpStdioEndpoint | McpHttpEndpoint:
    endpoint = _object(value, "endpoint")
    if transport is McpTransportKind.STDIO:
        _exact_fields(endpoint, _STDIO_FIELDS, "stdio_endpoint")
        return McpStdioEndpoint(
            command=_string(endpoint["command"], "command"),
            args=tuple(_string_array(endpoint["args"], "args")),
            cwd=_string(endpoint["cwd"], "cwd"),
            env_allowlist=frozenset(
                _string_array(endpoint["env_allowlist"], "env_allowlist")
            ),
        )
    _exact_fields(endpoint, _HTTP_FIELDS, "http_endpoint")
    return McpHttpEndpoint(
        url=_string(endpoint["url"], "url"),
        allowed_hosts=frozenset(
            _string_array(endpoint["allowed_hosts"], "allowed_hosts")
        ),
    )


def _parse_secret(value: object) -> McpSecretRef:
    document = _object(value, "secret_ref")
    _exact_fields(document, _SECRET_FIELDS, "secret_ref")
    invalid_target = False
    try:
        target = McpSecretTarget(document["target"])
    except (TypeError, ValueError):
        invalid_target = True
    if invalid_target:
        raise validation_error("invalid_mcp_secret_target")
    return McpSecretRef(
        secret_id=_string(document["secret_id"], "secret_id"),
        target=target,
        target_name=_string(document["target_name"], "target_name"),
    )


def _parse_timeouts(value: object) -> McpTimeoutPolicy:
    document = _object(value, "timeouts_seconds")
    _exact_fields(document, _TIMEOUT_FIELDS, "timeouts_seconds")
    return McpTimeoutPolicy(
        **{
            name: timedelta(seconds=_number(document[name], name))
            for name in _TIMEOUT_FIELDS
        }
    )


def _parse_retry(value: object) -> McpRetryPolicy:
    document = _object(value, "retry")
    _exact_fields(document, _RETRY_FIELDS, "retry")
    return McpRetryPolicy(
        maximum_attempts=_integer(document["maximum_attempts"], "maximum_attempts"),
        base_delay=timedelta(
            milliseconds=_number(document["base_delay_ms"], "base_delay_ms")
        ),
    )


def _parse_circuit(value: object) -> McpCircuitPolicy:
    document = _object(value, "circuit")
    _exact_fields(document, _CIRCUIT_FIELDS, "circuit")
    return McpCircuitPolicy(
        failure_threshold=_integer(document["failure_threshold"], "failure_threshold"),
        failure_window=timedelta(
            seconds=_number(
                document["failure_window_seconds"], "failure_window_seconds"
            )
        ),
        open_duration=timedelta(
            seconds=_number(document["open_duration_seconds"], "open_duration_seconds")
        ),
    )


def _validate_reload_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_mcp_registry_call_context")
    cancellation_failed = False
    try:
        cancelled = call.cancellation.is_cancelled
    except Exception:
        cancellation_failed = True
        cancelled = False
    if cancellation_failed:
        raise error(
            "mcp_registry_cancellation_unavailable",
            ErrorCategory.INTERNAL,
            "service.unavailable",
        )
    if cancelled:
        raise error(
            "mcp_registry_reload_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if now >= call.deadline:
        raise error(
            "mcp_registry_reload_deadline",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise validation_error("duplicate_mcp_config_field")
        result[key] = value
    return result


def _object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise validation_error("invalid_mcp_config_object", field)
    if any(not isinstance(key, str) for key in value):
        raise validation_error("invalid_mcp_config_key", field)
    return value


def _array(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise validation_error("invalid_mcp_config_array", field)
    return tuple(value)


def _string_array(value: object, field: str) -> tuple[str, ...]:
    return tuple(_string(item, field) for item in _array(value, field))


def _exact_fields(
    value: Mapping[str, object], expected: frozenset[str], field: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise validation_error("invalid_mcp_config_fields", field)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_mcp_config_string", field)
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise validation_error("invalid_mcp_config_boolean", field)
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise validation_error("invalid_mcp_config_integer", field)
    return value


def _number(value: object, field: str) -> int | float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise validation_error("invalid_mcp_config_number", field)
    return value
