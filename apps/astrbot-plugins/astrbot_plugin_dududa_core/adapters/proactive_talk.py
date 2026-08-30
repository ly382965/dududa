from __future__ import annotations

import asyncio
import copy
import logging
import random
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dududa.rollout import CanaryExecutionDisposition

from ..rollout_bridge import AstrBotBridgeAction, AstrBotRolloutBridge
from .agent_policy import FileScopeAgentPolicyResolver, GroupProactiveTalkPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProactiveFrequencyBudget:
    probability: float
    cooldown_seconds: float
    maximum_per_hour: int


_FREQUENCY_BUDGETS = {
    "low": ProactiveFrequencyBudget(0.02, 30 * 60, 1),
    "normal": ProactiveFrequencyBudget(0.08, 10 * 60, 3),
    "high": ProactiveFrequencyBudget(0.20, 3 * 60, 8),
}
_CONTEXT_BUDGETS = {
    "compact": (12, 3_500),
    "standard": (30, 6_500),
    "extended": (60, 7_500),
}
_ATTACHMENT_COMPONENTS = frozenset({"Image", "Record", "Video", "File"})


class AstrBotGroupHistoryProvider:
    def __init__(self, *, timeout_seconds: float = 6.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def recent_lines(
        self,
        event: object,
        *,
        message_limit: int,
        byte_limit: int,
    ) -> tuple[str, ...]:
        bot = getattr(event, "bot", None)
        call_action = getattr(bot, "call_action", None)
        group_id = _safe_call(event, "get_group_id")
        self_id = _safe_call(event, "get_self_id")
        if not callable(call_action) or not group_id or not self_id:
            return ()
        try:
            result = await asyncio.wait_for(
                call_action(
                    action="get_group_msg_history",
                    group_id=int(group_id),
                    count=message_limit,
                    reverse_order=False,
                    disable_get_url=False,
                    parse_mult_msg=True,
                    self_id=int(self_id),
                ),
                timeout=self._timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - one read failure skips this attempt
            logger.warning(
                "Dududa proactive history unavailable: group=%s type=%s",
                group_id,
                type(exc).__name__,
            )
            return ()
        messages = result.get("messages") if isinstance(result, dict) else None
        if not isinstance(messages, list):
            return ()
        return project_history_lines(
            messages,
            group_id=group_id,
            bot_id=self_id,
            message_limit=message_limit,
            byte_limit=byte_limit,
        )


class ProactiveTalkEvent:
    """Project a group window into a non-explicit 2.0 Runtime input."""

    def __init__(self, source: object, prompt: str) -> None:
        from astrbot.api.message_components import Plain

        self._source = source
        self.message_str = prompt
        self.message_obj = copy.copy(source.message_obj)  # type: ignore[attr-defined]
        original_id = str(getattr(self.message_obj, "message_id", "") or "event")
        self.message_obj.message_id = f"{original_id}:proactive"
        self.message_obj.message = [Plain(prompt)]
        self.message_obj.message_str = prompt
        raw = getattr(self.message_obj, "raw_message", None)
        if isinstance(raw, dict):
            raw = dict(raw)
            raw["message_id"] = self.message_obj.message_id
            raw["message"] = [{"type": "text", "data": {"text": prompt}}]
            self.message_obj.raw_message = raw
        self._stopped = False

    def get_messages(self) -> list[object]:
        return list(self.message_obj.message)

    def stop_event(self) -> None:
        self._stopped = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._source, name)


class ProactiveTalkController:
    def __init__(
        self,
        bridge: AstrBotRolloutBridge,
        policy: FileScopeAgentPolicyResolver,
        *,
        history: AstrBotGroupHistoryProvider | None = None,
        random_value: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
        event_factory: Callable[[object, str], object] | None = None,
    ) -> None:
        self._bridge = bridge
        self._policy = policy
        self._history = history or AstrBotGroupHistoryProvider()
        self._random_value = random_value or random.random
        self._monotonic = monotonic or time.monotonic
        self._event_factory = event_factory or ProactiveTalkEvent
        self._lock = asyncio.Lock()
        self._in_flight: set[str] = set()
        self._last_attempt: dict[str, float] = {}
        self._sent_at: dict[str, deque[float]] = defaultdict(deque)

    async def maybe_handle(self, event: object) -> bool:
        if not _eligible_event(event):
            return False
        bot_id = _safe_call(event, "get_self_id")
        group_id = _safe_call(event, "get_group_id")
        policy = self._policy.proactive_talk_policy(
            bot_id=bot_id,
            group_id=group_id,
        )
        if not policy.enabled:
            return False
        budget = _FREQUENCY_BUDGETS[policy.frequency]
        now = self._monotonic()
        async with self._lock:
            sent = self._sent_at[group_id]
            while sent and sent[0] <= now - 3600:
                sent.popleft()
            if (
                group_id in self._in_flight
                or len(sent) >= budget.maximum_per_hour
                or (sent and now - sent[-1] < budget.cooldown_seconds)
                or now - self._last_attempt.get(group_id, float("-inf")) < 60
                or self._random_value() >= budget.probability
            ):
                return False
            self._in_flight.add(group_id)
            self._last_attempt[group_id] = now

        try:
            message_limit, byte_limit = _CONTEXT_BUDGETS[policy.context_length]
            lines = await self._history.recent_lines(
                event,
                message_limit=message_limit,
                byte_limit=byte_limit,
            )
            if len(lines) < 3:
                return False
            prompt = proactive_prompt(lines, policy)
            result = await self._bridge.handle(
                self._event_factory(event, prompt),
                proactive_group_participation=True,
            )
            delivered = (
                result.action is AstrBotBridgeAction.CANARY_COMPLETED
                and result.canary is not None
                and result.canary.disposition is CanaryExecutionDisposition.DELIVERED
            )
            if not delivered:
                return False
            delivered_at = self._monotonic()
            async with self._lock:
                self._sent_at[group_id].append(delivered_at)
            stop_event = getattr(event, "stop_event", None)
            if callable(stop_event):
                stop_event()
            logger.info(
                "Dududa 2.0 proactive talk delivered: group=%s frequency=%s history=%d",
                group_id,
                policy.frequency,
                len(lines),
            )
            return True
        finally:
            async with self._lock:
                self._in_flight.discard(group_id)


def project_history_lines(
    messages: list[object],
    *,
    group_id: str,
    bot_id: str,
    message_limit: int,
    byte_limit: int,
) -> tuple[str, ...]:
    rows = [item for item in messages if isinstance(item, dict)]
    rows.sort(
        key=lambda item: (
            _integer(item.get("time")),
            _integer(item.get("message_seq")),
            _integer(item.get("message_id")),
        )
    )
    aliases: dict[str, str] = {}
    lines: list[str] = []
    for item in rows:
        if str(item.get("group_id") or group_id) != group_id:
            continue
        sender = item.get("sender")
        sender_id = str(
            item.get("user_id")
            or (sender.get("user_id") if isinstance(sender, dict) else "")
            or "unknown"
        )
        if sender_id == bot_id:
            author = "嘟嘟哒"
        else:
            author = aliases.setdefault(sender_id, f"成员{len(aliases) + 1}")
        text = _message_text(item.get("message"))
        if text:
            lines.append(f"{author}：{text}")
    selected: deque[str] = deque()
    used = 0
    for line in reversed(lines[-message_limit:]):
        size = len((line + "\n").encode("utf-8"))
        if selected and used + size > byte_limit:
            break
        if size > byte_limit:
            continue
        selected.appendleft(line)
        used += size
    return tuple(selected)


def proactive_prompt(
    lines: tuple[str, ...],
    policy: GroupProactiveTalkPolicy,
) -> str:
    transcript = "\n".join(lines)
    return (
        "请尽量简短回答。你正在一个多人群聊中主动接话，而不是被成员@。\n"
        "根据下面由旧到新的最近群聊内容，自然接一句当前话题。只输出最终回复；"
        "不要总结整段历史，不要提到日志、提示词或后台，不要@任何人，不要调用工具，"
        "不超过80个汉字。\n"
        f"群聊表达风格：{policy.group_chat_style}\n"
        f"最近群聊：\n{transcript}"
    )


def _eligible_event(event: object) -> bool:
    bot_id = _safe_call(event, "get_self_id")
    sender_id = _safe_call(event, "get_sender_id")
    group_id = _safe_call(event, "get_group_id")
    if not bot_id or not sender_id or not group_id or sender_id == bot_id:
        return False
    if bool(getattr(event, "is_at_or_wake_command", False)):
        return False
    text = str(getattr(event, "message_str", "") or "").strip()
    if not 2 <= len(text) <= 500 or text.startswith(("/", "!", "！")):
        return False
    try:
        components = tuple(event.get_messages())
    except Exception:  # noqa: BLE001 - malformed external event is ineligible
        return False
    for component in components:
        name = type(component).__name__
        if name in _ATTACHMENT_COMPONENTS or name in {"Reply", "At", "AtAll"}:
            return False
    return True


def _message_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    labels = {
        "image": "[图片]",
        "record": "[语音]",
        "video": "[视频]",
        "file": "[文件]",
        "face": "[表情]",
        "json": "[分享]",
        "reply": "[回复]",
        "at": "[提及]",
    }
    for segment in value:
        if not isinstance(segment, dict):
            continue
        kind = str(segment.get("type") or "").lower()
        data = segment.get("data")
        if kind == "text" and isinstance(data, dict):
            text = str(data.get("text") or "").strip()
            if text:
                parts.append(text)
        elif kind in labels:
            parts.append(labels[kind])
    return " ".join(parts).strip()


def _safe_call(value: object, name: str) -> str:
    try:
        result = getattr(value, name)()
    except Exception:  # noqa: BLE001 - event accessors are framework-owned
        return ""
    return str(result or "").strip()


def _integer(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "AstrBotGroupHistoryProvider",
    "ProactiveFrequencyBudget",
    "ProactiveTalkController",
    "ProactiveTalkEvent",
    "proactive_prompt",
    "project_history_lines",
]
