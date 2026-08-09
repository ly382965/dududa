from .contracts import (
    MAX_ARGUMENT_BYTES,
    MAX_CONTENT_BLOCKS,
    MAX_CONTENT_BYTES,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_SCHEMA_BYTES,
    MAX_SCHEMA_SNAPSHOT_BYTES,
    McpCallContext,
    McpCircuitPolicy,
    McpContentBlock,
    McpContentKind,
    McpDispatchState,
    McpHealthStatus,
    McpHttpEndpoint,
    McpOperationSemantics,
    McpProtocolMode,
    McpRegistrySnapshot,
    McpRetryPolicy,
    McpSchemaSnapshot,
    McpSecretRef,
    McpSecretTarget,
    McpServerDefinition,
    McpServerHealth,
    McpStdioEndpoint,
    McpTimeoutPolicy,
    McpToolDescriptor,
    McpToolResult,
    McpTransportFailureKind,
    McpTransportKind,
    McpTransportPhase,
    McpTransportToolResult,
    freeze_mcp_json,
)
from .digests import (
    mcp_registry_digest,
    mcp_schema_snapshot_digest,
    mcp_server_definition_digest,
    mcp_tool_request_digest,
    mcp_tool_result_digest,
    mcp_tool_schema_facts_digest,
)
from .errors import McpClientError, McpFailureKind, mcp_client_error, mcp_error_info
from .registry import ConfigMcpServerRegistry

__all__ = [
    "MAX_ARGUMENT_BYTES",
    "MAX_CONTENT_BLOCKS",
    "MAX_CONTENT_BYTES",
    "MAX_JSON_DEPTH",
    "MAX_JSON_NODES",
    "MAX_SCHEMA_BYTES",
    "MAX_SCHEMA_SNAPSHOT_BYTES",
    "ConfigMcpServerRegistry",
    "McpCallContext",
    "McpClientError",
    "McpCircuitPolicy",
    "McpContentBlock",
    "McpContentKind",
    "McpDispatchState",
    "McpHealthStatus",
    "McpFailureKind",
    "McpHttpEndpoint",
    "McpOperationSemantics",
    "McpProtocolMode",
    "McpRegistrySnapshot",
    "McpRetryPolicy",
    "McpSchemaSnapshot",
    "McpSecretRef",
    "McpSecretTarget",
    "McpServerDefinition",
    "McpServerHealth",
    "McpStdioEndpoint",
    "McpTimeoutPolicy",
    "McpToolDescriptor",
    "McpToolResult",
    "McpTransportKind",
    "McpTransportFailureKind",
    "McpTransportPhase",
    "McpTransportToolResult",
    "ManagedUnifiedMcpClient",
    "SubprocessMcpV2Session",
    "SubprocessMcpV2SessionFactory",
    "freeze_mcp_json",
    "mcp_registry_digest",
    "mcp_client_error",
    "mcp_error_info",
    "mcp_schema_snapshot_digest",
    "mcp_server_definition_digest",
    "mcp_tool_request_digest",
    "mcp_tool_result_digest",
    "mcp_tool_schema_facts_digest",
]


def __getattr__(name: str) -> object:
    if name == "ManagedUnifiedMcpClient":
        from .client import ManagedUnifiedMcpClient

        return ManagedUnifiedMcpClient
    if name in {"SubprocessMcpV2Session", "SubprocessMcpV2SessionFactory"}:
        from .subprocess_v2 import (
            SubprocessMcpV2Session,
            SubprocessMcpV2SessionFactory,
        )

        return {
            "SubprocessMcpV2Session": SubprocessMcpV2Session,
            "SubprocessMcpV2SessionFactory": SubprocessMcpV2SessionFactory,
        }[name]
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
