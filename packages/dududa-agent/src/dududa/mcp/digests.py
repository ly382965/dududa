from __future__ import annotations

from collections.abc import Iterable

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString, JsonValue

from .contracts import (
    McpContentBlock,
    McpOperationSemantics,
    McpSchemaSnapshot,
    McpServerDefinition,
    McpToolDescriptor,
)


def mcp_server_definition_digest(
    definition: McpServerDefinition | dict[str, object],
) -> DigestString:
    value: object
    if isinstance(definition, McpServerDefinition):
        value = {
            "schema_version": definition.schema_version,
            "server_id": definition.server_id,
            "enabled": definition.enabled,
            "transport": definition.transport,
            "protocol_mode": definition.protocol_mode,
            "endpoint": definition.endpoint,
            "secret_refs": definition.secret_refs,
            "allowed_tools": definition.allowed_tools,
            "denied_tools": definition.denied_tools,
            "timeouts": definition.timeouts,
            "retry": definition.retry,
            "circuit": definition.circuit,
            "maximum_concurrency": definition.maximum_concurrency,
            "schema_ttl": definition.schema_ttl,
            "config_revision": definition.config_revision,
        }
    else:
        value = definition
    return canonical_digest(value, domain="mcp.server-definition:v1")


def mcp_registry_digest(definitions: Iterable[McpServerDefinition]) -> DigestString:
    return canonical_digest(
        tuple(
            (item.server_id, item.config_revision, item.definition_digest)
            for item in sorted(definitions, key=lambda definition: definition.server_id)
        ),
        domain="mcp.registry:v1",
    )


def mcp_schema_snapshot_digest(
    server_id: str,
    config_revision: str,
    definition_digest: DigestString,
    generation: int,
    tools: Iterable[McpToolDescriptor],
) -> DigestString:
    ordered_tools = tuple(sorted(tools, key=lambda item: item.name))
    return canonical_digest(
        {
            "server_id": server_id,
            "config_revision": config_revision,
            "definition_digest": definition_digest,
            "schema_facts_digest": mcp_tool_schema_facts_digest(ordered_tools),
            "generation": generation,
            "tools": ordered_tools,
        },
        domain="mcp.schema-snapshot:v1",
    )


def mcp_tool_request_digest(
    server_id: str,
    tool_name: str,
    arguments: JsonValue,
    schema_snapshot: McpSchemaSnapshot,
    semantics: McpOperationSemantics,
    business_idempotency_key: str | None,
) -> DigestString:
    return canonical_digest(
        {
            "server_id": server_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "schema_snapshot_id": schema_snapshot.snapshot_id,
            "schema_snapshot_digest": schema_snapshot.snapshot_digest,
            "semantics": semantics,
            "business_idempotency_key": business_idempotency_key,
        },
        domain="mcp.tool-request:v1",
    )


def mcp_tool_result_digest(
    server_id: str,
    tool_name: str,
    generation: int,
    schema_snapshot_id: str,
    schema_snapshot_digest: DigestString,
    request_digest: DigestString,
    is_error: bool,
    structured_content: JsonValue | None,
    content: Iterable[McpContentBlock],
) -> DigestString:
    return canonical_digest(
        {
            "server_id": server_id,
            "tool_name": tool_name,
            "generation": generation,
            "schema_snapshot_id": schema_snapshot_id,
            "schema_snapshot_digest": schema_snapshot_digest,
            "request_digest": request_digest,
            "is_error": is_error,
            "structured_content": structured_content,
            "content": tuple(content),
        },
        domain="mcp.tool-result:v1",
    )


def mcp_tool_schema_facts_digest(
    tools: Iterable[McpToolDescriptor],
) -> DigestString:
    return canonical_digest(
        tuple(
            {
                "name": item.name,
                "input_schema": item.input_schema,
                "output_schema": item.output_schema,
            }
            for item in sorted(tools, key=lambda item: item.name)
        ),
        domain="mcp.tool-schema-facts:v1",
    )
