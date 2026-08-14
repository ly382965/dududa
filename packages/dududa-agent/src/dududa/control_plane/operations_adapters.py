from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dududa.ports.capabilities import CapabilityRegistry
from dududa.ports.context import ServiceCallContext
from dududa.ports.mcp import McpServerRegistry
from dududa.ports.models import (
    ModelOperationalStateRegistry,
    ModelRoutingRegistry,
)

from .operations import (
    OperationalEvidenceMode,
    OperationalFact,
    OperationalProjection,
    OperationalScope,
    OperationalStatus,
    OperationalSurface,
)


class ModelRouterOperationalProjectionProvider:
    surface = OperationalSurface.MODEL_ROUTER

    def __init__(
        self,
        routing: ModelRoutingRegistry,
        operational: ModelOperationalStateRegistry,
    ) -> None:
        self._routing = routing
        self._operational = operational

    async def project(
        self,
        scope: OperationalScope,
        *,
        call: ServiceCallContext,
    ) -> OperationalProjection:
        del call
        routing = self._routing.acquire_snapshot()
        operational = self._operational.acquire_snapshot()
        enabled_endpoints = sum(
            endpoint.enabled
            for provider in routing.provider_descriptors
            for endpoint in provider.endpoints
        )
        facts: list[OperationalFact] = [
            OperationalFact(
                1,
                "model.catalog",
                "模型路由目录",
                OperationalStatus.READY if enabled_endpoints else OperationalStatus.OFF,
                routing.catalog_revision,
                (
                    f"providers={len(routing.provider_descriptors)};"
                    f"enabled_endpoints={enabled_endpoints};"
                    f"route_policies={len(routing.route_policies)}"
                ),
                (),
                routing.acquired_at,
            )
        ]
        health_by_provider = {
            health.provider_id: health for health in operational.provider_health
        }
        projection_reasons: list[str] = []
        active_statuses: list[OperationalStatus] = []
        for provider in routing.provider_descriptors:
            enabled = tuple(endpoint for endpoint in provider.endpoints if endpoint.enabled)
            health = health_by_provider.get(provider.provider_id)
            if not enabled:
                status = OperationalStatus.OFF
                reasons = ("model_provider_disabled",)
                observed_at = routing.acquired_at
                revision = provider.revision.config_revision
            elif health is None:
                status = OperationalStatus.DEGRADED
                reasons = ("model_provider_health_not_cached",)
                observed_at = operational.acquired_at
                revision = provider.revision.config_revision
            else:
                status = _model_health_status(health.status)
                reasons = _health_reasons(
                    health.reason_codes,
                    status=status,
                    prefix="model_provider",
                )
                observed_at = health.checked_at
                revision = health.snapshot_revision
            if enabled:
                active_statuses.append(status)
                projection_reasons.extend(reasons)
            load_samples = sum(
                item.sample_count
                for item in operational.endpoint_load
                if item.provider_id == provider.provider_id
            )
            facts.append(
                OperationalFact(
                    1,
                    f"model.provider:{provider.provider_id}",
                    f"模型 Provider {provider.provider_id}",
                    status,
                    revision,
                    (
                        f"enabled_endpoints={len(enabled)};"
                        f"observed_endpoints={0 if health is None else len(health.endpoints)};"
                        f"load_samples={load_samples}"
                    ),
                    reasons,
                    observed_at,
                )
            )
        projection_status = _active_projection_status(active_statuses)
        return OperationalProjection(
            1,
            self.surface,
            scope,
            f"{routing.snapshot_id}|{operational.snapshot_id}",
            OperationalEvidenceMode.OFFLINE,
            projection_status,
            tuple(facts),
            _unique(projection_reasons),
            max(routing.acquired_at, operational.acquired_at),
        )


class McpRegistryOperationalAdapter:
    def __init__(self, registry: McpServerRegistry) -> None:
        self._registry = registry

    def adapt(self) -> _OperationalFragment:
        mcp = self._registry.acquire_snapshot()
        enabled_servers = tuple(item for item in mcp.definitions if item.enabled)
        facts: list[OperationalFact] = [
            OperationalFact(
                1,
                "mcp.registry",
                "MCP Server Registry",
                OperationalStatus.READY
                if enabled_servers
                else OperationalStatus.OFF,
                mcp.registry_revision,
                (
                    f"servers={len(mcp.definitions)};"
                    f"enabled_servers={len(enabled_servers)}"
                ),
                (),
                mcp.acquired_at,
            )
        ]
        reasons: list[str] = []
        for server in mcp.definitions:
            if server.enabled:
                status = OperationalStatus.DEGRADED
                fact_reasons = ("mcp_health_not_cached",)
                reasons.extend(fact_reasons)
            else:
                status = OperationalStatus.OFF
                fact_reasons = ("mcp_server_disabled",)
            facts.append(
                OperationalFact(
                    1,
                    f"mcp.server:{server.server_id}",
                    f"MCP Server {server.server_id}",
                    status,
                    server.config_revision,
                    (
                        f"transport={server.transport.value};"
                        f"allowed_tools={len(server.allowed_tools)};"
                        f"maximum_concurrency={server.maximum_concurrency}"
                    ),
                    fact_reasons,
                    mcp.acquired_at,
                )
            )
        return _OperationalFragment(
            mcp.snapshot_id,
            OperationalStatus.DEGRADED
            if enabled_servers
            else OperationalStatus.OFF,
            tuple(facts),
            _unique(reasons),
            mcp.acquired_at,
        )


