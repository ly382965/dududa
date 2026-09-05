from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.delivery import (
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryStatus,
)
from dududa.domain.primitives import RuntimeBudget, TraceContext
from dududa.ports.context import (
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.ports.runtime import AgentRuntime, InputConnector, RuntimeStateStore
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
    CompletionReceipt,
    ConnectorResult,
    RuntimeInvocationOptions,
    RuntimePhase,
    RuntimeResult,
    RuntimeStartRequest,
    runtime_start_digest,
)

from .adapters.output import AstrBotOutputAdapter, InMemoryDeliveryLedger
from .runtime_admission import tracked_runtime_call


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
    runtime_reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AstrBotRuntimePreviewResult:
    runtime_result: RuntimeResult
    completion: CompletionReceipt
    tool_calls: int
    capability_ids: tuple[str, ...] = ()
    context_usage: Mapping[str, object] | None = None
    generation_observed: bool = False
    diagnostics: Mapping[str, object] | None = None


class AstrBotRuntimePreviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RolloutRequestFactory(Protocol):
    async def prepare(
        self,
        event: object,
        *,
        control_revision: str,
        timeout_seconds: float,
        tools_enabled: bool = False,
        memory_enabled: bool = False,
        proactive_group_participation: bool = False,
    ) -> tuple[RuntimeStartRequest, PortCallContext]: ...


class ScopePolicyResolver(Protocol):
    def feature_flags(self, connector: ConnectorResult) -> Mapping[str, bool]: ...


