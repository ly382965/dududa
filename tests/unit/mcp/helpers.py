from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from dududa.mcp import (
    McpCircuitPolicy,
    McpProtocolMode,
    McpRetryPolicy,
    McpServerDefinition,
    McpStdioEndpoint,
    McpTimeoutPolicy,
    McpToolDescriptor,
    McpTransportKind,
    mcp_server_definition_digest,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def server_document(
    server_id: str = "fake-a",
    *,
    config_revision: str = "config-v1",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "server_id": server_id,
        "enabled": True,
        "transport": "stdio",
        "protocol_mode": "auto",
        "endpoint": {
            "command": "/usr/bin/python3",
            "args": ["-m", "fake_mcp"],
            "cwd": "/tmp",
            "env_allowlist": ["PATH"],
        },
        "secret_refs": [],
        "allowed_tools": ["echo"],
        "denied_tools": ["admin"],
        "timeouts_seconds": {
            "connect": 2,
            "discovery": 2,
            "call": 3,
            "maximum_call": 5,
            "close": 1,
        },
        "retry": {"maximum_attempts": 2, "base_delay_ms": 10},
        "circuit": {
            "failure_threshold": 3,
            "failure_window_seconds": 60,
            "open_duration_seconds": 10,
        },
        "maximum_concurrency": 2,
        "schema_ttl_seconds": 300,
        "config_revision": config_revision,
    }


def server_definition(
    server_id: str = "fake-a",
    *,
    config_revision: str = "config-v1",
) -> McpServerDefinition:
    values = {
        "schema_version": 1,
        "server_id": server_id,
        "enabled": True,
        "transport": McpTransportKind.STDIO,
        "protocol_mode": McpProtocolMode.AUTO,
        "endpoint": McpStdioEndpoint(
            command="/usr/bin/python3",
            args=("-m", "fake_mcp"),
            cwd="/tmp",
            env_allowlist=frozenset({"PATH"}),
        ),
        "secret_refs": (),
        "allowed_tools": frozenset({"echo"}),
        "denied_tools": frozenset({"admin"}),
        "timeouts": McpTimeoutPolicy(
            connect=timedelta(seconds=2),
            discovery=timedelta(seconds=2),
            call=timedelta(seconds=3),
            maximum_call=timedelta(seconds=5),
            close=timedelta(seconds=1),
        ),
        "retry": McpRetryPolicy(
            maximum_attempts=2,
            base_delay=timedelta(milliseconds=10),
        ),
        "circuit": McpCircuitPolicy(
            failure_threshold=3,
            failure_window=timedelta(minutes=1),
            open_duration=timedelta(seconds=10),
        ),
        "maximum_concurrency": 2,
        "schema_ttl": timedelta(minutes=5),
        "config_revision": config_revision,
    }
    return McpServerDefinition(
        **values,
        definition_digest=mcp_server_definition_digest(values),
    )


def replace_server_definition(
    definition: McpServerDefinition,
    **changes: Any,
) -> McpServerDefinition:
    values = {
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
    values.update(changes)
    return McpServerDefinition(
        **values,
        definition_digest=mcp_server_definition_digest(values),
    )


def tool_descriptor(
    name: str = "echo",
    *,
    value_type: str = "string",
) -> McpToolDescriptor:
    return McpToolDescriptor(
        schema_version=1,
        name=name,
        description="Returns the supplied value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": value_type}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        annotations={"readOnlyHint": True},
    )
