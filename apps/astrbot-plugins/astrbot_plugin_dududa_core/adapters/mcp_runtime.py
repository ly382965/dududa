from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dududa.mcp import (
    ConfigMcpServerRegistry,
    ManagedUnifiedMcpClient,
    SubprocessMcpV2SessionFactory,
)
from dududa.ports.mcp import UnifiedMcpClient

from ..course import ICourseClient, UnavailableICourseClient
from .mcp_schema import JsonSchemaMcpValidator


class RejectingMcpSecretResolver:
    """Current iCourse transport has no SecretRef; future resolvers are injected."""

    async def resolve(self, reference, *, call) -> str:
        raise RuntimeError("MCP secret resolver is not configured")


class AllowlistedEnvironmentProvider:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment

    def select(self, allowlist: frozenset[str]) -> Mapping[str, str]:
        source = os.environ if self._environment is None else self._environment
        return {key: source[key] for key in allowlist if key in source}


def build_icourse_client(
    config: Mapping[str, Any],
    *,
    registry_directory: Path,
    worker_python: Path,
    environment_provider: AllowlistedEnvironmentProvider | None = None,
    secret_resolver: RejectingMcpSecretResolver | None = None,
    unified_client: UnifiedMcpClient | None = None,
) -> tuple[ICourseClient | UnavailableICourseClient, str, str]:
    try:
        directory = Path(config.get("mcp_registry_dir", registry_directory))
        python = Path(config.get("mcp_worker_python", worker_python))
        if not directory.is_absolute() or not python.is_absolute():
            return _unavailable("unified_path_not_absolute")
        if not directory.is_dir() or not python.is_file():
            return _unavailable("unified_infrastructure_missing")
        registry = ConfigMcpServerRegistry(directory)
        snapshot = registry.acquire_snapshot()
        definition = registry.resolve_server(snapshot, "icourse")
        if not definition.enabled:
            return _unavailable("icourse_definition_disabled")
        unified = unified_client
        if unified is None:
            unified, reason = build_unified_mcp_client(
                config,
                registry_directory=registry_directory,
                worker_python=worker_python,
                environment_provider=environment_provider,
                secret_resolver=secret_resolver,
            )
            if unified is None:
                return _unavailable(reason)
        elif not isinstance(unified, UnifiedMcpClient):
            return _unavailable("unified_composition_invalid")
    except Exception:  # noqa: BLE001 - composition must not break unrelated commands
        return _unavailable("unified_composition_invalid")
    return (
        ICourseClient(unified, owns_client=unified_client is None),
        "unified",
        "unified_ready",
    )


def build_unified_mcp_client(
    config: Mapping[str, Any],
    *,
    registry_directory: Path,
    worker_python: Path,
    environment_provider: AllowlistedEnvironmentProvider | None = None,
    secret_resolver: RejectingMcpSecretResolver | None = None,
) -> tuple[UnifiedMcpClient | None, str]:
    try:
        directory = Path(config.get("mcp_registry_dir", registry_directory))
        python = Path(config.get("mcp_worker_python", worker_python))
        if not directory.is_absolute() or not python.is_absolute():
            return None, "unified_path_not_absolute"
        if not directory.is_dir() or not python.is_file():
            return None, "unified_infrastructure_missing"
        registry = ConfigMcpServerRegistry(directory)
        factory = SubprocessMcpV2SessionFactory(
            python,
            secret_resolver or RejectingMcpSecretResolver(),
            environment_provider or AllowlistedEnvironmentProvider(),
        )
        return (
            ManagedUnifiedMcpClient(
                registry,
                factory,
                JsonSchemaMcpValidator(),
            ),
            "unified_ready",
        )
    except Exception:  # noqa: BLE001 - composition must not break unrelated commands
        return None, "unified_composition_invalid"


def _unavailable(
    reason: str,
) -> tuple[UnavailableICourseClient, str, str]:
    return UnavailableICourseClient(reason), "unavailable", reason