class AstrBotRuntimeRequestFactory:
    def __init__(
        self,
        connector: InputConnector[object],
        runtime_budget: RuntimeBudget,
        policy_snapshot_id: str,
        *,
        response_profiles_enabled: bool = False,
        scope_policy_resolver: ScopePolicyResolver | None = None,
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
        self._scope_policy_resolver = scope_policy_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def prepare(
        self,
        event: object,
        *,
        control_revision: str,
        timeout_seconds: float,
        tools_enabled: bool = False,
        memory_enabled: bool = False,
        proactive_group_participation: bool = False,
    ) -> tuple[RuntimeStartRequest, PortCallContext]:
        if timeout_seconds <= 0:
            raise ValueError("invalid rollout request timeout")
        if any(
            type(value) is not bool
            for value in (
                tools_enabled,
                memory_enabled,
                proactive_group_participation,
            )
        ):
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
        requested_features: dict[str, bool] = {
            "tools": tools_enabled and not proactive_group_participation,
            "memory": memory_enabled and not proactive_group_participation,
        }
        if self._response_profiles_enabled:
            requested_features["response_profiles"] = True
        if self._scope_policy_resolver is not None:
            scope_features = dict(self._scope_policy_resolver.feature_flags(connector))
            if set(scope_features) & set(requested_features):
                raise ValueError("Scope policy cannot replace global feature flags")
            requested_features.update(scope_features)
        if proactive_group_participation:
            adaptive_tools = requested_features.get("proactive_readonly_tools", False)
            requested_features.update(
                {
                    "proactive_group_participation": True,
                    "tools": tools_enabled and adaptive_tools,
                    "response_profile.force_short": not adaptive_tools,
                    "response_profile.force_medium": False,
                    "response_profile.force_long": adaptive_tools,
                }
            )
        options = RuntimeInvocationOptions(
            1,
            None,
            (
                "astrbot_proactive_talk"
                if proactive_group_participation
                else "astrbot_rollout"
            ),
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
        runtime: AgentRuntime,
        state_store: RuntimeStateStore | None = None,
        output_factory: Callable[[object, InMemoryDeliveryLedger, object], object]
        | None = None,
        runtime_ready: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(controls, RolloutControlProvider):
            raise TypeError("controls do not implement RolloutControlProvider")
        if not isinstance(shadow, BoundedShadowSupervisor):
            raise TypeError("invalid bounded Shadow supervisor")
        if not isinstance(canary, CanaryCoordinator):
            raise TypeError("invalid Canary coordinator")
        if not isinstance(output_ledger, InMemoryDeliveryLedger):
            raise TypeError("invalid AstrBot Output ledger")
        if not isinstance(runtime, AgentRuntime):
            raise TypeError("runtime does not implement AgentRuntime")
        if state_store is not None and not isinstance(state_store, RuntimeStateStore):
            raise TypeError("state_store does not implement RuntimeStateStore")
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
        self._runtime = runtime
        self._state_store = state_store
        self._runtime_ready = runtime_ready
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @tracked_runtime_call
    async def preview(self, event: object, *, proactive_group_participation: bool = False) -> AstrBotRuntimePreviewResult:
        """Run the installed 2.0 Runtime and acknowledge a synthetic no-send output."""

        try:
            config = self._controls.current()
        except Exception as exc:  # noqa: BLE001 - return one stable public code
            raise AstrBotRuntimePreviewError("rollout_config_invalid") from exc
        if not self._runtime_ready:
            raise AstrBotRuntimePreviewError("rollout_runtime_unavailable")
        timeout = config.canary_timeout.total_seconds()
        try:
            request, call = await self._requests.prepare(
                event,
                control_revision=config.revision,
                timeout_seconds=timeout,
                tools_enabled=config.tools_enabled,
                memory_enabled=False,
                proactive_group_participation=proactive_group_participation,
            )
        except Exception as exc:  # noqa: BLE001 - synthetic input stays fail closed
            raise AstrBotRuntimePreviewError("rollout_event_not_supported") from exc
        if not request.options.feature_flags.get("scope_agent_enabled", True):
            raise AstrBotRuntimePreviewError("scope_agent_disabled")
        admission = decide_rollout_admission(
            request.connector_result, config, allow_proactive_group=proactive_group_participation,
        )
        if admission.action is RolloutAdmissionAction.LEGACY:
            raise AstrBotRuntimePreviewError(admission.reason_codes[0])
        try:
            result = await asyncio.wait_for(
                self._runtime.run(request, call=call),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise AstrBotRuntimePreviewError("runtime_preview_timeout") from exc
        completion = result.completion
        capability_ids: tuple[str, ...] = ()
        history = getattr(event, "dududa_preview_history", None) or {}
        context_usage: Mapping[str, object] | None = {
            "messagesRead": 0, "charactersRead": 0,
            "coverage": {"source": history.get("source", "unavailable"), "partial": True,
                         "truncated": bool(history.get("messages")), "historyMessagesRead": 0,
                         "oldestAt": None, "newestAt": None},
        }
        generation_observed = False
        diagnostics: dict[str, object] = {}
        if self._state_store is not None:
            checkpoint = await self._state_store.load(result.run_id, call=call)
            if checkpoint is not None:
                state = checkpoint.state
                perception_execution = state.perception_execution
                if perception_execution is not None:
                    diagnostics.update(
                        perceptionFailure=perception_execution.failure_code,
                        perceptionModelStarted=perception_execution.model_call_started,
                        perceptionReasons=list(perception_execution.result.reason_codes),
                    )
                    perception_route = perception_execution.route_decision
                    if perception_route is not None:
                        diagnostics["perceptionRejections"] = [list(item.reason_codes) for item in perception_route.rejected_endpoints]
                if state.tool_plan is not None:
                    diagnostics["toolArguments"] = [dict(step.arguments.literal_template) for step in state.tool_plan.steps]
                if state.direct_chat_failure is not None:
                    route = state.direct_chat_failure.route_decision
                    diagnostics["directFailure"] = state.direct_chat_failure.failure_code
                    diagnostics["directRejections"] = [list(item.reason_codes) for item in route.rejected_endpoints] if route else []
                    diagnostics["directErrorReasons"] = list(route.terminal_error.reason_codes) if route and route.terminal_error else []
                    diagnostics["directAttempts"] = [{"model": attempt.model_id, "error": attempt.error.code if attempt.error else None,
                        "reasons": list(attempt.error.reason_codes) if attempt.error else []} for attempt in route.attempts] if route else []
                if state.capability_run_receipt is not None:
                    from dududa.runtime.capabilities import tool_context_tokens_upper_bound
                    receipt = state.capability_run_receipt
                    diagnostics["capabilityStatus"] = receipt.status.value
                    if receipt.status.value == "completed" and receipt.validation and receipt.validation.accepted_observations:
                        diagnostics["toolInputBytes"] = tool_context_tokens_upper_bound(receipt)
                if state.current_context is not None:
                    diagnostics["historyInputBytes"] = state.current_context.perception.content_input_tokens_upper_bound
                generation_observed = state.direct_chat_execution is not None
                if state.tool_plan is not None:
                    capability_ids = tuple(step.capability_id for step in state.tool_plan.steps)
                if state.current_context is not None:
                    perception = state.current_context.perception
                    history = getattr(event, "dududa_preview_history", None) or {}
                    records = history.get("messages", [])
                    used = [records[int(item.message_ref.rsplit(":", 1)[1])]
                            for item in perception.messages if item.message_ref.startswith("message:history:")]
                    dates = sorted(item["timestamp"] for item in used if item.get("timestamp"))
                    context_usage = {
                        "messagesRead": len(perception.messages),
                        "charactersRead": sum(len(item.text) for item in perception.messages),
                        "coverage": {
                            "source": history.get("source", "unavailable"), "partial": True,
                            "truncated": bool(history.get("truncated")) or len(used) < len(records)
                            or "preview_history_truncated" in perception.degraded_components,
                            "historyMessagesRead": len(used),
                            "oldestAt": dates[0] if dates else None,
                            "newestAt": dates[-1] if dates else None,
                        },
                    }
        if result.delivery_request is not None:
            receipt = _preview_delivery_receipt(
                result.delivery_request,
                acknowledged_at=self._clock(),
            )
            completion = await self._runtime.acknowledge_delivery(receipt, call=call)
        if completion is None:
            raise AstrBotRuntimePreviewError("runtime_preview_completion_missing")
        return AstrBotRuntimePreviewResult(
            runtime_result=result,
            completion=completion,
            tool_calls=(
                1 if RuntimePhase.TOOLS_EXECUTED in result.trace_summary.phases else 0
            ),
            capability_ids=capability_ids,
            context_usage=context_usage,
            generation_observed=generation_observed,
            diagnostics=diagnostics,
        )

    @tracked_runtime_call
    async def handle(
        self,
        event: object,
        *,
        proactive_group_participation: bool = False,
    ) -> AstrBotBridgeResult:
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
                proactive_group_participation=proactive_group_participation,
            )
            if not request.options.feature_flags.get("scope_agent_enabled", True):
                return _legacy("scope_agent_disabled")
            admission = decide_rollout_admission(
                request.connector_result,
                config,
                allow_proactive_group=proactive_group_participation,
            )
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
        runtime_reason_codes = await self._runtime_reason_codes(
            result.run_id,
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
            runtime_reason_codes,
        )

    async def _runtime_reason_codes(
        self,
        run_id: str,
        *,
        call: PortCallContext,
    ) -> tuple[str, ...]:
        if self._state_store is None:
            return ()
        try:
            checkpoint = await self._state_store.load(run_id, call=call)
        except Exception:  # noqa: BLE001 - diagnostics must not alter execution
            return ()
        pending = checkpoint.state.pending_result if checkpoint is not None else None
        return pending.reason_codes if pending is not None else ()

    async def close(self) -> None:
        self._configuration_paused = True
        if getattr(self, "_active_configuration_calls", 0):
            raise RuntimeError("runtime_requests_active")
        await self._shadow.close()

    def pause_configuration(self) -> bool:
        if getattr(self, "_active_configuration_calls", 0) or self._shadow.active_count:
            return False
        self._configuration_paused = True
        return True

    def resume_configuration(self) -> None:
        self._configuration_paused = False


def _legacy(reason: str) -> AstrBotBridgeResult:
    return AstrBotBridgeResult(
        1,
        AstrBotBridgeAction.LEGACY,
        True,
        False,
        reason,
    )


def _preview_delivery_receipt(request, *, acknowledged_at) -> DeliveryReceipt:
    parts = tuple(
        DeliveryPartReceipt(
            schema_version=1,
            part_id=part.part_id,
            content_digest=part.content_digest,
            status=DeliveryPartStatus.SUCCEEDED,
            platform_message_ref=None,
            error_code=None,
        )
        for part in request.part_intents
    )
    return DeliveryReceipt(
        schema_version=1,
        delivery_id=request.delivery_id,
        run_id=request.run_id,
        delivery_request_digest=request.request_digest,
        idempotency_key=request.idempotency_key,
        attempt=request.attempt,
        adapter_revision=request.adapter_binding.component_revision,
        status=DeliveryStatus.SUCCEEDED,
        parts=parts,
        acknowledged_at=acknowledged_at,
        error_code=None,
    )
