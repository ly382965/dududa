from __future__ import annotations

import unittest

from dududa.domain.delivery import DeliveryStatus
from dududa.runtime.offline import OfflineDeliveryDriver

from .test_delivery_runtime import _receipt
from .test_orchestrator import OrchestratorFixture


class _RecordingOutput:
    def __init__(self, status: DeliveryStatus) -> None:
        self.status = status
        self.calls = []

    async def deliver(self, request, *, call):
        self.calls.append((request, call))
        return _receipt(request, self.status)


class OfflineDeliveryDriverTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_is_acknowledged_once_without_retry(self) -> None:
        fixture = OrchestratorFixture()
        output = _RecordingOutput(DeliveryStatus.UNKNOWN)
        driver = OfflineDeliveryDriver(fixture.runtime, output)
        request, call = fixture.start()

        result = await driver.execute(request, call=call)

        self.assertIs(result.delivery_receipt.status, DeliveryStatus.UNKNOWN)
        self.assertIs(result.completion.delivery_status, DeliveryStatus.UNKNOWN)
        self.assertEqual(len(output.calls), 1)

    async def test_no_reply_never_calls_output(self) -> None:
        fixture = OrchestratorFixture()
        output = _RecordingOutput(DeliveryStatus.SUCCEEDED)
        driver = OfflineDeliveryDriver(fixture.runtime, output)
        request, call = fixture.start(mentioned=False)

        result = await driver.execute(request, call=call)

        self.assertIsNone(result.delivery_receipt)
        self.assertEqual(output.calls, [])


if __name__ == "__main__":
    unittest.main()
