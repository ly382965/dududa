from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from dududa.contracts.canonical import canonical_json_bytes
from dududa.domain.primitives import Outcome
from dududa.errors import DududaError
from dududa.runtime.state import RuntimePhase, append_runtime_phase_trace

from tests.unit.runtime.test_orchestrator import OrchestratorFixture


class RuntimeTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_reply_records_the_sanitized_committed_phase_path(
        self,
    ) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.RESPONSE)
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        phases = tuple(event.phase for event in checkpoint.state.trace)
        self.assertEqual(
            phases,
            (
                RuntimePhase.RECEIVED,
                RuntimePhase.PREPROCESSED,
                RuntimePhase.CONTEXT_READY,
                RuntimePhase.PERCEIVED,
                RuntimePhase.DECIDED,
                RuntimePhase.COMPOSED,
                RuntimePhase.RENDERED,
                RuntimePhase.READY_TO_EMIT,
            ),
        )
        self.assertEqual(result.trace_summary.phases, phases)
        self.assertEqual(
            tuple(event.attributes["sequence"] for event in checkpoint.state.trace),
            tuple(range(len(phases))),
        )
        self.assertTrue(
            all(
                previous.occurred_at <= current.occurred_at
                for previous, current in zip(
                    checkpoint.state.trace,
                    checkpoint.state.trace[1:],
                )
            )
        )
        serialized = canonical_json_bytes(checkpoint.state.trace).decode("utf-8")
        for private_value in (
            "Please explain this task.",
            "A bounded answer.",
            "user-123",
            "bot-123",
            "group-456",
            "message-789",
        ):
            self.assertNotIn(private_value, serialized)

    async def test_terminal_failure_binds_safe_reason_codes_to_the_last_event(
        self,
    ) -> None:
        fixture = OrchestratorFixture(direct_output="   ")
        request, call = fixture.start()

        result = await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)

        self.assertIs(result.outcome, Outcome.FAILED)
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        self.assertIs(checkpoint.state.trace[-1].phase, RuntimePhase.FAILED)
        self.assertEqual(
            checkpoint.state.trace[-1].reason_codes,
            tuple(sorted(result.reason_codes)),
        )
        self.assertEqual(
            result.trace_summary.phases,
            tuple(event.phase for event in checkpoint.state.trace),
        )

    async def test_trace_rejects_payload_fields_digest_drift_and_time_regression(
        self,
    ) -> None:
        fixture = OrchestratorFixture()
        request, call = fixture.start()
        await fixture.runtime.run(request, call=call)
        checkpoint = await fixture.store.load(call.run_id, call=call)
        assert checkpoint is not None
        event = checkpoint.state.trace[-1]

        with self.assertRaises(DududaError):
            replace(
                event,
                attributes={"sequence": event.attributes["sequence"], "text": "raw"},
            )
        with self.assertRaises(DududaError):
            replace(event, event_id="forged")
        with self.assertRaises(DududaError):
            append_runtime_phase_trace(
                checkpoint.state,
                RuntimePhase.COMPLETED,
                event.occurred_at - timedelta(seconds=1),
            )


if __name__ == "__main__":
    unittest.main()
