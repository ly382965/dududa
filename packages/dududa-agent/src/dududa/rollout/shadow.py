from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

from dududa._compat import StrEnum
from dududa.domain.primitives import Outcome
from dududa.models.contracts import ModelRole
from dududa.ports.context import PortCallContext
from dududa.runtime.shadow import ShadowRunner
from dududa.runtime.state import RuntimeStartRequest

from .contracts import RolloutControlConfig, RolloutMode
from .metrics import (
    RolloutFailureKind,
    RolloutLatencyBucket,
    RolloutMetricObservation,
    RolloutMetricStage,
    latency_bucket,
)
from .ports import RolloutMetricSink


class ShadowSubmissionDisposition(StrEnum):
    ACCEPTED = "accepted"
    CAPACITY_REJECTED = "capacity_rejected"
    CLOSED = "closed"
    EXPIRED = "expired"


class BoundedShadowSupervisor:
    def __init__(
        self,
        runner: ShadowRunner,
        config: RolloutControlConfig,
        metrics: RolloutMetricSink,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(runner, ShadowRunner):
            raise TypeError("invalid ShadowRunner")
        if not isinstance(config, RolloutControlConfig):
            raise TypeError("invalid rollout config")
        if not isinstance(metrics, RolloutMetricSink):
            raise TypeError("invalid rollout metrics")
        self._runner = runner
        self._config = config
        self._metrics = metrics
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def submit(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> ShadowSubmissionDisposition:
        if self._closed:
            self._record(RolloutFailureKind.OTHER)
            return ShadowSubmissionDisposition.CLOSED
        now = self._clock()
        if call.deadline <= now or call.cancellation.is_cancelled:
            self._record(RolloutFailureKind.TIMEOUT)
            return ShadowSubmissionDisposition.EXPIRED
        if len(self._tasks) >= self._config.shadow_max_in_flight:
            self._record(RolloutFailureKind.CAPACITY)
            return ShadowSubmissionDisposition.CAPACITY_REJECTED
        task = asyncio.create_task(self._execute(request, call=call))
        self._tasks.add(task)
        task.add_done_callback(self._consume)
        return ShadowSubmissionDisposition.ACCEPTED

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        await self.drain()

    async def _execute(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> None:
        started = self._clock()
        remaining = max(0.0, (call.deadline - started).total_seconds())
        timeout = min(self._config.shadow_timeout.total_seconds(), remaining)
        if timeout <= 0:
            self._record(RolloutFailureKind.TIMEOUT)
            return
        try:
            receipt = await asyncio.wait_for(
                self._runner.run(request, call=call),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self._record(RolloutFailureKind.TIMEOUT, started=started)
        except asyncio.CancelledError:
            self._record(RolloutFailureKind.TIMEOUT, started=started)
            raise
        except Exception:  # noqa: BLE001 - background boundary is fail-closed
            self._record(RolloutFailureKind.RUNTIME, started=started)
        else:
            elapsed = int((self._clock() - started).total_seconds() * 1_000)
            self._metrics.record(
                RolloutMetricObservation(
                    1,
                    RolloutMode.SHADOW,
                    RolloutMetricStage.SHADOW,
                    self._config.revision,
                    ModelRole.DIRECT_CHAT
                    if receipt.selected_tier is not None
                    else None,
                    receipt.selected_tier,
                    None,
                    receipt.outcome,
                    None,
                    RolloutFailureKind.NONE,
                    latency_bucket(max(0, elapsed)),
                    RolloutLatencyBucket.NOT_RECORDED,
                )
            )

    def _consume(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _record(
        self,
        failure: RolloutFailureKind,
        *,
        started: datetime | None = None,
    ) -> None:
        elapsed = None
        if started is not None:
            elapsed = max(
                0,
                int((self._clock() - started).total_seconds() * 1_000),
            )
        self._metrics.record(
            RolloutMetricObservation(
                1,
                RolloutMode.SHADOW,
                RolloutMetricStage.SHADOW,
                self._config.revision,
                None,
                None,
                None,
                Outcome.FAILED,
                None,
                failure,
                latency_bucket(elapsed),
                RolloutLatencyBucket.NOT_RECORDED,
            )
        )
