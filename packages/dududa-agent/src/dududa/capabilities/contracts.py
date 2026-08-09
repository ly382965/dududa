from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from dududa._compat import StrEnum
from dududa.contracts.canonical import (
    canonical_digest,
    canonical_json_bytes,
    canonical_schema_digest,
)
from dududa.domain.capability import (
    CapabilityDefinition,
    CostHint,
    Idempotency,
    LatencyHint,
    ProviderRef,
)
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    DigestString,
    JsonValue,
    PrivacyLevel,
    ResourceRef,
    ResourceUsage,
    RiskLevel,
    SchemaRef,
    SideEffect,
    freeze_json,
    require_aware,
    require_non_empty,
)
from dududa.errors import ErrorInfo, validation_error
from dududa.mcp.contracts import McpOperationSemantics
from dududa.security.digests import actor_digest, resource_digest, scope_digest
from dududa.security.models import AuthorizationDecision, AuthorizationEffect

from .revisions import (
    capability_catalog_revision,
    capability_mapping_revision,
    capability_provider_registry_revision,
)

MAX_CAPABILITY_DEFINITIONS = 256
MAX_CAPABILITY_CANDIDATES = 20
DEFAULT_TOOL_ATTEMPTS = 4
MAX_TOOL_ATTEMPTS = 8
MAX_SCHEMA_BYTES = 262_144
MAX_ARGUMENT_BYTES = 65_536
MAX_OBSERVATION_BYTES = 1_048_576
MAX_PLAN_STEPS = 8
MAX_SOURCE_REFS = 64
_MAX_IDENTIFIER_BYTES = 128
_MAX_REASON_CODES = 32
_MAX_GOAL_BYTES = 8_192
_MAX_DESCRIPTION_BYTES = 4_096
_MAX_COLLECTION_ITEMS = 256
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_DIGEST = re.compile(
    r"^dududa-c14n-v1:[a-z0-9][a-z0-9._:/-]*:v[1-9][0-9]*:"
    r"sha-256:[0-9a-f]{64}$"
)
_JSON_POINTER_TOKEN = re.compile(r"(?:[^~/]|~[01])*")


class CapabilityProviderKind(StrEnum):
    BUILTIN = "builtin"
    MCP = "mcp"
    WORKFLOW = "workflow"


class CapabilityHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ValidationAction(StrEnum):
    FINISH = "finish"
    CONTINUE = "continue"
    RETRY = "retry"
    CLARIFY = "clarify"
    ABORT = "abort"
    DEGRADE = "degrade"


class CapabilityRunStatus(StrEnum):
    COMPLETED = "completed"
    DEFERRED = "deferred"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolInvocationDisposition(StrEnum):
    ACQUIRED = "acquired"
    DUPLICATE_PENDING = "duplicate_pending"
    DUPLICATE_COMPLETED = "duplicate_completed"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class CapabilitySchemaDocument:
    schema_version: int
    schema_ref: SchemaRef
    document: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.schema_ref, SchemaRef):
            raise validation_error("invalid_capability_schema_ref")
        document = _mapping(
            self.document,
            "capability_schema_document",
            maximum_bytes=MAX_SCHEMA_BYTES,
        )
        expected = canonical_schema_digest(
            document,
            schema_id=self.schema_ref.schema_id,
            schema_version=self.schema_ref.schema_version,
        )
        if expected != self.schema_ref.digest:
            raise validation_error("capability_schema_digest_mismatch")
        object.__setattr__(self, "document", document)


@dataclass(frozen=True, slots=True)
class CapabilityProviderDescriptor:
    schema_version: int
    provider: ProviderRef
    kind: CapabilityProviderKind
    capability_ids: frozenset[str]
    descriptor_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_capability_provider")
        if not isinstance(self.kind, CapabilityProviderKind):
            raise validation_error("invalid_capability_provider_kind")
        capability_ids = _identifier_set(
            self.capability_ids,
            "provider_capability_ids",
            maximum_items=MAX_CAPABILITY_DEFINITIONS,
            required=True,
        )
        object.__setattr__(self, "capability_ids", capability_ids)
        _check_digest(
            self.descriptor_digest,
            {
                "schema_version": self.schema_version,
                "provider": self.provider,
                "kind": self.kind,
                "capability_ids": capability_ids,
            },
            domain="capability.provider-descriptor:v1",
            code="capability_provider_descriptor_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityEndpointHealth:
    schema_version: int
    capability_id: str
    definition_digest: DigestString
    status: CapabilityHealthStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.capability_id, "health_capability_id")
        _digest(self.definition_digest, "health_definition_digest")
        if not isinstance(self.status, CapabilityHealthStatus):
            raise validation_error("invalid_capability_health_status")
        object.__setattr__(
            self,
            "reason_codes",
            _strings(self.reason_codes, "health_reason_codes", required=False),
        )


