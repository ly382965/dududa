from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from dududa.domain.delivery import DeliveryReceipt
from dududa.ports.context import PortCallContext, ServiceCallContext
from dududa.runtime.state import (
    CompletionReceipt,
    ConnectorResult,
    RuntimeResult,
    RuntimeStartRequest,
)
from dududa.runtime.contracts import DeliveryReconciliationReceipt


RawEventT = TypeVar("RawEventT")


class FakeInputConnector(Generic[RawEventT]):
    def __init__(self, convert: Callable[[RawEventT], ConnectorResult]) -> None:
        self._convert = convert
        self.calls: list[tuple[RawEventT, ServiceCallContext]] = []

    async def convert(
        self,
        event: RawEventT,
        *,
        operation: ServiceCallContext,
    ) -> ConnectorResult:
        self.calls.append((event, operation))
        return self._convert(event)


class FakeAgentRuntime:
    def __init__(
        self,
        run: Callable[[RuntimeStartRequest], RuntimeResult],
        acknowledge: Callable[[DeliveryReceipt], CompletionReceipt],
        reconcile: Callable[[DeliveryReceipt], DeliveryReconciliationReceipt]
        | None = None,
    ) -> None:
        self._run = run
        self._acknowledge = acknowledge
        self._reconcile = reconcile
        self.run_calls: list[tuple[RuntimeStartRequest, PortCallContext]] = []
        self.acknowledge_calls: list[tuple[DeliveryReceipt, PortCallContext]] = []
        self.reconcile_calls: list[tuple[DeliveryReceipt, PortCallContext]] = []

    async def run(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeResult:
        self.run_calls.append((request, call))
        return self._run(request)

    async def acknowledge_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> CompletionReceipt:
        self.acknowledge_calls.append((receipt, call))
        return self._acknowledge(receipt)

    async def reconcile_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> DeliveryReconciliationReceipt:
        self.reconcile_calls.append((receipt, call))
        if self._reconcile is None:
            raise RuntimeError("Fake Agent Runtime reconciliation is not scripted")
        return self._reconcile(receipt)
