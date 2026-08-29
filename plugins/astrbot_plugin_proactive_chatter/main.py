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

        self.window_seconds = float(self.config.get("window_seconds", 240))
        self.activity_threshold = int(self.config.get("activity_threshold", 15))
        self.trigger_probability = float(self.config.get("trigger_probability", 0.35))
        self.global_cooldown_seconds = float(self.config.get("global_cooldown_seconds", 360))
        self.group_cooldown_seconds = float(self.config.get("group_cooldown_seconds", 600))
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
        active_users = self.store.most_active_users(group, self.window_seconds, limit=6)
        context_text = self._build_context(recent)
        style_blurb = await self._style_blurb(group, active_users)

        content, at_target = await self._generate_speech(context_text, style_blurb, active_users)
        if not content:
            return
        chain = []
        if at_target:
            chain.append(At(qq=at_target))
            chain.append(Plain(" "))
        chain.append(Plain(content))
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

    async def _style_blurb(self, group: str, active_users: list[dict[str, Any]]) -> str:
        if not active_users:
            return ""
        # pick the most active user; refresh style stats occasionally
        top = active_users[0]
        uid = str(top["user_id"])
        cache_key = (group, uid)
        cached = self.last_style_compute.get(cache_key)
        if cached and time.time() - cached[1] < 600:
            return cached[0]
        target = self.style_history_target
        stats = self.store.style_stats(group, uid, sample_limit=target)
        if not stats or stats.get("sample_count", 0) < self.require_style_n:
            return ""
        style = stats.get("style") or {}
        blurb = (
            f"参考群里最活跃的群友「{stats.get('nick') or uid}」的说话风格：\n"
            f"- 平均句长：{style.get('length_hint')}\n"
            f"- 常用词：{'、'.join(style.get('top_words', [])[:8]) or '无明显'}\n"
            f"- 口头禅：{'、'.join(style.get('catchphrases', [])) or '无明显'}\n"
            f"- 是否常用表情：{'是' if style.get('uses_emoji') else '否'}\n"
            f"如果话题合适，你的发言可带一点这种风格，但仍保持嘟嘟哒的底色。"
        )
        self.last_style_compute[cache_key] = (blurb, time.time())
        return blurb

    async def _generate_speech(
        self,
        context_text: str,
        style_blurb: str,
        active_users: list[dict[str, Any]],
    ) -> tuple[str, str | None]:
        candidates = []
        if active_users:
            candidates = [str(u["user_id"]) for u in active_users]
        prompt = (
            "下面是某 QQ 群里最近的一小段聊天记录。\n"
            f"群消息：\n{context_text}\n"
            "请以嘟嘟哒的身份，自然地插入一句话参与当前讨论。要求：\n"
            "1. 贴合当前正在聊的话题，不要跑题、不要强行总结；\n"
            f"2. 风格：{self.legend}\n"
        )
        if style_blurb:
            prompt += f"3. {style_blurb}\n"
        prompt += (
            "4. 简短（1-2 句，<=60 字），不要刷屏，不要连续输出；\n"
            "5. 如果当前聊天不需要机器人插话（比如纯寒暄或私事），直接回复空串。\n"
            "只输出说话内容本身，不要任何解释、引号或前缀。"
        )
        at_target: str | None = None
        try:
            provider = self.context.get_using_provider()
            if not provider:
                return self._fallback(context_text, at_target)
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是嘟嘟哒，一个可爱、聪明的群聊助手，只在适合时短暂插话。",
                max_tokens=120,
                temperature=0.9,
            )
            content = (getattr(response, "completion_text", "") or "").strip().strip('"“”')
            if not content or len(content) < 2:
                return "", None
            # contextual @ decision
            if random.random() < 0.45 and candidates:
                at_target = random.choice(candidates)
            return content[:120], at_target
        except Exception as exc:  # noqa: BLE001
            logger.warning("Proactive chatter LLM failed: %s", exc)
            return self._fallback(context_text, at_target)

    def _fallback(self, context_text: str, at_target: str | None) -> tuple[str, str | None]:
        replies = [
            "诶，就这个话题我也想说两句~",
            "哈哈感觉你们聊得挺热闹的w",
            "对呀对呀，我也有同感！",
            "这个我最近也在想呢～",
        ]
        at_target = None
        return random.choice(replies), at_target