@dataclass(frozen=True, slots=True)
class CapabilityProviderHealth:
    schema_version: int
    provider: ProviderRef
    status: CapabilityHealthStatus
    capabilities: tuple[CapabilityEndpointHealth, ...]
    observed_at: datetime
    expires_at: datetime
    health_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_capability_provider")
        if not isinstance(self.status, CapabilityHealthStatus):
            raise validation_error("invalid_capability_health_status")
        capabilities = _typed_tuple(
            self.capabilities,
            CapabilityEndpointHealth,
            "provider_health_capabilities",
            maximum=MAX_CAPABILITY_DEFINITIONS,
        )
        capability_ids = tuple(item.capability_id for item in capabilities)
        if capability_ids != tuple(sorted(capability_ids)) or len(
            capability_ids
        ) != len(set(capability_ids)):
            raise validation_error("invalid_provider_health_capability_order")
        _fresh_window(self.observed_at, self.expires_at, "provider_health")
        object.__setattr__(self, "capabilities", capabilities)
        _check_digest(
            self.health_digest,
            {
                "schema_version": self.schema_version,
                "provider": self.provider,
                "status": self.status,
                "capabilities": capabilities,
                "observed_at": self.observed_at,
                "expires_at": self.expires_at,
            },
            domain="capability.provider-health:v1",
            code="capability_provider_health_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityHealthSnapshot:
    schema_version: int
    snapshot_id: str
    snapshot_digest: DigestString
    providers: tuple[CapabilityProviderHealth, ...]
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.snapshot_id, "capability_health_snapshot_id")
        providers = _typed_tuple(
            self.providers,
            CapabilityProviderHealth,
            "capability_health_providers",
            maximum=128,
        )
        provider_ids = tuple(item.provider.provider_id for item in providers)
        if provider_ids != tuple(sorted(provider_ids)) or len(provider_ids) != len(
            set(provider_ids)
        ):
            raise validation_error("invalid_capability_health_provider_order")
        _fresh_window(self.observed_at, self.expires_at, "capability_health_snapshot")
        object.__setattr__(self, "providers", providers)
        _check_digest(
            self.snapshot_digest,
            {
                "schema_version": self.schema_version,
                "providers": providers,
                "observed_at": self.observed_at,
                "expires_at": self.expires_at,
            },
            domain="capability.health-snapshot:v1",
            code="capability_health_snapshot_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class McpCapabilityMapping:
    schema_version: int
    capability_id: str
    capability_definition_digest: DigestString
    server_id: str
    tool_name: str
    expected_input_schema_digest: DigestString
    expected_output_schema_digest: DigestString | None
    semantics: McpOperationSemantics
    fixed_arguments: Mapping[str, JsonValue]
    argument_mapping_revision: str
    result_mapping_revision: str
    enabled: bool
    mapping_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.capability_id, "mapping_capability_id")
        _digest(
            self.capability_definition_digest,
            "mapping_capability_definition_digest",
        )
        _identifier(self.server_id, "mapping_server_id")
        _identifier(self.tool_name, "mapping_tool_name")
        _digest(self.expected_input_schema_digest, "mapping_input_schema_digest")
        if self.expected_output_schema_digest is not None:
            _digest(
                self.expected_output_schema_digest,
                "mapping_output_schema_digest",
            )
        if not isinstance(self.semantics, McpOperationSemantics):
            raise validation_error("invalid_mapping_operation_semantics")
        if type(self.enabled) is not bool:
            raise validation_error("invalid_mapping_enabled")
        fixed_arguments = _mapping(
            self.fixed_arguments,
            "mapping_fixed_arguments",
            maximum_bytes=MAX_ARGUMENT_BYTES,
        )
        _identifier(self.argument_mapping_revision, "argument_mapping_revision")
        _identifier(self.result_mapping_revision, "result_mapping_revision")
        object.__setattr__(self, "fixed_arguments", fixed_arguments)
        _check_digest(
            self.mapping_digest,
            {
                "schema_version": self.schema_version,
                "capability_id": self.capability_id,
                "capability_definition_digest": self.capability_definition_digest,
                "server_id": self.server_id,
                "tool_name": self.tool_name,
                "expected_input_schema_digest": self.expected_input_schema_digest,
                "expected_output_schema_digest": self.expected_output_schema_digest,
                "semantics": self.semantics,
                "fixed_arguments": fixed_arguments,
                "argument_mapping_revision": self.argument_mapping_revision,
                "result_mapping_revision": self.result_mapping_revision,
                "enabled": self.enabled,
            },
            domain="capability.mcp-mapping:v1",
            code="mcp_capability_mapping_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    schema_version: int
    snapshot_id: str
    catalog_revision: str
    mapping_revision: str
    provider_registry_revision: str
    catalog_digest: DigestString
    definitions: tuple[CapabilityDefinition, ...]
    schema_documents: tuple[CapabilitySchemaDocument, ...]
    provider_descriptors: tuple[CapabilityProviderDescriptor, ...]
    mcp_mappings: tuple[McpCapabilityMapping, ...]
    acquired_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "snapshot_id",
            "catalog_revision",
            "mapping_revision",
            "provider_registry_revision",
        ):
            _identifier(getattr(self, field_name), field_name)
        require_aware(self.acquired_at, "catalog_acquired_at")
        definitions = _sorted_unique_objects(
            self.definitions,
            CapabilityDefinition,
            key=lambda item: item.capability_id,
            field="catalog_definitions",
            maximum=MAX_CAPABILITY_DEFINITIONS,
            required=True,
        )
        schemas = _sorted_unique_objects(
            self.schema_documents,
            CapabilitySchemaDocument,
            key=lambda item: (
                item.schema_ref.schema_id,
                item.schema_ref.schema_version,
            ),
            field="catalog_schema_documents",
            maximum=MAX_CAPABILITY_DEFINITIONS * 2,
            required=True,
        )
        providers = _sorted_unique_objects(
            self.provider_descriptors,
            CapabilityProviderDescriptor,
            key=lambda item: item.provider.provider_id,
            field="catalog_provider_descriptors",
            maximum=128,
            required=True,
        )
        mappings = _sorted_unique_objects(
            self.mcp_mappings,
            McpCapabilityMapping,
            key=lambda item: item.capability_id,
            field="catalog_mcp_mappings",
            maximum=MAX_CAPABILITY_DEFINITIONS,
            required=False,
        )
        _validate_catalog_bindings(definitions, schemas, providers, mappings)
        _validate_catalog_revisions(
            self.catalog_revision,
            self.mapping_revision,
            self.provider_registry_revision,
            definitions,
            schemas,
            providers,
            mappings,
        )
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(self, "schema_documents", schemas)
        object.__setattr__(self, "provider_descriptors", providers)
        object.__setattr__(self, "mcp_mappings", mappings)
        _check_digest(
            self.catalog_digest,
            {
                "schema_version": self.schema_version,
                "catalog_revision": self.catalog_revision,
                "mapping_revision": self.mapping_revision,
                "provider_registry_revision": self.provider_registry_revision,
                "definitions": definitions,
                "schema_documents": schemas,
                "provider_descriptors": providers,
                "mcp_mappings": mappings,
            },
            domain="capability.catalog:v1",
            code="capability_catalog_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityCatalogUpdate:
    schema_version: int
    expected_revision: str
    catalog_revision: str
    mapping_revision: str
    provider_registry_revision: str
    update_digest: DigestString
    definitions: tuple[CapabilityDefinition, ...]
    schema_documents: tuple[CapabilitySchemaDocument, ...]
    provider_descriptors: tuple[CapabilityProviderDescriptor, ...]
    mcp_mappings: tuple[McpCapabilityMapping, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "expected_revision",
            "catalog_revision",
            "mapping_revision",
            "provider_registry_revision",
        ):
            _identifier(getattr(self, field_name), field_name)
        definitions = _sorted_unique_objects(
            self.definitions,
            CapabilityDefinition,
            key=lambda item: item.capability_id,
            field="catalog_update_definitions",
            maximum=MAX_CAPABILITY_DEFINITIONS,
            required=True,
        )
        schemas = _sorted_unique_objects(
            self.schema_documents,
            CapabilitySchemaDocument,
            key=lambda item: (
                item.schema_ref.schema_id,
                item.schema_ref.schema_version,
            ),
            field="catalog_update_schemas",
            maximum=MAX_CAPABILITY_DEFINITIONS * 2,
            required=True,
        )
        providers = _sorted_unique_objects(
            self.provider_descriptors,
            CapabilityProviderDescriptor,
            key=lambda item: item.provider.provider_id,
            field="catalog_update_providers",
            maximum=128,
            required=True,
        )
        mappings = _sorted_unique_objects(
            self.mcp_mappings,
            McpCapabilityMapping,
            key=lambda item: item.capability_id,
            field="catalog_update_mappings",
            maximum=MAX_CAPABILITY_DEFINITIONS,
            required=False,
        )
        _validate_catalog_bindings(definitions, schemas, providers, mappings)
        _validate_catalog_revisions(
            self.catalog_revision,
            self.mapping_revision,
            self.provider_registry_revision,
            definitions,
            schemas,
            providers,
            mappings,
        )
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(self, "schema_documents", schemas)
        object.__setattr__(self, "provider_descriptors", providers)
        object.__setattr__(self, "mcp_mappings", mappings)
        _check_digest(
            self.update_digest,
            {
                "schema_version": self.schema_version,
                "expected_revision": self.expected_revision,
                "catalog_revision": self.catalog_revision,
                "mapping_revision": self.mapping_revision,
                "provider_registry_revision": self.provider_registry_revision,
                "definitions": definitions,
                "schema_documents": schemas,
                "provider_descriptors": providers,
                "mcp_mappings": mappings,
            },
            domain="capability.catalog-update:v1",
            code="capability_catalog_update_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityCatalogPublishReceipt:
    schema_version: int
    previous_revision: str
    catalog_revision: str
    snapshot_id: str
    catalog_digest: DigestString
    published_at: datetime
    receipt_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in ("previous_revision", "catalog_revision", "snapshot_id"):
            _identifier(getattr(self, field_name), field_name)
        _digest(self.catalog_digest, "published_catalog_digest")
        require_aware(self.published_at, "catalog_published_at")
        _check_digest(
            self.receipt_digest,
            {
                "schema_version": self.schema_version,
                "previous_revision": self.previous_revision,
                "catalog_revision": self.catalog_revision,
                "snapshot_id": self.snapshot_id,
                "catalog_digest": self.catalog_digest,
                "published_at": self.published_at,
            },
            domain="capability.catalog-publish-receipt:v1",
            code="capability_catalog_publish_receipt_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityQuery:
    schema_version: int
    query_digest: DigestString
    intent_ids: tuple[str, ...]
    natural_language_goal: str
    entity_terms: tuple[str, ...]
    required_output_schema: SchemaRef | None
    preferred_categories: tuple[str, ...]
    excluded_side_effects: frozenset[SideEffect]
    maximum_risk_level: RiskLevel

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        intents = _strings(
            self.intent_ids,
            "capability_query_intents",
            required=False,
            maximum=64,
        )
        goal = _bounded(
            self.natural_language_goal,
            "capability_query_goal",
            _MAX_GOAL_BYTES,
        )
        entities = _strings(
            self.entity_terms,
            "capability_query_entities",
            required=False,
            maximum=128,
            maximum_bytes=512,
        )
        categories = _strings(
            self.preferred_categories,
            "capability_query_categories",
            required=False,
            maximum=64,
        )
        if self.required_output_schema is not None and not isinstance(
            self.required_output_schema, SchemaRef
        ):
            raise validation_error("invalid_query_output_schema")
        excluded = frozenset(self.excluded_side_effects)
        if len(excluded) > len(SideEffect) or any(
            not isinstance(item, SideEffect) for item in excluded
        ):
            raise validation_error("invalid_query_excluded_side_effect")
        if not isinstance(self.maximum_risk_level, RiskLevel):
            raise validation_error("invalid_query_maximum_risk")
        object.__setattr__(self, "intent_ids", intents)
        object.__setattr__(self, "natural_language_goal", goal)
        object.__setattr__(self, "entity_terms", entities)
        object.__setattr__(self, "preferred_categories", categories)
        object.__setattr__(self, "excluded_side_effects", excluded)
        _check_digest(
            self.query_digest,
            {
                "schema_version": self.schema_version,
                "intent_ids": intents,
                "natural_language_goal": goal,
                "entity_terms": entities,
                "required_output_schema": self.required_output_schema,
                "preferred_categories": categories,
                "excluded_side_effects": excluded,
                "maximum_risk_level": self.maximum_risk_level,
            },
            domain="capability.query:v1",
            code="capability_query_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    schema_version: int
    capability_id: str
    definition_digest: DigestString
    name: str
    description: str
    category: str
    provider: ProviderRef
    input_schema: SchemaRef
    output_schema: SchemaRef
    risk_level: RiskLevel
    privacy_level: PrivacyLevel
    cost_hint: CostHint
    latency_hint: LatencyHint
    idempotency: Idempotency
    side_effects: frozenset[SideEffect]
    rank_score: int
    reason_codes: tuple[str, ...]
    candidate_digest: DigestString

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.capability_id, "candidate_capability_id")
        _digest(self.definition_digest, "candidate_definition_digest")
        _bounded(self.name, "candidate_name", 256)
        _bounded(self.description, "candidate_description", _MAX_DESCRIPTION_BYTES)
        _bounded(self.category, "candidate_category", 128)
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_candidate_provider")
        if not isinstance(self.input_schema, SchemaRef) or not isinstance(
            self.output_schema, SchemaRef
        ):
            raise validation_error("invalid_candidate_schema")
        if not isinstance(self.risk_level, RiskLevel) or not isinstance(
            self.privacy_level, PrivacyLevel
        ):
            raise validation_error("invalid_candidate_classification")
        if not isinstance(self.cost_hint, CostHint) or not isinstance(
            self.latency_hint, LatencyHint
        ):
            raise validation_error("invalid_candidate_hint")
        if not isinstance(self.idempotency, Idempotency):
            raise validation_error("invalid_candidate_idempotency")
        side_effects = frozenset(self.side_effects)
        if not side_effects or any(
            not isinstance(item, SideEffect) for item in side_effects
        ):
            raise validation_error("invalid_candidate_side_effect")
        if (
            type(self.rank_score) is not int
            or not -1_000_000 <= self.rank_score <= 1_000_000
        ):
            raise validation_error("invalid_candidate_rank_score")
        reasons = _strings(
            self.reason_codes,
            "candidate_reason_codes",
            required=True,
        )
        object.__setattr__(self, "side_effects", side_effects)
        object.__setattr__(self, "reason_codes", reasons)
        _check_digest(
            self.candidate_digest,
            {
                "schema_version": self.schema_version,
                "capability_id": self.capability_id,
                "definition_digest": self.definition_digest,
                "name": self.name,
                "description": self.description,
                "category": self.category,
                "provider": self.provider,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "risk_level": self.risk_level,
                "privacy_level": self.privacy_level,
                "cost_hint": self.cost_hint,
                "latency_hint": self.latency_hint,
                "idempotency": self.idempotency,
                "side_effects": side_effects,
                "rank_score": self.rank_score,
                "reason_codes": reasons,
            },
            domain="capability.candidate:v1",
            code="capability_candidate_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityRetrievalRequest:
    schema_version: int
    request_digest: DigestString
    query: CapabilityQuery
    actor: Actor
    conversation_scope: ConversationScope
    data_classification: PrivacyLevel
    available_input_schemas: tuple[SchemaRef, ...]
    maximum_latency_ms: int
    limit: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.query, CapabilityQuery):
            raise validation_error("invalid_capability_query")
        _identity_scope(self.actor, self.conversation_scope)
        if not isinstance(self.data_classification, PrivacyLevel):
            raise validation_error("invalid_retrieval_data_classification")
        schemas = _typed_tuple(
            self.available_input_schemas,
            SchemaRef,
            "available_input_schemas",
            maximum=64,
        )
        schema_keys = tuple(
            (item.schema_id, item.schema_version, item.digest) for item in schemas
        )
        if len(schema_keys) != len(set(schema_keys)):
            raise validation_error("duplicate_available_input_schema")
        if (
            type(self.maximum_latency_ms) is not int
            or not 0 <= self.maximum_latency_ms <= 600_000
        ):
            raise validation_error("invalid_retrieval_latency_limit")
        if (
            type(self.limit) is not int
            or not 1 <= self.limit <= MAX_CAPABILITY_CANDIDATES
        ):
            raise validation_error("invalid_capability_retrieval_limit")
        object.__setattr__(self, "available_input_schemas", schemas)
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "query": self.query,
                "actor": self.actor,
                "conversation_scope": self.conversation_scope,
                "data_classification": self.data_classification,
                "available_input_schemas": schemas,
                "maximum_latency_ms": self.maximum_latency_ms,
                "limit": self.limit,
            },
            domain="capability.retrieval-request:v1",
            code="capability_retrieval_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityRetrievalResult:
    schema_version: int
    result_digest: DigestString
    request_digest: DigestString
    query_digest: DigestString
    candidates: tuple[CapabilityCandidate, ...]
    catalog_snapshot_id: str
    catalog_digest: DigestString
    policy_revision: str
    health_snapshot_id: str
    health_snapshot_digest: DigestString
    retriever_revision: ComponentRevision
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.request_digest, "retrieval_request_digest")
        _digest(self.query_digest, "retrieval_query_digest")
        candidates = _typed_tuple(
            self.candidates,
            CapabilityCandidate,
            "retrieval_candidates",
            maximum=MAX_CAPABILITY_CANDIDATES,
        )
        ids = tuple(item.capability_id for item in candidates)
        if len(ids) != len(set(ids)):
            raise validation_error("duplicate_retrieval_candidate")
        expected_order = tuple(
            sorted(candidates, key=lambda item: (-item.rank_score, item.capability_id))
        )
        if candidates != expected_order:
            raise validation_error("unstable_retrieval_candidate_order")
        _identifier(self.catalog_snapshot_id, "retrieval_catalog_snapshot_id")
        _digest(self.catalog_digest, "retrieval_catalog_digest")
        _identifier(self.policy_revision, "retrieval_policy_revision")
        _identifier(self.health_snapshot_id, "retrieval_health_snapshot_id")
        _digest(self.health_snapshot_digest, "retrieval_health_snapshot_digest")
        if not isinstance(self.retriever_revision, ComponentRevision):
            raise validation_error("invalid_retriever_revision")
        reasons = _strings(
            self.reason_codes,
            "retrieval_reason_codes",
            required=True,
        )
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "reason_codes", reasons)
        _check_digest(
            self.result_digest,
            {
                "schema_version": self.schema_version,
                "request_digest": self.request_digest,
                "query_digest": self.query_digest,
                "candidates": candidates,
                "catalog_snapshot_id": self.catalog_snapshot_id,
                "catalog_digest": self.catalog_digest,
                "policy_revision": self.policy_revision,
                "health_snapshot_id": self.health_snapshot_id,
                "health_snapshot_digest": self.health_snapshot_digest,
                "retriever_revision": self.retriever_revision,
                "reason_codes": reasons,
            },
            domain="capability.retrieval-result:v1",
            code="capability_retrieval_result_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ObservationBinding:
    schema_version: int
    source_step_id: str
    source_json_pointer: str
    target_json_pointer: str

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.source_step_id, "binding_source_step_id")
        _json_pointer(self.source_json_pointer, "binding_source_pointer")
        _json_pointer(self.target_json_pointer, "binding_target_pointer")


