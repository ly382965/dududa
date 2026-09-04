from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENABLED_MODES = frozenset({"auto", "on", "locked"})


@dataclass(frozen=True)
class PluginPolicyDecision:
    managed: bool
    mode: str

    @property
    def enabled(self) -> bool:
        return self.mode in ENABLED_MODES


def resolve_plugin_policy(
    *,
    policy_path: str,
    account_id: Any,
    conversation_id: Any,
    plugin_id: str,
    fallback_enabled: bool,
) -> PluginPolicyDecision:
    """Resolve one Web Control Plane plugin mode for an exact Runtime Scope."""
    path_value = str(policy_path or "").strip()
    if not path_value:
        return PluginPolicyDecision(
            managed=False,
            mode="on" if fallback_enabled else "off",
        )

    try:
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return PluginPolicyDecision(managed=True, mode="off")

    account = str(account_id or "").strip()
    conversation = str(conversation_id or "").strip()
    policies = payload.get("policies") if isinstance(payload, dict) else None
    if not account or not conversation or not isinstance(policies, dict):
        return PluginPolicyDecision(managed=True, mode="off")

    for record in policies.values():
        if not isinstance(record, dict):
            continue
        scope = record.get("scope")
        plugins = record.get("plugins")
        if not isinstance(scope, dict) or not isinstance(plugins, dict):
            continue
        if (
            str(scope.get("accountId") or "").strip() != account
            or str(scope.get("conversationId") or "").strip() != conversation
        ):
            continue
        if record.get("enabled") is not True:
            return PluginPolicyDecision(managed=True, mode="off")
        mode = str(plugins.get(plugin_id) or "off").strip().lower()
        if mode not in ENABLED_MODES and mode != "off":
            mode = "off"
        return PluginPolicyDecision(managed=True, mode=mode)

    return PluginPolicyDecision(managed=True, mode="off")
