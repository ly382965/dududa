from __future__ import annotations

import asyncio
import itertools
import unittest
from datetime import timedelta

from dududa.capabilities import (
    CapabilityRetrievalResult,
    CapabilityRunRequest,
    CapabilityRunStatus,
    DeterministicArgumentBinder,
    DeterministicBoundedCapabilityRuntime,
    DeterministicToolPlanner,
    DeterministicToolResultValidator,
    capability_retrieval_result_digest,
    capability_run_request_digest,
)
from dududa.domain.primitives import ResourceUsage
from dududa.ports.capabilities import BoundedCapabilityRuntime
from dududa.ports.context import ManualCancellationToken

from tests.unit.capabilities import test_executor as executor_fixtures
from tests.unit.capabilities.test_planning import SimpleSchemaValidator


class EmptyRetriever:
    def __init__(self, source) -> None:
        self.source = source

    async def retrieve(self, request, *, call):
        original = await self.source.retrieve(request, call=call)
        values = {
            "schema_version": 1,
            "request_digest": request.request_digest,
            "query_digest": request.query.query_digest,
            "candidates": (),
            "catalog_snapshot_id": original.catalog_snapshot_id,
            "catalog_digest": original.catalog_digest,
            "policy_revision": original.policy_revision,
            "health_snapshot_id": original.health_snapshot_id,
            "health_snapshot_digest": original.health_snapshot_digest,
            "retriever_revision": original.retriever_revision,
            "reason_codes": ("no_eligible_capability",),
        }
        return CapabilityRetrievalResult(
            result_digest=capability_retrieval_result_digest(values),
            **values,
        )


class InvalidPlanner:
    async def plan(self, request, *, call):
        raise RuntimeError("private planner payload /srv/planner")


class StubbornExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, request, *, call):
        self.started.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                continue


class BoundedCapabilityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = executor_fixtures.GovernedToolExecutorTests(
            methodName="test_success_reauthorizes_audits_and_calls_provider_once"
        )
        await self.fixture.asyncSetUp()
        identifiers = itertools.count()
        self.planner = DeterministicToolPlanner(
            {self.fixture.definition.capability_id: {"query": "database"}},
            clock=lambda: self.fixture.catalog.acquired_at,
            id_factory=lambda: f"runtime-plan-{next(identifiers)}",
        )
        self.binder = DeterministicArgumentBinder(self.fixture.schema_validator)
        self.result_validator = DeterministicToolResultValidator(
            self.fixture.registry,
            SimpleSchemaValidator(),
            self.fixture.plan_validator,
            clock=lambda: self.fixture.catalog.acquired_at,
        )
        self.ids = itertools.count()
        self.runtime = self._runtime()
        self.assertIsInstance(self.runtime, BoundedCapabilityRuntime)

    def _runtime(self, **changes) -> DeterministicBoundedCapabilityRuntime:
        values = {
            "registry": self.fixture.registry,
            "retriever": self._retriever(),
            "planner": self.planner,
            "plan_validator": self.fixture.plan_validator,
            "binder": self.binder,
            "executor": self.fixture.executor,
            "result_validator": self.result_validator,
            "clock": lambda: self.fixture.catalog.acquired_at,
            "id_factory": lambda: f"runtime-{next(self.ids)}",
        }
        values.update(changes)
        return DeterministicBoundedCapabilityRuntime(**values)

    def _retriever(self):
        from dududa.capabilities.retrieval import DeterministicCapabilityRetriever

        return DeterministicCapabilityRetriever(
            self.fixture.registry,
            self.fixture.health,
            self.fixture.authorization,
            self.fixture.authorization,
            clock=lambda: self.fixture.catalog.acquired_at,
        )

    def _request(self, *, maximum_attempts: int = 4) -> CapabilityRunRequest:
        source = self.fixture.retrieval_request
        values = {
            "schema_version": 1,
            "query": source.query,
            "actor": source.actor,
            "conversation_scope": source.conversation_scope,
            "data_classification": source.data_classification,
            "available_input_schemas": source.available_input_schemas,
            "maximum_attempts": maximum_attempts,
        }
        return CapabilityRunRequest(
            request_digest=capability_run_request_digest(values),
            **values,
        )

    async def test_single_step_success_completes_with_bound_receipt(self) -> None:
        receipt = await self.runtime.run(
            self._request(),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(receipt.status, CapabilityRunStatus.COMPLETED)
        self.assertEqual(len(receipt.observations), 1)
        self.assertEqual(receipt.usage.tool_steps, 1)
        self.assertEqual(len(self.fixture.provider.requests), 1)

    async def test_retryable_failure_then_success_counts_attempts(self) -> None:
        self.fixture.provider.sequence = ["failed", "success"]
        receipt = await self.runtime.run(
            self._request(maximum_attempts=2),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(receipt.status, CapabilityRunStatus.COMPLETED)
        self.assertEqual(
            tuple(item.status.value for item in receipt.observations),
            ("failed", "succeeded"),
        )
        self.assertEqual(receipt.usage.tool_steps, 2)
        self.assertEqual(receipt.usage.retries, 1)
        self.assertEqual(len(self.fixture.provider.requests), 2)

    async def test_unknown_and_attempt_exhaustion_stop_without_replan(self) -> None:
        self.fixture.provider.mode = "unknown"
        receipt = await self.runtime.run(
            self._request(maximum_attempts=4),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(receipt.status, CapabilityRunStatus.FAILED)
        self.assertEqual(len(receipt.observations), 1)
        self.assertEqual(len(self.fixture.provider.requests), 1)

        fixture = executor_fixtures.GovernedToolExecutorTests(
            methodName="test_success_reauthorizes_audits_and_calls_provider_once"
        )
        await fixture.asyncSetUp()
        fixture.provider.mode = "failed"
        runtime = self._runtime(executor=fixture.executor)
        exhausted = await runtime.run(
            self._request(maximum_attempts=1),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(exhausted.status, CapabilityRunStatus.FAILED)

    async def test_no_candidate_defers_without_plan_or_provider(self) -> None:
        empty = EmptyRetriever(self._retriever())
        runtime = self._runtime(retriever=empty)
        receipt = await runtime.run(
            self._request(),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(receipt.status, CapabilityRunStatus.DEFERRED)
        self.assertIsNone(receipt.plan)
        self.assertEqual(receipt.observations, ())
        self.assertEqual(self.fixture.provider.requests, [])

    async def test_planner_failure_is_sanitized_and_finite(self) -> None:
        runtime = self._runtime(planner=InvalidPlanner())
        receipt = await runtime.run(
            self._request(),
            call=executor_fixtures.execution_call(),
        )
        self.assertIs(receipt.status, CapabilityRunStatus.FAILED)
        self.assertEqual(receipt.observations, ())
        self.assertNotIn("planner payload", repr(receipt))

    async def test_cancellation_after_dispatch_keeps_unknown_observation(self) -> None:
        self.fixture.provider.mode = "blocked"
        cancellation = ManualCancellationToken()
        running = asyncio.create_task(
            self.runtime.run(
                self._request(),
                call=executor_fixtures.execution_call(cancellation=cancellation),
            )
        )
        await self.fixture.provider.started.wait()
        cancellation.cancel()
        receipt = await running
        self.assertIs(receipt.status, CapabilityRunStatus.CANCELLED)
        self.assertEqual(len(receipt.observations), 1)
        self.assertEqual(receipt.observations[0].status.value, "unknown")
        self.assertEqual(receipt.usage.tool_steps, 1)
        self.assertEqual(len(self.fixture.provider.requests), 1)
        self.assertIsNone(receipt.validation_request)
        self.assertIsNone(receipt.validation)

    async def test_stubborn_executor_becomes_one_conservative_unobserved_attempt(
        self,
    ) -> None:
        executor = StubbornExecutor()
        runtime = self._runtime(
            executor=executor,
            execution_terminal_grace=timedelta(milliseconds=10),
        )
        cancellation = ManualCancellationToken()
        running = asyncio.create_task(
            runtime.run(
                self._request(),
                call=executor_fixtures.execution_call(cancellation=cancellation),
            )
        )
        await executor.started.wait()
        cancellation.cancel()
        receipt = await asyncio.wait_for(running, timeout=1)
        self.assertIs(receipt.status, CapabilityRunStatus.CANCELLED)
        self.assertEqual(receipt.observations, ())
        self.assertEqual(len(receipt.unobserved_attempts), 1)
        self.assertTrue(receipt.unobserved_attempts[0].outcome_unknown)
        self.assertEqual(receipt.usage.tool_steps, 1)
        self.assertIsNone(receipt.validation_request)
        self.assertIsNone(receipt.validation)
        executor.release.set()
        await asyncio.sleep(0)

    async def test_zero_call_budget_defers_at_retrieval(self) -> None:
        call = executor_fixtures.execution_call(tool_steps=0)
        receipt = await self.runtime.run(self._request(), call=call)
        self.assertIs(receipt.status, CapabilityRunStatus.DEFERRED)
        self.assertEqual(
            receipt.usage, ResourceUsage(1, cost_units=receipt.usage.cost_units)
        )


if __name__ == "__main__":
    unittest.main()