@dataclass(frozen=True, slots=True)
class ArgumentTemplate:
    schema_version: int
    literal_template: Mapping[str, JsonValue]
    bindings: tuple[ObservationBinding, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        literal = _mapping(
            self.literal_template,
            "argument_literal_template",
            maximum_bytes=MAX_ARGUMENT_BYTES,
        )
        bindings = _typed_tuple(
            self.bindings,
            ObservationBinding,
            "argument_bindings",
            maximum=64,
        )
        targets = tuple(item.target_json_pointer for item in bindings)
        if len(targets) != len(set(targets)):
            raise validation_error("duplicate_argument_binding_target")
        object.__setattr__(self, "literal_template", literal)
        object.__setattr__(self, "bindings", bindings)


@dataclass(frozen=True, slots=True)
class ToolStep:
    schema_version: int
    step_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    arguments: ArgumentTemplate
    purpose: str
    depends_on: tuple[str, ...]
    expected_output_schema: SchemaRef

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.step_id, "tool_step_id")
        _identifier(self.logical_operation_id, "tool_logical_operation_id")
        _identifier(self.capability_id, "tool_step_capability_id")
        _digest(self.definition_digest, "tool_step_definition_digest")
        if not isinstance(self.arguments, ArgumentTemplate):
            raise validation_error("invalid_tool_argument_template")
        _bounded(self.purpose, "tool_step_purpose", 1_024)
        depends_on = _strings(
            self.depends_on,
            "tool_step_dependencies",
            required=False,
            maximum=MAX_PLAN_STEPS,
        )
        if self.step_id in depends_on:
            raise validation_error("tool_step_self_dependency")
        if not isinstance(self.expected_output_schema, SchemaRef):
            raise validation_error("invalid_tool_expected_output_schema")
        object.__setattr__(self, "depends_on", depends_on)


