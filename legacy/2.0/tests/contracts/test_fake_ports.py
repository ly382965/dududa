from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from dududa.domain.delivery import DeliveryStatus
from dududa.domain.identity import Actor
from dududa.domain.message import MessageEnvelope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    RuntimeBudget,
    TraceContext,
)
from dududa.ports import (
    AgentRuntime,
    InputConnector,
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.runtime.state import (
    CompletionReceipt,
    ConnectorResult,
    Outcome,
    RuntimePhase,
    RuntimeResult,
    TraceSummary,
)
from dududa.testing import FakeAgentRuntime, FakeInputConnector


class FakePortContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.message = MessageEnvelope(
            1,
            "m-1",
            "qq",
            "bot-1",
            ConversationType.PRIVATE,
            "private:u-1",
            None,
            "u-1",
            None,
            self.now,
            "hello",
        )
        self.connector_result = ConnectorResult(
            1,
            self.message,
            Actor("qq", "bot-1", "u-1", frozenset()),
            self.now,
            ComponentRevision("fake.connector", "1", "cfg", DigestString("artifact")),
        )
        self.budget = RuntimeBudget(1, 0, 0, 100, 100, Decimal("1"))
        self.completion = CompletionReceipt(
            1,
            "run-1",
            final_phase=RuntimePhase.COMPLETED,
            delivery_status=DeliveryStatus.NOT_REQUIRED,
            completed_at=self.now,
        )

    async def test_fake_connector_structurally_conforms_and_records_context(
        self,
    ) -> None:
        connector = FakeInputConnector(lambda event: self.connector_result)
        self.assertIsInstance(connector, InputConnector)
        operation = ServiceCallContext(
            "connector.convert",
            ServicePrincipal("astrbot", "test", frozenset({"connector"})),
            "platform_input",
            TraceContext("trace-1"),
            self.now + timedelta(seconds=1),
            NeverCancelled(),
            self.budget,
            "policy-1",
        )
        result = await connector.convert("event", operation=operation)
        self.assertEqual(result, self.connector_result)
        self.assertEqual(connector.calls, [("event", operation)])

    async def test_fake_runtime_structurally_conforms(self) -> None:
        result = RuntimeResult(
            1,
            "run-1",
            Outcome.NO_REPLY,
            None,
            None,
            None,
            self.completion,
            ("ignored",),
            TraceSummary(1, "trace-1", (), (), ()),
        )
        runtime = FakeAgentRuntime(
            lambda request: result, lambda receipt: self.completion
        )
        self.assertIsInstance(runtime, AgentRuntime)
        call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(seconds=1),
            NeverCancelled(),
            self.budget,
            "policy-1",
        )
        self.assertFalse(call.cancellation.is_cancelled)


if __name__ == "__main__":
    unittest.main()
