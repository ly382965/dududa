from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .storage import ChatterStore

_NAME = "astrbot_plugin_proactive_chatter"


def _sender(event: AstrMessageEvent) -> str:
    try:
        return str(event.message_obj.sender.user_id)
    except Exception:
        return ""


def _group(event: AstrMessageEvent) -> str:
    try:
        return str(event.message_obj.group_id)
    except Exception:
        return ""


def _nick(event: AstrMessageEvent) -> str:
    try:
        sender = event.message_obj.sender
        return sender.card or sender.nickname or ""
    except Exception:
        return ""


def _text(event: AstrMessageEvent) -> str:
    try:
        return event.message_str or event.get_message_outline() or ""
    except Exception:
        return ""


@register(_NAME, "mmdustc", "择机闲聊：检测群热闹度，低频率主动发言", "0.1.0")
class ProactiveChatter(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))

        # data dir: /AstrBot/data/plugin_data/astrbot_plugin_proactive_chatter
        DATA_ROOT = Path(__file__).resolve().parents[2]
        data_dir = DATA_ROOT / "plugin_data" / _NAME
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ChatterStore(data_dir / "chatter.sqlite3")

        self.window_seconds = float(self.config.get("window_seconds", 900))
        self.activity_threshold = int(self.config.get("activity_threshold", 1))
        self.trigger_probability = float(self.config.get("trigger_probability", 0.3))
        self.global_cooldown_seconds = float(self.config.get("global_cooldown_seconds", 1800))
        self.group_cooldown_seconds = float(self.config.get("group_cooldown_seconds", 1800))
        self.style_history_target = int(self.config.get("style_history_target", 250))
        self.require_style_n = int(self.config.get("require_style_n", 200))

        self.group_exclude = self._str_set(self.config.get("group_whitelist", []))
        self.global_last_sent = 0.0
        self.group_last_sent: dict[str, float] = {}
        self.last_style_compute: dict[str, tuple[str, float]] = {}
        self.pending_style: dict[str, str] = {}

        self.legend = (
            "嘟嘟哒是一个可爱、聪明、认真又有点早熟的小小 USTC 预备役，喜欢数学和计算机，"
            "说话亲切、轻松、偶尔用小玩笑，不刷屏、不机械，像个活泼小妹妹。"
        )

        logger.info("ProactiveChatter loaded: enabled=%s", self.enabled)

    @staticmethod
    def _str_set(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value.strip()} if value.strip() else set()
        if isinstance(value, (list, tuple, set)):
            return {str(x).strip() for x in value if str(x).strip()}
        return set()

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AiocqhttpMessageEvent):
        if not self.enabled:
            return
        group = _group(event)
        sender = _sender(event)
        text = _text(event)

        # skip bot's own messages
        if not group or not sender or not text:
            return
        self.store.add(group, sender, _nick(event), text)

        if self.group_exclude and group not in self.group_exclude:
            return

        # check activity + cooldown
        if not self._should_speak(group):
            return
        asyncio.create_task(self._maybe_talk(event))

    def _should_speak(self, group: str) -> bool:
        now = time.time()
        if now - self.global_last_sent < self.global_cooldown_seconds:
            return False
        if now - self.group_last_sent.get(group, 0.0) < self.group_cooldown_seconds:
            return False
        active = self.store.recent_activity_count(group, self.window_seconds)
        if active < self.activity_threshold:
            return False
        return True

    async def _maybe_talk(self, event: AiocqhttpMessageEvent) -> None:
        group = _group(event)
        if random.random() > self.trigger_probability:
            return
        recent = self.store.recent_by_group(group, self.window_seconds, limit=60)
        if not recent:
            return
        context_text = self._build_context(recent)

        content = await self._generate_speech(context_text)
        if not content:
            return
        chain = [Plain(content)]
        try:
            await event.send(event.chain_result(chain))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Proactive chatter send failed: %s", exc)
            return
        now = time.time()
        self.global_last_sent = now
        self.group_last_sent[group] = now

    def _build_context(self, recent: list[dict[str, Any]]) -> str:
        lines = []
        for m in recent[:50][::-1]:
            nick = m.get("nick") or m.get("user_id") or "?"
            lines.append(f"{nick}: {m.get('text')}")
        return "\n".join(lines[-40:])

    async def _generate_speech(self, context_text: str) -> str | None:
        prompt = (
            "下面是某 QQ 群里最近的一小段聊天记录，你是群里一个叫嘟嘟哒的成员，想自然接一句话。\n"
            f"群消息：\n{context_text}\n"
            "请以嘟嘟哒的身份，自然、像真的人一样地接一句话参与当前讨论。要求：\n"
            "1. 严格贴合当前正在聊的话题（谁说的、在聊什么），不要跑题、不要面面俱到地总结；\n"
            f"2. 语气：{self.legend}\n"
            "3. 说得像随口插的一句话，有真实感（可以轻轻认同、补充一点、轻问一句、或幽默一下），"
            "像真人插话，不要官方、不要机械、不要报菜名式列举；\n"
            "4. 很短（1-2 句，<=60 字），只在你说得合时宜时接；\n"
            "5. 如果你觉得现在插话会唐突（比如大家在说私事、只是在玩梗刷屏、或你没什么好说的），就直接回复空串。\n"
            "只输出要说的那句话本身，不要解释、引号、@ 或前缀。"
        )
        try:
            provider = self.context.get_using_provider()
            if not provider:
                return self._fallback()
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是嘟嘟哒，一个可爱、聪明、认真又有点早熟的小小 USTC 预备役，喜欢数学和计算机，说话亲切轻松，只在适合时短暂插话，不 @ 别人、不模仿别人。",
                max_tokens=120,
                temperature=0.9,
            )
            content = (getattr(response, "completion_text", "") or "").strip().strip('"“”')
            if not content or len(content) < 2:
                return None
            return content[:120]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Proactive chatter LLM failed: %s", exc)
            return self._fallback()

    def _fallback(self) -> str | None:
        replies = [
            "诶，就这个话题我也想说两句~",
            "哈哈感觉你们聊得挺热闹的w",
            "对呀对呀，我也有同感！",
            "这个我最近也在想呢～",
        ]
        return random.choice(replies)