@dataclass(frozen=True, slots=True)
class ToolPlan:
    schema_version: int
    plan_id: str
    plan_digest: DigestString
    query_digest: DigestString
    retrieval_result_digest: DigestString
    steps: tuple[ToolStep, ...]
    completion_criteria: tuple[str, ...]
    planner_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.plan_id, "tool_plan_id")
        _digest(self.query_digest, "tool_plan_query_digest")
        _digest(self.retrieval_result_digest, "tool_plan_retrieval_digest")
        steps = _typed_tuple(
            self.steps,
            ToolStep,
            "tool_plan_steps",
            maximum=MAX_PLAN_STEPS,
            required=True,
        )
        step_ids = tuple(item.step_id for item in steps)
        logical_ids = tuple(item.logical_operation_id for item in steps)
        if len(step_ids) != len(set(step_ids)):
            raise validation_error("duplicate_tool_step_id")
        if len(logical_ids) != len(set(logical_ids)):
            raise validation_error("duplicate_tool_logical_operation_id")
        criteria = _strings(
            self.completion_criteria,
            "tool_completion_criteria",
            required=True,
            maximum=32,
            maximum_bytes=512,
        )
        if not isinstance(self.planner_revision, ComponentRevision):
            raise validation_error("invalid_tool_planner_revision")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "completion_criteria", criteria)
        _check_digest(
            self.plan_digest,
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "query_digest": self.query_digest,
                "retrieval_result_digest": self.retrieval_result_digest,
                "steps": steps,
                "completion_criteria": criteria,
                "planner_revision": self.planner_revision,
            },
            domain="capability.tool-plan:v1",
            code="tool_plan_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolPlanningRequest:
    schema_version: int
    request_digest: DigestString
    query: CapabilityQuery
    retrieval: CapabilityRetrievalResult
    prior_observations: tuple[ToolObservation, ...]
    remaining_attempts: int

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.query, CapabilityQuery) or not isinstance(
            self.retrieval, CapabilityRetrievalResult
        ):
            raise validation_error("invalid_tool_planning_input")
        if self.retrieval.query_digest != self.query.query_digest:
            raise validation_error("tool_planning_query_binding_mismatch")
        observations = _typed_tuple(
            self.prior_observations,
            ToolObservation,
            "planning_prior_observations",
            maximum=MAX_TOOL_ATTEMPTS,
        )
        if (
            type(self.remaining_attempts) is not int
            or not 1 <= self.remaining_attempts <= MAX_TOOL_ATTEMPTS
        ):
            raise validation_error("invalid_remaining_tool_attempts")
        object.__setattr__(self, "prior_observations", observations)
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "query": self.query,
                "retrieval": self.retrieval,
                "prior_observations": observations,
                "remaining_attempts": self.remaining_attempts,
            },
            domain="capability.tool-planning-request:v1",
            code="tool_planning_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolPlanValidationRequest:
    schema_version: int
    request_digest: DigestString
    query: CapabilityQuery
    retrieval: CapabilityRetrievalResult
    plan: ToolPlan
    maximum_attempts: int = DEFAULT_TOOL_ATTEMPTS

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.query, CapabilityQuery) or not isinstance(
            self.retrieval, CapabilityRetrievalResult
        ):
            raise validation_error("invalid_tool_plan_validation_input")
        if not isinstance(self.plan, ToolPlan):
            raise validation_error("invalid_tool_plan")
        if self.retrieval.query_digest != self.query.query_digest:
            raise validation_error("tool_plan_validation_query_mismatch")
        if self.plan.query_digest != self.query.query_digest:
            raise validation_error("tool_plan_query_binding_mismatch")
        if self.plan.retrieval_result_digest != self.retrieval.result_digest:
            raise validation_error("tool_plan_retrieval_binding_mismatch")
        if (
            type(self.maximum_attempts) is not int
            or not 1 <= self.maximum_attempts <= MAX_TOOL_ATTEMPTS
        ):
            raise validation_error("invalid_tool_plan_attempt_limit")
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "query": self.query,
                "retrieval": self.retrieval,
                "plan": self.plan,
                "maximum_attempts": self.maximum_attempts,
            },
            domain="capability.tool-plan-validation-request:v1",
            code="tool_plan_validation_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolPlanValidationResult:
    schema_version: int
    result_digest: DigestString
    request_digest: DigestString
    plan_digest: DigestString
    valid: bool
    reason_codes: tuple[str, ...]
    validator_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.request_digest, "plan_validation_request_digest")
        _digest(self.plan_digest, "validated_plan_digest")
        if type(self.valid) is not bool:
            raise validation_error("invalid_tool_plan_validation_flag")
        reasons = _strings(
            self.reason_codes,
            "tool_plan_validation_reasons",
            required=True,
        )
        if not isinstance(self.validator_revision, ComponentRevision):
            raise validation_error("invalid_tool_plan_validator_revision")
        object.__setattr__(self, "reason_codes", reasons)
        _check_digest(
            self.result_digest,
            {
                "schema_version": self.schema_version,
                "request_digest": self.request_digest,
                "plan_digest": self.plan_digest,
                "valid": self.valid,
                "reason_codes": reasons,
                "validator_revision": self.validator_revision,
            },
            domain="capability.tool-plan-validation-result:v1",
            code="tool_plan_validation_result_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ArgumentBindingRequest:
    schema_version: int
    request_digest: DigestString
    step: ToolStep
    accepted_observations: tuple[ToolObservation, ...]
    input_schema: CapabilitySchemaDocument
    fixed_arguments: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.step, ToolStep):
            raise validation_error("invalid_argument_binding_step")
        observations = _typed_tuple(
            self.accepted_observations,
            ToolObservation,
            "binding_accepted_observations",
            maximum=MAX_TOOL_ATTEMPTS,
        )
        if any(
            item.status is not ToolExecutionStatus.SUCCEEDED for item in observations
        ):
            raise validation_error("binding_observation_not_successful")
        if not isinstance(self.input_schema, CapabilitySchemaDocument):
            raise validation_error("invalid_binding_input_schema")
        fixed = _mapping(
            self.fixed_arguments,
            "binding_fixed_arguments",
            maximum_bytes=MAX_ARGUMENT_BYTES,
        )
        object.__setattr__(self, "accepted_observations", observations)
        object.__setattr__(self, "fixed_arguments", fixed)
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "step": self.step,
                "accepted_observations": observations,
                "input_schema": self.input_schema,
                "fixed_arguments": fixed,
            },
            domain="capability.argument-binding-request:v1",
            code="argument_binding_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ArgumentBindingResult:
    schema_version: int
    result_digest: DigestString
    request_digest: DigestString
    step_id: str
    resolved_arguments: Mapping[str, JsonValue]
    source_invocation_ids: tuple[str, ...]
    binder_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.request_digest, "argument_binding_request_digest")
        _identifier(self.step_id, "argument_binding_step_id")
        arguments = _mapping(
            self.resolved_arguments,
            "resolved_tool_arguments",
            maximum_bytes=MAX_ARGUMENT_BYTES,
        )
        sources = _strings(
            self.source_invocation_ids,
            "binding_source_invocation_ids",
            required=False,
            maximum=MAX_TOOL_ATTEMPTS,
        )
        if not isinstance(self.binder_revision, ComponentRevision):
            raise validation_error("invalid_argument_binder_revision")
        object.__setattr__(self, "resolved_arguments", arguments)
        object.__setattr__(self, "source_invocation_ids", sources)
        _check_digest(
            self.result_digest,
            {
                "schema_version": self.schema_version,
                "request_digest": self.request_digest,
                "step_id": self.step_id,
                "resolved_arguments": arguments,
                "source_invocation_ids": sources,
                "binder_revision": self.binder_revision,
            },
            domain="capability.argument-binding-result:v1",
            code="argument_binding_result_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityExecutionContext:
    schema_version: int
    actor: Actor
    conversation_scope: ConversationScope

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identity_scope(self.actor, self.conversation_scope)


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    schema_version: int
    request_digest: DigestString
    invocation_id: str
    plan_id: str
    plan_digest: DigestString
    step_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    catalog_snapshot_id: str
    catalog_digest: DigestString
    provider: ProviderRef
    mapping_digest: DigestString | None
    resolved_arguments: Mapping[str, JsonValue]
    source_invocation_ids: tuple[str, ...]
    idempotency_key: str
    attempt: int
    context: CapabilityExecutionContext

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "invocation_id",
            "plan_id",
            "step_id",
            "logical_operation_id",
            "capability_id",
            "catalog_snapshot_id",
            "idempotency_key",
        ):
            _identifier(getattr(self, field_name), field_name)
        for field_name in ("plan_digest", "definition_digest", "catalog_digest"):
            _digest(getattr(self, field_name), field_name)
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_execution_provider")
        if self.mapping_digest is not None:
            _digest(self.mapping_digest, "execution_mapping_digest")
        arguments = _mapping(
            self.resolved_arguments,
            "execution_arguments",
            maximum_bytes=MAX_ARGUMENT_BYTES,
        )
        sources = _strings(
            self.source_invocation_ids,
            "execution_source_invocation_ids",
            required=False,
            maximum=MAX_TOOL_ATTEMPTS,
        )
        if type(self.attempt) is not int or not 1 <= self.attempt <= MAX_TOOL_ATTEMPTS:
            raise validation_error("invalid_tool_execution_attempt")
        if not isinstance(self.context, CapabilityExecutionContext):
            raise validation_error("invalid_capability_execution_context")
        object.__setattr__(self, "resolved_arguments", arguments)
        object.__setattr__(self, "source_invocation_ids", sources)
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "invocation_id": self.invocation_id,
                "plan_id": self.plan_id,
                "plan_digest": self.plan_digest,
                "step_id": self.step_id,
                "logical_operation_id": self.logical_operation_id,
                "capability_id": self.capability_id,
                "definition_digest": self.definition_digest,
                "catalog_snapshot_id": self.catalog_snapshot_id,
                "catalog_digest": self.catalog_digest,
                "provider": self.provider,
                "mapping_digest": self.mapping_digest,
                "resolved_arguments": arguments,
                "source_invocation_ids": sources,
                "idempotency_key": self.idempotency_key,
                "attempt": self.attempt,
                "context": self.context,
            },
            domain="capability.tool-execution-request:v1",
            code="tool_execution_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ProviderInvocation:
    schema_version: int
    invocation_digest: DigestString
    invocation_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    provider: ProviderRef
    mapping_digest: DigestString | None
    arguments: Mapping[str, JsonValue]
    idempotency_key: str
    attempt: int
    context: CapabilityExecutionContext
    authorizations: tuple[AuthorizationDecision, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        for field_name in (
            "invocation_id",
            "logical_operation_id",
            "capability_id",
            "idempotency_key",
        ):
            _identifier(getattr(self, field_name), field_name)
        _digest(self.definition_digest, "provider_invocation_definition_digest")
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_provider_invocation_provider")
        if self.mapping_digest is not None:
            _digest(self.mapping_digest, "provider_invocation_mapping_digest")
        arguments = _mapping(
            self.arguments,
            "provider_invocation_arguments",
            maximum_bytes=MAX_ARGUMENT_BYTES,
        )
        if type(self.attempt) is not int or not 1 <= self.attempt <= MAX_TOOL_ATTEMPTS:
            raise validation_error("invalid_provider_invocation_attempt")
        if not isinstance(self.context, CapabilityExecutionContext):
            raise validation_error("invalid_capability_execution_context")
        authorizations = _typed_tuple(
            self.authorizations,
            AuthorizationDecision,
            "provider_invocation_authorizations",
            maximum=32,
            required=True,
        )
        if any(
            item.effect is not AuthorizationEffect.ALLOW
            or item.capability_id != self.capability_id
            for item in authorizations
        ):
            raise validation_error("invalid_provider_invocation_authorization")
        expected_actor = actor_digest(self.context.actor)
        expected_scope = scope_digest(self.context.conversation_scope)
        expected_resource = resource_digest(
            ResourceRef("capability", self.capability_id, expected_scope)
        )
        if any(
            item.actor_digest != expected_actor
            or item.scope_digest != expected_scope
            or item.resource_digest != expected_resource
            for item in authorizations
        ):
            raise validation_error("provider_invocation_authorization_scope_mismatch")
        actions = tuple(str(item.action) for item in authorizations)
        if len(actions) != len(set(actions)):
            raise validation_error("duplicate_provider_invocation_authorization")
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "authorizations", authorizations)
        _check_digest(
            self.invocation_digest,
            {
                "schema_version": self.schema_version,
                "invocation_id": self.invocation_id,
                "logical_operation_id": self.logical_operation_id,
                "capability_id": self.capability_id,
                "definition_digest": self.definition_digest,
                "provider": self.provider,
                "mapping_digest": self.mapping_digest,
                "arguments": arguments,
                "idempotency_key": self.idempotency_key,
                "attempt": self.attempt,
                "context": self.context,
                "authorizations": authorizations,
            },
            domain="capability.provider-invocation:v1",
            code="provider_invocation_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolError:
    schema_version: int
    info: ErrorInfo
    provider_error_code: str | None
    safe_details: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.info, ErrorInfo):
            raise validation_error("invalid_tool_error_info")
        if self.provider_error_code is not None:
            _identifier(self.provider_error_code, "provider_error_code")
        details = _mapping(
            self.safe_details,
            "tool_error_safe_details",
            maximum_bytes=16_384,
        )
        object.__setattr__(self, "safe_details", details)


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    schema_version: int
    result_digest: DigestString
    invocation_id: str
    capability_id: str
    definition_digest: DigestString
    provider: ProviderRef
    status: ToolExecutionStatus
    data: JsonValue | None
    error: ToolError | None
    source_refs: tuple[str, ...]
    sensitivity: PrivacyLevel
    usage: ResourceUsage
    observed_at: datetime
    truncated: bool
    untrusted: bool = True

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.invocation_id, "capability_result_invocation_id")
        _identifier(self.capability_id, "capability_result_capability_id")
        _digest(self.definition_digest, "capability_result_definition_digest")
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_capability_result_provider")
        if not isinstance(self.status, ToolExecutionStatus):
            raise validation_error("invalid_tool_execution_status")
        data = (
            None
            if self.data is None
            else _json(
                self.data,
                "capability_result_data",
                maximum_bytes=MAX_OBSERVATION_BYTES,
            )
        )
        _execution_payload(self.status, data, self.error)
        sources = _strings(
            self.source_refs,
            "capability_result_source_refs",
            required=False,
            maximum=MAX_SOURCE_REFS,
            maximum_bytes=1_024,
        )
        if not isinstance(self.sensitivity, PrivacyLevel):
            raise validation_error("invalid_capability_result_sensitivity")
        if not isinstance(self.usage, ResourceUsage):
            raise validation_error("invalid_capability_result_usage")
        require_aware(self.observed_at, "capability_result_observed_at")
        if type(self.truncated) is not bool or self.untrusted is not True:
            raise validation_error("invalid_capability_result_flags")
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "source_refs", sources)
        _check_digest(
            self.result_digest,
            {
                "schema_version": self.schema_version,
                "invocation_id": self.invocation_id,
                "capability_id": self.capability_id,
                "definition_digest": self.definition_digest,
                "provider": self.provider,
                "status": self.status,
                "data": data,
                "error": self.error,
                "source_refs": sources,
                "sensitivity": self.sensitivity,
                "usage": self.usage,
                "observed_at": self.observed_at,
                "truncated": self.truncated,
                "untrusted": self.untrusted,
            },
            domain="capability.result:v1",
            code="capability_result_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolObservation:
    schema_version: int
    observation_digest: DigestString
    provider_result_digest: DigestString
    invocation_id: str
    plan_id: str
    plan_digest: DigestString
    step_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    catalog_snapshot_id: str
    catalog_digest: DigestString
    provider: ProviderRef
    mapping_digest: DigestString | None
    policy_revision: str
    idempotency_key: str
    attempt: int
    status: ToolExecutionStatus
    data: JsonValue | None
    error: ToolError | None
    source_refs: tuple[str, ...]
    observed_at: datetime
    latency_ms: int
    cache_status: str | None
    sensitivity: PrivacyLevel
    usage: ResourceUsage
    truncated: bool
    untrusted: bool = True

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.provider_result_digest, "observation_provider_result_digest")
        for field_name in (
            "invocation_id",
            "plan_id",
            "step_id",
            "logical_operation_id",
            "capability_id",
            "catalog_snapshot_id",
            "policy_revision",
            "idempotency_key",
        ):
            _identifier(getattr(self, field_name), field_name)
        for field_name in ("plan_digest", "definition_digest", "catalog_digest"):
            _digest(getattr(self, field_name), field_name)
        if not isinstance(self.provider, ProviderRef):
            raise validation_error("invalid_observation_provider")
        if self.mapping_digest is not None:
            _digest(self.mapping_digest, "observation_mapping_digest")
        if type(self.attempt) is not int or not 1 <= self.attempt <= MAX_TOOL_ATTEMPTS:
            raise validation_error("invalid_observation_attempt")
        if not isinstance(self.status, ToolExecutionStatus):
            raise validation_error("invalid_tool_execution_status")
        data = (
            None
            if self.data is None
            else _json(
                self.data,
                "tool_observation_data",
                maximum_bytes=MAX_OBSERVATION_BYTES,
            )
        )
        _execution_payload(self.status, data, self.error)
        sources = _strings(
            self.source_refs,
            "tool_observation_source_refs",
            required=False,
            maximum=MAX_SOURCE_REFS,
            maximum_bytes=1_024,
        )
        require_aware(self.observed_at, "tool_observation_observed_at")
        if type(self.latency_ms) is not int or not 0 <= self.latency_ms <= 3_600_000:
            raise validation_error("invalid_tool_observation_latency")
        if self.cache_status is not None:
            _identifier(self.cache_status, "tool_observation_cache_status")
        if not isinstance(self.sensitivity, PrivacyLevel):
            raise validation_error("invalid_tool_observation_sensitivity")
        if not isinstance(self.usage, ResourceUsage):
            raise validation_error("invalid_tool_observation_usage")
        if self.usage.tool_steps != 1:
            raise validation_error("tool_observation_usage_step_mismatch")
        if type(self.truncated) is not bool or self.untrusted is not True:
            raise validation_error("invalid_tool_observation_flags")
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "source_refs", sources)
        _check_digest(
            self.observation_digest,
            {
                "schema_version": self.schema_version,
                "provider_result_digest": self.provider_result_digest,
                "invocation_id": self.invocation_id,
                "plan_id": self.plan_id,
                "plan_digest": self.plan_digest,
                "step_id": self.step_id,
                "logical_operation_id": self.logical_operation_id,
                "capability_id": self.capability_id,
                "definition_digest": self.definition_digest,
                "catalog_snapshot_id": self.catalog_snapshot_id,
                "catalog_digest": self.catalog_digest,
                "provider": self.provider,
                "mapping_digest": self.mapping_digest,
                "policy_revision": self.policy_revision,
                "idempotency_key": self.idempotency_key,
                "attempt": self.attempt,
                "status": self.status,
                "data": data,
                "error": self.error,
                "source_refs": sources,
                "observed_at": self.observed_at,
                "latency_ms": self.latency_ms,
                "cache_status": self.cache_status,
                "sensitivity": self.sensitivity,
                "usage": self.usage,
                "truncated": self.truncated,
                "untrusted": self.untrusted,
            },
            domain="capability.tool-observation:v1",
            code="tool_observation_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolValidationRequest:
    schema_version: int
    request_digest: DigestString
    retrieval: CapabilityRetrievalResult
    plan: ToolPlan
    observations: tuple[ToolObservation, ...]
    output_schemas: tuple[CapabilitySchemaDocument, ...]

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.retrieval, CapabilityRetrievalResult):
            raise validation_error("invalid_tool_validation_retrieval")
        if not isinstance(self.plan, ToolPlan):
            raise validation_error("invalid_tool_validation_plan")
        if self.plan.retrieval_result_digest != self.retrieval.result_digest:
            raise validation_error("tool_validation_retrieval_mismatch")
        observations = _typed_tuple(
            self.observations,
            ToolObservation,
            "tool_validation_observations",
            maximum=MAX_TOOL_ATTEMPTS,
        )
        schemas = _typed_tuple(
            self.output_schemas,
            CapabilitySchemaDocument,
            "tool_validation_output_schemas",
            maximum=MAX_PLAN_STEPS,
            required=True,
        )
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "output_schemas", schemas)
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "retrieval": self.retrieval,
                "plan": self.plan,
                "observations": observations,
                "output_schemas": schemas,
            },
            domain="capability.tool-validation-request:v1",
            code="tool_validation_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolValidationResult:
    schema_version: int
    result_digest: DigestString
    request_digest: DigestString
    action: ValidationAction
    accepted_observations: tuple[ToolObservation, ...]
    retry_step_id: str | None
    clarification_key: str | None
    reason_codes: tuple[str, ...]
    validator_revision: ComponentRevision

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _digest(self.request_digest, "tool_validation_request_digest")
        if not isinstance(self.action, ValidationAction):
            raise validation_error("invalid_tool_validation_action")
        observations = _typed_tuple(
            self.accepted_observations,
            ToolObservation,
            "accepted_tool_observations",
            maximum=MAX_TOOL_ATTEMPTS,
        )
        if any(
            item.status is not ToolExecutionStatus.SUCCEEDED for item in observations
        ):
            raise validation_error("accepted_observation_not_successful")
        invocation_ids = tuple(item.invocation_id for item in observations)
        if len(invocation_ids) != len(set(invocation_ids)):
            raise validation_error("duplicate_accepted_observation")
        if self.action is ValidationAction.FINISH and not observations:
            raise validation_error("tool_validation_finish_without_observation")
        if (self.retry_step_id is not None) is (
            self.action is not ValidationAction.RETRY
        ):
            raise validation_error("tool_validation_retry_binding_mismatch")
        if self.retry_step_id is not None:
            _identifier(self.retry_step_id, "tool_validation_retry_step_id")
        if (self.clarification_key is not None) is (
            self.action is not ValidationAction.CLARIFY
        ):
            raise validation_error("tool_validation_clarification_binding_mismatch")
        if self.clarification_key is not None:
            _identifier(self.clarification_key, "tool_validation_clarification_key")
        reasons = _strings(
            self.reason_codes,
            "tool_validation_reason_codes",
            required=True,
        )
        if not isinstance(self.validator_revision, ComponentRevision):
            raise validation_error("invalid_tool_result_validator_revision")
        object.__setattr__(self, "accepted_observations", observations)
        object.__setattr__(self, "reason_codes", reasons)
        _check_digest(
            self.result_digest,
            {
                "schema_version": self.schema_version,
                "request_digest": self.request_digest,
                "action": self.action,
                "accepted_observations": observations,
                "retry_step_id": self.retry_step_id,
                "clarification_key": self.clarification_key,
                "reason_codes": reasons,
                "validator_revision": self.validator_revision,
            },
            domain="capability.tool-validation-result:v1",
            code="tool_validation_result_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolInvocationClaimRequest:
    schema_version: int
    request_digest: DigestString
    idempotency_key: str
    execution_request_digest: DigestString
    expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.idempotency_key, "tool_invocation_idempotency_key")
        _digest(self.execution_request_digest, "execution_request_digest")
        require_aware(self.expires_at, "tool_invocation_claim_expiry")
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "idempotency_key": self.idempotency_key,
                "execution_request_digest": self.execution_request_digest,
                "expires_at": self.expires_at,
            },
            domain="capability.tool-invocation-claim-request:v1",
            code="tool_invocation_claim_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolInvocationClaim:
    schema_version: int
    claim_digest: DigestString
    claim_id: str
    claim_request_digest: DigestString
    idempotency_key: str
    execution_request_digest: DigestString
    disposition: ToolInvocationDisposition
    terminal_receipt_digest: DigestString | None
    claimed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.claim_id, "tool_invocation_claim_id")
        _digest(self.claim_request_digest, "tool_claim_request_digest")
        _identifier(self.idempotency_key, "tool_invocation_idempotency_key")
        _digest(self.execution_request_digest, "execution_request_digest")
        if not isinstance(self.disposition, ToolInvocationDisposition):
            raise validation_error("invalid_tool_invocation_disposition")
        if self.terminal_receipt_digest is not None:
            _digest(
                self.terminal_receipt_digest,
                "tool_terminal_receipt_digest",
            )
        if (
            self.disposition is ToolInvocationDisposition.DUPLICATE_COMPLETED
            and self.terminal_receipt_digest is None
        ):
            raise validation_error("duplicate_tool_claim_without_receipt")
        if (
            self.disposition is not ToolInvocationDisposition.DUPLICATE_COMPLETED
            and self.terminal_receipt_digest is not None
        ):
            raise validation_error("nonduplicate_tool_claim_has_receipt")
        _fresh_window(self.claimed_at, self.expires_at, "tool_invocation_claim")
        _check_digest(
            self.claim_digest,
            {
                "schema_version": self.schema_version,
                "claim_id": self.claim_id,
                "claim_request_digest": self.claim_request_digest,
                "idempotency_key": self.idempotency_key,
                "execution_request_digest": self.execution_request_digest,
                "disposition": self.disposition,
                "terminal_receipt_digest": self.terminal_receipt_digest,
                "claimed_at": self.claimed_at,
                "expires_at": self.expires_at,
            },
            domain="capability.tool-invocation-claim:v1",
            code="tool_invocation_claim_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class ToolInvocationReceipt:
    schema_version: int
    receipt_digest: DigestString
    claim_id: str
    claim_request_digest: DigestString
    idempotency_key: str
    execution_request_digest: DigestString
    observation: ToolObservation
    completed_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.claim_id, "tool_invocation_claim_id")
        _digest(self.claim_request_digest, "tool_claim_request_digest")
        _identifier(self.idempotency_key, "tool_invocation_idempotency_key")
        _digest(self.execution_request_digest, "execution_request_digest")
        if not isinstance(self.observation, ToolObservation):
            raise validation_error("invalid_tool_invocation_observation")
        if self.observation.idempotency_key != self.idempotency_key:
            raise validation_error("tool_invocation_receipt_key_mismatch")
        require_aware(self.completed_at, "tool_invocation_completed_at")
        _check_digest(
            self.receipt_digest,
            {
                "schema_version": self.schema_version,
                "claim_id": self.claim_id,
                "claim_request_digest": self.claim_request_digest,
                "idempotency_key": self.idempotency_key,
                "execution_request_digest": self.execution_request_digest,
                "observation": self.observation,
                "completed_at": self.completed_at,
            },
            domain="capability.tool-invocation-receipt:v1",
            code="tool_invocation_receipt_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityRunRequest:
    schema_version: int
    request_digest: DigestString
    query: CapabilityQuery
    actor: Actor
    conversation_scope: ConversationScope
    data_classification: PrivacyLevel
    available_input_schemas: tuple[SchemaRef, ...]
    maximum_attempts: int = DEFAULT_TOOL_ATTEMPTS

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        if not isinstance(self.query, CapabilityQuery):
            raise validation_error("invalid_capability_run_query")
        _identity_scope(self.actor, self.conversation_scope)
        if not isinstance(self.data_classification, PrivacyLevel):
            raise validation_error("invalid_capability_run_classification")
        schemas = _typed_tuple(
            self.available_input_schemas,
            SchemaRef,
            "capability_run_input_schemas",
            maximum=64,
        )
        if (
            type(self.maximum_attempts) is not int
            or not 1 <= self.maximum_attempts <= MAX_TOOL_ATTEMPTS
        ):
            raise validation_error("invalid_capability_run_attempt_limit")
        object.__setattr__(self, "available_input_schemas", schemas)
        _check_digest(
            self.request_digest,
            {
                "schema_version": self.schema_version,
                "query": self.query,
                "actor": self.actor,
                "conversation_scope": self.conversation_scope,
                "data_classification": self.data_classification,
                "available_input_schemas": schemas,
                "maximum_attempts": self.maximum_attempts,
            },
            domain="capability.run-request:v1",
            code="capability_run_request_digest_mismatch",
        )


@dataclass(frozen=True, slots=True)
class CapabilityRunReceipt:
    schema_version: int
    receipt_digest: DigestString
    run_id: str
    request_digest: DigestString
    status: CapabilityRunStatus
    retrieval: CapabilityRetrievalResult | None
    plan: ToolPlan | None
    observations: tuple[ToolObservation, ...]
    validation: ToolValidationResult | None
    usage: ResourceUsage
    reason_codes: tuple[str, ...]
    completed_at: datetime

    def __post_init__(self) -> None:
        _v1(self.schema_version)
        _identifier(self.run_id, "capability_run_id")
        _digest(self.request_digest, "capability_run_request_digest")
        if not isinstance(self.status, CapabilityRunStatus):
            raise validation_error("invalid_capability_run_status")
        if self.retrieval is not None and not isinstance(
            self.retrieval, CapabilityRetrievalResult
        ):
            raise validation_error("invalid_capability_run_retrieval")
        if self.plan is not None and not isinstance(self.plan, ToolPlan):
            raise validation_error("invalid_capability_run_plan")
        if self.plan is not None and self.retrieval is None:
            raise validation_error("capability_run_plan_without_retrieval")
        if (
            self.plan is not None
            and self.retrieval is not None
            and self.plan.retrieval_result_digest != self.retrieval.result_digest
        ):
            raise validation_error("capability_run_plan_retrieval_mismatch")
        observations = _typed_tuple(
            self.observations,
            ToolObservation,
            "capability_run_observations",
            maximum=MAX_TOOL_ATTEMPTS,
        )
        if self.validation is not None and not isinstance(
            self.validation, ToolValidationResult
        ):
            raise validation_error("invalid_capability_run_validation")
        if self.validation is not None and self.plan is None:
            raise validation_error("capability_run_validation_without_plan")
        if self.status is CapabilityRunStatus.COMPLETED and (
            self.validation is None
            or self.validation.action is not ValidationAction.FINISH
            or not self.validation.accepted_observations
        ):
            raise validation_error("completed_capability_run_not_accepted")
        if not isinstance(self.usage, ResourceUsage):
            raise validation_error("invalid_capability_run_usage")
        if self.usage.tool_steps != len(observations):
            raise validation_error("capability_run_usage_step_mismatch")
        reasons = _strings(
            self.reason_codes,
            "capability_run_reason_codes",
            required=True,
        )
        require_aware(self.completed_at, "capability_run_completed_at")
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "reason_codes", reasons)
        _check_digest(
            self.receipt_digest,
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "request_digest": self.request_digest,
                "status": self.status,
                "retrieval": self.retrieval,
                "plan": self.plan,
                "observations": observations,
                "validation": self.validation,
                "usage": self.usage,
                "reason_codes": reasons,
                "completed_at": self.completed_at,
            },
            domain="capability.run-receipt:v1",
            code="capability_run_receipt_digest_mismatch",
        )


