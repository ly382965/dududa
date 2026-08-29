from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dududa.runtime.context import CAPABILITY_CATEGORY_FEATURE_PREFIX
from dududa.runtime.state import ConnectorResult

SCOPE_AGENT_ENABLED_FLAG = "scope_agent_enabled"
_ENABLED_PLUGIN_MODES = frozenset({"auto", "on", "locked"})
_PLUGIN_CAPABILITY_CATEGORIES: Mapping[str, str] = {
    "icourse.read": "campus.course-review",
    "ustc.young.read": "campus.second-class",
    "ustc.academic.read": "campus.academic",
    "ustc.curriculum.read": "campus.curriculum",
    "ustc.shuttle.read": "campus.shuttle",
}


class FileScopeAgentPolicyResolver:
    """Project one exact Web Control Plane Scope into Runtime feature flags."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not str(path).strip():
            raise ValueError("invalid Agent policy path")
        self._path = path

    def feature_flags(self, connector: ConnectorResult) -> Mapping[str, bool]:
        if not isinstance(connector, ConnectorResult):
            raise TypeError("invalid Connector result")
        disabled = self._capability_flags({})
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {SCOPE_AGENT_ENABLED_FLAG: False, **disabled}

        record = _scope_record(payload, connector)
        if record is None:
            # Preserve the existing global inbound rollout for unmanaged Scopes,
            # while keeping every Web-managed Capability off by default.
            return {SCOPE_AGENT_ENABLED_FLAG: True, **disabled}
        enabled = record.get("enabled") is True
        plugins = record.get("plugins") if enabled else {}
        if not isinstance(plugins, dict):
            plugins = {}
        return {
            SCOPE_AGENT_ENABLED_FLAG: enabled,
            **self._capability_flags(plugins),
        }

    @staticmethod
    def _capability_flags(plugins: Mapping[str, Any]) -> dict[str, bool]:
        return {
            f"{CAPABILITY_CATEGORY_FEATURE_PREFIX}{category}": (
                str(plugins.get(plugin_id) or "off").strip().lower()
                in _ENABLED_PLUGIN_MODES
            )
            for plugin_id, category in _PLUGIN_CAPABILITY_CATEGORIES.items()
        }


def _scope_record(payload: object, connector: ConnectorResult) -> dict[str, Any] | None:
    policies = payload.get("policies") if isinstance(payload, dict) else None
    if not isinstance(policies, dict):
        return None
    message = connector.message
    account_id = f"qq-{message.bot_id}"
    if message.group_id:
        conversation_id = f"{account_id}:group:{message.group_id}"
    else:
        conversation_id = f"{account_id}:private:{message.user_id}"
    for value in policies.values():
        if not isinstance(value, dict):
            continue
        scope = value.get("scope")
        if not isinstance(scope, dict):
            continue
        if (
            str(scope.get("accountId") or "").strip() == account_id
            and str(scope.get("conversationId") or "").strip() == conversation_id
        ):
            return value
    return None


__all__ = ["FileScopeAgentPolicyResolver", "SCOPE_AGENT_ENABLED_FLAG"]
