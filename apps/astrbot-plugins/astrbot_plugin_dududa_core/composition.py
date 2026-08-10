from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from dududa.adapters import InMemoryAttachmentRepository
from dududa.domain.primitives import ComponentRevision, DigestString, RuntimeBudget
from dududa.errors import ErrorCategory, error
from dududa.ports.runtime import AgentRuntime, InputConnector
from dududa.rollout import (
    BoundedShadowSupervisor,
    CanaryCoordinator,
    InMemoryRolloutMetrics,
    SQLiteRolloutLedger,
    SQLiteRolloutLedgerConfig,
)
from dududa.runtime.shadow import ShadowRunner

from .adapters.mcp_runtime import build_icourse_client
from .adapters.message import AstrBotInputConnector
from .adapters.output import InMemoryDeliveryLedger
from .config import (
    MCP_REGISTRY_DIR,
    MCP_WORKER_PYTHON,
    PLUGIN_DATA_DIR,
    ROLLOUT_LEDGER_PATH,
    AstrBotRolloutControlProvider,
    ensure_dirs,
    load_json,
)
from .rollout_bridge import AstrBotRolloutBridge, AstrBotRuntimeRequestFactory

logger = logging.getLogger(__name__)


class ProductionRuntimeAssembly:
    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        ready: bool,
        closeables: Iterable[object] = (),
        abort_callbacks: Iterable[Callable[[], None]] = (),
    ) -> None:
        if not isinstance(runtime, AgentRuntime):
            raise TypeError("runtime does not implement AgentRuntime")
        if type(ready) is not bool:
            raise TypeError("invalid production Runtime readiness")
        resources = tuple(closeables)
        if any(not callable(getattr(item, "close", None)) for item in resources):
            raise TypeError("production Runtime resource is not closeable")
        callbacks = tuple(abort_callbacks)
        if any(not callable(callback) for callback in callbacks):
            raise TypeError("invalid production Runtime abort callback")
        self.runtime = runtime
        self.ready = ready
        self._closeables = list(resources)
        self._abort_callbacks = list(callbacks)
        self._abort_started = False
        self._aborted = False
        self._closed = False
        self._installed = False

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def installable(self) -> bool:
        return not self._installed and not self._abort_started and not self._closed

    def mark_installed(self) -> None:
        if not self.installable:
            raise RuntimeError("production Runtime assembly is not installable")
        self._installed = True

    def abort(self) -> None:
        if self._aborted or self._closed:
            return
        self._abort_started = True
        first_error = self._run_abort_callbacks()
        if first_error is not None:
            raise first_error

    def _run_abort_callbacks(self) -> BaseException | None:
        first_error: BaseException | None = None
        failed: list[Callable[[], None]] = []
        for callback in reversed(self._abort_callbacks):
            try:
                callback()
            except BaseException as exc:  # cleanup continues before surfacing
                first_error = first_error or exc
                failed.append(callback)
        self._abort_callbacks = list(reversed(failed))
        self._aborted = not self._abort_callbacks
        return first_error

    async def close(self) -> None:
        if self._closed:
            return
        first_error: BaseException | None = None
        if self._abort_started and self._abort_callbacks:
            first_error = self._run_abort_callbacks()
        failed: list[object] = []
        for resource in reversed(self._closeables):
            try:
                result = resource.close()
                if inspect.isawaitable(result):
                    await result
            except BaseException as exc:  # cleanup continues before surfacing
                first_error = first_error or exc
                failed.append(resource)
        self._closeables = list(reversed(failed))
        self._closed = not self._closeables and (
            not self._abort_started or self._aborted
        )
        if first_error is not None:
            raise first_error


class _UnavailableAgentRuntime:
    async def run(self, request: object, *, call: object) -> object:
        raise _runtime_unavailable()

    async def acknowledge_delivery(self, receipt: object, *, call: object) -> object:
        raise _runtime_unavailable()

    async def reconcile_delivery(self, receipt: object, *, call: object) -> object:
        raise _runtime_unavailable()