def _validate_catalog_bindings(
    definitions: tuple[CapabilityDefinition, ...],
    schemas: tuple[CapabilitySchemaDocument, ...],
    providers: tuple[CapabilityProviderDescriptor, ...],
    mappings: tuple[McpCapabilityMapping, ...],
) -> None:
    schema_refs = {item.schema_ref for item in schemas}
    provider_by_ref = {item.provider: item for item in providers}
    mapping_by_capability = {item.capability_id: item for item in mappings}
    definition_ids_by_provider: dict[ProviderRef, set[str]] = {}
    for definition in definitions:
        definition_ids_by_provider.setdefault(definition.provider, set()).add(
            definition.capability_id
        )
        if (
            definition.input_schema not in schema_refs
            or definition.output_schema not in schema_refs
        ):
            raise validation_error(
                "capability_definition_schema_not_in_catalog",
                definition.capability_id,
            )
        descriptor = provider_by_ref.get(definition.provider)
        if (
            descriptor is None
            or definition.capability_id not in descriptor.capability_ids
        ):
            raise validation_error(
                "capability_provider_not_bound",
                definition.capability_id,
            )
        mapping = mapping_by_capability.get(definition.capability_id)
        if descriptor.kind is CapabilityProviderKind.MCP:
            if mapping is None:
                raise validation_error(
                    "mcp_capability_mapping_missing",
                    definition.capability_id,
                )
            if mapping.capability_definition_digest != definition.definition_digest:
                raise validation_error(
                    "mcp_mapping_definition_digest_mismatch",
                    definition.capability_id,
                )
        elif mapping is not None:
            raise validation_error(
                "non_mcp_capability_has_mcp_mapping",
                definition.capability_id,
            )
    for descriptor in providers:
        expected = frozenset(definition_ids_by_provider.get(descriptor.provider, set()))
        if descriptor.capability_ids != expected:
            raise validation_error(
                "capability_provider_surface_mismatch",
                descriptor.provider.provider_id,
            )
    mcp_definition_ids = {
        definition.capability_id
        for definition in definitions
        if provider_by_ref[definition.provider].kind is CapabilityProviderKind.MCP
    }
    if set(mapping_by_capability) != mcp_definition_ids:
        raise validation_error("mcp_capability_mapping_surface_mismatch")
    expected_semantics = {
        Idempotency.READ_ONLY: McpOperationSemantics.READ_ONLY,
        Idempotency.IDEMPOTENT_WRITE: McpOperationSemantics.IDEMPOTENT,
        Idempotency.NON_IDEMPOTENT: McpOperationSemantics.NON_IDEMPOTENT,
    }
    for definition in definitions:
        mapping = mapping_by_capability.get(definition.capability_id)
        if (
            mapping is not None
            and mapping.semantics is not expected_semantics[definition.idempotency]
        ):
            raise validation_error(
                "mcp_mapping_operation_semantics_mismatch",
                definition.capability_id,
            )


