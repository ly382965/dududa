from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from dududa._compat import StrEnum
from dududa.domain.delivery import DeliveryRequest, DeliveryStatus
from dududa.domain.primitives import Outcome
from dududa.errors import validation_error
from dududa.ports.context import PortCallContext
from dududa.ports.output import OutputAdapter
from dududa.ports.runtime import AgentRuntime
from dududa.runtime.state import CompletionReceipt, RuntimeStartRequest

from .admission import decide_rollout_admission
from .contracts import (
    RolloutAdmissionAction,
    RolloutAdmissionDecision,
    RolloutClaimDisposition,
    RolloutClaimResult,
    RolloutControlProvider,
    RolloutMode,
    RolloutOwnershipRecord,
    RolloutOwnershipState,
)
from .metrics import (
    RolloutFailureKind,
    RolloutLatencyBucket,
    RolloutMetricObservation,
    RolloutMetricStage,
    latency_bucket,
)
from .ports import RolloutMetricSink, RolloutOwnershipLedger


class CanaryExecutionDisposition(StrEnum):
    REPLAY = "replay"
    NO_DELIVERY = "no_delivery"
    SUPPRESSED = "suppressed"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CanaryExecutionResult:
    schema_version: int
    run_id: str
    disposition: CanaryExecutionDisposition
    ownership: RolloutOwnershipRecord
    completion: CompletionReceipt | None
    reason_code: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        if not self.run_id.strip():
            raise validation_error("empty_canary_run_id")
        if not isinstance(self.disposition, CanaryExecutionDisposition):
            raise validation_error("invalid_canary_execution_disposition")
        if not isinstance(self.ownership, RolloutOwnershipRecord):
            raise validation_error("invalid_rollout_ownership_record")
        if self.completion is not None and not isinstance(
            self.completion, CompletionReceipt
        ):
            raise validation_error("invalid_canary_completion")
        if not self.reason_code.strip():
            raise validation_error("empty_canary_reason_code")


class CanarySendGuard(Protocol):
    def __call__(self, request: DeliveryRequest, part_number: int) -> str | None: ...


class CanaryOutputFactory(Protocol):
    def __call__(self, send_guard: CanarySendGuard) -> OutputAdapter: ...


