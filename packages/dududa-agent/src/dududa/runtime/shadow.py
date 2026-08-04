from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from dududa.errors import validation_error
from dududa.ports.context import PortCallContext
from dududa.ports.runtime import AgentRuntime, ShadowReceiptSink

from .contracts import ShadowRunReceipt
from .state import RuntimeResult, RuntimeStartRequest


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ShadowRunner:
    def __init__(
        self,
        runtime: AgentRuntime,
        sink: ShadowReceiptSink,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(runtime, AgentRuntime):
            raise TypeError("runtime does not implement AgentRuntime")
        if not isinstance(sink, ShadowReceiptSink):
            raise TypeError("sink does not implement ShadowReceiptSink")
        self._runtime = runtime
        self._sink = sink
        self._clock = clock or _utc_now

    async def run(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> ShadowRunReceipt:
        result = await self._runtime.run(request, call=call)
        if not isinstance(result, RuntimeResult):
            raise validation_error("invalid_shadow_runtime_result")
        if result.run_id != call.run_id:
            raise validation_error("shadow_runtime_run_mismatch")
        selection = result.selection_summary
        delivery = result.delivery_request
        receipt = ShadowRunReceipt(
            schema_version=1,
            run_id=result.run_id,
            outcome=result.outcome,
            selected_tier=(selection.selected_tier if selection is not None else None),
            tier_decision_digest=(
                selection.tier_decision_digest if selection is not None else None
            ),
            route_decision_digest=(
                selection.route_decision_digest if selection is not None else None
            ),
            candidate_delivery_digest=(
                delivery.request_digest if delivery is not None else None
            ),
            reason_codes=result.reason_codes,
            recorded_at=self._clock(),
        )
        await self._sink.write(receipt, call=call)
        return receipt
