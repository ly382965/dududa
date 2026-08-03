from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from dududa.domain.delivery import DeliveryReceipt
from dududa.runtime.state import (
    CompletionReceipt,
    ConnectorResult,
    RuntimeResult,
    RuntimeStartRequest,
)

from .context import PortCallContext, ServiceCallContext


RawEventT = TypeVar("RawEventT")


@runtime_checkable
class InputConnector(Protocol, Generic[RawEventT]):
    async def convert(
        self,
        event: RawEventT,
        *,
        operation: ServiceCallContext,
    ) -> ConnectorResult: ...


@runtime_checkable
class AgentRuntime(Protocol):
    async def run(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeResult: ...

    async def acknowledge_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> CompletionReceipt: ...
