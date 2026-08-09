from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dududa.domain.primitives import JsonValue, freeze_json
from dududa.mcp import (
    McpServerDefinition,
    McpToolDescriptor,
    McpTransportToolResult,
)
from dududa.ports.mcp import McpCallerContext, McpTransportError

FakeMcpCallOutcome = McpTransportToolResult | McpTransportError


@dataclass(frozen=True, slots=True)
class FakeMcpSessionPlan:
    tools: tuple[McpToolDescriptor, ...]
    call_outcomes: tuple[FakeMcpCallOutcome, ...] = ()
    discovery_error: McpTransportError | None = None
    close_error: McpTransportError | None = None
    discovery_started: asyncio.Event | None = None
    discovery_release: asyncio.Event | None = None
    call_started: asyncio.Event | None = None
    call_release: asyncio.Event | None = None

    def __post_init__(self) -> None:
        tools = tuple(self.tools)
        if not all(isinstance(item, McpToolDescriptor) for item in tools):
            raise TypeError("invalid fake MCP tools")
        outcomes = tuple(self.call_outcomes)
        if not all(
            isinstance(item, (McpTransportToolResult, McpTransportError))
            for item in outcomes
        ):
            raise TypeError("invalid fake MCP call outcome")
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "call_outcomes", outcomes)


FakeMcpOpenOutcome = FakeMcpSessionPlan | McpTransportError


class RecordingFakeMcpSession:
    def __init__(
        self,
        definition: McpServerDefinition,
        generation: int,
        plan: FakeMcpSessionPlan,
    ) -> None:
        self._server_id = definition.server_id
        self._generation = generation
        self._plan = plan
        self._outcomes = deque(plan.call_outcomes)
        self.discover_calls: list[McpCallerContext] = []
        self.call_records: list[tuple[str, JsonValue, object]] = []
        self.close_calls = 0
        self.active_calls = 0
        self.maximum_active_calls = 0
        self._closed = False

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def discover(
        self,
        *,
        call: McpCallerContext,
    ) -> tuple[McpToolDescriptor, ...]:
        if self._closed:
            raise RuntimeError("fake MCP session is closed")
        self.discover_calls.append(call)
        if self._plan.discovery_started is not None:
            self._plan.discovery_started.set()
        if self._plan.discovery_release is not None:
            await self._plan.discovery_release.wait()
        if self._plan.discovery_error is not None:
            raise self._plan.discovery_error
        return self._plan.tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: JsonValue,
        *,
        call,
    ) -> McpTransportToolResult:
        if self._closed:
            raise RuntimeError("fake MCP session is closed")
        self.call_records.append((tool_name, freeze_json(arguments), call))
        self.active_calls += 1
        self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
        try:
            if self._plan.call_started is not None:
                self._plan.call_started.set()
            if self._plan.call_release is not None:
                await self._plan.call_release.wait()
            if not self._outcomes:
                raise RuntimeError("fake MCP call outcome script exhausted")
            outcome = self._outcomes.popleft()
            if isinstance(outcome, McpTransportError):
                raise outcome
            return outcome
        finally:
            self.active_calls -= 1

    async def close(self) -> None:
        self.close_calls += 1
        if self._plan.close_error is not None:
            raise self._plan.close_error
        self._closed = True


class RecordingFakeMcpSessionFactory:
    def __init__(self, outcomes: Iterable[FakeMcpOpenOutcome]) -> None:
        self._outcomes = deque(outcomes)
        self.open_calls: list[tuple[McpServerDefinition, int, McpCallerContext]] = []
        self.sessions: list[RecordingFakeMcpSession] = []

    async def open(
        self,
        definition: McpServerDefinition,
        generation: int,
        *,
        call: McpCallerContext,
    ) -> RecordingFakeMcpSession:
        self.open_calls.append((definition, generation, call))
        if not self._outcomes:
            raise RuntimeError("fake MCP open outcome script exhausted")
        outcome = self._outcomes.popleft()
        if isinstance(outcome, McpTransportError):
            raise outcome
        session = RecordingFakeMcpSession(definition, generation, outcome)
        self.sessions.append(session)
        return session


class RecordingMcpSchemaValidator:
    def __init__(self) -> None:
        self.checked: list[tuple[Mapping[str, JsonValue], str]] = []
        self.validated: list[tuple[JsonValue, Mapping[str, JsonValue], str]] = []

    def check_schema(
        self,
        schema: Mapping[str, JsonValue],
        *,
        schema_id: str,
    ) -> None:
        self.checked.append((schema, schema_id))

    def validate(
        self,
        value: JsonValue,
        schema: Mapping[str, JsonValue],
        *,
        schema_id: str,
    ) -> JsonValue:
        frozen = freeze_json(value)
        self.validated.append((frozen, schema, schema_id))
        return frozen


class MappingMcpSecretResolver:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self.resolved: list[object] = []

    async def resolve(self, reference, *, call: McpCallerContext) -> str:
        self.resolved.append(reference)
        return self._values[reference.secret_id]


class MappingMcpEnvironmentProvider:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self.requests: list[frozenset[str]] = []

    def select(self, allowlist: frozenset[str]) -> Mapping[str, str]:
        self.requests.append(allowlist)
        return {key: self._values[key] for key in allowlist if key in self._values}
