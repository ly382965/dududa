from __future__ import annotations

from dataclasses import dataclass

from dududa.domain.delivery import DeliveryReceipt
from dududa.errors import validation_error
from dududa.ports.context import PortCallContext
from dududa.ports.output import OutputAdapter
from dududa.ports.runtime import AgentRuntime

from .state import CompletionReceipt, RuntimeResult, RuntimeStartRequest


@dataclass(frozen=True, slots=True)
class OfflineDeliveryRunResult:
    schema_version: int
    runtime_result: RuntimeResult
    delivery_receipt: DeliveryReceipt | None
    completion: CompletionReceipt

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not isinstance(self.runtime_result, RuntimeResult):
            raise validation_error("invalid_offline_runtime_result")
        if self.delivery_receipt is not None and not isinstance(
            self.delivery_receipt,
            DeliveryReceipt,
        ):
            raise validation_error("invalid_offline_delivery_receipt")
        if not isinstance(self.completion, CompletionReceipt):
            raise validation_error("invalid_offline_completion_receipt")
        if self.completion.run_id != self.runtime_result.run_id:
            raise validation_error("offline_completion_run_mismatch")
        if self.runtime_result.delivery_request is None:
            if (
                self.delivery_receipt is not None
                or self.runtime_result.completion != self.completion
            ):
                raise validation_error("offline_no_delivery_result_mismatch")
        elif (
            self.delivery_receipt is None
            or self.delivery_receipt.run_id != self.runtime_result.run_id
            or self.delivery_receipt.delivery_request_digest
            != self.runtime_result.delivery_request.request_digest
            or self.completion.delivery_status is not self.delivery_receipt.status
        ):
            raise validation_error("offline_delivery_result_mismatch")


class OfflineDeliveryDriver:
    def __init__(self, runtime: AgentRuntime, output: OutputAdapter) -> None:
        if not isinstance(runtime, AgentRuntime):
            raise TypeError("runtime does not implement AgentRuntime")
        if not isinstance(output, OutputAdapter):
            raise TypeError("output does not implement OutputAdapter")
        self._runtime = runtime
        self._output = output

    async def execute(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> OfflineDeliveryRunResult:
        result = await self._runtime.run(request, call=call)
        delivery = result.delivery_request
        if delivery is None:
            if result.completion is None:
                raise validation_error("offline_terminal_result_missing_completion")
            return OfflineDeliveryRunResult(1, result, None, result.completion)
        receipt = await self._output.deliver(delivery, call=call)
        completion = await self._runtime.acknowledge_delivery(receipt, call=call)
        return OfflineDeliveryRunResult(1, result, receipt, completion)
