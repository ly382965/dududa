from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

ECHO_FLOOD = "echo_flood"
BOT_INTERACTION = "bot_interaction"

_ECHO_WORDS = frozenset(
    {
        "+1",
        "＋1",
        "1",
        "接龙",
        "同上",
        "同",
        "赞",
        "收到",
        "哦",
        "嗯",
        "好",
        "对",
        "是的",
    }
)
_BOT_INTERACTION_SIGNALS = (
    "打卡",
    "签到",
    "运势",
    "抽签",
    "塔罗",
    "占卜",
    "骰子",
    "猜拳",
    "点歌",
    "答题",
    "解签",
    "许愿",
    "/help",
    "/菜单",
    "/功能",
)


def proactive_context_skip_reason(lines: Iterable[str]) -> str | None:
    """Return why 2.0 should stay silent for the projected group context."""

    messages = tuple(
        text
        for line in lines
        if (text := _message_body(str(line))).strip()
    )
    if _is_echo_or_chain(messages[-10:]):
        return ECHO_FLOOD
    if _is_bot_interaction(messages[-8:]):
        return BOT_INTERACTION
    return None


def _message_body(line: str) -> str:
    _, separator, body = line.partition("：")
    return body if separator else line


def _is_echo_or_chain(messages: tuple[str, ...]) -> bool:
    if len(messages) < 3:
        return False
    normalized = tuple(re.sub(r"\s+", "", text) for text in messages)
    most_common = Counter(normalized).most_common(1)[0][1]
    if most_common / len(normalized) >= 0.6:
        return True
    echo_count = sum(text in _ECHO_WORDS for text in normalized)
    return echo_count / len(normalized) >= 0.6


def _is_bot_interaction(messages: tuple[str, ...]) -> bool:
    if not messages:
        return False
    interaction_count = sum(
        any(signal in text for signal in _BOT_INTERACTION_SIGNALS)
        for text in messages
    )
    return interaction_count / len(messages) >= 0.5


__all__ = [
    "BOT_INTERACTION",
    "ECHO_FLOOD",
    "proactive_context_skip_reason",
]
