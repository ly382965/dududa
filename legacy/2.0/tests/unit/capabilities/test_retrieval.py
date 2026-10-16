from __future__ import annotations

import itertools
import unittest
from datetime import timedelta
from decimal import Decimal

from dududa.capabilities.contracts import (
    CapabilityCatalogSnapshot,
    CapabilityEndpointHealth,
    CapabilityHealthSnapshot,
    CapabilityHealthStatus,
    CapabilityProviderDescriptor,
    CapabilityProviderHealth,
    CapabilityProviderKind,
    CapabilityQuery,
    CapabilityRetrievalRequest,
    McpCapabilityMapping,
)
from dududa.capabilities.digests import (
    capability_catalog_digest,
    capability_health_snapshot_digest,
    capability_provider_descriptor_digest,
    capability_provider_health_digest,
    capability_query_digest,
    capability_retrieval_request_digest,
    mcp_capability_mapping_digest,
)
from dududa.capabilities.registry import (
    InMemoryCapabilityProviderRegistry,
    InMemoryCapabilityRegistry,
)
from dududa.capabilities.retrieval import DeterministicCapabilityRetriever
from dududa.domain.capability import (
    CapabilityDefinition,
    CostHint,
    LatencyHint,
    capability_definition_digest,
)
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ConversationType,
    PrivacyLevel,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    SideEffect,
    TraceContext,
)
from dududa.mcp.contracts import McpOperationSemantics
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)

from tests.unit.capabilities.test_contracts import NOW, catalog_values
from tests.unit.capabilities.test_registry import (
    FakeProvider,
    SchemaValidator,
    catalog_fixture,
)


class StaticHealthRegistry:
    def __init__(self, value: CapabilityHealthSnapshot) -> None:
        self.value = value
        self.calls = 0

    async def snapshot(self, catalog, *, call):
        self.calls += 1
        return self.value


class RecordingAuthorization:
    def __init__(self, policy: RoleAuthorizationPolicy) -> None:
        self.policy = policy
        self.requests = []

    async def decide(self, request, *, call):
        self.requests.append(request)
        return await self.policy.decide(request, call=call)

    def verify(self, decision, *, at=None):
        return self.policy.verify(decision, at=at)


def revised_definition(base: CapabilityDefinition, **changes) -> CapabilityDefinition:
    values = {
        "schema_version": base.schema_version,
        "capability_id": base.capability_id,
        "name": base.name,
        "description": base.description,
        "category": base.category,
        "provider": base.provider,
        "input_schema": base.input_schema,
        "output_schema": base.output_schema,
        "risk_level": base.risk_level,
        "privacy_level": base.privacy_level,
        "allowed_contexts": base.allowed_contexts,
        "required_permissions": base.required_permissions,
        "cost_hint": base.cost_hint,
        "latency_hint": base.latency_hint,
        "tags": base.tags,
        "idempotency": base.idempotency,
        "side_effects": base.side_effects,
        "enabled": base.enabled,
    }
    values.update(changes)
    return CapabilityDefinition(
        definition_digest=capability_definition_digest(values),
        **values,
    )


def mapping_for(
    definition: CapabilityDefinition,
    *,
    enabled: bool = True,
) -> McpCapabilityMapping:
    values = {
        "schema_version": 1,
        "capability_id": definition.capability_id,
        "capability_definition_digest": definition.definition_digest,
        "server_id": "icourse",
        "tool_name": "search_courses",
        "expected_input_schema_digest": capability_query_digest(
            {
                "schema_version": 1,
                "intent_ids": (),
                "natural_language_goal": "schema",
                "entity_terms": (),
                "required_output_schema": None,
                "preferred_categories": (),
                "excluded_side_effects": frozenset(),
                "maximum_risk_level": RiskLevel.LOW,
            }
        ),
        "expected_output_schema_digest": capability_query_digest(
            {
                "schema_version": 1,
                "intent_ids": (),
                "natural_language_goal": "output",
                "entity_terms": (),
                "required_output_schema": None,
                "preferred_categories": (),
                "excluded_side_effects": frozenset(),
                "maximum_risk_level": RiskLevel.LOW,
            }
        ),
        "semantics": McpOperationSemantics.READ_ONLY,
        "fixed_arguments": {},
        "argument_mapping_revision": "identity-v1",
        "result_mapping_revision": "structured-content-v1",
        "enabled": enabled,
    }
    return McpCapabilityMapping(
        mapping_digest=mcp_capability_mapping_digest(values),
        **values,
    )


