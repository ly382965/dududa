from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from dududa.domain.primitives import JsonValue
from dududa.errors import DududaError
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.ports.mcp import (
    McpCallerContext,
    McpSchemaValidator,
    McpServerRegistry,
    McpTransportError,
    McpTransportSession,
    McpTransportSessionFactory,
)

from .contracts import (
    MAX_ARGUMENT_BYTES,
    McpCallContext,
    McpDispatchState,
    McpHealthStatus,
    McpOperationSemantics,
    McpSchemaSnapshot,
    McpServerDefinition,
    McpServerHealth,
    McpToolDescriptor,
    McpToolResult,
    McpTransportFailureKind,
    McpTransportPhase,
    McpTransportToolResult,
    freeze_mcp_json,
)
from .digests import (
    mcp_schema_snapshot_digest,
    mcp_tool_request_digest,
    mcp_tool_result_digest,
    mcp_tool_schema_facts_digest,
)
from .errors import McpClientError, McpFailureKind, mcp_client_error

_T = TypeVar("_T")


@dataclass(slots=True)
class _Generation:
    number: int
    session: McpTransportSession
    semaphore: asyncio.Semaphore
    close_timeout: timedelta
    schema: McpSchemaSnapshot | None = None
    active_calls: int = 0
    retired: bool = False
    closed: bool = False
    close_lock: asyncio.Lock | None = None

    def __post_init__(self) -> None:
        self.close_lock = asyncio.Lock()


class _ServerState:
    def __init__(self, definition: McpServerDefinition) -> None:
        self.definition = definition
        self.lock = asyncio.Lock()
        self.generation_counter = 0
        self.current: _Generation | None = None
        self.generations: list[_Generation] = []
        self.last_good_schema: McpSchemaSnapshot | None = None
        self.status = McpHealthStatus.INITIALIZING
        self.reason_codes: tuple[str, ...] = ()
        self.failures: deque[float] = deque()
        self.circuit_open_until_tick: float | None = None
        self.half_open_in_flight = False
        self.last_monotonic: float | None = None
        self.last_wall: datetime | None = None