def _validate_catalog_revisions(
    catalog_revision: str,
    mapping_revision: str,
    provider_registry_revision: str,
    definitions: tuple[CapabilityDefinition, ...],
    schemas: tuple[CapabilitySchemaDocument, ...],
    providers: tuple[CapabilityProviderDescriptor, ...],
    mappings: tuple[McpCapabilityMapping, ...],
) -> None:
    if catalog_revision != capability_catalog_revision(
        definitions,
        schemas,
        providers,
        mappings,
    ):
        raise validation_error("capability_catalog_revision_mismatch")
    if mapping_revision != capability_mapping_revision(mappings):
        raise validation_error("capability_mapping_revision_mismatch")
    if provider_registry_revision != capability_provider_registry_revision(providers):
        raise validation_error("capability_provider_registry_revision_mismatch")


def _execution_payload(
    status: ToolExecutionStatus,
    data: JsonValue | None,
    error: ToolError | None,
) -> None:
    if status is ToolExecutionStatus.SUCCEEDED:
        if data is None or error is not None:
            raise validation_error("invalid_successful_tool_payload")
    elif data is not None or not isinstance(error, ToolError):
        raise validation_error("invalid_failed_tool_payload")
    if (
        status is ToolExecutionStatus.UNKNOWN
        and error is not None
        and not error.info.outcome_unknown
    ):
        raise validation_error("unknown_tool_outcome_flag_missing")


