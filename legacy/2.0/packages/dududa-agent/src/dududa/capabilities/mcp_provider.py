from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.contracts.canonical import canonical_schema_digest
from dududa.domain.capability import CapabilityDefinition
from dududa.domain.primitives import JsonValue, ResourceUsage
from dududa.errors import (
    ErrorCategory,
    ErrorInfo,
    error,
    validation_error,
)
from dududa.mcp import (
    McpCallContext,
    McpClientError,
    McpFailureKind,
    McpSchemaSnapshot,
    McpToolDescriptor,
    McpToolResult,
    mcp_error_info,
    mcp_schema_snapshot_digest,
    mcp_tool_request_digest,
    mcp_tool_result_digest,
)
from dududa.ports.capabilities import CapabilitySchemaValidator
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.ports.mcp import UnifiedMcpClient

from .contracts import (
    CapabilityCatalogSnapshot,
    CapabilityEndpointHealth,
    CapabilityHealthStatus,
    CapabilityProviderDescriptor,
    CapabilityProviderHealth,
    CapabilityProviderKind,
    CapabilityResult,
    CapabilitySchemaDocument,
    McpCapabilityMapping,
    ProviderInvocation,
    ToolError,
    ToolExecutionStatus,
)
from .digests import (
    capability_provider_health_digest,
    capability_result_digest,
    provider_invocation_digest,
)
from .mapping_policy import (
    IDENTITY_ARGUMENT_MAPPING_REVISION,
    RESULT_MAPPING_REVISIONS,
    SCHEMA_PROJECT_RESULT_MAPPING_REVISION,
    STRUCTURED_RESULT_MAPPING_REVISION,
    check_projection_schema,
    fixed_arguments_match,
    projection_schema_types,
)

CapabilityCallerContext = PortCallContext | ServiceCallContext