class CapabilityCatalogOperationalAdapter:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def adapt(self) -> _OperationalFragment:
        capabilities = self._registry.acquire_snapshot()
        enabled_capabilities = tuple(
            item for item in capabilities.definitions if item.enabled
        )
        facts: list[OperationalFact] = []
        reasons: list[str] = []
        facts.append(
            OperationalFact(
                1,
                "capability.catalog",
                "Capability Catalog",
                OperationalStatus.READY
                if enabled_capabilities
                else OperationalStatus.OFF,
                capabilities.catalog_revision,
                (
                    f"capabilities={len(capabilities.definitions)};"
                    f"enabled_capabilities={len(enabled_capabilities)};"
                    f"mcp_mappings={len(capabilities.mcp_mappings)}"
                ),
                (),
                capabilities.acquired_at,
            )
        )
        definitions_by_provider = {
            descriptor.provider.provider_id: tuple(
                definition
                for definition in capabilities.definitions
                if definition.provider == descriptor.provider
            )
            for descriptor in capabilities.provider_descriptors
        }
        for descriptor in capabilities.provider_descriptors:
            definitions = definitions_by_provider[descriptor.provider.provider_id]
            enabled = tuple(item for item in definitions if item.enabled)
            if enabled:
                status = OperationalStatus.DEGRADED
                fact_reasons = ("capability_health_not_cached",)
                reasons.extend(fact_reasons)
            else:
                status = OperationalStatus.OFF
                fact_reasons = ("capability_provider_disabled",)
            facts.append(
                OperationalFact(
                    1,
                    f"capability.provider:{descriptor.provider.provider_id}",
                    f"Capability Provider {descriptor.provider.provider_id}",
                    status,
                    descriptor.provider.revision.config_revision,
                    (
                        f"kind={descriptor.kind.value};"
                        f"capabilities={len(definitions)};"
                        f"enabled_capabilities={len(enabled)}"
                    ),
                    fact_reasons,
                    capabilities.acquired_at,
                )
            )
        return _OperationalFragment(
            capabilities.snapshot_id,
            OperationalStatus.DEGRADED
            if enabled_capabilities
            else OperationalStatus.OFF,
            tuple(facts),
            _unique(reasons),
            capabilities.acquired_at,
        )


class McpCapabilityOperationalProjectionProvider:
    surface = OperationalSurface.MCP_CAPABILITY

    def __init__(
        self,
        mcp: McpServerRegistry,
        capabilities: CapabilityRegistry,
    ) -> None:
        self._mcp = McpRegistryOperationalAdapter(mcp)
        self._capabilities = CapabilityCatalogOperationalAdapter(capabilities)

    async def project(
        self,
        scope: OperationalScope,
        *,
        call: ServiceCallContext,
    ) -> OperationalProjection:
        del call
        mcp = self._mcp.adapt()
        capabilities = self._capabilities.adapt()
        active_statuses = [
            item.status
            for item in (mcp, capabilities)
            if item.status is not OperationalStatus.OFF
        ]
        return OperationalProjection(
            1,
            self.surface,
            scope,
            f"{mcp.revision}|{capabilities.revision}",
            OperationalEvidenceMode.OFFLINE,
            _active_projection_status(active_statuses),
            (*mcp.facts, *capabilities.facts),
            _unique([*mcp.reason_codes, *capabilities.reason_codes]),
            max(mcp.observed_at, capabilities.observed_at),
        )


@dataclass(frozen=True, slots=True)
class _OperationalFragment:
    revision: str
    status: OperationalStatus
    facts: tuple[OperationalFact, ...]
    reason_codes: tuple[str, ...]
    observed_at: datetime


def _model_health_status(status: object) -> OperationalStatus:
    value = getattr(status, "value", status)
    if value == "healthy":
        return OperationalStatus.READY
    if value == "unavailable":
        return OperationalStatus.UNAVAILABLE
    return OperationalStatus.DEGRADED


def _health_reasons(
    values: tuple[str, ...],
    *,
    status: OperationalStatus,
    prefix: str,
) -> tuple[str, ...]:
    reasons = list(values)
    if status not in {OperationalStatus.READY, OperationalStatus.OFF}:
        reasons.append(f"{prefix}_{status.value}")
    return _unique(reasons)


def _active_projection_status(
    statuses: list[OperationalStatus],
) -> OperationalStatus:
    if not statuses:
        return OperationalStatus.OFF
    if any(
        item in {OperationalStatus.DEGRADED, OperationalStatus.UNAVAILABLE}
        for item in statuses
    ):
        return OperationalStatus.DEGRADED
    return OperationalStatus.READY


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "CapabilityCatalogOperationalAdapter",
    "McpCapabilityOperationalProjectionProvider",
    "McpRegistryOperationalAdapter",
    "ModelRouterOperationalProjectionProvider",
]