def _identity_scope(actor: Actor, scope: ConversationScope) -> None:
    if not isinstance(actor, Actor) or not isinstance(scope, ConversationScope):
        raise validation_error("invalid_capability_identity_scope")
    if actor.platform != scope.platform or actor.bot_id != scope.bot_id:
        raise validation_error("capability_identity_scope_mismatch")


def _fresh_window(observed_at: datetime, expires_at: datetime, field: str) -> None:
    require_aware(observed_at, f"{field}_observed_at")
    require_aware(expires_at, f"{field}_expires_at")
    if expires_at <= observed_at:
        raise validation_error("invalid_capability_freshness", field)


def _v1(value: int) -> None:
    if type(value) is not int or value != 1:
        raise validation_error("unsupported_capability_schema_version")


def _bounded(value: object, field: str, maximum_bytes: int) -> str:
    if not isinstance(value, str):
        raise validation_error("invalid_capability_string", field)
    normalized = require_non_empty(value, field)
    if len(normalized.encode("utf-8")) > maximum_bytes:
        raise validation_error("capability_string_too_large", field)
    return normalized


def _identifier(value: object, field: str) -> str:
    normalized = _bounded(value, field, _MAX_IDENTIFIER_BYTES)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise validation_error("invalid_capability_identifier", field)
    return normalized


