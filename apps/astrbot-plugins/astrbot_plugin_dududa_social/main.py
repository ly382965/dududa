"""AstrBot adapter for the optional, explicit Dududa social commands.

This adapter intentionally registers command handlers only.  It does not
subscribe to ``ALL`` events, schedule work, invoke a model/MCP service, or
send a message unless a user explicitly invokes one of its commands.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .policy import (
    SocialFeature,
    SocialPolicyConfig,
    SocialPolicyError,
    SocialScope,
    classify_compliment,
    classify_mood,
    match_keyword,
)
from .storage import SocialStateStore

PLUGIN_ID = "astrbot_plugin_dududa_social"
PLUGIN_VERSION = "2.0.0"


@register(
    PLUGIN_ID,
    "mmdustc",
    "嘟嘟哒 2.0 可选社交策略与显式群互动命令",
    PLUGIN_VERSION,
)
class DududaSocialPlugin(Star):
    """Keep PR #10 social ideas behind a small, independently gated adapter."""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = dict(config or {})
        self.policy = _policy_from_config(self.config)
        self.state_path = _state_path(self.config)
        self._store: SocialStateStore | None = None
        logger.info(
            "%s loaded: enabled=%s groups=%d features=%d handlers=commands-only",
            PLUGIN_ID,
            self.policy.enabled,
            len(self.policy.allowed_groups),
            len(self.policy.enabled_features),
        )

    def _store_for_commands(self) -> SocialStateStore:
        if self._store is None:
            self._store = SocialStateStore(self.state_path)
        return self._store

    def _scope(self, event: AstrMessageEvent) -> SocialScope | None:
        platform = _event_id(event, "get_platform_id")
        bot_id = _event_id(event, "get_self_id")
        group_id = _event_id(event, "get_group_id")
        sender_id = _event_id(event, "get_sender_id")
        if not platform or not bot_id or not sender_id:
            return None
        if group_id:
            return SocialScope(platform, bot_id, group_id, group_id)
        return SocialScope(platform, bot_id, f"private:{sender_id}", None)

    def _allowed(
        self,
        event: AstrMessageEvent,
        feature: SocialFeature,
    ) -> SocialScope | None:
        scope = self._scope(event)
        if scope is None or not self.policy.allows(scope, feature):
            return None
        return scope

    @filter.command_group("dududa-social", alias={"dududa_social", "社交"})
    def dududa_social(self):
        """Dududa social commands; no implicit message listener is installed."""

    @dududa_social.command("help", alias={"帮助"})
    async def social_help(self, event: AstrMessageEvent):
        """Show the explicitly enabled social command surface."""
        yield event.plain_result(
            "嘟嘟哒社交扩展（默认关闭）\n"
            "/dududa-social birthday set MMDD|list|delete\n"
            "/dududa-social sleep record|rank\n"
            "/dududa-social vote start <主题>|join|status|end\n"
            "/dududa-social cp rank\n"
            "情绪、夸奖和关键词只提供给 Runtime 的纯策略，不会自动回复。"
        )
        event.stop_event()

    @dududa_social.command("birthday", alias={"生日"})
    async def birthday(
        self,
        event: AstrMessageEvent,
        action: str = "list",
        date_value: str | None = None,
    ):
        """Set/list/delete a recurring birthday in the current group scope."""
        scope = self._allowed(event, SocialFeature.BIRTHDAY)
        if scope is None:
            yield event.plain_result(_disabled_message())
            event.stop_event()
            return
        sender = _event_id(event, "get_sender_id")
        normalized = str(action or "list").strip().casefold()
        store = self._store_for_commands()
        try:
            if normalized in {"set", "设置"}:
                if date_value is None:
                    raise SocialPolicyError("birthday_required")
                canonical = store.set_birthday(scope, sender, date_value)
                reply = f"已记录你的生日：{canonical[:2]}月{canonical[3:]}日。"
            elif normalized in {"delete", "del", "删除"}:
                reply = "已删除你的生日记录。" if store.delete_birthday(scope, sender) else "你还没有生日记录。"
            elif normalized in {"list", "查看", ""}:
                records = store.list_birthdays(scope)
                if not records:
                    reply = "本群还没有生日记录。"
                else:
                    lines = ["本群生日记录："]
                    lines.extend(
                        f"- {_display_id(user_id)}：{value[:2]}月{value[3:]}日"
                        for user_id, value in records.items()
                    )
                    reply = "\n".join(lines)
            else:
                raise SocialPolicyError("unknown_birthday_action")
        except SocialPolicyError as exc:
            reply = _policy_error_message(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @dududa_social.command("sleep", alias={"睡眠"})
    async def sleep(
        self,
        event: AstrMessageEvent,
        action: str = "rank",
    ):
        """Explicitly record a sleep marker or inspect the scoped ranking."""
        scope = self._allowed(event, SocialFeature.SLEEP)
        if scope is None:
            yield event.plain_result(_disabled_message())
            event.stop_event()
            return
        sender = _event_id(event, "get_sender_id")
        normalized = str(action or "rank").strip().casefold()
        store = self._store_for_commands()
        if normalized in {"record", "记录"}:
            now = datetime.now(timezone.utc).astimezone()
            from .policy import make_sleep_log

            try:
                recorded = store.append_sleep(scope, make_sleep_log(sender, now))
            except SocialPolicyError as exc:
                reply = _policy_error_message(exc)
            else:
                reply = "已记录今晚的睡觉时间。" if recorded else "今天已经记录过了。"
        elif normalized in {"rank", "list", "排行", "查看", ""}:
            summaries = store.sleep_summaries(scope)
            if not summaries:
                reply = "本群还没有睡眠记录。"
            else:
                lines = ["睡眠记录（仅当前群可见）："]
                for index, summary in enumerate(summaries[:10], 1):
                    average = summary.average_time.strftime("%H:%M")
                    lines.append(
                        f"{index}. {_display_id(summary.user_id)}：{summary.count}天，平均 {average}"
                    )
                reply = "\n".join(lines)
        else:
            reply = "用法：/dududa-social sleep record|rank"
        yield event.plain_result(reply)
        event.stop_event()

    @dududa_social.command("vote", alias={"投票"})
    async def vote(
        self,
        event: AstrMessageEvent,
        action: str = "status",
        topic: GreedyStr | None = None,
    ):
        """Run a creator/admin-authorised vote state transition."""
        scope = self._allowed(event, SocialFeature.VOTE)
        if scope is None:
            yield event.plain_result(_disabled_message())
            event.stop_event()
            return
        sender = _event_id(event, "get_sender_id")
        try:
            transition = self._store_for_commands().apply_vote(
                scope,
                action,
                sender,
                topic=str(topic).strip() if topic is not None else None,
                is_admin=_is_admin(event),
            )
            state = transition.state
            if transition.action == "start" and state is not None:
                reply = f"投票已开始：{state.topic}（发起人 {_display_id(state.creator_id)}）"
            elif transition.action == "join" and state is not None:
                reply = f"已加入「{state.topic}」，当前 {len(state.participants)} 人参与。"
            elif transition.action == "end":
                reply = "投票已结束。"
            elif state is None:
                reply = "当前没有进行中的投票。"
            else:
                reply = (
                    f"当前投票：{state.topic}\n"
                    f"参与人数：{len(state.participants)}\n"
                    "结束权限仅限发起人或管理员。"
                )
        except SocialPolicyError as exc:
            reply = _policy_error_message(exc)
        yield event.plain_result(reply)
        event.stop_event()

    @dududa_social.command("cp", alias={"互动"})
    async def cp(self, event: AstrMessageEvent, action: str = "rank"):
        """Show a redacted interaction ranking; no passive detector is installed."""
        scope = self._allowed(event, SocialFeature.CP)
        if scope is None:
            yield event.plain_result(_disabled_message())
            event.stop_event()
            return
        if str(action or "rank").strip().casefold() not in {"rank", "list", "排行", "查看", ""}:
            yield event.plain_result("用法：/dududa-social cp rank")
            event.stop_event()
            return
        rows = self._store_for_commands().rank_interactions(scope)
        if not rows:
            reply = "本群还没有互动记录。"
        else:
            lines = ["互动排行榜（账号已脱敏）："]
            lines.extend(
                f"{index}. {_display_id(pair.first)} × {_display_id(pair.second)}：{count}次"
                for index, (pair, count) in enumerate(rows, 1)
            )
            reply = "\n".join(lines)
        yield event.plain_result(reply)
        event.stop_event()

    # These methods are intentionally ordinary helpers, not message handlers.
    @staticmethod
    def classify_mood(text: object):
        return classify_mood(text)

    @staticmethod
    def classify_compliment(text: object, *, bot_mentioned: bool = False):
        return classify_compliment(text, bot_mentioned=bot_mentioned)

    @staticmethod
    def match_keyword(text: object):
        return match_keyword(text)

    async def terminate(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None


def _policy_from_config(config: dict[str, Any]) -> SocialPolicyConfig:
    features = config.get("features", {})
    if not isinstance(features, dict):
        features = {}
    enabled_features = {
        feature
        for feature in SocialFeature
        if features.get(feature.value) is True
    }
    return SocialPolicyConfig(
        enabled=config.get("enabled") is True,
        allowed_groups=frozenset(_string_values(config.get("group_allowlist", []))),
        allow_private=config.get("allow_private") is True,
        enabled_features=frozenset(enabled_features),
    )


def _state_path(config: dict[str, Any]) -> Path:
    configured = config.get("state_path")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser()
    environment = os.environ.get("DUDUDA_SOCIAL_STATE_PATH", "").strip()
    if environment:
        return Path(environment).expanduser()
    data_root = Path(__file__).resolve().parents[2]
    return data_root / "plugin_data" / PLUGIN_ID / "social.sqlite3"


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _event_id(event: object, method_name: str) -> str:
    try:
        value = getattr(event, method_name)()
    except Exception:  # noqa: BLE001 - framework accessor failures make command ineligible
        return ""
    return str(value or "").strip()


def _is_admin(event: object) -> bool:
    try:
        return bool(event.is_admin())
    except Exception:  # noqa: BLE001 - missing/failed framework role lookup denies access
        return False


def _display_id(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= 4:
        return "用户" + normalized
    return "用户***" + normalized[-4:]


def _disabled_message() -> str:
    return "社交扩展未启用，或当前会话未加入群白名单。"


def _policy_error_message(error: SocialPolicyError) -> str:
    messages = {
        "birthday_required": "请提供生日，例如 /dududa-social birthday set 0315。",
        "invalid_birthday": "生日格式无效，请使用 MMDD，例如 0315。",
        "unknown_birthday_action": "用法：birthday set MMDD|list|delete。",
        "vote_topic_required": "请提供投票主题。",
        "vote_already_active": "当前已有进行中的投票。",
        "vote_not_active": "当前没有进行中的投票。",
        "vote_end_forbidden": "只有投票发起人或管理员可以结束投票。",
        "unknown_vote_action": "用法：vote start <主题>|join|status|end。",
    }
    return messages.get(error.code, "社交命令参数或状态无效。")


__all__ = ["PLUGIN_ID", "PLUGIN_VERSION", "DududaSocialPlugin"]
