from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.ports.context import (
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.ports.runtime import InputConnector
from dududa.rollout import (
    BoundedShadowSupervisor,
    CanaryCoordinator,
    CanaryExecutionDisposition,
    CanaryExecutionResult,
    RolloutAdmissionAction,
    RolloutClaimDisposition,
    RolloutControlProvider,
    ShadowSubmissionDisposition,
    decide_rollout_admission,
)
from dududa.runtime.state import (
    RuntimeInvocationOptions,
    RuntimeStartRequest,
    runtime_start_digest,
)

from .adapters.output import AstrBotOutputAdapter, InMemoryDeliveryLedger


class AstrBotBridgeAction(StrEnum):
    LEGACY = "legacy"
    SHADOW_SCHEDULED = "shadow_scheduled"
    SHADOW_DROPPED = "shadow_dropped"
    CANARY_COMPLETED = "canary_completed"
    CANARY_REPLAY = "canary_replay"
    CANARY_FAILED = "canary_failed"


@dataclass(frozen=True, slots=True)
class AstrBotBridgeResult:
    schema_version: int
    action: AstrBotBridgeAction
    legacy_owner: bool
    runtime_owner: bool
    reason_code: str
    canary: CanaryExecutionResult | None = None


class RolloutRequestFactory(Protocol):
    async def prepare(
        self,
        event: object,
        *,
        control_revision: str,
        timeout_seconds: float,
        tools_enabled: bool = False,
        memory_enabled: bool = False,
    ) -> tuple[RuntimeStartRequest, PortCallContext]: ...


class AstrBotRuntimeRequestFactory:
    def __init__(
        self,
        connector: InputConnector[object],
        runtime_budget: RuntimeBudget,
        policy_snapshot_id: str,
        *,
        response_profiles_enabled: bool = False,
        clock=None,
    ) -> None:
        if not isinstance(connector, InputConnector):
            raise TypeError("connector does not implement InputConnector")
        if not isinstance(runtime_budget, RuntimeBudget):
            raise TypeError("invalid rollout Runtime budget")
        if not isinstance(policy_snapshot_id, str) or not policy_snapshot_id.strip():
            raise ValueError("invalid rollout policy snapshot id")
        self._connector = connector
        self._runtime_budget = runtime_budget
        self._policy_snapshot_id = policy_snapshot_id
        self._response_profiles_enabled = response_profiles_enabled
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def prepare(
        self,
        event: object,
        *,
        control_revision: str,
        timeout_seconds: float,
        tools_enabled: bool = False,
        memory_enabled: bool = False,
    ) -> tuple[RuntimeStartRequest, PortCallContext]:
        if timeout_seconds <= 0:
            raise ValueError("invalid rollout request timeout")
        if type(tools_enabled) is not bool or type(memory_enabled) is not bool:
            raise ValueError("invalid rollout feature flag")
        now = self._clock()
        deadline = now + timedelta(seconds=timeout_seconds)
        operation_token = uuid4().hex
        connector_call = ServiceCallContext(
            operation_id=f"rollout-connector:{operation_token}",
            principal=ServicePrincipal(
                "astrbot-rollout",
                "local-plugin",
                frozenset({"connector"}),
            ),
            operation_kind="platform_input",
            trace=TraceContext(f"rollout-connector:{operation_token}"),
            deadline=deadline,
            cancellation=NeverCancelled(),
            budget=RuntimeBudget(0, 0, 0, 0, 0, Decimal("0")),
            policy_snapshot_id=self._policy_snapshot_id,
        )
        connector = await self._connector.convert(event, operation=connector_call)
        requested_features = {
            "tools": tools_enabled,
            "memory": memory_enabled,
        }
        if self._response_profiles_enabled:
            requested_features["response_profiles"] = True
        options = RuntimeInvocationOptions(
            1,
            None,
            "astrbot_rollout",
            requested_features,
            control_revision,
        )
        request = RuntimeStartRequest(
            1,
            connector,
            options,
            runtime_start_digest(connector, options),
        )
        run_id = str(
            canonical_digest(
                {
                    "message_key": connector.message.dedup_key,
                    "start_digest": request.start_digest,
                },
                domain="rollout:runtime-run:v1",
            )
        )
        call = PortCallContext(
            run_id=run_id,
            trace=TraceContext(
                str(
                    canonical_digest(
                        {"run_id": run_id},
                        domain="rollout:trace:v1",
                    )
                )
            ),
            deadline=deadline,
            cancellation=NeverCancelled(),
            budget=self._runtime_budget,
            policy_snapshot_id=self._policy_snapshot_id,
        )
        return request, call


class AstrBotRolloutBridge:
    def __init__(
        self,
        controls: RolloutControlProvider,
        requests: RolloutRequestFactory,
        shadow: BoundedShadowSupervisor,
        canary: CanaryCoordinator,
        output_ledger: InMemoryDeliveryLedger,
        *,
        output_factory: Callable[[object, InMemoryDeliveryLedger, object], object]
        | None = None,
        runtime_ready: bool = True,
    ) -> None:
        if not isinstance(controls, RolloutControlProvider):
            raise TypeError("controls do not implement RolloutControlProvider")
        if not isinstance(shadow, BoundedShadowSupervisor):
            raise TypeError("invalid bounded Shadow supervisor")
        if not isinstance(canary, CanaryCoordinator):
            raise TypeError("invalid Canary coordinator")
        if not isinstance(output_ledger, InMemoryDeliveryLedger):
            raise TypeError("invalid AstrBot Output ledger")
        if type(runtime_ready) is not bool:
            raise TypeError("invalid Runtime readiness flag")
        self._controls = controls
        self._requests = requests
        self._shadow = shadow
        self._canary = canary
        self._output_ledger = output_ledger
        self._output_factory = output_factory or (
            lambda event, ledger, guard: AstrBotOutputAdapter(
                event,
                ledger,
                send_guard=guard,
            )
        )
        self._runtime_ready = runtime_ready

    async def handle(self, event: object) -> AstrBotBridgeResult:
        try:
            config = self._controls.current()
        except Exception:  # noqa: BLE001 - invalid pre-claim config keeps legacy owner
            return _legacy("rollout_config_invalid")
        if config.mode.value == "off" or config.kill_switch:
            return _legacy("rollout_not_active")
        if not self._runtime_ready:
            return _legacy("rollout_runtime_unavailable")
        timeout = (
            config.shadow_timeout
            if config.mode.value == "shadow"
            else config.canary_timeout
        )
        try:
            request, call = await self._requests.prepare(
                event,
                control_revision=config.revision,
                timeout_seconds=timeout.total_seconds(),
                tools_enabled=config.tools_enabled,
                memory_enabled=config.memory_enabled,
            )
            admission = decide_rollout_admission(request.connector_result, config)
        except Exception:  # noqa: BLE001 - unsupported Event stays on legacy path
            return _legacy("rollout_event_not_supported")
        if admission.action is RolloutAdmissionAction.LEGACY:
            return _legacy(admission.reason_codes[0])
        if admission.action is RolloutAdmissionAction.SHADOW:
            disposition = self._shadow.submit(request, call=call)
            if disposition is ShadowSubmissionDisposition.ACCEPTED:
                return AstrBotBridgeResult(
                    1,
                    AstrBotBridgeAction.SHADOW_SCHEDULED,
                    True,
                    False,
                    "shadow_scheduled",
                )
            return AstrBotBridgeResult(
                1,
                AstrBotBridgeAction.SHADOW_DROPPED,
                True,
                False,
                disposition.value,
            )
        try:
            claim = self._canary.claim(admission, request)
        except Exception:  # noqa: BLE001 - claim commit may have succeeded
            try:
                event.stop_event()
            except Exception:  # noqa: BLE001 - no safe fallback remains
                pass
            return AstrBotBridgeResult(
                1,
                AstrBotBridgeAction.CANARY_FAILED,
                False,
                True,
                "canary_claim_outcome_unknown",
            )
        if claim is None:
            return _legacy("canary_control_changed_before_claim")
        try:
            event.stop_event()
        except Exception:  # noqa: BLE001 - claim remains owner; do not attempt send
            aborted = self._canary.abort_claim(
                claim,
                run_id=call.run_id,
                reason_code="event_stop_failed",
            )
            return AstrBotBridgeResult(
                1,
                AstrBotBridgeAction.CANARY_FAILED,
                False,
                True,
                "event_stop_failed",
                aborted,
            )
        if claim.disposition is not RolloutClaimDisposition.ACQUIRED:
            replay = self._canary.replay_result(claim, run_id=call.run_id)
            return AstrBotBridgeResult(
                1,
                AstrBotBridgeAction.CANARY_REPLAY,
                False,
                True,
                replay.reason_code,
                replay,
            )
        result = await self._canary.execute(
            claim,
            request,
            lambda guard: self._output_factory(
                event,
                self._output_ledger,
                guard,
            ),
            call=call,
        )
        action = (
            AstrBotBridgeAction.CANARY_FAILED
            if result.disposition is CanaryExecutionDisposition.FAILED
            else AstrBotBridgeAction.CANARY_COMPLETED
        )
        return AstrBotBridgeResult(
            1,
            action,
            False,
            True,
            result.reason_code,
            result,
        )

    async def close(self) -> None:
        await self._shadow.close()


def _legacy(reason: str) -> AstrBotBridgeResult:
    return AstrBotBridgeResult(
        1,
        AstrBotBridgeAction.LEGACY,
        True,
        False,
        reason,
    )
