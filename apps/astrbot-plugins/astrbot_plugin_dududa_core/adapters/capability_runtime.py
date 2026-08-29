from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from dududa.capabilities import (
    ConfigCapabilityRegistry,
    DeterministicArgumentBinder,
    DeterministicBoundedCapabilityRuntime,
    DeterministicCapabilityRetriever,
    DeterministicToolPlanValidator,
    DeterministicToolResultValidator,
    GovernedToolExecutor,
    InMemoryCapabilityProviderRegistry,
    InMemoryToolInvocationLedger,
    McpCapabilityProvider,
    PollingCapabilityHealthRegistry,
    load_capability_catalog_snapshot,
)
from dududa.domain.primitives import ResourceUsage, SchemaRef
from dududa.ports.mcp import UnifiedMcpClient
from dududa.security.audit import InMemoryAuditSink
from dududa.security.limits import InMemoryBudgetLedger, InMemoryInteractionLimiter
from dududa.security.ports import AuthorizationDecisionVerifier, AuthorizationPolicy

from .capability_planner import (
    EntityQueryToolPlanner,
    supports_production_query_schema,
)
from .mcp_schema import JsonSchemaCapabilityValidator


@dataclass(frozen=True, slots=True)
class ProductionCapabilityAssembly:
    runtime: DeterministicBoundedCapabilityRuntime
    registry: ConfigCapabilityRegistry
    provider_registry: InMemoryCapabilityProviderRegistry
    categories: tuple[str, ...]
    input_schemas: tuple[SchemaRef, ...]


def build_production_capability_runtime(
    unified_client: UnifiedMcpClient,
    authorization: AuthorizationPolicy,
    authorization_verifier: AuthorizationDecisionVerifier,
    *,
    definitions_directory: Path,
    mappings_directory: Path,
    policy_revision: str,
    clock: Callable[[], datetime] | None = None,
) -> ProductionCapabilityAssembly:
    if not isinstance(policy_revision, str) or not policy_revision.strip():
        raise ValueError("invalid Capability Runtime policy revision")
    schema_validator = JsonSchemaCapabilityValidator()
    initial = load_capability_catalog_snapshot(
        definitions_directory,
        mappings_directory,
        snapshot_id="capability-catalog:production-startup",
        acquired_at=(clock() if clock is not None else datetime.now(timezone.utc)),
    )
    providers = tuple(
        McpCapabilityProvider.from_catalog(
            initial,
            descriptor,
            unified_client,
            schema_validator,
            clock=clock,
        )
        for descriptor in initial.provider_descriptors
    )
    provider_registry = InMemoryCapabilityProviderRegistry(providers)
    registry = ConfigCapabilityRegistry(
        definitions_directory,
        mappings_directory,
        schema_validator=schema_validator,
        provider_registry=provider_registry,
        clock=clock,
        initial_snapshot=initial,
    )
    health = PollingCapabilityHealthRegistry(provider_registry, clock=clock)
    retriever = DeterministicCapabilityRetriever(
        registry,
        health,
        authorization,
        authorization_verifier,
        clock=clock,
    )
    plan_validator = DeterministicToolPlanValidator(registry, schema_validator)
    executor = GovernedToolExecutor(
        registry,
        provider_registry,
        health,
        schema_validator,
        plan_validator,
        authorization,
        authorization_verifier,
        InMemoryInteractionLimiter(
            {"capability.invoke": 1_024},
            policy_revision=policy_revision,
            clock=clock,
        ),
        InMemoryBudgetLedger(
            ResourceUsage(
                schema_version=1,
                tool_steps=100_000,
                retries=100_000,
                cost_units=Decimal(1_000_000),
            ),
            policy_revision=policy_revision,
            clock=clock,
        ),
        InMemoryAuditSink(clock=clock),
        InMemoryToolInvocationLedger(clock=clock),
        clock=clock,
    )
    runtime = DeterministicBoundedCapabilityRuntime(
        registry,
        retriever,
        EntityQueryToolPlanner(
            registry,
            ignored_entity_terms=frozenset(
                {
                    "评课社区",
                    "iCourse",
                    "USTC评课社区",
                    "中国科大评课社区",
                    "二课",
                    "第二课堂",
                    "中国科大第二课堂",
                    "培养方案",
                    "培养计划",
                    "课程体系",
                    "中国科大培养方案",
                }
            ),
            clock=clock,
        ),
        plan_validator,
        DeterministicArgumentBinder(schema_validator),
        executor,
        DeterministicToolResultValidator(
            registry,
            schema_validator,
            plan_validator,
            clock=clock,
        ),
        clock=clock,
    )
    schema_documents = {
        document.schema_ref: document.document for document in initial.schema_documents
    }
    plannable = tuple(
        definition
        for definition in initial.definitions
        if definition.enabled
        and supports_production_query_schema(
            definition.capability_id,
            schema_documents[definition.input_schema],
        )
    )
    categories = tuple(sorted({definition.category for definition in plannable}))
    schemas = {
        (
            definition.input_schema.schema_id,
            definition.input_schema.schema_version,
            str(definition.input_schema.digest),
        ): definition.input_schema
        for definition in plannable
    }
    return ProductionCapabilityAssembly(
        runtime=runtime,
        registry=registry,
        provider_registry=provider_registry,
        categories=categories,
        input_schemas=tuple(schemas[key] for key in sorted(schemas)),
    )


__all__ = ["ProductionCapabilityAssembly", "build_production_capability_runtime"]