class McpCapabilityProvider:
    """Generic MCP transport Adapter with no Capability authority."""

    def __init__(
        self,
        descriptor: CapabilityProviderDescriptor,
        definitions: Iterable[CapabilityDefinition],
        schema_documents: Iterable[CapabilitySchemaDocument],
        mappings: Iterable[McpCapabilityMapping],
        client: UnifiedMcpClient,
        schema_validator: CapabilitySchemaValidator,
        *,
        health_ttl: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(descriptor, CapabilityProviderDescriptor):
            raise TypeError("descriptor must be a CapabilityProviderDescriptor")
        if descriptor.kind is not CapabilityProviderKind.MCP:
            raise ValueError("MCP Provider requires an MCP descriptor")
        if not isinstance(client, UnifiedMcpClient):
            raise TypeError("client must implement UnifiedMcpClient")
        if not isinstance(schema_validator, CapabilitySchemaValidator):
            raise TypeError("schema_validator must implement CapabilitySchemaValidator")
        if (
            not isinstance(health_ttl, timedelta)
            or health_ttl <= timedelta(0)
            or health_ttl > timedelta(minutes=5)
        ):
            raise ValueError("health_ttl is out of range")
        definitions_by_id = _definitions(descriptor, definitions)
        output_schemas = _output_schemas(definitions_by_id, schema_documents)
        mappings_by_id = _mappings(descriptor, definitions_by_id, mappings)
        checked_schema_refs: set[tuple[str, int, str]] = set()
        for capability_id, mapping in mappings_by_id.items():
            output_schema = output_schemas[capability_id]
            schema_key = (
                output_schema.schema_ref.schema_id,
                output_schema.schema_ref.schema_version,
                str(output_schema.schema_ref.digest),
            )
            if schema_key not in checked_schema_refs:
                schema_validator.check_schema(output_schema)
                checked_schema_refs.add(schema_key)
            if (
                mapping.result_mapping_revision
                == SCHEMA_PROJECT_RESULT_MAPPING_REVISION
            ):
                check_projection_schema(output_schema.document)
        self._descriptor = descriptor
        self._definitions = definitions_by_id
        self._output_schemas = output_schemas
        self._mappings = mappings_by_id
        self._client = client
        self._schema_validator = schema_validator
        self._health_ttl = health_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._closed = False

    @classmethod
    def from_catalog(
        cls,
        snapshot: CapabilityCatalogSnapshot,
        descriptor: CapabilityProviderDescriptor,
        client: UnifiedMcpClient,
        schema_validator: CapabilitySchemaValidator,
        *,
        health_ttl: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
    ) -> McpCapabilityProvider:
        if not isinstance(snapshot, CapabilityCatalogSnapshot):
            raise TypeError("snapshot must be a CapabilityCatalogSnapshot")
        if (
            not isinstance(descriptor, CapabilityProviderDescriptor)
            or descriptor not in snapshot.provider_descriptors
            or descriptor.kind is not CapabilityProviderKind.MCP
        ):
            raise validation_error("mcp_provider_descriptor_not_in_catalog")
        definitions = tuple(
            item
            for item in snapshot.definitions
            if item.provider == descriptor.provider
        )
        capability_ids = frozenset(item.capability_id for item in definitions)
        mappings = tuple(
            item
            for item in snapshot.mcp_mappings
            if item.capability_id in capability_ids
        )
        output_refs = frozenset(item.output_schema for item in definitions)
        schemas = tuple(
            item for item in snapshot.schema_documents if item.schema_ref in output_refs
        )
        return cls(
            descriptor,
            definitions,
            schemas,
            mappings,
            client,
            schema_validator,
            health_ttl=health_ttl,
            clock=clock,
        )

    @property
    def descriptor(self) -> CapabilityProviderDescriptor:
        return self._descriptor

    async def health(
        self,
        *,
        call: CapabilityCallerContext,
    ) -> CapabilityProviderHealth:
        now = self._now()
        self._validate_call(call, now)
        self._ensure_open()
        schemas: dict[str, McpSchemaSnapshot] = {}
        for server_id in sorted({item.server_id for item in self._mappings.values()}):
            schemas[server_id] = await self._client.discover(
                server_id,
                refresh=False,
                call=call,
            )
        endpoints: list[CapabilityEndpointHealth] = []
        expires_at = now + self._health_ttl
        for capability_id in sorted(self._definitions):
            definition = self._definitions[capability_id]
            mapping = self._mappings[capability_id]
            schema = schemas[mapping.server_id]
            self._validate_schema(schema, mapping, at=self._now())
            expires_at = min(expires_at, schema.expires_at)
            endpoints.append(
                CapabilityEndpointHealth(
                    schema_version=1,
                    capability_id=capability_id,
                    definition_digest=definition.definition_digest,
                    status=CapabilityHealthStatus.HEALTHY,
                    reason_codes=("mcp_schema_mapping_current",),
                )
            )
        observed_at = self._now()
        if expires_at <= observed_at:
            raise error(
                "mcp_capability_schema_expired",
                ErrorCategory.EXTERNAL,
                "service.unavailable",
            )
        values = {
            "schema_version": 1,
            "provider": self._descriptor.provider,
            "status": CapabilityHealthStatus.HEALTHY,
            "capabilities": tuple(endpoints),
            "observed_at": observed_at,
            "expires_at": expires_at,
        }
        return CapabilityProviderHealth(
            health_digest=capability_provider_health_digest(values),
            **values,
        )

    async def invoke(
        self,
        request: ProviderInvocation,
        *,
        call: PortCallContext,
    ) -> CapabilityResult:
        now = self._now()
        self._validate_call(call, now)
        self._ensure_open()
        definition, mapping = self._validate_invocation(request)
        try:
            schema = await self._client.discover(
                mapping.server_id,
                refresh=False,
                call=call,
            )
            self._validate_schema(schema, mapping, at=self._now())
            mcp_request_digest = mcp_tool_request_digest(
                mapping.server_id,
                mapping.tool_name,
                request.arguments,
                schema,
                mapping.semantics,
                request.idempotency_key,
            )
            mcp_call = McpCallContext(
                schema_version=1,
                caller=call,
                schema_snapshot_id=schema.snapshot_id,
                schema_snapshot_digest=schema.snapshot_digest,
                request_digest=mcp_request_digest,
                semantics=mapping.semantics,
                business_idempotency_key=request.idempotency_key,
            )
            result = await self._client.call_tool(
                mapping.server_id,
                mapping.tool_name,
                request.arguments,
                call=mcp_call,
            )
            self._validate_mcp_result(result, mapping, schema, mcp_request_digest)
        except McpClientError as exc:
            return self._error_result(request, definition, exc)
        if result.is_error:
            return self._server_error_result(request, definition, mapping, result)
        if result.structured_content is None:
            raise validation_error("mcp_capability_structured_result_missing")
        try:
            output_schema = self._output_schemas[definition.capability_id]
            data = self._map_result(
                result.structured_content,
                mapping,
                output_schema,
            )
            data = self._schema_validator.validate(data, output_schema)
        except Exception:  # noqa: BLE001 - validation internals remain private.
            return self._result_mapping_error(request, definition)
        return self._result(
            request,
            definition,
            status=ToolExecutionStatus.SUCCEEDED,
            data=data,
            error_value=None,
            source_refs=(
                (
                    f"mcp://{mapping.server_id}/{mapping.tool_name}"
                    f"?schema={schema.snapshot_id}"
                ),
            ),
            cost_units=Decimal(definition.cost_hint.units),
        )

    async def close(self) -> None:
        self._closed = True

    def _validate_invocation(
        self,
        request: ProviderInvocation,
    ) -> tuple[CapabilityDefinition, McpCapabilityMapping]:
        if (
            not isinstance(request, ProviderInvocation)
            or provider_invocation_digest(request) != request.invocation_digest
            or request.provider != self._descriptor.provider
        ):
            raise validation_error("invalid_mcp_provider_invocation")
        definition = self._definitions.get(request.capability_id)
        mapping = self._mappings.get(request.capability_id)
        if (
            definition is None
            or mapping is None
            or not definition.enabled
            or not mapping.enabled
            or definition.definition_digest != request.definition_digest
            or mapping.mapping_digest != request.mapping_digest
            or mapping.capability_definition_digest != request.definition_digest
            or not fixed_arguments_match(request.arguments, mapping.fixed_arguments)
        ):
            raise validation_error("mcp_provider_mapping_binding_mismatch")
        return definition, mapping

    def _validate_schema(
        self,
        schema: McpSchemaSnapshot,
        mapping: McpCapabilityMapping,
        *,
        at: datetime,
    ) -> McpToolDescriptor:
        if (
            not isinstance(schema, McpSchemaSnapshot)
            or schema.snapshot_digest
            != mcp_schema_snapshot_digest(
                schema.server_id,
                schema.config_revision,
                schema.definition_digest,
                schema.generation,
                schema.tools,
            )
            or schema.server_id != mapping.server_id
            or schema.observed_at > at
            or schema.expires_at <= at
        ):
            raise validation_error("mcp_provider_schema_binding_invalid")
        tool = next(
            (item for item in schema.tools if item.name == mapping.tool_name), None
        )
        if tool is None:
            raise validation_error("mcp_provider_tool_missing")
        input_digest = canonical_schema_digest(
            tool.input_schema,
            schema_id=f"mcp.{mapping.server_id}.{mapping.tool_name}.input",
            schema_version=1,
        )
        output_digest = (
            None
            if tool.output_schema is None
            else canonical_schema_digest(
                tool.output_schema,
                schema_id=f"mcp.{mapping.server_id}.{mapping.tool_name}.output",
                schema_version=1,
            )
        )
        if (
            input_digest != mapping.expected_input_schema_digest
            or output_digest != mapping.expected_output_schema_digest
        ):
            raise validation_error("mcp_provider_tool_schema_drifted")
        if (
            mapping.result_mapping_revision == STRUCTURED_RESULT_MAPPING_REVISION
            and tool.output_schema
            != self._output_schemas[mapping.capability_id].document
        ):
            raise validation_error("mcp_provider_structured_schema_mismatch")
        return tool

    def _validate_mcp_result(
        self,
        result: McpToolResult,
        mapping: McpCapabilityMapping,
        schema: McpSchemaSnapshot,
        request_digest,
    ) -> None:
        if (
            not isinstance(result, McpToolResult)
            or result.result_digest
            != mcp_tool_result_digest(
                result.server_id,
                result.tool_name,
                result.generation,
                result.schema_snapshot_id,
                result.schema_snapshot_digest,
                result.request_digest,
                result.is_error,
                result.structured_content,
                result.content,
            )
            or result.server_id != mapping.server_id
            or result.tool_name != mapping.tool_name
            or result.generation != schema.generation
            or result.schema_snapshot_id != schema.snapshot_id
            or result.schema_snapshot_digest != schema.snapshot_digest
            or result.request_digest != request_digest
        ):
            raise validation_error("mcp_provider_result_binding_invalid")

    def _error_result(
        self,
        request: ProviderInvocation,
        definition: CapabilityDefinition,
        caught: McpClientError,
    ) -> CapabilityResult:
        status = (
            ToolExecutionStatus.UNKNOWN
            if caught.info.outcome_unknown
            else ToolExecutionStatus.FAILED
        )
        safe_info = mcp_error_info(
            caught.failure_kind,
            code=f"mcp_capability_{caught.failure_kind.value}",
            reason_codes=(f"mcp_failure_{caught.failure_kind.value}",),
            outcome_unknown=caught.info.outcome_unknown,
        )
        return self._result(
            request,
            definition,
            status=status,
            data=None,
            error_value=ToolError(
                schema_version=1,
                info=safe_info,
                provider_error_code=caught.failure_kind.value,
                safe_details={},
            ),
            source_refs=(),
            cost_units=(
                Decimal(definition.cost_hint.units)
                if status is ToolExecutionStatus.UNKNOWN
                else Decimal(0)
            ),
        )

    def _server_error_result(
        self,
        request: ProviderInvocation,
        definition: CapabilityDefinition,
        mapping: McpCapabilityMapping,
        result: McpToolResult,
    ) -> CapabilityResult:
        return self._result(
            request,
            definition,
            status=ToolExecutionStatus.FAILED,
            data=None,
            error_value=ToolError(
                schema_version=1,
                info=ErrorInfo(
                    schema_version=1,
                    code="mcp_tool_reported_error",
                    category=ErrorCategory.EXTERNAL,
                    retryable=False,
                    outcome_unknown=False,
                    public_message_key="service.unavailable",
                    reason_codes=("mcp_tool_error",),
                ),
                provider_error_code="tool_error",
                safe_details={
                    "server_id": mapping.server_id,
                    "tool_name": mapping.tool_name,
                    "result_digest": str(result.result_digest),
                },
            ),
            source_refs=(),
            cost_units=Decimal(definition.cost_hint.units),
        )

    def _result_mapping_error(
        self,
        request: ProviderInvocation,
        definition: CapabilityDefinition,
    ) -> CapabilityResult:
        return self._result(
            request,
            definition,
            status=ToolExecutionStatus.FAILED,
            data=None,
            error_value=ToolError(
                schema_version=1,
                info=ErrorInfo(
                    schema_version=1,
                    code="mcp_capability_result_mapping_failed",
                    category=ErrorCategory.EXTERNAL,
                    retryable=False,
                    outcome_unknown=False,
                    public_message_key="service.unavailable",
                    reason_codes=("mcp_result_rejected",),
                ),
                provider_error_code=McpFailureKind.RESULT_INVALID.value,
                safe_details={},
            ),
            source_refs=(),
            cost_units=Decimal(definition.cost_hint.units),
        )

    @staticmethod
    def _map_result(
        value: JsonValue,
        mapping: McpCapabilityMapping,
        output_schema: CapabilitySchemaDocument,
    ) -> JsonValue:
        if mapping.result_mapping_revision == STRUCTURED_RESULT_MAPPING_REVISION:
            return value
        if mapping.result_mapping_revision == SCHEMA_PROJECT_RESULT_MAPPING_REVISION:
            return _project_json(value, output_schema.document)
        raise validation_error("unsupported_mcp_result_mapping_revision")

    def _result(
        self,
        request: ProviderInvocation,
        definition: CapabilityDefinition,
        *,
        status: ToolExecutionStatus,
        data,
        error_value: ToolError | None,
        source_refs: tuple[str, ...],
        cost_units: Decimal,
    ) -> CapabilityResult:
        values = {
            "schema_version": 1,
            "provider_invocation_digest": request.invocation_digest,
            "invocation_id": request.invocation_id,
            "capability_id": request.capability_id,
            "definition_digest": request.definition_digest,
            "provider": request.provider,
            "status": status,
            "data": data,
            "error": error_value,
            "source_refs": source_refs,
            "sensitivity": definition.privacy_level,
            "usage": ResourceUsage(1, tool_steps=1, cost_units=cost_units),
            "observed_at": self._now(),
            "truncated": False,
            "untrusted": True,
        }
        return CapabilityResult(
            result_digest=capability_result_digest(values),
            **values,
        )

    def _validate_call(self, call: CapabilityCallerContext, now: datetime) -> None:
        if not isinstance(call, (PortCallContext, ServiceCallContext)):
            raise validation_error("invalid_mcp_capability_call")
        if call.cancellation.is_cancelled:
            raise error(
                "mcp_capability_call_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if now >= call.deadline:
            raise error(
                "mcp_capability_call_expired",
                ErrorCategory.TIMEOUT,
                "request.timeout",
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise error(
                "mcp_capability_provider_closed",
                ErrorCategory.EXTERNAL,
                "service.unavailable",
            )

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - callback details are hidden.
            raise error(
                "mcp_capability_clock_unavailable",
                ErrorCategory.INTERNAL,
                "service.unavailable",
            ) from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise validation_error("invalid_mcp_capability_clock")
        return value


def _definitions(
    descriptor: CapabilityProviderDescriptor,
    definitions: Iterable[CapabilityDefinition],
) -> Mapping[str, CapabilityDefinition]:
    items = tuple(definitions)
    if (
        not items
        or not all(isinstance(item, CapabilityDefinition) for item in items)
        or len({item.capability_id for item in items}) != len(items)
        or frozenset(item.capability_id for item in items) != descriptor.capability_ids
        or any(item.provider != descriptor.provider for item in items)
    ):
        raise ValueError("definitions do not match the Provider descriptor")
    return {item.capability_id: item for item in items}


def _mappings(
    descriptor: CapabilityProviderDescriptor,
    definitions: Mapping[str, CapabilityDefinition],
    mappings: Iterable[McpCapabilityMapping],
) -> Mapping[str, McpCapabilityMapping]:
    items = tuple(mappings)
    if (
        len(items) != len(definitions)
        or not all(isinstance(item, McpCapabilityMapping) for item in items)
        or len({item.capability_id for item in items}) != len(items)
        or frozenset(item.capability_id for item in items) != descriptor.capability_ids
        or any(
            item.capability_definition_digest
            != definitions[item.capability_id].definition_digest
            or item.argument_mapping_revision != IDENTITY_ARGUMENT_MAPPING_REVISION
            or item.result_mapping_revision not in RESULT_MAPPING_REVISIONS
            for item in items
        )
    ):
        raise ValueError("mappings do not match the Provider descriptor")
    return {item.capability_id: item for item in items}


def _output_schemas(
    definitions: Mapping[str, CapabilityDefinition],
    schema_documents: Iterable[CapabilitySchemaDocument],
) -> Mapping[str, CapabilitySchemaDocument]:
    documents = tuple(schema_documents)
    if not documents or not all(
        isinstance(item, CapabilitySchemaDocument) for item in documents
    ):
        raise TypeError("schema_documents must contain Capability Schema documents")
    by_ref = {
        (
            item.schema_ref.schema_id,
            item.schema_ref.schema_version,
            str(item.schema_ref.digest),
        ): item
        for item in documents
    }
    if len(by_ref) != len(documents):
        raise ValueError("duplicate Capability Schema documents")
    expected_refs = {
        (
            item.output_schema.schema_id,
            item.output_schema.schema_version,
            str(item.output_schema.digest),
        )
        for item in definitions.values()
    }
    if frozenset(by_ref) != frozenset(expected_refs):
        raise ValueError("Capability output Schema set does not match definitions")
    result: dict[str, CapabilitySchemaDocument] = {}
    for capability_id, definition in definitions.items():
        reference = definition.output_schema
        key = (reference.schema_id, reference.schema_version, str(reference.digest))
        document = by_ref.get(key)
        if document is None or document.schema_ref != reference:
            raise ValueError("Capability output Schema is missing")
        result[capability_id] = document
    return result


def _project_json(
    value: JsonValue,
    schema: Mapping[str, JsonValue],
) -> JsonValue:
    return _project_json_value(value, schema, depth=0, nodes=[0])


def _project_json_value(
    value: JsonValue,
    schema: Mapping[str, JsonValue],
    *,
    depth: int,
    nodes: list[int],
) -> JsonValue:
    nodes[0] += 1
    if depth > 32 or nodes[0] > 10_000:
        raise validation_error("mcp_projected_result_too_complex")
    types = projection_schema_types(schema)
    if value is None:
        if "null" in types:
            return None
        raise validation_error("mcp_projected_result_type_mismatch")
    if isinstance(value, Mapping):
        if "object" not in types:
            raise validation_error("mcp_projected_result_type_mismatch")
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise validation_error("mcp_projected_result_schema_invalid")
        required = schema.get("required", ())
        if not isinstance(required, tuple) or not all(
            isinstance(item, str) for item in required
        ):
            raise validation_error("mcp_projected_result_schema_invalid")
        if any(name not in value for name in required):
            raise validation_error("mcp_projected_result_required_field_missing")
        projected: dict[str, JsonValue] = {}
        for name in sorted(properties):
            child = properties[name]
            if name in value:
                if not isinstance(child, Mapping):
                    raise validation_error("mcp_projected_result_schema_invalid")
                projected[name] = _project_json_value(
                    value[name],
                    child,
                    depth=depth + 1,
                    nodes=nodes,
                )
        return projected
    if isinstance(value, tuple):
        if "array" not in types:
            raise validation_error("mcp_projected_result_type_mismatch")
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise validation_error("mcp_projected_result_schema_invalid")
        maximum_items = schema.get("maxItems")
        if type(maximum_items) is not int or len(value) > maximum_items:
            raise validation_error("mcp_projected_result_array_too_large")
        return tuple(
            _project_json_value(
                item,
                items,
                depth=depth + 1,
                nodes=nodes,
            )
            for item in value
        )
    if isinstance(value, bool):
        valid = "boolean" in types
    elif isinstance(value, int):
        valid = "integer" in types or "number" in types
    elif isinstance(value, (float, Decimal)):
        valid = "number" in types
    elif isinstance(value, str):
        maximum_length = schema.get("maxLength")
        valid = (
            "string" in types
            and type(maximum_length) is int
            and len(value) <= maximum_length
        )
    else:
        valid = False
    if not valid:
        raise validation_error("mcp_projected_result_type_mismatch")
    return value


__all__ = [
    "IDENTITY_ARGUMENT_MAPPING_REVISION",
    "SCHEMA_PROJECT_RESULT_MAPPING_REVISION",
    "STRUCTURED_RESULT_MAPPING_REVISION",
    "McpCapabilityProvider",
]
