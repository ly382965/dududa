from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.domain.delivery import (
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryStatus,
)
from dududa.rollout import (
    BoundedShadowSupervisor,
    CanaryCoordinator,
    CanaryExecutionDisposition,
    InMemoryRolloutMetrics,
    RolloutClaimDisposition,
    RolloutMode,
    RolloutOwnershipState,
    ShadowSubmissionDisposition,
    decide_rollout_admission,
)
from dududa.runtime.shadow import ShadowRunner

from tests.unit.models.helpers import NOW
from tests.unit.runtime.test_orchestrator import OrchestratorFixture

from .helpers import control, ledger


class _MutableControls:
    def __init__(self, value) -> None:
        self.value = value
        self.failure: Exception | None = None

    def current(self):
        if self.failure is not None:
            raise self.failure
        return self.value


class _RuntimeProxy:
    def __init__(self, runtime, *, after_run=None) -> None:
        self.runtime = runtime
        self.after_run = after_run
        self.run_calls = 0
        self.ack_calls = 0

    async def run(self, request, *, call):
        self.run_calls += 1
        result = await self.runtime.run(request, call=call)
        if self.after_run is not None:
            self.after_run()
        return result

    async def acknowledge_delivery(self, receipt, *, call):
        self.ack_calls += 1
        return await self.runtime.acknowledge_delivery(receipt, call=call)

    async def reconcile_delivery(self, receipt, *, call):
        return await self.runtime.reconcile_delivery(receipt, call=call)


class _GuardedOutput:
    def __init__(self, guard, *, fail_after_guard: bool = False) -> None:
        self.guard = guard
        self.fail_after_guard = fail_after_guard
        self.send_calls = 0

    async def deliver(self, request, *, call):
        reason = self.guard(request, 1)
        if reason is None:
            self.send_calls += 1
            if self.fail_after_guard:
                raise RuntimeError("injected outcome loss")
            status = DeliveryStatus.SUCCEEDED
            part_status = DeliveryPartStatus.SUCCEEDED
        else:
            status = DeliveryStatus.FAILED
            part_status = DeliveryPartStatus.FAILED
        parts = tuple(
            DeliveryPartReceipt(
                1,
                part.part_id,
                part.content_digest,
                part_status,
                None,
                reason,
            )
            for part in request.part_intents
        )
        return DeliveryReceipt(
            1,
            request.delivery_id,
            request.run_id,
            request.request_digest,
            request.idempotency_key,
            request.attempt,
            request.adapter_binding.component_revision,
            status,
            parts,
            NOW,
            reason,
        )


class _OutputFactory:
    def __init__(self, *, fail_after_guard: bool = False) -> None:
        self.fail_after_guard = fail_after_guard
        self.outputs: list[_GuardedOutput] = []

    def __call__(self, guard):
        output = _GuardedOutput(guard, fail_after_guard=self.fail_after_guard)
        self.outputs.append(output)
        return output

    @property
    def send_calls(self) -> int:
        return sum(output.send_calls for output in self.outputs)


class _ShadowSink:
    def __init__(self) -> None:
        self.receipts = []

    async def write(self, receipt, *, call) -> None:
        self.receipts.append(receipt)


class _BlockingRuntime(_RuntimeProxy):
    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, request, *, call):
        self.run_calls += 1
        self.started.set()
        await self.release.wait()
        return await self.runtime.run(request, call=call)


class ControlledExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "rollout.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self):
        fixture = OrchestratorFixture()
        request, call = fixture.start()
        config = control(
            allowlisted_group_ids=frozenset({request.connector_result.message.group_id})
        )
        return fixture, request, call, config

    async def test_canary_claim_has_one_runtime_and_delivery_owner(self) -> None:
        fixture, request, call, config = self._fixture()
        controls = _MutableControls(config)
        runtime = _RuntimeProxy(fixture.runtime)
        metrics = InMemoryRolloutMetrics()
        first = CanaryCoordinator(
            runtime,
            controls,
            ledger(self.path, clock=lambda: NOW),
            metrics,
            clock=lambda: NOW,
        )
        second = CanaryCoordinator(
            runtime,
            controls,
            ledger(self.path, clock=lambda: NOW),
            metrics,
            clock=lambda: NOW,
        )
        admission = decide_rollout_admission(request.connector_result, config)

        first_claim = first.claim(admission, request)
        second_claim = second.claim(admission, request)

        self.assertIs(first_claim.disposition, RolloutClaimDisposition.ACQUIRED)
        self.assertIs(second_claim.disposition, RolloutClaimDisposition.EXISTING)
        output = _OutputFactory()
        result = await first.execute(first_claim, request, output, call=call)
        replay = second.replay_result(second_claim, run_id=call.run_id)
        self.assertIs(result.disposition, CanaryExecutionDisposition.DELIVERED)
        self.assertIs(result.ownership.state, RolloutOwnershipState.SUCCEEDED)
        self.assertIs(replay.disposition, CanaryExecutionDisposition.REPLAY)
        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(output.send_calls, 1)

    async def test_in_flight_kill_switch_suppresses_send_without_fallback(self) -> None:
        fixture, request, call, config = self._fixture()
        controls = _MutableControls(config)
        runtime = _RuntimeProxy(
            fixture.runtime,
            after_run=lambda: setattr(
                controls, "value", replace(config, kill_switch=True)
            ),
        )
        coordinator = CanaryCoordinator(
            runtime,
            controls,
            ledger(self.path, clock=lambda: NOW),
            InMemoryRolloutMetrics(),
            clock=lambda: NOW,
        )
        admission = decide_rollout_admission(request.connector_result, config)
        claim = coordinator.claim(admission, request)
        output = _OutputFactory()

        result = await coordinator.execute(claim, request, output, call=call)

        self.assertIs(result.disposition, CanaryExecutionDisposition.SUPPRESSED)
        self.assertIs(result.ownership.state, RolloutOwnershipState.SUPPRESSED)
        self.assertEqual(output.send_calls, 0)
        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(runtime.ack_calls, 1)

    async def test_no_reply_keeps_its_reason_instead_of_generic_no_delivery(
        self,
    ) -> None:
        fixture = OrchestratorFixture(
            perception_transform=lambda result, _context: replace(
                result,
                target_identity_refs=(),
            )
        )
        request, call = fixture.start()
        config = control(
            allowlisted_group_ids=frozenset(
                {request.connector_result.message.group_id}
            )
        )
        controls = _MutableControls(config)
        runtime = _RuntimeProxy(fixture.runtime)
        coordinator = CanaryCoordinator(
            runtime,
            controls,
            ledger(self.path, clock=lambda: NOW),
            InMemoryRolloutMetrics(),
            clock=lambda: NOW,
        )
        admission = decide_rollout_admission(request.connector_result, config)
        claim = coordinator.claim(admission, request)
        output = _OutputFactory()

        result = await coordinator.execute(claim, request, output, call=call)

        self.assertIs(result.disposition, CanaryExecutionDisposition.NO_DELIVERY)
        self.assertEqual(result.reason_code, "runtime_no_reply_without_delivery")
        self.assertEqual(result.ownership.reason_code, result.reason_code)
        self.assertEqual(output.send_calls, 0)

    async def test_unknown_send_is_tombstoned_and_replay_never_resends(self) -> None:
        fixture, request, call, config = self._fixture()
        controls = _MutableControls(config)
        runtime = _RuntimeProxy(fixture.runtime)
        coordinator = CanaryCoordinator(
            runtime,
            controls,
            ledger(self.path, clock=lambda: NOW),
            InMemoryRolloutMetrics(),
            clock=lambda: NOW,
        )
        admission = decide_rollout_admission(request.connector_result, config)
        claim = coordinator.claim(admission, request)
        output = _OutputFactory(fail_after_guard=True)

        result = await coordinator.execute(claim, request, output, call=call)

        self.assertIs(result.ownership.state, RolloutOwnershipState.UNKNOWN)
        self.assertEqual(output.send_calls, 1)
        restarted = CanaryCoordinator(
            runtime,
            controls,
            ledger(self.path, clock=lambda: NOW),
            InMemoryRolloutMetrics(),
            clock=lambda: NOW,
        )
        replay_claim = restarted.claim(admission, request)
        self.assertIs(replay_claim.disposition, RolloutClaimDisposition.EXISTING)
        self.assertIs(replay_claim.record.state, RolloutOwnershipState.UNKNOWN)
        self.assertEqual(output.send_calls, 1)

    async def test_shadow_capacity_is_bounded_and_never_owns_delivery(self) -> None:
        fixture, request, call, config = self._fixture()
        shadow_config = replace(
            config,
            mode=RolloutMode.SHADOW,
            delivery_enabled=False,
            shadow_max_in_flight=1,
        )
        runtime = _BlockingRuntime(fixture.runtime)
        sink = _ShadowSink()
        supervisor = BoundedShadowSupervisor(
            ShadowRunner(runtime, sink, clock=lambda: NOW),
            shadow_config,
            InMemoryRolloutMetrics(),
            clock=lambda: NOW,
        )

        first = supervisor.submit(request, call=call)
        await runtime.started.wait()
        second = supervisor.submit(request, call=call)
        runtime.release.set()
        await supervisor.drain()

        self.assertIs(first, ShadowSubmissionDisposition.ACCEPTED)
        self.assertIs(second, ShadowSubmissionDisposition.CAPACITY_REJECTED)
        self.assertEqual(runtime.run_calls, 1)
        self.assertEqual(runtime.ack_calls, 0)
        self.assertEqual(len(sink.receipts), 1)
        self.assertEqual(supervisor.active_count, 0)


if __name__ == "__main__":
    unittest.main()