def unavailable_runtime_assembly() -> ProductionRuntimeAssembly:
    return ProductionRuntimeAssembly(_UnavailableAgentRuntime(), ready=False)


def initialize_plugin(
    plugin: Any,
    config: dict | None = None,
    *,
    runtime_assembly: ProductionRuntimeAssembly | None = None,
) -> None:
    from .audit import AuditLog
    from .permissions import PermissionManager

    if getattr(plugin, "_dududa_runtime_initialized", False):
        raise RuntimeError("Dududa Runtime plugin is already initialized")
    plugin._dududa_runtime_initialized = True
    plugin.config = config or {}
    plugin.enabled = bool(plugin.config.get("enabled", True))
    ensure_dirs()
    plugin.perms = PermissionManager(plugin.config)
    plugin.audit = AuditLog()
    plugin.icourse, plugin.icourse_mode, icourse_reason = build_icourse_client(
        plugin.config,
        registry_directory=MCP_REGISTRY_DIR,
        worker_python=MCP_WORKER_PYTHON,
    )
    plugin.icourse_reason = icourse_reason
    if plugin.icourse_mode != "unified":
        logger.warning("Unified iCourse MCP unavailable: reason=%s", icourse_reason)
    plugin.pending = {}
    plugin.course_refresh_at = {}
    plugin.user_state_path = PLUGIN_DATA_DIR / "user_state.json"
    plugin.group_state_path = PLUGIN_DATA_DIR / "group_state.json"
    plugin.user_state = load_json(plugin.user_state_path, {})
    plugin.group_state = load_json(plugin.group_state_path, {})
    plugin.rollout_controls = AstrBotRolloutControlProvider(plugin.config)
    plugin.rollout_metrics = InMemoryRolloutMetrics()
    plugin.rollout_ledger = None
    plugin.rollout_bridge = None
    plugin.runtime_assembly = None
    plugin._dududa_runtime_cleanup_assemblies = []
    plugin._dududa_runtime_terminated = False
    try:
        plugin.rollout_ledger = SQLiteRolloutLedger(
            SQLiteRolloutLedgerConfig(
                schema_version=1,
                path=ROLLOUT_LEDGER_PATH,
                busy_timeout=timedelta(seconds=5),
                terminal_ttl=timedelta(days=30),
                maximum_records=100_000,
                component_revision=ComponentRevision(
                    "rollout-ledger.sqlite",
                    "1.0.0",
                    "s11-v1",
                    DigestString("builtin"),
                ),
            )
        )
        recovered = plugin.rollout_ledger.recover_incomplete()
        if recovered:
            logger.warning(
                "Dududa rollout recovered %d incomplete ownership records",
                len(recovered),
            )
    except Exception:  # noqa: BLE001 - unavailable persistence keeps rollout disabled
        logger.error("Dududa rollout persistence unavailable; rollout remains disabled")
    install_production_runtime(
        plugin,
        runtime_assembly or unavailable_runtime_assembly(),
        _default_runtime_budget(),
        "production-shape-v1",
    )
    logger.info("DududaCore loaded: enabled=%s", plugin.enabled)