def catalog_for(
    definitions: tuple[CapabilityDefinition, ...],
    *,
    mapping_enabled: bool = True,
):
    source, _, _ = catalog_fixture()
    definitions = tuple(sorted(definitions, key=lambda item: item.capability_id))
    descriptor_values = {
        "schema_version": 1,
        "provider": definitions[0].provider,
        "kind": CapabilityProviderKind.MCP,
        "capability_ids": frozenset(item.capability_id for item in definitions),
    }
    descriptor = CapabilityProviderDescriptor(
        descriptor_digest=capability_provider_descriptor_digest(descriptor_values),
        **descriptor_values,
    )
    mappings = tuple(mapping_for(item, enabled=mapping_enabled) for item in definitions)
    values = catalog_values(
        definitions,
        source.schema_documents,
        (descriptor,),
        mappings,
    )
    snapshot = CapabilityCatalogSnapshot(
        snapshot_id="capability-catalog:retrieval",
        catalog_digest=capability_catalog_digest(values),
        acquired_at=NOW,
        **values,
    )
    providers = InMemoryCapabilityProviderRegistry((FakeProvider(descriptor),))
    registry = InMemoryCapabilityRegistry(
        snapshot,
        schema_validator=SchemaValidator(),
        provider_registry=providers,
        clock=lambda: NOW,
    )
    return registry, snapshot


def health_for(
    catalog: CapabilityCatalogSnapshot,
    *,
    status: CapabilityHealthStatus = CapabilityHealthStatus.HEALTHY,
) -> CapabilityHealthSnapshot:
    endpoints = tuple(
        CapabilityEndpointHealth(
            schema_version=1,
            capability_id=item.capability_id,
            definition_digest=item.definition_digest,
            status=status,
            reason_codes=("fixture",),
        )
        for item in catalog.definitions
    )
    provider_values = {
        "schema_version": 1,
        "provider": catalog.provider_descriptors[0].provider,
        "status": status,
        "capabilities": endpoints,
        "observed_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    provider = CapabilityProviderHealth(
        health_digest=capability_provider_health_digest(provider_values),
        **provider_values,
    )
    values = {
        "schema_version": 1,
        "providers": (provider,),
        "observed_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    return CapabilityHealthSnapshot(
        snapshot_id="capability-health:retrieval",
        snapshot_digest=capability_health_snapshot_digest(values),
        **values,
    )


def authorization_for(definitions: tuple[CapabilityDefinition, ...]):
    permissions = frozenset(
        permission
        for definition in definitions
        for permission in definition.required_permissions
    )
    constraint = AuthorizationConstraint(
        resource_types=frozenset({"capability"}),
        resource_ids=frozenset({"*"}),
        capability_ids=frozenset({"*"}),
        allow_without_capability=False,
    )
    counter = itertools.count()
    policy = RoleAuthorizationPolicy(
        AuthorizationPolicyConfig(
            policy_revision="policy-v1",
            role_permissions={"member": permissions},
            role_constraints={
                "member": {permission: constraint for permission in permissions}
            },
        ),
        clock=lambda: NOW,
        id_factory=lambda: f"decision-{next(counter)}",
    )
    return RecordingAuthorization(policy)