class ManagedUnifiedMcpClient:
    """Governed multi-Server MCP lifecycle and Schema authority."""

    def __init__(
        self,
        registry: McpServerRegistry,
        session_factory: McpTransportSessionFactory,
        schema_validator: McpSchemaValidator,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        id_factory: Callable[[], str] | None = None,
        cleanup_timeout: float = 2.0,
    ) -> None:
        if not isinstance(registry, McpServerRegistry):
            raise TypeError("registry must implement McpServerRegistry")
        if not isinstance(session_factory, McpTransportSessionFactory):
            raise TypeError("session_factory must implement McpTransportSessionFactory")
        if not isinstance(schema_validator, McpSchemaValidator):
            raise TypeError("schema_validator must implement McpSchemaValidator")
        if not isinstance(cleanup_timeout, (int, float)) or cleanup_timeout <= 0:
            raise ValueError("cleanup_timeout must be positive")
        self._registry = registry
        self._session_factory = session_factory
        self._schema_validator = schema_validator
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._cleanup_timeout = float(cleanup_timeout)
        self._states: dict[str, _ServerState] = {}
        self._cleanup_tasks: set[asyncio.Future[object]] = set()
        self._close_lock = asyncio.Lock()
        self._closed = False

    async def discover(
        self,
        server_id: str,
        *,
        refresh: bool = False,
        call: McpCallerContext,
    ) -> McpSchemaSnapshot:
        return await self._run_public(
            self._discover(server_id, refresh=refresh, call=call)
        )

    async def _discover(
        self,
        server_id: str,
        *,
        refresh: bool = False,
        call: McpCallerContext,
    ) -> McpSchemaSnapshot:
        now = self._now()
        self._validate_caller(call, now)
        definition = self._definition(server_id)
        state = self._state(definition)
        async with state.lock:
            self._validate_state_clocks(state, now)
            await self._sync_definition_locked(state, definition)
            current = state.current
            schema = current.schema if current is not None else None
            if (
                not refresh
                and schema is not None
                and schema.expires_at > now
                and not current.retired
                and not current.session.is_closed
            ):
                return schema
            return await self._open_and_discover_locked(state, call)

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: JsonValue,
        *,
        call: McpCallContext,
    ) -> McpToolResult:
        return await self._run_public(
            self._call_tool(server_id, tool_name, arguments, call=call)
        )

    async def _call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: JsonValue,
        *,
        call: McpCallContext,
    ) -> McpToolResult:
        now = self._now()
        if not isinstance(call, McpCallContext):
            raise mcp_client_error(
                McpFailureKind.ARGUMENT_INVALID,
                "invalid_mcp_call_context",
            )
        self._validate_caller(call.caller, now)
        if call.caller.budget.tool_steps_remaining < 1:
            raise mcp_client_error(
                McpFailureKind.BUDGET_EXHAUSTED,
                "mcp_tool_budget_exhausted",
            )
        frozen_arguments = self._validate_arguments_size(arguments)
        definition = self._definition(server_id)
        initial_schema = await self.discover(server_id, call=call.caller)
        descriptor = self._validate_call_binding(
            definition,
            initial_schema,
            tool_name,
            frozen_arguments,
            call,
        )
        attempts = min(
            definition.retry.maximum_attempts,
            1 + call.caller.budget.retries_remaining,
        )
        retry_eligible = (
            call.semantics
            in {
                McpOperationSemantics.READ_ONLY,
                McpOperationSemantics.IDEMPOTENT,
            }
            or call.business_idempotency_key is not None
        )
        last_failure: McpClientError | None = None
        for attempt in range(attempts):
            state = self._state(definition)
            generation = await self._acquire_generation(
                state,
                definition,
                initial_schema,
                call.caller,
            )
            transport_failure: McpTransportError | None = None
            result: McpTransportToolResult | None = None
            try:
                result = await self._await_operation(
                    generation.session.call_tool(
                        tool_name,
                        frozen_arguments,
                        call=call,
                    ),
                    call.caller,
                    definition.timeouts.call,
                    phase=McpTransportPhase.CALL,
                    dispatch_state=McpDispatchState.UNKNOWN,
                )
            except McpTransportError as exc:
                transport_failure = exc
            except McpClientError as exc:
                if exc.info.outcome_unknown:
                    await self._invalidate_generation(
                        state,
                        generation,
                        "call_outcome_unknown",
                    )
                await self._release_generation(state, generation)
                raise exc
            if transport_failure is None:
                try:
                    normalized = self._normalize_result(
                        result,
                        descriptor,
                        generation,
                        server_id,
                        tool_name,
                        call,
                    )
                except McpClientError:
                    await self._invalidate_generation(
                        state,
                        generation,
                        "result_validation_failed",
                    )
                    await self._release_generation(state, generation)
                    raise
                await self._release_generation(state, generation)
                await self._mark_call_success(state, generation)
                return normalized

            await self._invalidate_generation(
                state,
                generation,
                self._transport_failure_reason(transport_failure),
                transport_failure=transport_failure,
            )
            await self._release_generation(state, generation)
            last_failure = self._map_transport_failure(transport_failure)
            may_retry = (
                retry_eligible
                and attempt + 1 < attempts
                and transport_failure.dispatch_state is McpDispatchState.NOT_DISPATCHED
                and transport_failure.failure_kind
                in {
                    McpTransportFailureKind.UNAVAILABLE,
                    McpTransportFailureKind.TIMEOUT,
                }
            )
            if not may_retry:
                raise last_failure
            await self._await_backoff(definition.retry.base_delay, call.caller)
            await self.discover(server_id, refresh=True, call=call.caller)
        if last_failure is not None:  # pragma: no cover - loop always returns or raises
            raise last_failure
        raise mcp_client_error(McpFailureKind.INTERNAL, "mcp_attempt_state_invalid")

    async def health(
        self,
        server_id: str,
        *,
        call: McpCallerContext,
    ) -> McpServerHealth:
        return await self._run_public(self._health(server_id, call=call))

    async def _health(
        self,
        server_id: str,
        *,
        call: McpCallerContext,
    ) -> McpServerHealth:
        now = self._now()
        self._validate_caller(call, now)
        definition = self._definition(
            server_id,
            require_enabled=False,
            allow_closed=True,
        )
        state = self._state(definition)
        async with state.lock:
            self._validate_state_clocks(state, now)
            await self._sync_definition_locked(state, definition)
            status = state.status
            current = state.current
            if current is not None and current.session.is_closed:
                current.retired = True
                state.current = None
                state.status = McpHealthStatus.UNAVAILABLE
                state.reason_codes = ("transport_session_closed",)
                current = None
            schema = current.schema if current is not None else state.last_good_schema
            if status is McpHealthStatus.HEALTHY and (
                schema is None or schema.expires_at <= now
            ):
                status = McpHealthStatus.STALE
            open_until = self._circuit_wall_deadline(state, now)
            if open_until is not None:
                status = McpHealthStatus.CIRCUIT_OPEN
            if self._closed:
                status = McpHealthStatus.CLOSED
            return McpServerHealth(
                schema_version=1,
                server_id=server_id,
                config_revision=definition.config_revision,
                generation=state.generation_counter,
                status=status,
                schema_snapshot_id=None if schema is None else schema.snapshot_id,
                observed_at=now,
                circuit_open_until=open_until,
                reason_codes=state.reason_codes,
            )

    async def close(self) -> None:
        await self._run_public(self._close())

    async def _close(self) -> None:
        async with self._close_lock:
            self._closed = True
            generations: list[_Generation] = []
            for state in self._states.values():
                async with state.lock:
                    if state.current is not None:
                        state.current.retired = True
                        state.current = None
                    state.status = McpHealthStatus.CLOSED
                    state.reason_codes = ()
                    generations.extend(
                        item for item in state.generations if not item.closed
                    )
            failures = 0
            for generation in generations:
                if not await self._close_generation(generation, force=True):
                    failures += 1
            if not await self._settle_cleanup_tasks():
                failures += 1
            if failures:
                raise mcp_client_error(
                    McpFailureKind.TRANSPORT_UNAVAILABLE,
                    "mcp_close_failed",
                    "bounded_close_failed",
                )

    async def _run_public(self, operation: Awaitable[_T]) -> _T:
        failure: McpClientError | None = None
        try:
            return await operation
        except asyncio.CancelledError:
            failure = mcp_client_error(
                McpFailureKind.CANCELLED,
                "mcp_operation_cancelled",
                "caller_task_cancelled",
            )
        except McpClientError as caught:
            failure = mcp_client_error(
                caught.failure_kind,
                caught.info.code,
                *caught.info.reason_codes,
                outcome_unknown=caught.info.outcome_unknown,
            )
        except McpTransportError as caught:
            failure = self._map_transport_failure(caught)
        except Exception:
            failure = mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_internal_boundary_failure",
                "external_callback_failed",
            )
        raise failure

    def _definition(
        self,
        server_id: str,
        *,
        require_enabled: bool = True,
        allow_closed: bool = False,
    ) -> McpServerDefinition:
        if self._closed and not allow_closed:
            raise mcp_client_error(McpFailureKind.CLOSED, "mcp_client_closed")
        snapshot = self._registry.acquire_snapshot()
        try:
            definition = self._registry.resolve_server(snapshot, server_id)
        except DududaError as exc:
            raise mcp_client_error(
                McpFailureKind.NOT_FOUND,
                "mcp_server_not_found",
                "unknown_server_id",
            ) from exc
        if require_enabled and not definition.enabled:
            raise mcp_client_error(
                McpFailureKind.DISABLED,
                "mcp_server_disabled",
                "server_disabled",
            )
        return definition

    def _state(self, definition: McpServerDefinition) -> _ServerState:
        state = self._states.get(definition.server_id)
        if state is None:
            state = _ServerState(definition)
            self._states[definition.server_id] = state
        return state

    async def _sync_definition_locked(
        self,
        state: _ServerState,
        definition: McpServerDefinition,
    ) -> None:
        if state.definition.definition_digest == definition.definition_digest:
            return
        generation = self._retire_current_locked(state)
        state.definition = definition
        state.status = McpHealthStatus.INITIALIZING
        state.reason_codes = ("configuration_changed",)
        state.failures.clear()
        state.circuit_open_until_tick = None
        state.half_open_in_flight = False
        if generation is not None:
            await self._close_generation(generation)

    async def _open_and_discover_locked(
        self,
        state: _ServerState,
        call: McpCallerContext,
    ) -> McpSchemaSnapshot:
        self._admit_circuit_locked(state)
        was_half_open = state.half_open_in_flight
        retired = self._retire_current_locked(state)
        if retired is not None:
            await self._close_generation(retired)
        state.generation_counter += 1
        generation_number = state.generation_counter
        definition = state.definition
        state.status = McpHealthStatus.INITIALIZING
        state.reason_codes = ()
        generation: _Generation | None = None
        try:
            session = await self._await_operation(
                self._session_factory.open(
                    definition,
                    generation_number,
                    call=call,
                ),
                call,
                definition.timeouts.connect,
                phase=McpTransportPhase.CONNECT,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
            if (
                not isinstance(session, McpTransportSession)
                or session.server_id != definition.server_id
                or session.generation != generation_number
                or session.is_closed
            ):
                raise McpTransportError(
                    McpTransportFailureKind.PROTOCOL,
                    "invalid_session_identity",
                    phase=McpTransportPhase.CONNECT,
                    dispatch_state=McpDispatchState.NOT_DISPATCHED,
                )
            generation = _Generation(
                number=generation_number,
                session=session,
                semaphore=asyncio.Semaphore(definition.maximum_concurrency),
                close_timeout=definition.timeouts.close,
            )
            state.generations.append(generation)
            discovered = await self._await_operation(
                session.discover(call=call),
                call,
                definition.timeouts.discovery,
                phase=McpTransportPhase.DISCOVERY,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
            tools = self._validate_discovery(definition, discovered)
            previous = state.last_good_schema
            if (
                previous is not None
                and previous.definition_digest == definition.definition_digest
            ):
                if not _allowlisted_schema_compatible(
                    previous.tools, tools, definition.allowed_tools
                ):
                    state.status = McpHealthStatus.STALE
                    state.reason_codes = ("allowlisted_schema_incompatible",)
                    generation.retired = True
                    await self._close_generation(generation)
                    raise mcp_client_error(
                        McpFailureKind.SCHEMA_INCOMPATIBLE,
                        "mcp_schema_incompatible",
                        "allowlisted_schema_changed",
                    )
            observed_at = self._now()
            facts_digest = mcp_tool_schema_facts_digest(tools)
            snapshot = McpSchemaSnapshot(
                schema_version=1,
                snapshot_id=self._new_id("mcp-schema"),
                snapshot_digest=mcp_schema_snapshot_digest(
                    definition.server_id,
                    definition.config_revision,
                    definition.definition_digest,
                    generation_number,
                    tools,
                ),
                server_id=definition.server_id,
                config_revision=definition.config_revision,
                definition_digest=definition.definition_digest,
                schema_facts_digest=facts_digest,
                generation=generation_number,
                tools=tools,
                observed_at=observed_at,
                expires_at=observed_at + definition.schema_ttl,
            )
            generation.schema = snapshot
            state.current = generation
            state.last_good_schema = snapshot
            state.status = McpHealthStatus.HEALTHY
            state.reason_codes = ()
            if was_half_open:
                state.failures.clear()
            state.circuit_open_until_tick = None
            state.half_open_in_flight = False
            return snapshot
        except McpClientError:
            if generation is not None:
                generation.retired = True
                await self._close_generation(generation)
            if state.status is McpHealthStatus.INITIALIZING:
                state.status = McpHealthStatus.UNAVAILABLE
                state.reason_codes = ("schema_publication_failed",)
            state.half_open_in_flight = False
            raise
        except McpTransportError as exc:
            if generation is not None:
                generation.retired = True
                await self._close_generation(generation)
            self._record_transport_failure_locked(
                state,
                self._transport_failure_reason(exc),
            )
            raise self._map_transport_failure(exc) from None

    def _validate_discovery(
        self,
        definition: McpServerDefinition,
        discovered: object,
    ) -> tuple[McpToolDescriptor, ...]:
        if (
            not isinstance(discovered, tuple)
            or not discovered
            or not all(isinstance(item, McpToolDescriptor) for item in discovered)
        ):
            raise mcp_client_error(
                McpFailureKind.SCHEMA_UNAVAILABLE,
                "invalid_mcp_discovery_result",
                "tool_facts_invalid",
            )
        tools = tuple(sorted(discovered, key=lambda item: item.name))
        names = tuple(item.name for item in tools)
        if len(names) != len(set(names)):
            raise mcp_client_error(
                McpFailureKind.SCHEMA_UNAVAILABLE,
                "invalid_mcp_discovery_result",
                "duplicate_tool_name",
            )
        missing = definition.allowed_tools - frozenset(names)
        if missing:
            raise mcp_client_error(
                McpFailureKind.SCHEMA_UNAVAILABLE,
                "mcp_allowed_tool_missing",
                "allowlisted_tool_absent",
            )
        try:
            for descriptor in tools:
                self._schema_validator.check_schema(
                    descriptor.input_schema,
                    schema_id=f"mcp.{definition.server_id}.{descriptor.name}.input",
                )
                if descriptor.output_schema is not None:
                    self._schema_validator.check_schema(
                        descriptor.output_schema,
                        schema_id=f"mcp.{definition.server_id}.{descriptor.name}.output",
                    )
        except BaseException as exc:
            raise mcp_client_error(
                McpFailureKind.SCHEMA_UNAVAILABLE,
                "invalid_mcp_tool_schema",
                "schema_validator_rejected",
            ) from exc
        return tools

    def _validate_call_binding(
        self,
        definition: McpServerDefinition,
        schema: McpSchemaSnapshot,
        tool_name: str,
        arguments: JsonValue,
        call: McpCallContext,
    ) -> McpToolDescriptor:
        if (
            tool_name not in definition.allowed_tools
            or tool_name in definition.denied_tools
        ):
            raise mcp_client_error(
                McpFailureKind.TOOL_FORBIDDEN,
                "mcp_tool_forbidden",
                "transport_allowlist_denied",
            )
        if (
            call.schema_snapshot_id != schema.snapshot_id
            or call.schema_snapshot_digest != schema.snapshot_digest
        ):
            raise mcp_client_error(
                McpFailureKind.SCHEMA_STALE,
                "mcp_schema_binding_mismatch",
                "expected_snapshot_not_current",
            )
        expected_request_digest = mcp_tool_request_digest(
            definition.server_id,
            tool_name,
            arguments,
            schema,
            call.semantics,
            call.business_idempotency_key,
        )
        if call.request_digest != expected_request_digest:
            raise mcp_client_error(
                McpFailureKind.ARGUMENT_INVALID,
                "mcp_request_digest_mismatch",
                "request_binding_invalid",
            )
        descriptor = next(
            (item for item in schema.tools if item.name == tool_name), None
        )
        if descriptor is None:
            raise mcp_client_error(
                McpFailureKind.SCHEMA_STALE,
                "mcp_tool_schema_missing",
                "allowlisted_tool_absent",
            )
        try:
            validated = self._schema_validator.validate(
                arguments,
                descriptor.input_schema,
                schema_id=f"mcp.{definition.server_id}.{tool_name}.input",
            )
        except BaseException as exc:
            raise mcp_client_error(
                McpFailureKind.ARGUMENT_INVALID,
                "mcp_arguments_invalid",
                "input_schema_rejected",
            ) from exc
        if validated != arguments:
            raise mcp_client_error(
                McpFailureKind.ARGUMENT_INVALID,
                "mcp_arguments_transformed",
                "validator_must_not_transform",
            )
        return descriptor

    async def _acquire_generation(
        self,
        state: _ServerState,
        definition: McpServerDefinition,
        initial_schema: McpSchemaSnapshot,
        call: McpCallerContext,
    ) -> _Generation:
        while True:
            async with state.lock:
                if state.definition.definition_digest != definition.definition_digest:
                    raise mcp_client_error(
                        McpFailureKind.SCHEMA_STALE,
                        "mcp_definition_changed",
                        "configuration_changed",
                    )
                generation = state.current
                if generation is None or generation.schema is None:
                    raise mcp_client_error(
                        McpFailureKind.SCHEMA_UNAVAILABLE,
                        "mcp_session_unavailable",
                        "generation_missing",
                    )
                if (
                    generation.schema.schema_facts_digest
                    != initial_schema.schema_facts_digest
                ):
                    raise mcp_client_error(
                        McpFailureKind.SCHEMA_STALE,
                        "mcp_schema_changed",
                        "schema_facts_changed",
                    )
            await self._await_operation(
                generation.semaphore.acquire(),
                call,
                definition.timeouts.maximum_call,
                phase=McpTransportPhase.CALL,
                dispatch_state=McpDispatchState.NOT_DISPATCHED,
            )
            async with state.lock:
                if generation is state.current and not generation.retired:
                    generation.active_calls += 1
                    return generation
            generation.semaphore.release()

    async def _release_generation(
        self,
        state: _ServerState,
        generation: _Generation,
    ) -> None:
        should_close = False
        async with state.lock:
            if generation.active_calls > 0:
                generation.active_calls -= 1
                generation.semaphore.release()
            should_close = generation.retired and generation.active_calls == 0
        if should_close:
            await self._close_generation(generation)

    async def _invalidate_generation(
        self,
        state: _ServerState,
        generation: _Generation,
        reason: str,
        *,
        transport_failure: McpTransportError | None = None,
    ) -> None:
        async with state.lock:
            generation.retired = True
            if state.current is generation:
                state.current = None
            state.status = McpHealthStatus.UNAVAILABLE
            state.reason_codes = (reason,)
            if transport_failure is not None:
                self._record_transport_failure_locked(state, reason)

    async def _mark_call_success(
        self,
        state: _ServerState,
        generation: _Generation,
    ) -> None:
        async with state.lock:
            if state.current is generation and not generation.retired:
                state.status = McpHealthStatus.HEALTHY
                state.reason_codes = ()

    def _normalize_result(
        self,
        result: McpTransportToolResult | None,
        descriptor: McpToolDescriptor,
        generation: _Generation,
        server_id: str,
        tool_name: str,
        call: McpCallContext,
    ) -> McpToolResult:
        if not isinstance(result, McpTransportToolResult) or generation.schema is None:
            raise mcp_client_error(
                McpFailureKind.RESULT_INVALID,
                "invalid_mcp_tool_result",
                "transport_result_invalid",
            )
        if not result.is_error and descriptor.output_schema is not None:
            if result.structured_content is None:
                raise mcp_client_error(
                    McpFailureKind.RESULT_INVALID,
                    "mcp_structured_result_missing",
                    "output_schema_requires_structured_content",
                )
            try:
                validated = self._schema_validator.validate(
                    result.structured_content,
                    descriptor.output_schema,
                    schema_id=f"mcp.{server_id}.{tool_name}.output",
                )
            except BaseException as exc:
                raise mcp_client_error(
                    McpFailureKind.RESULT_INVALID,
                    "mcp_result_schema_invalid",
                    "output_schema_rejected",
                ) from exc
            if validated != result.structured_content:
                raise mcp_client_error(
                    McpFailureKind.RESULT_INVALID,
                    "mcp_result_transformed",
                    "validator_must_not_transform",
                )
        schema = generation.schema
        digest = mcp_tool_result_digest(
            server_id,
            tool_name,
            generation.number,
            schema.snapshot_id,
            schema.snapshot_digest,
            call.request_digest,
            result.is_error,
            result.structured_content,
            result.content,
        )
        return McpToolResult(
            schema_version=1,
            server_id=server_id,
            tool_name=tool_name,
            generation=generation.number,
            schema_snapshot_id=schema.snapshot_id,
            schema_snapshot_digest=schema.snapshot_digest,
            request_digest=call.request_digest,
            result_digest=digest,
            is_error=result.is_error,
            structured_content=result.structured_content,
            content=result.content,
            total_size_bytes=result.total_size_bytes,
        )

    def _validate_arguments_size(self, arguments: JsonValue) -> JsonValue:
        try:
            return freeze_mcp_json(
                arguments,
                "mcp_arguments",
                maximum_bytes=MAX_ARGUMENT_BYTES,
            )
        except DududaError as exc:
            raise mcp_client_error(
                McpFailureKind.ARGUMENT_INVALID,
                "mcp_arguments_out_of_bounds",
                "argument_bounds_exceeded",
            ) from exc

    async def _await_backoff(
        self,
        delay: timedelta,
        call: McpCallerContext,
    ) -> None:
        if delay <= timedelta(0):
            self._validate_caller(call, self._now())
            return
        await self._await_operation(
            self._sleep(delay.total_seconds()),
            call,
            delay + timedelta(seconds=self._cleanup_timeout),
            phase=McpTransportPhase.CONNECT,
            dispatch_state=McpDispatchState.NOT_DISPATCHED,
        )

    async def _await_operation(
        self,
        operation: Awaitable[_T],
        call: McpCallerContext,
        timeout: timedelta,
        *,
        phase: McpTransportPhase,
        dispatch_state: McpDispatchState,
    ) -> _T:
        now = self._now()
        self._validate_caller(call, now)
        remaining = min(timeout.total_seconds(), (call.deadline - now).total_seconds())
        if remaining <= 0:
            if hasattr(operation, "close"):
                operation.close()  # type: ignore[union-attr]
            raise self._phase_stop_error("deadline_before_operation", dispatch_state)
        try:
            operation_task = asyncio.ensure_future(operation)
            cancellation_task = asyncio.ensure_future(call.cancellation.wait())
        except BaseException as exc:
            if hasattr(operation, "close"):
                operation.close()  # type: ignore[union-attr]
            raise mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_operation_start_failed",
                "task_creation_failed",
            ) from exc
        try:
            done, _ = await asyncio.wait(
                (operation_task, cancellation_task),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation_task in done:
                return operation_task.result()
            if cancellation_task in done:
                try:
                    cancellation_task.result()
                except BaseException as exc:
                    await self._cancel_task(operation_task)
                    raise mcp_client_error(
                        McpFailureKind.INTERNAL,
                        "mcp_cancellation_watch_failed",
                        "cancellation_token_failed",
                        outcome_unknown=dispatch_state
                        is not McpDispatchState.NOT_DISPATCHED,
                    ) from exc
                await self._cancel_task(operation_task)
                raise self._phase_stop_error("operation_cancelled", dispatch_state)
            await self._cancel_task(operation_task)
            raise self._phase_stop_error(
                "operation_timed_out", dispatch_state, timeout=True
            )
        except asyncio.CancelledError:
            await self._cancel_task(operation_task)
            raise self._phase_stop_error(
                "caller_task_cancelled", dispatch_state
            ) from None
        except McpTransportError:
            raise
        except McpClientError:
            raise
        except Exception as exc:
            raise McpTransportError(
                McpTransportFailureKind.INTERNAL,
                "adapter_protocol_exception",
                phase=phase,
                dispatch_state=dispatch_state,
            ) from exc
        finally:
            await self._cancel_task(cancellation_task)

    def _phase_stop_error(
        self,
        reason: str,
        dispatch_state: McpDispatchState,
        *,
        timeout: bool = False,
    ) -> McpClientError:
        unknown = dispatch_state is not McpDispatchState.NOT_DISPATCHED
        return mcp_client_error(
            McpFailureKind.TIMEOUT if timeout else McpFailureKind.CANCELLED,
            "mcp_operation_timeout" if timeout else "mcp_operation_cancelled",
            reason,
            outcome_unknown=unknown,
        )

    async def _cancel_task(self, task: asyncio.Future[object]) -> None:
        if task.done():
            _consume_future(task)
            return
        task.cancel()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._cleanup_timeout
        while not task.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait((task,), timeout=remaining)
            except asyncio.CancelledError:
                continue
        if task.done():
            _consume_future(task)
            return
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)
        task.add_done_callback(_consume_future)

    async def _settle_cleanup_tasks(self) -> bool:
        pending = tuple(task for task in self._cleanup_tasks if not task.done())
        if not pending:
            return True
        for task in pending:
            task.cancel()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._cleanup_timeout
        while any(not task.done() for task in pending):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait(pending, timeout=remaining)
            except asyncio.CancelledError:
                continue
        for task in pending:
            if task.done():
                _consume_future(task)
        return all(task.done() for task in pending)

    def _retire_current_locked(self, state: _ServerState) -> _Generation | None:
        generation = state.current
        if generation is None:
            return None
        generation.retired = True
        state.current = None
        return generation if generation.active_calls == 0 else None

    async def _close_generation(
        self,
        generation: _Generation,
        *,
        force: bool = False,
    ) -> bool:
        if generation.closed:
            return True
        if generation.active_calls and not force:
            return True
        assert generation.close_lock is not None
        async with generation.close_lock:
            if generation.closed:
                return True
            try:
                await asyncio.wait_for(
                    generation.session.close(),
                    timeout=generation.close_timeout.total_seconds(),
                )
            except BaseException:
                return False
            generation.closed = True
            return True

    def _record_transport_failure_locked(
        self,
        state: _ServerState,
        reason: str,
    ) -> None:
        tick = self._state_tick(state)
        policy = state.definition.circuit
        cutoff = tick - policy.failure_window.total_seconds()
        while state.failures and state.failures[0] < cutoff:
            state.failures.popleft()
        state.failures.append(tick)
        if state.half_open_in_flight or len(state.failures) >= policy.failure_threshold:
            state.circuit_open_until_tick = tick + policy.open_duration.total_seconds()
            state.status = McpHealthStatus.CIRCUIT_OPEN
            state.reason_codes = ("circuit_open", reason)
        else:
            state.status = McpHealthStatus.UNAVAILABLE
            state.reason_codes = (reason,)
        state.half_open_in_flight = False

    def _admit_circuit_locked(self, state: _ServerState) -> None:
        tick = self._state_tick(state)
        open_until = state.circuit_open_until_tick
        if open_until is None:
            return
        if tick < open_until or state.half_open_in_flight:
            state.status = McpHealthStatus.CIRCUIT_OPEN
            state.reason_codes = ("circuit_open",)
            raise mcp_client_error(
                McpFailureKind.CIRCUIT_OPEN,
                "mcp_circuit_open",
                "server_circuit_open",
            )
        state.half_open_in_flight = True

    def _circuit_wall_deadline(
        self,
        state: _ServerState,
        now: datetime,
    ) -> datetime | None:
        if state.circuit_open_until_tick is None:
            return None
        remaining = state.circuit_open_until_tick - self._state_tick(state)
        if remaining <= 0:
            return None
        return now + timedelta(seconds=remaining)

    def _state_tick(self, state: _ServerState) -> float:
        tick = self._monotonic_clock()
        if not isinstance(tick, (int, float)):
            raise mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_monotonic_clock_invalid",
            )
        value = float(tick)
        if state.last_monotonic is not None and value < state.last_monotonic:
            state.status = McpHealthStatus.UNAVAILABLE
            state.reason_codes = ("monotonic_clock_rollback",)
            raise mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_monotonic_clock_rollback",
                "clock_rollback",
            )
        state.last_monotonic = value
        return value

    def _validate_state_clocks(self, state: _ServerState, now: datetime) -> None:
        if state.last_wall is not None and now < state.last_wall:
            state.status = McpHealthStatus.UNAVAILABLE
            state.reason_codes = ("wall_clock_rollback",)
            raise mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_wall_clock_rollback",
                "clock_rollback",
            )
        state.last_wall = now
        self._state_tick(state)

    def _map_transport_failure(self, failure: McpTransportError) -> McpClientError:
        reason = self._transport_failure_reason(failure)
        if failure.dispatch_state is not McpDispatchState.NOT_DISPATCHED:
            return mcp_client_error(
                McpFailureKind.OUTCOME_UNKNOWN,
                "mcp_tool_outcome_unknown",
                reason,
                outcome_unknown=True,
            )
        kind = {
            McpTransportFailureKind.TIMEOUT: McpFailureKind.TIMEOUT,
            McpTransportFailureKind.CANCELLED: McpFailureKind.CANCELLED,
            McpTransportFailureKind.CLOSED: McpFailureKind.CLOSED,
            McpTransportFailureKind.PROTOCOL: McpFailureKind.TRANSPORT_UNAVAILABLE,
            McpTransportFailureKind.UNAVAILABLE: McpFailureKind.TRANSPORT_UNAVAILABLE,
            McpTransportFailureKind.INTERNAL: McpFailureKind.INTERNAL,
        }[failure.failure_kind]
        return mcp_client_error(kind, "mcp_transport_failure", reason)

    @staticmethod
    def _transport_failure_reason(failure: McpTransportError) -> str:
        return (
            f"transport_{failure.failure_kind.value}_"
            f"{failure.phase.value}_{failure.dispatch_state.value}"
        )

    def _validate_caller(self, call: McpCallerContext, now: datetime) -> None:
        if not isinstance(call, (PortCallContext, ServiceCallContext)):
            raise mcp_client_error(
                McpFailureKind.ARGUMENT_INVALID,
                "invalid_mcp_caller_context",
            )
        try:
            cancelled = call.cancellation.is_cancelled
        except BaseException as exc:
            raise mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_cancellation_token_failed",
            ) from exc
        if cancelled:
            raise mcp_client_error(
                McpFailureKind.CANCELLED,
                "mcp_call_cancelled",
                "cancelled_before_operation",
            )
        if now >= call.deadline:
            raise mcp_client_error(
                McpFailureKind.TIMEOUT,
                "mcp_call_deadline_exceeded",
                "deadline_before_operation",
            )

    def _now(self) -> datetime:
        now = self._wall_clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_wall_clock_invalid",
            )
        return now

    def _new_id(self, prefix: str) -> str:
        value = self._id_factory()
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(item.isspace() for item in value)
        ):
            raise mcp_client_error(
                McpFailureKind.INTERNAL,
                "mcp_id_factory_invalid",
            )
        return f"{prefix}:{value}"


def _allowlisted_schema_compatible(
    previous: tuple[McpToolDescriptor, ...],
    candidate: tuple[McpToolDescriptor, ...],
    allowlist: frozenset[str],
) -> bool:
    old = {item.name: item for item in previous}
    new = {item.name: item for item in candidate}
    return all(
        name in old
        and name in new
        and old[name].input_schema == new[name].input_schema
        and old[name].output_schema == new[name].output_schema
        for name in allowlist
    )


def _consume_future(future: asyncio.Future[object]) -> None:
    try:
        future.result()
    except BaseException:
        pass
