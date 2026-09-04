"""Read existing Web Scope Policy for standalone QQ plugin entry points."""

from __future__ import annotations

import json
import os
from pathlib import Path


def group_plugin_enabled(plugin_id: str, *, bot_id: str, group_id: str) -> bool:
    """No configured store preserves standalone behavior; managed scopes fail closed."""
    path = os.environ.get("DUDUDA_AGENT_POLICY_PATH", "").strip()
    if not path:
        return True
    if not bot_id or not group_id:
        return False
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return False
    policies = payload.get("policies") if isinstance(payload, dict) else None
    if not isinstance(policies, dict):
        return False
    account = f"qq-{bot_id}"
    conversation = f"{account}:group:{group_id}"
    for record in policies.values():
        if not isinstance(record, dict):
            continue
        scope = record.get("scope")
        if (
            not isinstance(scope, dict)
            or scope.get("accountId") != account
            or scope.get("conversationId") != conversation
        ):
            continue
        plugins = record.get("plugins")
        mode = plugins.get(plugin_id) if isinstance(plugins, dict) else None
        return (
            record.get("enabled") is True
            and isinstance(plugins, dict)
            and isinstance(mode, str)
            and mode in {"auto", "on", "locked"}
        )
    return False