def retrieval_call(
    *,
    tool_steps: int = 4,
    cost_units: Decimal = Decimal(10),
) -> PortCallContext:
    return PortCallContext(
        run_id="retrieval-run",
        trace=TraceContext("retrieval-trace"),
        deadline=NOW + timedelta(minutes=1),
        cancellation=NeverCancelled(),
        budget=RuntimeBudget(0, tool_steps, 0, 0, 0, cost_units),
        policy_snapshot_id="policy-v1",
    )


def request_for(
    definition: CapabilityDefinition,
    *,
    available: bool = True,
    classification: PrivacyLevel = PrivacyLevel.PUBLIC,
    maximum_risk: RiskLevel = RiskLevel.LOW,
    excluded: frozenset[SideEffect] = frozenset(
        {SideEffect.EXTERNAL_WRITE, SideEffect.MESSAGE_SEND}
    ),
    maximum_latency_ms: int = 1_000,
    limit: int = 8,
) -> CapabilityRetrievalRequest:
    query_values = {
        "schema_version": 1,
        "intent_ids": ("course.search",),
        "natural_language_goal": "搜索 database 课程评价",
        "entity_terms": ("database",),
        "required_output_schema": None,
        "preferred_categories": (definition.category,),
        "excluded_side_effects": excluded,
        "maximum_risk_level": maximum_risk,
    }
    query = CapabilityQuery(
        query_digest=capability_query_digest(query_values),
        **query_values,
    )
    actor = Actor("qq", "bot", "user", frozenset({RoleId("member")}))
    scope = ConversationScope(
        "qq",
        "bot",
        ConversationType.GROUP,
        "group",
        "group",
        "dududa",
    )
    values = {
        "schema_version": 1,
        "query": query,
        "actor": actor,
        "conversation_scope": scope,
        "data_classification": classification,
        "available_input_schemas": (definition.input_schema,) if available else (),
        "maximum_latency_ms": maximum_latency_ms,
        "limit": limit,
    }
    return CapabilityRetrievalRequest(
        request_digest=capability_retrieval_request_digest(values),
        **values,
    )


async def run_retrieval(
    definitions: tuple[CapabilityDefinition, ...],
    request: CapabilityRetrievalRequest,
    *,
    health_status: CapabilityHealthStatus = CapabilityHealthStatus.HEALTHY,
    mapping_enabled: bool = True,
    call: PortCallContext | None = None,
    provider_cap: int | None = 4,
    category_cap: int | None = 4,
):
    registry, catalog = catalog_for(definitions, mapping_enabled=mapping_enabled)
    authorization = authorization_for(definitions)
    retriever_kwargs = {}
    if provider_cap is not None:
        retriever_kwargs["provider_cap"] = provider_cap
    if category_cap is not None:
        retriever_kwargs["category_cap"] = category_cap
    retriever = DeterministicCapabilityRetriever(
        registry,
        StaticHealthRegistry(health_for(catalog, status=health_status)),
        authorization,
        authorization,
        clock=lambda: NOW,
        **retriever_kwargs,
    )
    result = await retriever.retrieve(request, call=call or retrieval_call())
    return result, authorization


class CapabilityRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_caps_include_all_notifai_capabilities(self) -> None:
        _, base, _ = catalog_fixture()
        definitions = tuple(
            revised_definition(
                base,
                capability_id=f"notifai.notices.fixture{index}.v1",
                category="campus.notifications",
                provider=base.provider,
                name=f"NotifAI notice capability {index}",
                description="Read a public campus notice.",
                tags=frozenset({"campus", "notifications", "notifai"}),
            )
            for index in range(7)
        )
        result, _ = await run_retrieval(
            definitions,
            request_for(definitions[0], limit=8),
            provider_cap=None,
            category_cap=None,
        )
        self.assertEqual(len(result.candidates), 7)

    async def test_eligible_candidate_uses_one_exact_request_per_permission(
        self,
    ) -> None:
        _, base, _ = catalog_fixture()
        item = revised_definition(
            base,
            required_permissions=frozenset(
                {"capability.icourse.read", "capability.course.search"}
            ),
        )
        result, authorization = await run_retrieval(
            (item,),
            request_for(item),
        )
        self.assertEqual(
            tuple(candidate.capability_id for candidate in result.candidates),
            (item.capability_id,),
        )
        self.assertEqual(len(authorization.requests), 2)
        self.assertEqual(
            {str(request.action) for request in authorization.requests},
            item.required_permissions,
        )
        self.assertTrue(
            all(
                request.resource.resource_id == item.capability_id
                and request.resource.resource_type == "capability"
                for request in authorization.requests
            )
        )

    async def test_denial_returns_only_stable_empty_reason_without_definition_leak(
        self,
    ) -> None:
        _, item, _ = catalog_fixture()
        registry, catalog = catalog_for((item,))
        denied = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                policy_revision="policy-v1",
                role_permissions={"member": frozenset()},
            ),
            clock=lambda: NOW,
        )
        retriever = DeterministicCapabilityRetriever(
            registry,
            StaticHealthRegistry(health_for(catalog)),
            denied,
            denied,
            clock=lambda: NOW,
        )
        result = await retriever.retrieve(request_for(item), call=retrieval_call())
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.reason_codes, ("no_eligible_capability",))
        self.assertNotIn(item.capability_id, repr(result))

    async def test_fixed_eligibility_filters_fail_closed(self) -> None:
        _, base, _ = catalog_fixture()
        cases = (
            ("disabled", revised_definition(base, enabled=False), {}, {}),
            (
                "context",
                revised_definition(
                    base,
                    allowed_contexts=frozenset({ConversationType.PRIVATE}),
                ),
                {},
                {},
            ),
            (
                "privacy",
                base,
                {"classification": PrivacyLevel.RESTRICTED},
                {},
            ),
            (
                "risk",
                revised_definition(base, risk_level=RiskLevel.HIGH),
                {},
                {},
            ),
            (
                "side-effect",
                revised_definition(
                    base,
                    side_effects=frozenset({SideEffect.NETWORK_READ}),
                ),
                {"excluded": frozenset({SideEffect.NETWORK_READ})},
                {},
            ),
            ("input", base, {"available": False}, {}),
            (
                "latency",
                revised_definition(base, latency_hint=LatencyHint(500, 2_000)),
                {"maximum_latency_ms": 1_000},
                {},
            ),
            (
                "cost",
                revised_definition(base, cost_hint=CostHint(20)),
                {},
                {"call": retrieval_call(cost_units=Decimal(10))},
            ),
            (
                "health",
                base,
                {},
                {"health_status": CapabilityHealthStatus.DEGRADED},
            ),
            (
                "mapping",
                base,
                {},
                {"mapping_enabled": False},
            ),
        )
        for name, item, request_changes, run_changes in cases:
            with self.subTest(name=name):
                result, _ = await run_retrieval(
                    (item,),
                    request_for(item, **request_changes),
                    **run_changes,
                )
                self.assertEqual(result.candidates, ())
                self.assertEqual(
                    result.reason_codes,
                    ("no_eligible_capability",),
                )

    async def test_stable_ranking_and_provider_category_caps(self) -> None:
        _, base, _ = catalog_fixture()
        definitions = tuple(
            revised_definition(
                base,
                capability_id=f"fixture.course.{index}.read.v1",
                name="Cached course lookup",
                description="Read one approved cached course record.",
                tags=frozenset({"course", "cached"}),
            )
            for index in range(6)
        )
        request = request_for(definitions[0], limit=8)
        result, _ = await run_retrieval(definitions, request)
        self.assertEqual(len(result.candidates), 4)
        self.assertEqual(
            tuple(item.capability_id for item in result.candidates),
            tuple(sorted(item.capability_id for item in definitions)[:4]),
        )

        category_limited, _ = await run_retrieval(
            definitions,
            request,
            provider_cap=20,
            category_cap=2,
        )
        self.assertEqual(len(category_limited.candidates), 2)


if __name__ == "__main__":
    unittest.main()
