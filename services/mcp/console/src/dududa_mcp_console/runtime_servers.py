from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from dududa.errors import DududaError
from dududa.mcp import ConfigMcpServerRegistry

_REQUEST_FIELDS = frozenset(
    {
        "serverId",
        "displayName",
        "enabled",
        "transport",
        "protocolMode",
        "endpoint",
        "secretRefs",
        "allowedTools",
        "deniedTools",
        "timeoutsSeconds",
        "retry",
        "circuit",
        "maximumConcurrency",
        "schemaTtlSeconds",
        "configRevision",
    }
)
_REQUIRED_REQUEST_FIELDS = frozenset(
    {"serverId", "transport", "endpoint", "allowedTools"}
)
_STDIO_ENDPOINT_FIELDS = frozenset({"command", "args", "cwd", "envAllowlist"})
_HTTP_ENDPOINT_FIELDS = frozenset({"url", "allowedHosts"})
_SECRET_REF_FIELDS = frozenset({"secretId", "target", "targetName"})
_TIMEOUT_FIELDS = frozenset(
    {"connect", "discovery", "call", "maximumCall", "close"}
)
_RETRY_FIELDS = frozenset({"maximumAttempts", "baseDelayMs"})
_CIRCUIT_FIELDS = frozenset(
    {"failureThreshold", "failureWindowSeconds", "openDurationSeconds"}
)
_SERVER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

_DEFAULT_TIMEOUTS = {
    "connect": 10,
    "discovery": 10,
    "call": 30,
    "maximumCall": 60,
    "close": 5,
}
_DEFAULT_RETRY = {"maximumAttempts": 1, "baseDelayMs": 100}
_DEFAULT_CIRCUIT = {
    "failureThreshold": 3,
    "failureWindowSeconds": 60,
    "openDurationSeconds": 30,
}


