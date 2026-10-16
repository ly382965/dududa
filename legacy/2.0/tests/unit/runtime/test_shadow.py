from __future__ import annotations

from dataclasses import fields, replace
import inspect
import unittest

from dududa.domain.delivery import DeliveryReceipt, DeliveryRequest
from dududa.domain.primitives import Outcome
from dududa.errors import DududaError
from dududa.perception.contracts import (
    AmbiguityCandidate,
    AmbiguityKind,
    ClarificationKey,
)
from dududa.ports.context import ManualCancellationToken
from dududa.runtime.contracts import ShadowRunReceipt
from dududa.runtime.shadow import ShadowRunner

from tests.unit.models.helpers import NOW
from tests.unit.runtime.test_orchestrator import OrchestratorFixture


class _RecordingShadowSink:
    def __init__(self) -> None:
        self.calls = []

    async def write(self, receipt, *, call) -> None:
        self.calls.append((receipt, call))


class _FailingShadowSink(_RecordingShadowSink):
    async def write(self, receipt, *, call) -> None:
        await super().write(receipt, call=call)
        raise RuntimeError("injected shadow sink failure")


class _SideEffectGuardRuntime:
    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self.run_calls = 0
        self.last_result = None
        self.forbidden_calls = {
            "acknowledge_delivery": 0,
            "reconcile_delivery": 0,
            "output": 0,
            "memory": 0,
            "tool": 0,
            "event_stop": 0,
        }

    async def run(self, request, *, call):
        self.run_calls += 1
        self.last_result = await self._runtime.run(request, call=call)
        return self.last_result

    async def acknowledge_delivery(self, receipt: DeliveryReceipt, *, call):
        self.forbidden_calls["acknowledge_delivery"] += 1
        raise AssertionError("shadow must not acknowledge delivery")

    async def reconcile_delivery(self, receipt: DeliveryReceipt, *, call):
        self.forbidden_calls["reconcile_delivery"] += 1
        raise AssertionError("shadow must not reconcile delivery")

    async def deliver(self, request, *, call):
        self.forbidden_calls["output"] += 1
        raise AssertionError("shadow must not call Output")

    async def commit_write(self, command, *, call):
        self.forbidden_calls["memory"] += 1
        raise AssertionError("shadow must not write Memory")

    async def execute_tool(self, plan, *, call):
        self.forbidden_calls["tool"] += 1
        raise AssertionError("shadow must not execute Tools")

    def stop_event(self) -> None:
        self.forbidden_calls["event_stop"] += 1
        raise AssertionError("shadow must not stop an event")


class ShadowRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_reply_records_only_sanitized_non_deliverable_receipt(
        self,
    ) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()
        runtime = _SideEffectGuardRuntime(fixture.runtime)
        sink = _RecordingShadowSink()
        runner = ShadowRunner(runtime, sink, clock=lambda: NOW)

        receipt = await runner.run(request, call=call)

        self.assertEqual(runtime.run_calls, 1)
        self.assertTrue(all(count == 0 for count in runtime.forbidden_calls.values()))
        self.assertEqual(sink.calls, [(receipt, call)])
        self.assertIsNotNone(runtime.last_result)
        self.assertIsNotNone(runtime.last_result.delivery_request)
        self.assertEqual(
            receipt.candidate_delivery_digest,
            runtime.last_result.delivery_request.request_digest,
        )
        self.assertEqual(
            receipt.selected_tier,
            runtime.last_result.selection_summary.selected_tier,
        )
        self.assertNotIsInstance(receipt, DeliveryRequest)
        public_fields = {field.name for field in fields(ShadowRunReceipt)}
        self.assertEqual(
            public_fields,
            {
                "schema_version",
                "run_id",
                "outcome",
                "selected_tier",
                "tier_decision_digest",
                "route_decision_digest",
                "candidate_delivery_digest",
                "reason_codes",
                "recorded_at",
            },
        )
        serialized = repr(receipt)
        for secret in (
            "A bounded answer.",
            "private:u-1",
            "bot-1",
            "user-1",
            "group-1",
            "trace:run-1",
        ):
            self.assertNotIn(secret, serialized)
        self.assertTrue(
            all(not callable(getattr(receipt, field)) for field in public_fields)
        )

    async def test_no_reply_records_no_selection_or_delivery_candidate(self) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start(mentioned=False)
        runtime = _SideEffectGuardRuntime(fixture.runtime)
        sink = _RecordingShadowSink()

        receipt = await ShadowRunner(runtime, sink, clock=lambda: NOW).run(
            request,
            call=call,
        )

        self.assertIsNone(receipt.selected_tier)
        self.assertIsNone(receipt.tier_decision_digest)
        self.assertIsNone(receipt.route_decision_digest)
        self.assertIsNone(receipt.candidate_delivery_digest)
        self.assertTrue(all(count == 0 for count in runtime.forbidden_calls.values()))

    async def test_clarification_has_candidate_without_model_selection(self) -> None:
        def add_ambiguity(result, context):
            return replace(
                result,
                ambiguities=(
                    AmbiguityCandidate(
                        schema_version=1,
                        ambiguity_id="ambiguity:task",
                        kind=AmbiguityKind.TASK,
                        clarification_key=ClarificationKey.TASK,
                        confidence=0.9,
                        evidence_refs=(context.current_message_ref,),
                    ),
                ),
            )

        fixture = OrchestratorFixture(perception_transform=add_ambiguity)
        request, call = fixture.start()
        runtime = _SideEffectGuardRuntime(fixture.runtime)

        receipt = await ShadowRunner(
            runtime,
            _RecordingShadowSink(),
            clock=lambda: NOW,
        ).run(request, call=call)

        self.assertIs(receipt.outcome, Outcome.RESPONSE)
        self.assertIsNotNone(receipt.candidate_delivery_digest)
        self.assertIsNone(receipt.selected_tier)
        self.assertIsNone(receipt.tier_decision_digest)
        self.assertIsNone(receipt.route_decision_digest)
        self.assertEqual(fixture.router.calls, 0)
        self.assertTrue(all(count == 0 for count in runtime.forbidden_calls.values()))

    async def test_deferred_and_direct_failure_have_no_deliverable_candidate(
        self,
    ) -> None:
        def require_tool(result, context):
            return replace(result, need_tools=True, expected_tool_steps=1)

        fixtures = (
            OrchestratorFixture(perception_transform=require_tool),
            OrchestratorFixture(direct_output="   "),
        )
        for fixture, expected in zip(
            fixtures,
            (Outcome.DEFERRED, Outcome.FAILED),
            strict=True,
        ):
            with self.subTest(expected=expected):
                request, call = fixture.start()
                runtime = _SideEffectGuardRuntime(fixture.runtime)
                receipt = await ShadowRunner(
                    runtime,
                    _RecordingShadowSink(),
                    clock=lambda: NOW,
                ).run(request, call=call)
                self.assertIs(receipt.outcome, expected)
                self.assertIsNone(receipt.candidate_delivery_digest)
                self.assertIsNone(receipt.selected_tier)
                self.assertTrue(
                    all(count == 0 for count in runtime.forbidden_calls.values())
                )

    async def test_runtime_failure_does_not_write_sink(self) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()
        cancellation = ManualCancellationToken()
        cancellation.cancel()
        call = replace(call, cancellation=cancellation)
        runtime = _SideEffectGuardRuntime(fixture.runtime)
        sink = _RecordingShadowSink()

        with self.assertRaises(DududaError):
            await ShadowRunner(runtime, sink, clock=lambda: NOW).run(
                request,
                call=call,
            )

        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(sink.calls, [])

    async def test_sink_failure_is_not_retried_or_acknowledged(self) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()
        runtime = _SideEffectGuardRuntime(fixture.runtime)
        sink = _FailingShadowSink()

        with self.assertRaisesRegex(RuntimeError, "injected shadow sink failure"):
            await ShadowRunner(runtime, sink, clock=lambda: NOW).run(
                request,
                call=call,
            )

        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(len(sink.calls), 1)
        self.assertTrue(all(count == 0 for count in runtime.forbidden_calls.values()))

    def test_constructor_exposes_no_side_effect_capabilities(self) -> None:
        self.assertEqual(
            tuple(inspect.signature(ShadowRunner).parameters),
            ("runtime", "sink", "clock"),
        )

    def test_receipt_rejects_free_text_reason_before_recording(self) -> None:
        with self.assertRaises(DududaError):
            ShadowRunReceipt(
                schema_version=1,
                run_id="run-1",
                outcome=Outcome.NO_REPLY,
                selected_tier=None,
                tier_decision_digest=None,
                route_decision_digest=None,
                candidate_delivery_digest=None,
                reason_codes=("provider said secret text",),
                recorded_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
