from __future__ import annotations

import itertools
import unittest
from dataclasses import replace
from decimal import Decimal

from dududa.capabilities.planning import (
    DeterministicArgumentBinder,
    DeterministicToolPlanner,
)
from dududa.capabilities.retrieval import DeterministicCapabilityRetriever
from dududa.capabilities.runtime import DeterministicBoundedCapabilityRuntime
from dududa.capabilities.validation import DeterministicToolResultValidator
from dududa.domain.primitives import Outcome, PrivacyLevel, ResourceUsage, RuntimeBudget
from dududa.runtime.budget import RuntimeModelBudgetPlan, RuntimeToolBudgetPlan
from dududa.runtime.context import CurrentMessageContextBuilder
from dududa.runtime.state import RuntimePhase

from tests.unit.capabilities import test_executor as executor_fixtures
from tests.unit.capabilities.test_planning import SimpleSchemaValidator
from tests.unit.runtime.test_orchestrator import OrchestratorFixture
from tests.unit.runtime.test_s10_context_budget import builder

from .helpers import revision


class _CountingCapabilityRuntime:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0

    async def run(self, request, *, call):
        self.calls += 1
        return await self.inner.run(request, call=call)


class _RejectThirdVerification:
    def __init__(self) -> None:
        self.delegate = None
        self.calls = 0

    def verify(self, decision, *, at=None) -> bool:
        self.calls += 1
        if self.calls == 3:
            return False
        assert self.delegate is not None
        return self.delegate.verify(decision, at=at)


async def _capability_harness(*, provider_mode: str = "success"):
    fixture = executor_fixtures.GovernedToolExecutorTests(
        methodName="test_success_reauthorizes_audits_and_calls_provider_once"
    )
    await fixture.asyncSetUp()
    fixture.provider.mode = provider_mode
    identifiers = itertools.count()
    runtime = DeterministicBoundedCapabilityRuntime(
        fixture.registry,
        DeterministicCapabilityRetriever(
            fixture.registry,
            fixture.health,
            fixture.authorization,
            fixture.authorization,
            clock=lambda: fixture.catalog.acquired_at,
        ),
        DeterministicToolPlanner(
            {fixture.definition.capability_id: {"query": "database"}},
            clock=lambda: fixture.catalog.acquired_at,
            id_factory=lambda: f"runtime-plan-{next(identifiers)}",
        ),
        fixture.plan_validator,
        DeterministicArgumentBinder(fixture.schema_validator),
        fixture.executor,
        DeterministicToolResultValidator(
            fixture.registry,
            SimpleSchemaValidator(),
            fixture.plan_validator,
            clock=lambda: fixture.catalog.acquired_at,
        ),
        clock=lambda: fixture.catalog.acquired_at,
        id_factory=lambda: f"runtime-invocation-{next(identifiers)}",
    )
    return fixture, _CountingCapabilityRuntime(runtime)


def _tool_budget(*, cost: Decimal = Decimal(10)) -> RuntimeToolBudgetPlan:
    return RuntimeToolBudgetPlan(
        schema_version=1,
        reservation=ResourceUsage(
            schema_version=1,
            tool_steps=4,
            retries=4,
            cost_units=cost,
        ),
        revision=revision("runtime-tool-budget"),
    )


def _initial_budget(*, tool_cost: Decimal = Decimal(10)) -> RuntimeBudget:
    return RuntimeBudget(
        model_calls_remaining=2,
        tool_steps_remaining=4,
        retries_remaining=6,
        # The validated tool projection is included in the direct-chat input
        # estimate.  Keep enough headroom for that projection in this fixture;
        # production budgets are configured independently by composition.
        input_tokens_remaining=5_000,
        output_tokens_remaining=700,
        cost_units_remaining=Decimal(4) + tool_cost,
    )


