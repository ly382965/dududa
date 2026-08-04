from __future__ import annotations

from datetime import timedelta
from typing import Any

from astrbot.api import logger

from dududa.adapters import InMemoryAttachmentRepository
from dududa.domain.primitives import ComponentRevision, DigestString, RuntimeBudget
from dududa.ports.runtime import AgentRuntime, InputConnector
from dududa.rollout import (
    BoundedShadowSupervisor,
    CanaryCoordinator,
    InMemoryRolloutMetrics,
    SQLiteRolloutLedger,
    SQLiteRolloutLedgerConfig,
)
from dududa.runtime.shadow import ShadowRunner

from .audit import AuditLog
from .adapters.message import AstrBotInputConnector
from .adapters.output import InMemoryDeliveryLedger
from .config import (
    PLUGIN_DATA_DIR,
    ROLLOUT_LEDGER_PATH,
    AstrBotRolloutControlProvider,
    ensure_dirs,
    load_json,
)
from .course import ICourseClient
from .permissions import PermissionManager
from .rollout_bridge import AstrBotRolloutBridge, AstrBotRuntimeRequestFactory


def initialize_plugin(plugin: Any, config: dict | None = None) -> None:
    plugin.config = config or {}
    plugin.enabled = bool(plugin.config.get("enabled", True))
    ensure_dirs()
    plugin.perms = PermissionManager(plugin.config)
    plugin.audit = AuditLog()
    plugin.icourse = ICourseClient()
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
    logger.info("DududaCore loaded: enabled=%s", plugin.enabled)


def install_rollout_runtime(
    plugin: Any,
    runtime: AgentRuntime,
    runtime_budget: RuntimeBudget,
    policy_snapshot_id: str,
    *,
    connector: InputConnector[object] | None = None,
    clock: Any = None,
) -> AstrBotRolloutBridge:
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
    )
    plugin.rollout_bridge = bridge
    return bridge


class _NoopShadowSink:
    async def write(self, receipt: object, *, call: object) -> None:
        return None
