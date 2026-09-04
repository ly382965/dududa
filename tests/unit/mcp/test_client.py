from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from dududa.contracts.canonical import canonical_json_bytes
from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.mcp import (
    ManagedUnifiedMcpClient,
    McpCallContext,
    McpCircuitPolicy,
    McpClientError,
    McpContentBlock,
    McpContentKind,
    McpDispatchState,
    McpFailureKind,
    McpOperationSemantics,
    McpRegistrySnapshot,
    McpTransportFailureKind,
    McpTransportPhase,
    McpTransportToolResult,
    mcp_registry_digest,
    mcp_tool_request_digest,
)
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
)
from dududa.ports.mcp import McpTransportError
from dududa.testing import (
    FakeMcpSessionPlan,
    RecordingFakeMcpSessionFactory,
    RecordingMcpSchemaValidator,
)

from .helpers import (
    NOW,
    replace_server_definition,
    server_definition,
    tool_descriptor,
)


class _StaticRegistry:
    def __init__(self, definition) -> None:
        self.replace(definition)

    def replace(self, definition) -> None:
        definitions = (definition,)
        digest = mcp_registry_digest(definitions)
        self.snapshot = McpRegistrySnapshot(
            schema_version=1,
            snapshot_id=f"registry:{definition.config_revision}",
            registry_revision=str(digest),
            registry_digest=digest,
            definitions=definitions,
            acquired_at=NOW,
        )

    def acquire_snapshot(self):
        return self.snapshot

    def resolve_server(self, snapshot, server_id):
        if (
            snapshot != self.snapshot
            or server_id != self.snapshot.definitions[0].server_id
        ):
            raise ValueError("unknown server")
        return self.snapshot.definitions[0]

    async def reload(self, *, call: ServiceCallContext):
        return self.snapshot


@dataclass
class _Clock:
    wall: datetime = NOW
    monotonic: float = 100.0

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.monotonic += seconds


class _RejectOutputValidator(RecordingMcpSchemaValidator):
    def validate(self, value, schema, *, schema_id):
        if schema_id.endswith(".output"):
            raise ValueError("synthetic output rejection")
        return super().validate(value, schema, schema_id=schema_id)


def exception_graph_text(error: BaseException) -> str:
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    values: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        values.extend((str(current), repr(current)))
        for related in (current.__cause__, current.__context__):
            if isinstance(related, BaseException):
                pending.append(related)
    return "\n".join(values)


def transport_result(value: str = "ok") -> McpTransportToolResult:
    structured = {"value": value}
    text = value
    return McpTransportToolResult(
        schema_version=1,
        is_error=False,
        structured_content=structured,
        content=(
            McpContentBlock(
                schema_version=1,
                kind=McpContentKind.TEXT,
                text=text,
                mime_type="text/plain",
                uri=None,
                data_digest=None,
                size_bytes=len(text.encode("utf-8")),
            ),
        ),
        total_size_bytes=len(canonical_json_bytes(structured))
        + len(text.encode("utf-8")),
    )


def caller(
    *,
    cancellation=None,
    retries: int = 1,
    deadline: datetime | None = None,
) -> PortCallContext:
    return PortCallContext(
        run_id="run-mcp",
        trace=TraceContext("trace-mcp"),
        deadline=deadline or NOW + timedelta(minutes=2),
        cancellation=cancellation or NeverCancelled(),
        budget=RuntimeBudget(0, 4, retries, 0, 0, Decimal("0")),
        policy_snapshot_id="policy-v1",
    )


def tool_call(
    schema,
    arguments=None,
    *,
    call_context=None,
    semantics=McpOperationSemantics.READ_ONLY,
    idempotency_key=None,
) -> McpCallContext:
    arguments = arguments or {"value": "hello"}
    call_context = call_context or caller()
    digest = mcp_tool_request_digest(
        schema.server_id,
        "echo",
        arguments,
        schema,
        semantics,
        idempotency_key,
    )
    return McpCallContext(
        schema_version=1,
        caller=call_context,
        schema_snapshot_id=schema.snapshot_id,
        schema_snapshot_digest=schema.snapshot_digest,
        request_digest=digest,
        semantics=semantics,
        business_idempotency_key=idempotency_key,
    )


def transport_error(
    code: str,
    *,
    dispatch_state=McpDispatchState.NOT_DISPATCHED,
) -> McpTransportError:
    return McpTransportError(
        McpTransportFailureKind.UNAVAILABLE,
        code,
        phase=McpTransportPhase.CALL,
        dispatch_state=dispatch_state,
    )


class ManagedUnifiedMcpClientTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, plans, *, definition=None, clock=None, validator=None):
        definition = definition or server_definition()
        registry = _StaticRegistry(definition)
        factory = RecordingFakeMcpSessionFactory(plans)
        validator = validator or RecordingMcpSchemaValidator()
        clock = clock or _Clock()
        ids = iter(f"schema-{index}" for index in range(1, 100))
        client = ManagedUnifiedMcpClient(
            registry,
            factory,
            validator,
            wall_clock=lambda: clock.wall,
            monotonic_clock=lambda: clock.monotonic,
            id_factory=lambda: next(ids),
        )
        return client, registry, factory, validator, clock

    async def test_long_session_and_cached_discovery_are_reused(self) -> None:
        plan = FakeMcpSessionPlan(
            tools=(tool_descriptor(),),
            call_outcomes=(transport_result("one"), transport_result("two")),
        )
        client, _, factory, validator, _ = self.fixture((plan,))
        schema = await client.discover("fake-a", call=caller())
        self.assertIs(await client.discover("fake-a", call=caller()), schema)

        first = await client.call_tool(
            "fake-a", "echo", {"value": "hello"}, call=tool_call(schema)
        )
        second = await client.call_tool(
            "fake-a", "echo", {"value": "hello"}, call=tool_call(schema)
        )
        self.assertEqual((first.generation, second.generation), (1, 1))
        self.assertEqual(len(factory.open_calls), 1)
        self.assertEqual(len(factory.sessions[0].discover_calls), 1)
        self.assertEqual(len(factory.sessions[0].call_records), 2)
        self.assertGreaterEqual(len(validator.checked), 2)

        await client.close()
        await client.close()
        self.assertEqual(factory.sessions[0].close_calls, 1)
        health = await client.health("fake-a", call=caller())
        self.assertEqual(health.status.value, "closed")

    async def test_closed_transport_is_immediately_unavailable(self) -> None:
        client, _, factory, _, _ = self.fixture((FakeMcpSessionPlan(tools=(tool_descriptor(),)),))
        await client.discover("fake-a", call=caller())
        await factory.sessions[0].close()
        health = await client.health("fake-a", call=caller())
        self.assertEqual(health.status.value, "unavailable")
        self.assertEqual(health.reason_codes, ("transport_session_closed",))
        self.assertEqual(len(factory.open_calls), 1)
        await client.close()

    async def test_invalid_discovery_closes_unpublished_session(self) -> None:
        plan = FakeMcpSessionPlan(tools=(tool_descriptor("other"),))
        client, _, factory, _, _ = self.fixture((plan,))
        with self.assertRaises(McpClientError) as captured:
            await client.discover("fake-a", call=caller())
        self.assertEqual(
            captured.exception.failure_kind,
            McpFailureKind.SCHEMA_UNAVAILABLE,
        )
        self.assertTrue(factory.sessions[0].is_closed)

    async def test_configuration_change_retires_old_generation(self) -> None:
        plans = (
            FakeMcpSessionPlan(tools=(tool_descriptor(),)),
            FakeMcpSessionPlan(tools=(tool_descriptor(),)),
        )
        client, registry, factory, _, _ = self.fixture(plans)
        first = await client.discover("fake-a", call=caller())
        changed = replace_server_definition(
            registry.snapshot.definitions[0],
            config_revision="config-v2",
            maximum_concurrency=3,
        )
        registry.replace(changed)
        second = await client.discover("fake-a", call=caller())
        self.assertEqual((first.generation, second.generation), (1, 2))
        self.assertNotEqual(first.definition_digest, second.definition_digest)
        self.assertTrue(factory.sessions[0].is_closed)

    async def test_expired_schema_reconnects_and_retires_old_generation(self) -> None:
        plans = (
            FakeMcpSessionPlan(tools=(tool_descriptor(),)),
            FakeMcpSessionPlan(tools=(tool_descriptor(),)),
        )
        clock = _Clock()
        client, _, factory, _, _ = self.fixture(plans, clock=clock)
        first = await client.discover("fake-a", call=caller())
        clock.advance(301)
        second = await client.discover(
            "fake-a",
            call=caller(deadline=clock.wall + timedelta(minutes=1)),
        )
        self.assertEqual((first.generation, second.generation), (1, 2))
        self.assertTrue(factory.sessions[0].is_closed)

    async def test_schema_extension_is_compatible_but_allowlisted_drift_fails(
        self,
    ) -> None:
        plans = (
            FakeMcpSessionPlan(tools=(tool_descriptor(),)),
            FakeMcpSessionPlan(
                tools=(tool_descriptor(), tool_descriptor("extra")),
            ),
            FakeMcpSessionPlan(tools=(tool_descriptor(value_type="integer"),)),
        )
        client, _, factory, _, _ = self.fixture(plans)
        first = await client.discover("fake-a", call=caller())
        extended = await client.discover("fake-a", refresh=True, call=caller())
        self.assertNotEqual(first.schema_facts_digest, extended.schema_facts_digest)
        self.assertEqual(extended.generation, 2)

        with self.assertRaises(McpClientError) as captured:
            await client.discover("fake-a", refresh=True, call=caller())
        self.assertEqual(
            captured.exception.failure_kind, McpFailureKind.SCHEMA_INCOMPATIBLE
        )
        health = await client.health("fake-a", call=caller())
        self.assertEqual(health.status.value, "stale")
        self.assertEqual(health.schema_snapshot_id, extended.snapshot_id)
        self.assertTrue(factory.sessions[2].is_closed)

    async def test_forbidden_tool_never_reaches_transport(self) -> None:
        plan = FakeMcpSessionPlan(tools=(tool_descriptor(),))
        client, _, factory, _, _ = self.fixture((plan,))
        schema = await client.discover("fake-a", call=caller())
        call = tool_call(schema)
        with self.assertRaises(McpClientError) as captured:
            await client.call_tool("fake-a", "admin", {}, call=call)
        self.assertEqual(captured.exception.failure_kind, McpFailureKind.TOOL_FORBIDDEN)
        self.assertEqual(factory.sessions[0].call_records, [])

    async def test_only_pre_dispatch_failure_retries_with_same_request_digest(
        self,
    ) -> None:
        plans = (
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(transport_error("worker_died_before_dispatch"),),
            ),
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(transport_result("retried"),),
            ),
        )
        client, _, factory, _, _ = self.fixture(plans)
        schema = await client.discover("fake-a", call=caller())
        call = tool_call(schema)
        result = await client.call_tool("fake-a", "echo", {"value": "hello"}, call=call)
        self.assertEqual(result.generation, 2)
        self.assertEqual(result.request_digest, call.request_digest)
        self.assertEqual(len(factory.sessions), 2)
        self.assertEqual(len(factory.sessions[0].call_records), 1)
        self.assertEqual(len(factory.sessions[1].call_records), 1)

    async def test_dispatched_failure_is_unknown_and_never_retried(self) -> None:
        plans = (
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(
                    transport_error(
                        "worker_died_after_dispatch",
                        dispatch_state=McpDispatchState.DISPATCHED,
                    ),
                ),
            ),
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(transport_result("must-not-run"),),
            ),
        )
        client, _, factory, _, _ = self.fixture(plans)
        schema = await client.discover("fake-a", call=caller())
        with self.assertRaises(McpClientError) as captured:
            await client.call_tool(
                "fake-a", "echo", {"value": "hello"}, call=tool_call(schema)
            )
        self.assertEqual(
            captured.exception.failure_kind, McpFailureKind.OUTCOME_UNKNOWN
        )
        self.assertTrue(captured.exception.info.outcome_unknown)
        self.assertEqual(len(factory.sessions), 1)

    async def test_non_idempotent_call_without_key_never_retries(self) -> None:
        plans = (
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(transport_error("pre_dispatch_failure"),),
            ),
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(transport_result("must-not-run"),),
            ),
        )
        client, _, factory, _, _ = self.fixture(plans)
        schema = await client.discover("fake-a", call=caller())
        with self.assertRaises(McpClientError):
            await client.call_tool(
                "fake-a",
                "echo",
                {"value": "hello"},
                call=tool_call(
                    schema,
                    semantics=McpOperationSemantics.NON_IDEMPOTENT,
                ),
            )
        self.assertEqual(len(factory.sessions), 1)

    async def test_output_schema_rejection_retires_generation(self) -> None:
        plan = FakeMcpSessionPlan(
            tools=(tool_descriptor(),),
            call_outcomes=(transport_result(),),
        )
        validator = _RejectOutputValidator()
        client, _, factory, _, _ = self.fixture((plan,), validator=validator)
        schema = await client.discover("fake-a", call=caller())
        with self.assertRaises(McpClientError) as captured:
            await client.call_tool(
                "fake-a",
                "echo",
                {"value": "hello"},
                call=tool_call(schema),
            )
        self.assertEqual(
            captured.exception.failure_kind,
            McpFailureKind.RESULT_INVALID,
        )
        self.assertTrue(factory.sessions[0].is_closed)

    async def test_per_server_concurrency_limit_is_hard(self) -> None:
        release = asyncio.Event()
        started = asyncio.Event()
        plan = FakeMcpSessionPlan(
            tools=(tool_descriptor(),),
            call_outcomes=(
                transport_result("1"),
                transport_result("2"),
                transport_result("3"),
            ),
            call_started=started,
            call_release=release,
        )
        client, _, factory, _, _ = self.fixture((plan,))
        schema = await client.discover("fake-a", call=caller())
        call = tool_call(schema)
        tasks = tuple(
            asyncio.create_task(
                client.call_tool("fake-a", "echo", {"value": "hello"}, call=call)
            )
            for _ in range(3)
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertEqual(factory.sessions[0].active_calls, 2)
        release.set()
        await asyncio.gather(*tasks)
        self.assertEqual(factory.sessions[0].maximum_active_calls, 2)

    async def test_cancellation_during_call_is_unknown_and_closes_generation(
        self,
    ) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        plan = FakeMcpSessionPlan(
            tools=(tool_descriptor(),),
            call_outcomes=(transport_result(),),
            call_started=started,
            call_release=release,
        )
        client, _, factory, _, _ = self.fixture((plan,))
        token = ManualCancellationToken()
        call_context = caller(cancellation=token)
        schema = await client.discover("fake-a", call=call_context)
        invocation = asyncio.create_task(
            client.call_tool(
                "fake-a",
                "echo",
                {"value": "hello"},
                call=tool_call(schema, call_context=call_context),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        token.cancel()
        with self.assertRaises(McpClientError) as captured:
            await invocation
        self.assertTrue(captured.exception.info.outcome_unknown)
        self.assertTrue(factory.sessions[0].is_closed)

    async def test_semaphore_wait_can_cancel_before_dispatch_without_retiring(
        self,
    ) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        definition = replace_server_definition(
            server_definition(),
            maximum_concurrency=1,
        )
        plan = FakeMcpSessionPlan(
            tools=(tool_descriptor(),),
            call_outcomes=(transport_result("first"), transport_result("second")),
            call_started=started,
            call_release=release,
        )
        client, _, factory, _, _ = self.fixture((plan,), definition=definition)
        schema = await client.discover("fake-a", call=caller())
        first = asyncio.create_task(
            client.call_tool(
                "fake-a",
                "echo",
                {"value": "hello"},
                call=tool_call(schema),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        token = ManualCancellationToken()
        second_context = caller(cancellation=token)
        second = asyncio.create_task(
            client.call_tool(
                "fake-a",
                "echo",
                {"value": "hello"},
                call=tool_call(schema, call_context=second_context),
            )
        )
        await asyncio.sleep(0)
        token.cancel()
        with self.assertRaises(McpClientError) as captured:
            await second
        self.assertFalse(captured.exception.info.outcome_unknown)
        self.assertFalse(factory.sessions[0].is_closed)
        release.set()
        await first

    async def test_circuit_opens_and_one_half_open_probe_recovers(self) -> None:
        definition = replace_server_definition(
            server_definition(),
            retry=replace_server_definition(server_definition()).retry,
            circuit=McpCircuitPolicy(
                failure_threshold=3,
                failure_window=timedelta(seconds=60),
                open_duration=timedelta(seconds=10),
            ),
        )
        plans = tuple(
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(transport_error(f"failure-{index}"),),
            )
            for index in range(3)
        ) + (FakeMcpSessionPlan(tools=(tool_descriptor(),)),)
        clock = _Clock()
        client, _, factory, _, _ = self.fixture(
            plans, definition=definition, clock=clock
        )
        for _ in range(3):
            schema = await client.discover("fake-a", call=caller(retries=0))
            with self.assertRaises(McpClientError):
                await client.call_tool(
                    "fake-a",
                    "echo",
                    {"value": "hello"},
                    call=tool_call(schema, call_context=caller(retries=0)),
                )
        with self.assertRaises(McpClientError) as opened:
            await client.discover("fake-a", call=caller())
        self.assertEqual(opened.exception.failure_kind, McpFailureKind.CIRCUIT_OPEN)

        clock.advance(11)
        recovered = await client.discover("fake-a", call=caller())
        self.assertEqual(recovered.generation, 4)
        self.assertEqual(len(factory.sessions), 4)

    async def test_only_one_half_open_discovery_runs(self) -> None:
        definition = replace_server_definition(
            server_definition(),
            circuit=McpCircuitPolicy(
                failure_threshold=1,
                failure_window=timedelta(seconds=60),
                open_duration=timedelta(seconds=10),
            ),
        )
        probe_started = asyncio.Event()
        probe_release = asyncio.Event()
        plans = (
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                call_outcomes=(transport_error("failure"),),
            ),
            FakeMcpSessionPlan(
                tools=(tool_descriptor(),),
                discovery_started=probe_started,
                discovery_release=probe_release,
            ),
        )
        clock = _Clock()
        client, _, factory, _, _ = self.fixture(
            plans,
            definition=definition,
            clock=clock,
        )
        schema = await client.discover("fake-a", call=caller(retries=0))
        with self.assertRaises(McpClientError):
            await client.call_tool(
                "fake-a",
                "echo",
                {"value": "hello"},
                call=tool_call(schema, call_context=caller(retries=0)),
            )
        clock.advance(11)
        calls = tuple(
            asyncio.create_task(
                client.discover(
                    "fake-a",
                    call=caller(deadline=clock.wall + timedelta(minutes=1)),
                )
            )
            for _ in range(2)
        )
        await asyncio.wait_for(probe_started.wait(), timeout=1)
        self.assertEqual(len(factory.sessions), 2)
        probe_release.set()
        first, second = await asyncio.gather(*calls)
        self.assertIs(first, second)
        self.assertEqual(len(factory.sessions), 2)

    async def test_wall_clock_rollback_fails_closed(self) -> None:
        plan = FakeMcpSessionPlan(tools=(tool_descriptor(),))
        clock = _Clock()
        client, _, _, _, _ = self.fixture((plan,), clock=clock)
        await client.discover("fake-a", call=caller())
        clock.wall -= timedelta(seconds=1)
        with self.assertRaises(McpClientError) as captured:
            await client.health(
                "fake-a",
                call=caller(deadline=NOW + timedelta(minutes=1)),
            )
        self.assertEqual(captured.exception.failure_kind, McpFailureKind.INTERNAL)

    async def test_transport_codes_never_enter_public_error_or_health(self) -> None:
        sentinels = (
            "https://mcp.example.test/?token=secret",
            "/private/worker/command",
            "stderr-secret-sentinel",
            "Bearer-secret-sentinel",
        )
        for sentinel in sentinels:
            with self.subTest(sentinel=sentinel):
                plan = FakeMcpSessionPlan(
                    tools=(tool_descriptor(),),
                    call_outcomes=(transport_error(sentinel),),
                )
                client, _, _, _, _ = self.fixture((plan,))
                schema = await client.discover("fake-a", call=caller(retries=0))
                with self.assertRaises(McpClientError) as captured:
                    await client.call_tool(
                        "fake-a",
                        "echo",
                        {"value": "hello"},
                        call=tool_call(
                            schema,
                            call_context=caller(retries=0),
                        ),
                    )
                error = captured.exception
                health = await client.health("fake-a", call=caller())
                evidence = "\n".join(
                    (
                        exception_graph_text(error),
                        repr(error.info),
                        repr(health),
                    )
                )
                self.assertNotIn(sentinel, evidence)
                self.assertIsNone(error.__cause__)
                self.assertIsNone(error.__context__)
                await client.close()

    async def test_external_clock_exception_is_sanitized(self) -> None:
        sentinel = "clock-secret-sentinel"

        def broken_clock() -> datetime:
            raise RuntimeError(sentinel)

        definition = server_definition()
        client = ManagedUnifiedMcpClient(
            _StaticRegistry(definition),
            RecordingFakeMcpSessionFactory(
                (FakeMcpSessionPlan(tools=(tool_descriptor(),)),)
            ),
            RecordingMcpSchemaValidator(),
            wall_clock=broken_clock,
        )
        with self.assertRaises(McpClientError) as captured:
            await client.discover("fake-a", call=caller())
        error = captured.exception
        self.assertNotIn(sentinel, exception_graph_text(error))
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)


if __name__ == "__main__":
    unittest.main()