class RuntimeServerOverlay:
    """Persistent runtime definitions plus a resolved single-directory Registry."""

    def __init__(
        self,
        repository_directory: Path,
        overlay_directory: Path,
        *,
        revision_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository_directory = Path(repository_directory)
        self.overlay_directory = Path(overlay_directory)
        self.installed_directory = self.overlay_directory / "installed"
        self.metadata_directory = self.overlay_directory / "metadata"
        self.registry_directory = self.overlay_directory / "registry"
        self._revision_factory = revision_factory or (lambda: uuid.uuid4().hex)
        self.installed_directory.mkdir(parents=True, exist_ok=True)
        self.metadata_directory.mkdir(parents=True, exist_ok=True)
        self.registry_directory.mkdir(parents=True, exist_ok=True)

        repository = ConfigMcpServerRegistry(self.repository_directory)
        self._repository_ids = frozenset(
            item.server_id for item in repository.acquire_snapshot().definitions
        )
        self._materialize_registry()

    def origin(self, server_id: str) -> str:
        return "repository" if server_id in self._repository_ids else "runtime"

    def display_name(self, server_id: str) -> str:
        path = self.metadata_directory / f"{server_id}.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return server_id
        value = document.get("displayName") if isinstance(document, dict) else None
        return value if isinstance(value, str) and value.strip() else server_id

    def install(self, request: Mapping[str, Any]) -> dict[str, Any]:
        requested_name = request.get("displayName")
        if requested_name is not None and (
            not isinstance(requested_name, str)
            or not requested_name.strip()
            or len(requested_name.encode("utf-8")) > 128
        ):
            raise ValueError("invalid_mcp_server_display_name")
        document = build_server_document(request, revision=self._new_revision())
        server_id = str(document["server_id"])
        if _SERVER_ID.fullmatch(server_id) is None:
            raise ValueError("invalid_mcp_server_id")
        if server_id in self._repository_ids:
            raise ValueError("repository_mcp_server_cannot_be_replaced")
        target = self.installed_directory / f"{server_id}.json"
        if target.exists() or (self.registry_directory / target.name).exists():
            raise ValueError("mcp_server_already_exists")

        encoded = json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        self._validate_candidate(target.name, encoded)
        _atomic_write(target, encoded)
        try:
            _atomic_write(self.registry_directory / target.name, encoded)
            metadata = json.dumps(
                {"displayName": requested_name.strip() if requested_name else server_id},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            _atomic_write(self.metadata_directory / target.name, metadata)
        except Exception:
            target.unlink(missing_ok=True)
            (self.registry_directory / target.name).unlink(missing_ok=True)
            raise
        return document

    def rollback(self, server_id: str) -> None:
        if server_id in self._repository_ids:
            return
        (self.installed_directory / f"{server_id}.json").unlink(missing_ok=True)
        (self.registry_directory / f"{server_id}.json").unlink(missing_ok=True)
        (self.metadata_directory / f"{server_id}.json").unlink(missing_ok=True)

    def _materialize_registry(self) -> None:
        repository_files = _definition_files(self.repository_directory, allow_empty=False)
        installed_files = _definition_files(self.installed_directory, allow_empty=True)
        duplicate = set(repository_files) & set(installed_files)
        if duplicate:
            raise ValueError("runtime_mcp_server_conflicts_with_repository")
        sources = {**repository_files, **installed_files}
        for current in self.registry_directory.iterdir():
            if current.name.startswith("."):
                continue
            if not current.is_file() or current.is_symlink() or current.suffix != ".json":
                raise ValueError("invalid_runtime_mcp_registry_entry")
            if current.name not in sources:
                current.unlink()
        for name, source in sources.items():
            _atomic_write(self.registry_directory / name, source.read_bytes())
        ConfigMcpServerRegistry(self.registry_directory)

    def _validate_candidate(self, filename: str, encoded: bytes) -> None:
        with TemporaryDirectory(dir=self.overlay_directory) as temporary:
            candidate = Path(temporary)
            for name, source in _definition_files(
                self.registry_directory,
                allow_empty=False,
            ).items():
                (candidate / name).write_bytes(source.read_bytes())
            (candidate / filename).write_bytes(encoded)
            try:
                ConfigMcpServerRegistry(candidate)
            except DududaError as exc:
                raise ValueError(exc.info.code) from None

    def _new_revision(self) -> str:
        value = self._revision_factory()
        if not isinstance(value, str) or not value or any(item.isspace() for item in value):
            raise ValueError("invalid_runtime_mcp_revision")
        return f"runtime-{value}"


def build_server_document(
    request: Mapping[str, Any],
    *,
    revision: str,
) -> dict[str, Any]:
    document = _object(request, "invalid_mcp_server_install_request")
    keys = frozenset(document)
    if not _REQUIRED_REQUEST_FIELDS <= keys or not keys <= _REQUEST_FIELDS:
        raise ValueError("invalid_mcp_server_install_fields")

    transport = document["transport"]
    endpoint = _object(document["endpoint"], "invalid_mcp_endpoint")
    if transport == "stdio":
        _exact_fields(endpoint, _STDIO_ENDPOINT_FIELDS, "invalid_mcp_stdio_endpoint")
        projected_endpoint = {
            "command": endpoint["command"],
            "args": endpoint["args"],
            "cwd": endpoint["cwd"],
            "env_allowlist": endpoint["envAllowlist"],
        }
    elif transport == "streamable_http":
        _exact_fields(endpoint, _HTTP_ENDPOINT_FIELDS, "invalid_mcp_http_endpoint")
        projected_endpoint = {
            "url": endpoint["url"],
            "allowed_hosts": endpoint["allowedHosts"],
        }
    else:
        raise ValueError("invalid_mcp_transport")

    secret_refs = document.get("secretRefs", [])
    if not isinstance(secret_refs, list):
        raise ValueError("invalid_mcp_secret_refs")  # noqa: TRY004 - HTTP 400 contract.
    projected_refs = []
    for item in secret_refs:
        reference = _object(item, "invalid_mcp_secret_ref")
        _exact_fields(reference, _SECRET_REF_FIELDS, "invalid_mcp_secret_ref")
        projected_refs.append(
            {
                "secret_id": reference["secretId"],
                "target": reference["target"],
                "target_name": reference["targetName"],
            }
        )

    timeouts = _defaults_object(
        document.get("timeoutsSeconds"),
        _DEFAULT_TIMEOUTS,
        _TIMEOUT_FIELDS,
        "invalid_mcp_timeouts",
    )
    retry = _defaults_object(
        document.get("retry"),
        _DEFAULT_RETRY,
        _RETRY_FIELDS,
        "invalid_mcp_retry",
    )
    circuit = _defaults_object(
        document.get("circuit"),
        _DEFAULT_CIRCUIT,
        _CIRCUIT_FIELDS,
        "invalid_mcp_circuit",
    )
    result = {
        "schema_version": 1,
        "server_id": document["serverId"],
        "enabled": document.get("enabled", True),
        "transport": transport,
        "protocol_mode": document.get("protocolMode", "auto"),
        "endpoint": projected_endpoint,
        "secret_refs": projected_refs,
        "allowed_tools": document["allowedTools"],
        "denied_tools": document.get("deniedTools", []),
        "timeouts_seconds": {
            "connect": timeouts["connect"],
            "discovery": timeouts["discovery"],
            "call": timeouts["call"],
            "maximum_call": timeouts["maximumCall"],
            "close": timeouts["close"],
        },
        "retry": {
            "maximum_attempts": retry["maximumAttempts"],
            "base_delay_ms": retry["baseDelayMs"],
        },
        "circuit": {
            "failure_threshold": circuit["failureThreshold"],
            "failure_window_seconds": circuit["failureWindowSeconds"],
            "open_duration_seconds": circuit["openDurationSeconds"],
        },
        "maximum_concurrency": document.get("maximumConcurrency", 1),
        "schema_ttl_seconds": document.get("schemaTtlSeconds", 300),
        "config_revision": document.get("configRevision", revision),
    }
    # The strict Core Registry owns value, URL, path, allowlist and timeout checks.
    return result


def _definition_files(directory: Path, *, allow_empty: bool) -> dict[str, Path]:
    try:
        entries = tuple(directory.iterdir())
    except OSError as exc:
        raise ValueError("runtime_mcp_directory_unavailable") from exc
    result: dict[str, Path] = {}
    for item in entries:
        if item.name.startswith("."):
            continue
        if item.suffix != ".json" or not item.is_file() or item.is_symlink():
            raise ValueError("invalid_runtime_mcp_registry_entry")
        result[item.name] = item
    if not result and not allow_empty:
        raise ValueError("runtime_mcp_registry_empty")
    return result


def _atomic_write(path: Path, value: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _object(value: object, error_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(error_code)
    return value


def _exact_fields(value: Mapping[str, Any], fields: frozenset[str], error_code: str) -> None:
    if frozenset(value) != fields:
        raise ValueError(error_code)


def _defaults_object(
    value: object,
    defaults: Mapping[str, Any],
    fields: frozenset[str],
    error_code: str,
) -> dict[str, Any]:
    if value is None:
        return dict(defaults)
    document = _object(value, error_code)
    if not frozenset(document) <= fields:
        raise ValueError(error_code)
    return {**defaults, **document}
