from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dududa.runtime.context import CAPABILITY_CATEGORY_FEATURE_PREFIX
from dududa.runtime.state import ConnectorResult

SCOPE_AGENT_ENABLED_FLAG = "scope_agent_enabled"
PROACTIVE_TALK_PLUGIN_ID = "social.proactive_talk"
_ENABLED_PLUGIN_MODES = frozenset({"auto", "on", "locked"})
_ANSWER_PROFILES = frozenset({"short", "medium", "long"})
_CONTEXT_LENGTHS = frozenset({"compact", "standard", "extended"})
_GROUP_CHAT_STYLES = frozenset({"restrained", "natural", "lively", "technical"})
_PLUGIN_CAPABILITY_CATEGORIES: Mapping[str, str] = {
    "icourse.read": "campus.course-review",
    "notifai.read": "campus.notifications",
    "ustc.young.read": "campus.second-class",
    "ustc.academic.read": "campus.academic",
    "ustc.curriculum.read": "campus.curriculum",
    "ustc.shuttle.read": "campus.shuttle",
}


@dataclass(frozen=True, slots=True)
class GroupProactiveTalkPolicy:
    enabled: bool
    probability_percent: int
    cooldown_seconds: int
    maximum_per_hour: int
    context_length: str
    group_chat_style: str


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
        flags = {
            SCOPE_AGENT_ENABLED_FLAG: enabled,
            **self._capability_flags(plugins),
        }
        locked_profile = _locked_answer_profile(record) if enabled else None
        for profile in _ANSWER_PROFILES:
            flags[f"response_profile.force_{profile}"] = locked_profile == profile
        return flags

    def proactive_talk_policy(
        self,
        *,
        bot_id: str,
        group_id: str,
    ) -> GroupProactiveTalkPolicy:
        disabled = GroupProactiveTalkPolicy(
            False,
            probability_percent=2,
            cooldown_seconds=1_800,
            maximum_per_hour=1,
            context_length="compact",
            group_chat_style="natural",
        )
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return disabled
        record = _scope_record_for_ids(payload, bot_id=bot_id, group_id=group_id)
        if record is None or record.get("enabled") is not True:
            return disabled
        plugins = record.get("plugins")
        if not isinstance(plugins, dict):
            return disabled
        mode = str(plugins.get(PROACTIVE_TALK_PLUGIN_ID) or "off").strip().lower()
        if mode not in _ENABLED_PLUGIN_MODES:
            return disabled
        proactive = record.get("proactiveTalk")
        if not isinstance(proactive, dict):
            proactive = {}
        legacy_defaults = _legacy_proactive_defaults(proactive.get("frequency"))
        probability_percent = _bounded_integer(
            proactive.get("probabilityPercent"),
            default=legacy_defaults[0],
            minimum=0,
            maximum=100,
        )
        cooldown_seconds = _bounded_integer(
            proactive.get("cooldownSeconds"),
            default=legacy_defaults[1],
            minimum=5,
            maximum=1_800,
        )
        maximum_per_hour = _bounded_integer(
            proactive.get("maximumPerHour"),
            default=legacy_defaults[2],
            minimum=1,
            maximum=500,
        )
        context_length = _adaptive_preferred(
            record.get("contextLength"),
            _CONTEXT_LENGTHS,
            "compact",
        )
        group_chat_style = _adaptive_preferred(
            record.get("groupChatStyle"),
            _GROUP_CHAT_STYLES,
            "natural",
        )
        return GroupProactiveTalkPolicy(
            True,
            probability_percent,
            cooldown_seconds,
            maximum_per_hour,
            context_length,
            group_chat_style,
        )

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
    message = connector.message
    return _scope_record_for_ids(
        payload,
        bot_id=message.bot_id,
        group_id=message.group_id,
        user_id=message.user_id,
    )


def _scope_record_for_ids(
    payload: object,
    *,
    bot_id: str,
    group_id: str | None,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    policies = payload.get("policies") if isinstance(payload, dict) else None
    if not isinstance(policies, dict):
        return None
    account_id = f"qq-{bot_id}"
    if group_id:
        conversation_id = f"{account_id}:group:{group_id}"
    else:
        conversation_id = f"{account_id}:private:{user_id or ''}"
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


def _locked_answer_profile(record: Mapping[str, Any]) -> str | None:
    value = record.get("answerProfile")
    if not isinstance(value, dict) or str(value.get("mode") or "") != "locked":
        return None
    preferred = str(value.get("preferred") or "").strip().lower()
    return preferred if preferred in _ANSWER_PROFILES else None


def _adaptive_preferred(
    value: object,
    choices: frozenset[str],
    default: str,
) -> str:
    if not isinstance(value, dict):
        return default
    return _choice(value.get("preferred"), choices, default)


def _choice(value: object, choices: frozenset[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in choices else default


def _legacy_proactive_defaults(value: object) -> tuple[int, int, int]:
    return {
        "low": (2, 1_800, 1),
        "normal": (8, 600, 3),
        "high": (20, 180, 8),
    }.get(str(value or "").strip().lower(), (2, 1_800, 1))


def _bounded_integer(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if minimum <= value <= maximum else default


__all__ = [
    "PROACTIVE_TALK_PLUGIN_ID",
    "SCOPE_AGENT_ENABLED_FLAG",
    "FileScopeAgentPolicyResolver",
    "GroupProactiveTalkPolicy",
]