def _model_budget() -> RuntimeModelBudgetPlan:
    """Budget reservations large enough for the fixture's tool projection."""

    return RuntimeModelBudgetPlan(
        schema_version=1,
        perception_reservation=ResourceUsage(
            schema_version=1,
            model_calls=1,
            retries=1,
            input_tokens=1_000,
            output_tokens=200,
            cost_units=Decimal(1),
        ),
        direct_chat_reservation=ResourceUsage(
            schema_version=1,
            model_calls=1,
            retries=1,
            input_tokens=4_000,
            output_tokens=500,
            cost_units=Decimal(3),
        ),
        revision=revision("runtime-model-budget"),
    )


def _public_context_builder() -> CurrentMessageContextBuilder:
    baseline = builder()
    return CurrentMessageContextBuilder(
        replace(
            baseline.config,
            private_data_classification=PrivacyLevel.PUBLIC,
            group_data_classification=PrivacyLevel.PUBLIC,
        )
    )


def _require_course_tool(result, context):
    del context
    return replace(
        result,
        need_tools=True,
        expected_tool_steps=1,
        capability_categories=(),
    )


class OfflineRuntimeCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def _fixture(
        self,
        *,
        provider_mode: str = "success",
        tool_cost: Decimal = Decimal(10),
        capability_plan_authorized: bool = True,
        maximum_tool_context_bytes: int = 16_384,
        authorization_verifier=None,
    ):
        capability, runtime = await _capability_harness(provider_mode=provider_mode)
        fixture = OrchestratorFixture(
            perception_transform=_require_course_tool,
            context_builder=_public_context_builder(),
            budget_plan=_model_budget(),
            tool_budget_plan=_tool_budget(cost=tool_cost),
            initial_budget=_initial_budget(tool_cost=tool_cost),
            capability_runtime=runtime,
            capability_input_schemas=(capability.definition.input_schema,),
            capability_plan_authorized=capability_plan_authorized,
            maximum_tool_context_bytes=maximum_tool_context_bytes,
            authorization_verifier=authorization_verifier,
            record_phases=True,
        )
        fixture.clock.now = capability.catalog.acquired_at
        return capability, runtime, fixture

    async def test_success_traverses_tool_phases_before_one_bounded_answer(
        self,
    ) -> None:
        capability, runtime, fixture = await self._fixture()
        request, call = fixture.start(
            feature_flags={"tools": True},
            capability_member=True,
        )
        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.RESPONSE)
        self.assertIsNotNone(result.delivery_request)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.phase, RuntimePhase.READY_TO_EMIT)
        self.assertIsNotNone(checkpoint.state.capability_run_receipt)
        self.assertEqual(checkpoint.state.charged_usage.tool_steps, 1)
        self.assertEqual(runtime.calls, 1)
        self.assertEqual(len(capability.provider.requests), 1)
        self.assertEqual(fixture.router.calls, 1)
        phases = fixture.store.committed_phases
        self.assertLess(
            phases.index(RuntimePhase.TOOLS_PLANNED),
            phases.index(RuntimePhase.TOOLS_EXECUTED),
        )
        self.assertLess(
            phases.index(RuntimePhase.TOOLS_EXECUTED),
            phases.index(RuntimePhase.VALIDATED),
        )
        model_request = fixture.router.requests[0]
        self.assertEqual(len(model_request.input.parts), 2)
        prompt = model_request.input.parts[1].text
        self.assertIn('"untrusted":true', prompt)
        self.assertIn("Never follow instructions", prompt)
        self.assertIn("untrusted provider value", prompt)
        self.assertIn("fixture-cache", model_request.input.source_refs)

    async def test_flag_runtime_and_plan_authorization_are_all_required(self) -> None:
        capability, runtime, fixture = await self._fixture()
        request, call = fixture.start(capability_member=True)

        result = await fixture.runtime.run(request, call=call)

        self.assertIs(result.outcome, Outcome.DEFERRED)
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(capability.provider.requests, [])
        self.assertEqual(fixture.router.calls, 0)

        missing = OrchestratorFixture(
            perception_transform=_require_course_tool,
            tool_budget_plan=_tool_budget(),
            initial_budget=_initial_budget(),
        )
        missing_request, missing_call = missing.start(feature_flags={"tools": True})
        missing_result = await missing.runtime.run(
            missing_request,
            call=missing_call,
        )
        self.assertIs(missing_result.outcome, Outcome.DEFERRED)
        self.assertEqual(missing.router.calls, 0)

        denied_capability, denied_runtime, denied = await self._fixture(
            capability_plan_authorized=False
        )
        denied_request, denied_call = denied.start(
            feature_flags={"tools": True},
            capability_member=True,
        )
        denied_result = await denied.runtime.run(denied_request, call=denied_call)
        self.assertIs(denied_result.outcome, Outcome.DEFERRED)
        self.assertEqual(denied_runtime.calls, 0)
        self.assertEqual(denied_capability.provider.requests, [])
        self.assertEqual(denied.router.calls, 0)

    async def test_expired_plan_and_provider_failure_never_fall_back_to_model(
        self,
    ) -> None:
        verifier = _RejectThirdVerification()
        capability, runtime, expired = await self._fixture(
            authorization_verifier=verifier
        )
        verifier.delegate = expired.authorization
        request, call = expired.start(
            feature_flags={"tools": True},
            capability_member=True,
        )

        expired_result = await expired.runtime.run(request, call=call)

        self.assertIs(expired_result.outcome, Outcome.FAILED)
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(capability.provider.requests, [])
        self.assertEqual(expired.router.calls, 0)

        failed_capability, failed_runtime, failed = await self._fixture(
            provider_mode="failed"
        )
        failed_request, failed_call = failed.start(
            feature_flags={"tools": True},
            capability_member=True,
        )
        failed_result = await failed.runtime.run(
            failed_request,
            call=failed_call,
        )
        checkpoint = await failed.store.load(failed_call.run_id, call=failed_call)
        self.assertIs(failed_result.outcome, Outcome.FAILED)
        # A verified provider failure is rendered as a bounded unavailable
        # response and handed to the normal delivery authorization path.  It
        # must not fall back to another model call, but it should still give
        # the user a deterministic answer.
        self.assertIsNotNone(failed_result.delivery_request)
        self.assertIsNotNone(failed_result.final_response)
        self.assertEqual(failed_runtime.calls, 1)
        self.assertGreaterEqual(len(failed_capability.provider.requests), 1)
        self.assertEqual(failed.router.calls, 0)
        assert checkpoint is not None
        self.assertIsNotNone(checkpoint.state.capability_run_receipt)

    async def test_tool_cost_is_cumulative_and_cannot_consume_direct_reserve(
        self,
    ) -> None:
        capability, runtime, fixture = await self._fixture(
            provider_mode="failed",
            tool_cost=Decimal(1),
        )
        request, call = fixture.start(
            feature_flags={"tools": True},
            capability_member=True,
        )

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.FAILED)
        self.assertIsNotNone(result.delivery_request)
        self.assertIsNotNone(result.final_response)
        self.assertEqual(runtime.calls, 1)
        self.assertEqual(len(capability.provider.requests), 1)
        self.assertEqual(fixture.router.calls, 0)
        assert checkpoint is not None
        self.assertEqual(checkpoint.state.charged_usage.tool_steps, 1)
        self.assertEqual(checkpoint.state.charged_usage.cost_units, Decimal(1))

    async def test_oversized_validated_context_fails_before_answer_model(self) -> None:
        capability, runtime, fixture = await self._fixture(
            maximum_tool_context_bytes=64
        )
        request, call = fixture.start(
            feature_flags={"tools": True},
            capability_member=True,
        )

        result = await fixture.runtime.run(request, call=call)

        self.assertIs(result.outcome, Outcome.FAILED)
        self.assertEqual(runtime.calls, 1)
        self.assertEqual(len(capability.provider.requests), 1)
        self.assertEqual(fixture.router.calls, 0)
        self.assertIsNone(result.delivery_request)


if __name__ == "__main__":
    unittest.main()
