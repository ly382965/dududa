from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from dududa.domain.primitives import JsonValue
from dududa.mcp.contracts import (
    McpCallContext,
    McpDispatchState,
    McpRegistrySnapshot,
    McpSchemaSnapshot,
    McpSecretRef,
    McpServerDefinition,
    McpServerHealth,
    McpToolDescriptor,
    McpToolResult,
    McpTransportFailureKind,
    McpTransportPhase,
    McpTransportToolResult,
)
from dududa.ports.context import PortCallContext, ServiceCallContext

McpCallerContext = PortCallContext | ServiceCallContext


class McpTransportError(Exception):
    """Sanitized session failure; raw SDK and process errors stop at adapters."""

    def __init__(
        self,
        failure_kind: McpTransportFailureKind,
        code: str,
        *,
        phase: McpTransportPhase,
        dispatch_state: McpDispatchState,
    ) -> None:
        if not isinstance(failure_kind, McpTransportFailureKind):
            raise TypeError("invalid MCP transport failure kind")
        if (
            not isinstance(code, str)
            or not code
            or any(item.isspace() for item in code)
        ):
            raise ValueError("invalid MCP transport error code")
        if not isinstance(phase, McpTransportPhase):
            raise TypeError("invalid MCP transport phase")
        if not isinstance(dispatch_state, McpDispatchState):
            raise TypeError("invalid MCP dispatch state")
        super().__init__(code)
        self.code = code
        self.failure_kind = failure_kind
        self.phase = phase
        self.dispatch_state = dispatch_state


@runtime_checkable
class UnifiedMcpClient(Protocol):
    async def discover(
        self,
        server_id: str,
        *,
        refresh: bool = False,
        call: McpCallerContext,
    ) -> McpSchemaSnapshot: ...

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: JsonValue,
        *,
        call: McpCallContext,
    ) -> McpToolResult: ...

    async def health(
        self,
        server_id: str,
        *,
        call: McpCallerContext,
    ) -> McpServerHealth: ...

    async def close(self) -> None: ...


@runtime_checkable
class McpServerRegistry(Protocol):
    def acquire_snapshot(self) -> McpRegistrySnapshot: ...

    def resolve_server(
        self,
        snapshot: McpRegistrySnapshot,
        server_id: str,
    ) -> McpServerDefinition: ...

    async def reload(
        self,
        *,
        call: ServiceCallContext,
    ) -> McpRegistrySnapshot: ...


@runtime_checkable
class McpTransportSession(Protocol):
    @property
    def server_id(self) -> str: ...

    @property
    def generation(self) -> int: ...

    @property
    def is_closed(self) -> bool: ...

    async def discover(
        self,
        *,
        call: McpCallerContext,
    ) -> tuple[McpToolDescriptor, ...]: ...

    async def call_tool(
        self,
        tool_name: str,
        arguments: JsonValue,
        *,
        call: McpCallContext,
    ) -> McpTransportToolResult: ...

    async def close(self) -> None: ...


@runtime_checkable
class McpTransportSessionFactory(Protocol):
    async def open(
        self,
        definition: McpServerDefinition,
        generation: int,
        *,
        call: McpCallerContext,
    ) -> McpTransportSession: ...


@runtime_checkable
class McpSchemaValidator(Protocol):
    def check_schema(
        self,
        schema: Mapping[str, JsonValue],
        *,
        schema_id: str,
    ) -> None: ...

    def validate(
        self,
        value: JsonValue,
        schema: Mapping[str, JsonValue],
        *,
        schema_id: str,
    ) -> JsonValue: ...


@runtime_checkable
class McpSecretResolver(Protocol):
    async def resolve(
        self,
        reference: McpSecretRef,
        *,
        call: McpCallerContext,
    ) -> str: ...


@runtime_checkable
class McpEnvironmentProvider(Protocol):
    def select(self, allowlist: frozenset[str]) -> Mapping[str, str]: ...
