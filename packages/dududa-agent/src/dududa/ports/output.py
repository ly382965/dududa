from __future__ import annotations

from typing import Protocol, runtime_checkable

from dududa.domain.delivery import DeliveryReceipt, DeliveryRequest

from .context import PortCallContext


@runtime_checkable
class OutputAdapter(Protocol):
    async def deliver(
        self,
        request: DeliveryRequest,
        *,
        call: PortCallContext,
    ) -> DeliveryReceipt: ...