class CanaryCoordinator:
    def __init__(
        self,
        runtime: AgentRuntime,
        controls: RolloutControlProvider,
        ledger: RolloutOwnershipLedger,
        metrics: RolloutMetricSink,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(runtime, AgentRuntime):
            raise TypeError("runtime does not implement AgentRuntime")
        if not isinstance(controls, RolloutControlProvider):
            raise TypeError("controls do not implement RolloutControlProvider")
        if not isinstance(ledger, RolloutOwnershipLedger):
            raise TypeError("invalid rollout ledger")
        if not isinstance(metrics, RolloutMetricSink):
            raise TypeError("invalid rollout metrics")
        self._runtime = runtime
        self._controls = controls
        self._ledger = ledger
        self._metrics = metrics
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def claim(
        self,
        admission: RolloutAdmissionDecision,
        request: RuntimeStartRequest,
    ) -> RolloutClaimResult | None:
        if admission.action is not RolloutAdmissionAction.CANARY:
            return None
        try:
            current = self._controls.current()
            refreshed = decide_rollout_admission(
                request.connector_result,
                current,
                allow_proactive_group=request.options.feature_flags.get(
                    "proactive_group_participation",
                    False,
                ),
            )
        except Exception:  # noqa: BLE001 - invalid live control fails before ownership
            self._record(
                RolloutMetricStage.CLAIM,
                RolloutFailureKind.CONFIG_INVALID,
                admission.control_revision,
            )
            return None
        if (
            refreshed.action is not RolloutAdmissionAction.CANARY
            or refreshed.control_revision != admission.control_revision
            or refreshed.message_key_digest != admission.message_key_digest
        ):
            self._record(
                RolloutMetricStage.CLAIM,
                RolloutFailureKind.CONTROL_CHANGED,
                current.revision,
            )
            return None
        result = self._ledger.claim(
            admission.message_key_digest,
            request.start_digest,
            admission.control_revision,
        )
        failure = (
            RolloutFailureKind.NONE
            if result.disposition is not RolloutClaimDisposition.CONFLICT
            else RolloutFailureKind.CONFLICT
        )
        self._record(RolloutMetricStage.CLAIM, failure, admission.control_revision)
        return result

    def replay_result(
        self,
        claim: RolloutClaimResult,
        *,
        run_id: str,
    ) -> CanaryExecutionResult:
        if claim.disposition is RolloutClaimDisposition.ACQUIRED:
            raise validation_error("acquired_canary_claim_is_not_replay")
        return CanaryExecutionResult(
            1,
            run_id,
            CanaryExecutionDisposition.REPLAY,
            claim.record,
            None,
            (
                "ownership_conflict"
                if claim.disposition is RolloutClaimDisposition.CONFLICT
                else "ownership_replay"
            ),
        )

    def abort_claim(
        self,
        claim: RolloutClaimResult,
        *,
        run_id: str,
        reason_code: str,
    ) -> CanaryExecutionResult:
        if claim.disposition is not RolloutClaimDisposition.ACQUIRED:
            return self.replay_result(claim, run_id=run_id)
        record = self._ledger.mark_aborted(
            claim.record.message_key_digest,
            claim.record.revision,
            RolloutOwnershipState.CLAIMED,
            reason_code,
        )
        return CanaryExecutionResult(
            1,
            run_id,
            CanaryExecutionDisposition.FAILED,
            record,
            None,
            reason_code,
        )

    async def execute(
        self,
        claim: RolloutClaimResult,
        request: RuntimeStartRequest,
        output_factory: CanaryOutputFactory,
        *,
        call: PortCallContext,
    ) -> CanaryExecutionResult:
        if claim.disposition is not RolloutClaimDisposition.ACQUIRED:
            return self.replay_result(claim, run_id=call.run_id)
        if claim.record.invocation_digest != request.start_digest:
            raise validation_error("canary_claim_request_mismatch")
        started = self._clock()
        record = self._ledger.mark_runtime_started(
            claim.record.message_key_digest,
            claim.record.revision,
        )
        try:
            control = self._controls.current()
            remaining = max(0.0, (call.deadline - started).total_seconds())
            timeout = min(control.canary_timeout.total_seconds(), remaining)
            if timeout <= 0:
                raise asyncio.TimeoutError
            runtime_result = await asyncio.wait_for(
                self._runtime.run(request, call=call),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            record = self._ledger.mark_aborted(
                record.message_key_digest,
                record.revision,
                record.state,
                "canary_cancelled_before_send",
            )
            self._record_runtime_failure(started, RolloutFailureKind.TIMEOUT, record)
            raise
        except asyncio.TimeoutError:
            record = self._ledger.mark_aborted(
                record.message_key_digest,
                record.revision,
                record.state,
                "canary_runtime_timeout",
            )
            self._record_runtime_failure(started, RolloutFailureKind.TIMEOUT, record)
            return CanaryExecutionResult(
                1,
                call.run_id,
                CanaryExecutionDisposition.FAILED,
                record,
                None,
                "canary_runtime_timeout",
            )
        except Exception:  # noqa: BLE001 - claimed messages cannot fall back
            record = self._ledger.mark_aborted(
                record.message_key_digest,
                record.revision,
                record.state,
                "canary_runtime_failed",
            )
            self._record_runtime_failure(started, RolloutFailureKind.RUNTIME, record)
            return CanaryExecutionResult(
                1,
                call.run_id,
                CanaryExecutionDisposition.FAILED,
                record,
                None,
                "canary_runtime_failed",
            )
        delivery = runtime_result.delivery_request
        if delivery is None:
            no_delivery_reason = {
                Outcome.NO_REPLY: "runtime_no_reply_without_delivery",
                Outcome.DEFERRED: "runtime_deferred_without_delivery",
                Outcome.FAILED: "runtime_failed_without_delivery",
            }.get(runtime_result.outcome, "runtime_completed_without_delivery")
            record = self._ledger.mark_no_delivery(
                record.message_key_digest,
                record.revision,
                no_delivery_reason,
            )
            self._record_result(
                started,
                runtime_result.outcome,
                DeliveryStatus.NOT_REQUIRED,
                RolloutFailureKind.NONE,
                record,
            )
            return CanaryExecutionResult(
                1,
                call.run_id,
                CanaryExecutionDisposition.NO_DELIVERY,
                record,
                runtime_result.completion,
                no_delivery_reason,
            )
        try:
            record = self._ledger.mark_ready_to_send(
                record.message_key_digest,
                record.revision,
                delivery.delivery_id,
                delivery.request_digest,
            )
        except Exception:  # noqa: BLE001 - ownership remains Runtime on conflict
            current = self._ledger.load(record.message_key_digest)
            if (
                current is not None
                and current.state is RolloutOwnershipState.RUNTIME_STARTED
            ):
                record = self._ledger.mark_aborted(
                    current.message_key_digest,
                    current.revision,
                    current.state,
                    "canary_delivery_binding_conflict",
                )
            self._record_result(
                started,
                runtime_result.outcome,
                None,
                RolloutFailureKind.CONFLICT,
                record,
            )
            return CanaryExecutionResult(
                1,
                call.run_id,
                CanaryExecutionDisposition.FAILED,
                record,
                None,
                "canary_delivery_binding_conflict",
            )
        guard = _PersistentCanarySendGuard(
            self._controls,
            self._ledger,
            request,
            record,
        )
        try:
            output = output_factory(guard)
            if not isinstance(output, OutputAdapter):
                raise validation_error("invalid_canary_output_adapter")
            receipt = await output.deliver(delivery, call=call)
        except asyncio.CancelledError:
            record = self._finalize_output_exception(record, "canary_send_cancelled")
            self._record_result(
                started,
                runtime_result.outcome,
                record.delivery_status,
                RolloutFailureKind.OUTCOME_UNKNOWN,
                record,
            )
            raise
        except Exception:  # noqa: BLE001 - normalize side-effect boundary failure
            record = self._finalize_output_exception(record, "canary_output_failed")
            failure = (
                RolloutFailureKind.OUTCOME_UNKNOWN
                if record.state is RolloutOwnershipState.UNKNOWN
                else RolloutFailureKind.OUTPUT
            )
            self._record_result(
                started,
                runtime_result.outcome,
                record.delivery_status,
                failure,
                record,
            )
            return CanaryExecutionResult(
                1,
                call.run_id,
                CanaryExecutionDisposition.FAILED,
                record,
                None,
                record.reason_code or "canary_output_failed",
            )
        current = self._ledger.load(record.message_key_digest)
        if current is None:
            raise validation_error("rollout_ownership_not_found")
        if current.state is RolloutOwnershipState.READY_TO_SEND:
            record = self._ledger.mark_suppressed(
                current.message_key_digest,
                current.revision,
                receipt.error_code or "pre_delivery_control_rejected",
            )
            disposition = CanaryExecutionDisposition.SUPPRESSED
            failure = RolloutFailureKind.CONTROL_CHANGED
        elif current.state is RolloutOwnershipState.SEND_STARTED:
            record = self._ledger.finish_delivery(current.message_key_digest, receipt)
            disposition = CanaryExecutionDisposition.DELIVERED
            failure = (
                RolloutFailureKind.OUTCOME_UNKNOWN
                if receipt.status is DeliveryStatus.UNKNOWN
                else RolloutFailureKind.NONE
            )
        else:
            raise validation_error("invalid_rollout_delivery_gate_state")
        try:
            completion = await self._runtime.acknowledge_delivery(receipt, call=call)
        except Exception:  # noqa: BLE001 - delivery tombstone already owns replay
            self._record_result(
                started,
                runtime_result.outcome,
                record.delivery_status,
                RolloutFailureKind.ACKNOWLEDGEMENT,
                record,
            )
            return CanaryExecutionResult(
                1,
                call.run_id,
                CanaryExecutionDisposition.FAILED,
                record,
                None,
                "canary_acknowledgement_failed",
            )
        self._record_result(
            started,
            runtime_result.outcome,
            receipt.status,
            failure,
            record,
        )
        return CanaryExecutionResult(
            1,
            call.run_id,
            disposition,
            record,
            completion,
            record.reason_code or "canary_delivery_recorded",
        )

    def _finalize_output_exception(
        self,
        previous: RolloutOwnershipRecord,
        reason_code: str,
    ) -> RolloutOwnershipRecord:
        current = self._ledger.load(previous.message_key_digest)
        if current is None:
            raise validation_error("rollout_ownership_not_found")
        if current.state is RolloutOwnershipState.SEND_STARTED:
            return self._ledger.mark_send_unknown(
                current.message_key_digest,
                current.revision,
                reason_code,
            )
        if current.state is RolloutOwnershipState.READY_TO_SEND:
            return self._ledger.mark_aborted(
                current.message_key_digest,
                current.revision,
                current.state,
                reason_code,
            )
        return current

    def _record_runtime_failure(
        self,
        started: datetime,
        failure: RolloutFailureKind,
        record: RolloutOwnershipRecord,
    ) -> None:
        self._record_result(started, Outcome.FAILED, None, failure, record)

    def _record_result(
        self,
        started: datetime,
        outcome: Outcome,
        status: DeliveryStatus | None,
        failure: RolloutFailureKind,
        record: RolloutOwnershipRecord,
    ) -> None:
        elapsed = max(0, int((self._clock() - started).total_seconds() * 1_000))
        self._metrics.record(
            RolloutMetricObservation(
                1,
                RolloutMode.CANARY,
                RolloutMetricStage.DELIVERY,
                record.control_revision,
                None,
                None,
                None,
                outcome,
                status,
                failure,
                latency_bucket(elapsed),
                RolloutLatencyBucket.NOT_RECORDED,
            )
        )

    def _record(
        self,
        stage: RolloutMetricStage,
        failure: RolloutFailureKind,
        revision: str,
    ) -> None:
        self._metrics.record(
            RolloutMetricObservation(
                1,
                RolloutMode.CANARY,
                stage,
                revision,
                None,
                None,
                None,
                None,
                None,
                failure,
                RolloutLatencyBucket.NOT_RECORDED,
                RolloutLatencyBucket.NOT_RECORDED,
            )
        )


class _PersistentCanarySendGuard:
    def __init__(
        self,
        controls: RolloutControlProvider,
        ledger: RolloutOwnershipLedger,
        request: RuntimeStartRequest,
        record: RolloutOwnershipRecord,
    ) -> None:
        self._controls = controls
        self._ledger = ledger
        self._request = request
        self._message_key_digest = record.message_key_digest
        self._control_revision = record.control_revision
        self._started = False

    def __call__(self, request: DeliveryRequest, part_number: int) -> str | None:
        if type(part_number) is not int or part_number < 1:
            return "invalid_delivery_part"
        try:
            control = self._controls.current()
            admission = decide_rollout_admission(
                self._request.connector_result,
                control,
            )
        except Exception:  # noqa: BLE001 - malformed live config denies send
            return "rollout_config_invalid"
        if control.revision != self._control_revision:
            return "rollout_control_revision_changed"
        if control.mode is not RolloutMode.CANARY:
            return "rollout_mode_changed"
        if control.kill_switch:
            return "rollout_kill_switch_active"
        if not control.delivery_enabled:
            return "rollout_delivery_disabled"
        if admission.action is not RolloutAdmissionAction.CANARY:
            return "rollout_admission_changed"
        if not self._started:
            try:
                self._ledger.begin_delivery(
                    self._message_key_digest,
                    request.delivery_id,
                    request.request_digest,
                )
            except Exception:  # noqa: BLE001 - uncertain reservation denies send
                return "rollout_delivery_reservation_failed"
            self._started = True
        return None
