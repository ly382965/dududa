from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from dududa.domain.delivery import DeliveryStatus
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.message import MessageEnvelope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DenyFlag,
    DigestString,
    RoleId,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.runtime.state import (
    CompletionReceipt,
    ConnectorResult,
    Outcome,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeResult,
    RuntimeStartRequest,
    RuntimeState,
    TraceSummary,
    runtime_start_digest,
    transition,
)


class RuntimeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        now = datetime.now(timezone.utc)
        self.message = MessageEnvelope(
            schema_version=1,
            message_id="m-1",
            platform="qq",
            bot_id="bot-1",
            conversation_type=ConversationType.GROUP,
            conversation_id="g-1",
            group_id="g-1",
            user_id="u-1",
            reply_to=None,
            timestamp=now,
            text="hello",
        )
        self.actor = Actor(
            "qq",
            "bot-1",
            "u-1",
            frozenset({RoleId("normal")}),
            frozenset({DenyFlag("none")}),
        )
        revision = ComponentRevision(
            "connector.astrbot",
            "0.1.0",
            "cfg-1",
            DigestString("digest"),
        )
        self.state = RuntimeState(
            schema_version=1,
            run_id="run-1",
            phase=RuntimePhase.RECEIVED,
            message=self.message,
            actor=self.actor,
            received_at=now,
            connector_revision=revision,
            invocation_options=RuntimeInvocationOptions(
                1, None, "astrbot", {"runtime_v2": False}, "flags-1"
            ),
            start_digest=DigestString("start"),
            conversation_scope=ConversationScope(
                "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
            ),
            budget=RuntimeBudget(2, 0, 1, 1000, 500, Decimal("1")),
            trace_context=TraceContext("trace-1"),
            policy_snapshot_id="policy-1",
        )

    def test_valid_transition_returns_new_state(self) -> None:
        updated = transition(self.state, RuntimePhase.PREPROCESSED)
        self.assertEqual(updated.phase, RuntimePhase.PREPROCESSED)
        self.assertEqual(self.state.phase, RuntimePhase.RECEIVED)

    def test_invalid_transition_is_rejected(self) -> None:
        with self.assertRaises(DududaError):
            transition(self.state, RuntimePhase.COMPLETED)

    def test_runtime_scope_binds_conversation_type_and_group(self) -> None:
        private_scope = ConversationScope(
            "qq", "bot-1", ConversationType.PRIVATE, "g-1", None, "dududa"
        )
        with self.assertRaises(DududaError):
            replace(self.state, conversation_scope=private_scope)

    def test_runtime_start_digest_binds_connector_and_options(self) -> None:
        connector = ConnectorResult(
            1,
            self.message,
            self.actor,
            self.message.timestamp,
            self.state.connector_revision,
        )
        options = self.state.invocation_options
        digest = runtime_start_digest(connector, options)
        request = RuntimeStartRequest(1, connector, options, digest)
        self.assertEqual(request.start_digest, digest)
        changed_connector = replace(
            connector,
            message=replace(self.message, text="changed"),
        )
        with self.assertRaises(DududaError):
            RuntimeStartRequest(1, changed_connector, options, digest)

    def test_runtime_state_defensively_freezes_collections(self) -> None:
        trace: list[object] = []
        state = replace(self.state, trace=trace)  # type: ignore[arg-type]
        trace.append(object())
        self.assertEqual(state.trace, ())

    def test_no_reply_requires_completion(self) -> None:
        completion = CompletionReceipt(
            schema_version=1,
            run_id="run-1",
            final_phase=RuntimePhase.COMPLETED,
            delivery_status=DeliveryStatus.NOT_REQUIRED,
            completed_at=datetime.now(timezone.utc),
        )
        result = RuntimeResult(
            schema_version=1,
            run_id="run-1",
            outcome=Outcome.NO_REPLY,
            final_response=None,
            reaction=None,
            delivery_request=None,
            completion=completion,
            reason_codes=("policy_ignore",),
            trace_summary=TraceSummary(1, "trace-1", (), (), ()),
        )
        self.assertEqual(result.outcome, Outcome.NO_REPLY)
        with self.assertRaises(DududaError):
            RuntimeResult(
                1,
                "run-1",
                Outcome.NO_REPLY,
                None,
                None,
                None,
                None,
                (),
                TraceSummary(1, "trace-1", (), (), ()),
            )


if __name__ == "__main__":
    unittest.main()