def _digest(value: DigestString, field: str) -> None:
    encoded = _bounded(str(value), field, 512)
    if _DIGEST.fullmatch(encoded) is None:
        raise validation_error("invalid_capability_digest", field)


def _strings(
    values: object,
    field: str,
    *,
    required: bool,
    maximum: int = _MAX_REASON_CODES,
    maximum_bytes: int = _MAX_IDENTIFIER_BYTES,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(
        values, (tuple, list, set, frozenset)
    ):
        raise validation_error("invalid_capability_string_collection", field)
    normalized = tuple(_bounded(item, field, maximum_bytes) for item in values)
    if (required and not normalized) or len(normalized) > maximum:
        raise validation_error("invalid_capability_string_collection", field)
    if len(normalized) != len(set(normalized)):
        raise validation_error("duplicate_capability_string", field)
    return normalized


def _identifier_set(
    values: object,
    field: str,
    *,
    maximum_items: int,
    required: bool,
) -> frozenset[str]:
    if isinstance(values, (str, bytes)) or not isinstance(
        values, (tuple, list, set, frozenset)
    ):
        raise validation_error("invalid_capability_identifier_set", field)
    result = frozenset(_identifier(item, field) for item in values)
    if (required and not result) or len(result) > maximum_items:
        raise validation_error("invalid_capability_identifier_set", field)
    return result


def _typed_tuple(
    values: object,
    expected: type[object],
    field: str,
    *,
    maximum: int,
    required: bool = False,
) -> tuple:
    if isinstance(values, (str, bytes)) or not isinstance(
        values, (tuple, list, set, frozenset)
    ):
        raise validation_error("invalid_capability_collection", field)
    result = tuple(values)
    if (required and not result) or len(result) > maximum:
        raise validation_error("invalid_capability_collection", field)
    if any(not isinstance(item, expected) for item in result):
        raise validation_error("invalid_capability_collection_item", field)
    return result


def _sorted_unique_objects(
    values: object,
    expected: type[object],
    *,
    key,
    field: str,
    maximum: int,
    required: bool,
) -> tuple:
    result = _typed_tuple(
        values,
        expected,
        field,
        maximum=maximum,
        required=required,
    )
    keys = tuple(key(item) for item in result)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise validation_error("invalid_capability_catalog_order", field)
    return result


def _json(value: object, field: str, *, maximum_bytes: int) -> JsonValue:
    frozen = freeze_json(value, path=f"$.{field}")
    if len(canonical_json_bytes(frozen)) > maximum_bytes:
        raise validation_error("capability_json_too_large", field)
    return frozen


def _mapping(
    value: object,
    field: str,
    *,
    maximum_bytes: int,
) -> Mapping[str, JsonValue]:
    frozen = _json(value, field, maximum_bytes=maximum_bytes)
    if not isinstance(frozen, Mapping):
        raise validation_error("invalid_capability_mapping", field)
    return MappingProxyType(dict(frozen))


def _json_pointer(value: str, field: str) -> str:
    pointer = _bounded(value, field, 1_024)
    if not pointer.startswith("/"):
        raise validation_error("invalid_capability_json_pointer", field)
    if any(
        _JSON_POINTER_TOKEN.fullmatch(item) is None for item in pointer[1:].split("/")
    ):
        raise validation_error("invalid_capability_json_pointer", field)
    return pointer


def _check_digest(
    actual: DigestString,
    value: object,
    *,
    domain: str,
    code: str,
) -> None:
    _digest(actual, "digest")
    if actual != canonical_digest(value, domain=domain):
        raise validation_error(code)


__all__ = [
    "DEFAULT_TOOL_ATTEMPTS",
    "MAX_ARGUMENT_BYTES",
    "MAX_CAPABILITY_CANDIDATES",
    "MAX_CAPABILITY_DEFINITIONS",
    "MAX_OBSERVATION_BYTES",
    "MAX_PLAN_STEPS",
    "MAX_SCHEMA_BYTES",
    "MAX_SOURCE_REFS",
    "MAX_TOOL_ATTEMPTS",
    "ArgumentBindingRequest",
    "ArgumentBindingResult",
    "ArgumentTemplate",
    "CapabilityCandidate",
    "CapabilityCatalogPublishReceipt",
    "CapabilityCatalogSnapshot",
    "CapabilityCatalogUpdate",
    "CapabilityEndpointHealth",
    "CapabilityExecutionContext",
    "CapabilityHealthSnapshot",
    "CapabilityProviderDescriptor",
    "CapabilityProviderHealth",
    "CapabilityProviderKind",
    "CapabilityQuery",
    "CapabilityResult",
    "CapabilityRetrievalRequest",
    "CapabilityRetrievalResult",
    "CapabilityRunReceipt",
    "CapabilityRunRequest",
    "CapabilityRunStatus",
    "CapabilitySchemaDocument",
    "McpCapabilityMapping",
    "ObservationBinding",
    "ProviderInvocation",
    "ToolError",
    "ToolExecutionRequest",
    "ToolExecutionStatus",
    "ToolInvocationClaim",
    "ToolInvocationClaimRequest",
    "ToolInvocationDisposition",
    "ToolInvocationReceipt",
    "ToolObservation",
    "ToolPlan",
    "ToolPlanValidationRequest",
    "ToolPlanValidationResult",
    "ToolPlanningRequest",
    "ToolStep",
    "ToolValidationRequest",
    "ToolValidationResult",
    "ValidationAction",
]