def install_production_runtime(
    plugin: Any,
    assembly: ProductionRuntimeAssembly,
    runtime_budget: RuntimeBudget,
    policy_snapshot_id: str,
    *,
    connector: InputConnector[object] | None = None,
    clock: Any = None,
) -> AstrBotRolloutBridge | None:
    if not isinstance(assembly, ProductionRuntimeAssembly):
        raise TypeError("invalid production Runtime assembly")
    existing = getattr(plugin, "rollout_bridge", None)
    if existing is not None:
        if getattr(plugin, "runtime_assembly", None) is assembly:
            return existing
        if not assembly.installable:
            raise RuntimeError("production Runtime assembly is not installable")
        try:
            assembly.abort()
        except Exception:
            logger.error("Duplicate Dududa Runtime assembly abort failed")
        _retain_cleanup_assembly(plugin, assembly)
        return existing
    if not assembly.installable or any(
        item is assembly
        for item in getattr(plugin, "_dududa_runtime_cleanup_assemblies", ())
    ):
        raise RuntimeError("production Runtime assembly is not installable")
    try:
        bridge = install_rollout_runtime(
            plugin,
            assembly.runtime,
            runtime_budget,
            policy_snapshot_id,
            connector=connector,
            clock=clock,
            runtime_ready=assembly.ready,
        )
    except Exception:  # unavailable composition preserves the legacy owner
        try:
            assembly.abort()
        except Exception:
            logger.error("Dududa Runtime assembly abort failed")
        plugin.rollout_bridge = None
        plugin.runtime_assembly = None
        _retain_cleanup_assembly(plugin, assembly)
        logger.error("Dududa Runtime composition unavailable; legacy remains owner")
        return None
    assembly.mark_installed()
    plugin.runtime_assembly = assembly
    return bridge


def install_rollout_runtime(
    plugin: Any,
    runtime: AgentRuntime,
    runtime_budget: RuntimeBudget,
    policy_snapshot_id: str,
    *,
    connector: InputConnector[object] | None = None,
    clock: Any = None,
    runtime_ready: bool = True,
) -> AstrBotRolloutBridge:
    if getattr(plugin, "rollout_bridge", None) is not None:
        raise RuntimeError("rollout Runtime is already installed")
    ledger = getattr(plugin, "rollout_ledger", None)
    controls = getattr(plugin, "rollout_controls", None)
    metrics = getattr(plugin, "rollout_metrics", None)
    if not isinstance(ledger, SQLiteRolloutLedger):
        raise RuntimeError("rollout persistence is unavailable")
    if not isinstance(metrics, InMemoryRolloutMetrics):
        raise RuntimeError("rollout metrics are unavailable")
    config = controls.current()
    connector = connector or AstrBotInputConnector(
        InMemoryAttachmentRepository(clock=clock),
        clock=clock,
    )
    requests = AstrBotRuntimeRequestFactory(
        connector,
        runtime_budget,
        policy_snapshot_id,
        clock=clock,
    )
    shadow = BoundedShadowSupervisor(
        ShadowRunner(runtime, _NoopShadowSink(), clock=clock),
        config,
        metrics,
        clock=clock,
    )
    canary = CanaryCoordinator(
        runtime,
        controls,
        ledger,
        metrics,
        clock=clock,
    )
    bridge = AstrBotRolloutBridge(
        controls,
        requests,
        shadow,
        canary,
        InMemoryDeliveryLedger(),
        runtime_ready=runtime_ready,
    )
    plugin.rollout_bridge = bridge
    return bridge


class _NoopShadowSink:
    async def write(self, receipt: object, *, call: object) -> None:
        return None


def _default_runtime_budget() -> RuntimeBudget:
    return RuntimeBudget(
        model_calls_remaining=2,
        tool_steps_remaining=0,
        retries_remaining=1,
        input_tokens_remaining=32_000,
        output_tokens_remaining=8_000,
        cost_units_remaining=Decimal("0"),
    )


def _retain_cleanup_assembly(
    plugin: Any,
    assembly: ProductionRuntimeAssembly,
) -> None:
    pending = list(getattr(plugin, "_dududa_runtime_cleanup_assemblies", ()))
    if not any(item is assembly for item in pending):
        pending.append(assembly)
    plugin._dududa_runtime_cleanup_assemblies = pending


def _runtime_unavailable():
    return error(
        "production_runtime_unavailable",
        ErrorCategory.EXTERNAL,
        "runtime.unavailable",
        "missing_conformance_evidence",
    )
