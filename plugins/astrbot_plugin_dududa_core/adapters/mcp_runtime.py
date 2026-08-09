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

from ..course import ICourseClient, LegacyICourseClient
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
) -> tuple[ICourseClient | LegacyICourseClient, str, str]:
    requested = str(config.get("icourse_mcp_mode", "unified")).strip().lower()
    if requested not in {"unified", "legacy"}:
        raise ValueError("icourse_mcp_mode must be unified or legacy")
    if requested == "legacy":
        return LegacyICourseClient(), "legacy", "operator_selected_legacy"
    directory = Path(config.get("mcp_registry_dir", registry_directory))
    python = Path(config.get("mcp_worker_python", worker_python))
    if not directory.is_absolute() or not python.is_absolute():
        return LegacyICourseClient(), "legacy", "unified_path_not_absolute"
    if not directory.is_dir() or not python.is_file():
        return LegacyICourseClient(), "legacy", "unified_infrastructure_missing"
    try:
        registry = ConfigMcpServerRegistry(directory)
        snapshot = registry.acquire_snapshot()
        definition = registry.resolve_server(snapshot, "icourse")
        if not definition.enabled:
            return LegacyICourseClient(), "legacy", "icourse_definition_disabled"
        factory = SubprocessMcpV2SessionFactory(
            python,
            secret_resolver or RejectingMcpSecretResolver(),
            environment_provider or AllowlistedEnvironmentProvider(),
        )
        unified = ManagedUnifiedMcpClient(
            registry,
            factory,
            JsonSchemaMcpValidator(),
        )
    except BaseException:
        return LegacyICourseClient(), "legacy", "unified_composition_invalid"
    return ICourseClient(unified), "unified", "unified_ready"
