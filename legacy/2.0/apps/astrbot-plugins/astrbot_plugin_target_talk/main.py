from __future__ import annotations

import random
import re
import time
from collections import defaultdict, deque
from typing import Any

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from dududa.compatibility.target_talk import (
    TargetUser,
    clamp_float,
    clean_reply,
    coerce_bool,
    coerce_int,
    coerce_string_list,
    float_or_none,
    history_entry,
    in_cooldown,
    load_targets,
    matches_any,
    should_handle_message,
    target_enabled_for_group,
)


@register(
    "astrbot_plugin_target_talk",
    "mmdustc",
    "监听指定 QQ 号发言，按概率 @ 对方并生成回复",
    "0.1.0",
)
class TargetTalkPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}

        self.enabled = self._bool(self.config.get("enabled", False), False)
        self.group_whitelist = self._str_set(self.config.get("group_whitelist", []))
        self.probability = self._clamp_float(
            self.config.get("probability", 0.35), 0.35, 0.0, 1.0
        )
        self.cooldown_seconds = self._int(self.config.get("cooldown_seconds", 90), 90)
        self.global_cooldown_seconds = self._int(
            self.config.get("global_cooldown_seconds", 15), 15
        )
        self.ignore_at_or_wake_command = self._bool(
            self.config.get("ignore_at_or_wake_command", True), True
        )
        self.trigger_keywords = self._str_list(self.config.get("trigger_keywords", []))
        self.exclude_keywords = self._str_list(self.config.get("exclude_keywords", []))
        self.min_message_chars = max(
            0, self._int(self.config.get("min_message_chars", 1), 1)
        )
        self.max_message_chars = max(
            0, self._int(self.config.get("max_message_chars", 500), 500)
        )
        self.recent_context_messages = max(
            0, self._int(self.config.get("recent_context_messages", 6), 6)
        )
        self.provider_id = str(self.config.get("provider_id", "") or "").strip()
        self.max_tokens = max(1, self._int(self.config.get("max_tokens", 160), 160))
        self.temperature = self._clamp_float(
            self.config.get("temperature", 0.8), 0.8, 0.0, 2.0
        )
        self.max_reply_chars = max(
            1, self._int(self.config.get("max_reply_chars", 48), 48)
        )
        self.mention_target = self._bool(self.config.get("mention_target", True), True)
        self.reply_style = str(self.config.get("reply_style", "") or "").strip()
        self.system_prompt = str(self.config.get("system_prompt", "") or "").strip()
        self.prompt_template = str(
            self.config.get("prompt_template", "") or ""
        ).strip()
        self.fallback_reply = str(self.config.get("fallback_reply", "") or "").strip()
        self.stop_event = self._bool(self.config.get("stop_event", False), False)

        self.targets = self._load_targets(self.config.get("target_users", []))
        self.history: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=max(1, self.recent_context_messages))
        )
        self.cooldowns: dict[str, float] = {}
        self.last_global_at = 0.0

        logger.info(
            "TargetTalk loaded: enabled=%s targets=%d probability=%.2f cooldown=%ds",
            self.enabled,
            len(self.targets),
            self.probability,
            self.cooldown_seconds,
        )

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AiocqhttpMessageEvent):
        group_id = str(event.get_group_id() or "")
        sender_id = str(event.get_sender_id() or "")
        text = self._message_text(event)
        recent_context = self._recent_context(group_id)
        self._remember(group_id, event, text)

        if not self._should_handle_event(event, group_id, sender_id, text):
            return

        target = self.targets.get(sender_id)
        if not target or not self._target_enabled_for_group(target, group_id):
            return

        probability = target.probability
        if probability is None:
            probability = self.probability
        if random.random() >= probability:
            return

        now = time.monotonic()
        cooldown_key = f"{group_id}:{sender_id}"
        if self._in_cooldown(cooldown_key, now):
            return
        if self._in_global_cooldown(now):
            return
        self.cooldowns[cooldown_key] = now
        self.last_global_at = now

        reply = await self._generate_reply(
            event=event,
            target=target,
            group_id=group_id,
            sender_id=sender_id,
            sender_message=text,
            recent_context=recent_context,
        )
        reply = self._clean_reply(reply)
        if not reply:
            return

        chain = []
        if self.mention_target:
            chain.extend([At(qq=sender_id), Plain(" ")])
        chain.append(Plain(reply))
        await event.send(event.chain_result(chain))

        logger.info(
            "TargetTalk triggered: group=%s target=%s chars=%d",
            group_id,
            sender_id,
            len(reply),
        )
        if self.stop_event:
            event.stop_event()

    def _should_handle_event(
        self,
        event: AiocqhttpMessageEvent,
        group_id: str,
        sender_id: str,
        text: str,
    ) -> bool:
        return should_handle_message(
            enabled=self.enabled,
            group_id=group_id,
            sender_id=sender_id,
            self_id=str(event.get_self_id()),
            is_at_or_wake_command=bool(
                getattr(event, "is_at_or_wake_command", False)
            ),
            ignore_at_or_wake_command=self.ignore_at_or_wake_command,
            configured_targets=self.targets,
            group_whitelist=self.group_whitelist,
            text=text,
            minimum_characters=self.min_message_chars,
            maximum_characters=self.max_message_chars,
            exclude_patterns=self.exclude_keywords,
            trigger_patterns=self.trigger_keywords,
            on_invalid_regex=self._invalid_regex,
        )

    def _target_enabled_for_group(self, target: TargetUser, group_id: str) -> bool:
        return target_enabled_for_group(target, group_id)

    async def _generate_reply(
        self,
        *,
        event: AiocqhttpMessageEvent,
        target: TargetUser,
        group_id: str,
        sender_id: str,
        sender_message: str,
        recent_context: str,
    ) -> str:
        alias = target.alias or self._sender_name(event) or sender_id
        reply_style = target.reply_style or self.reply_style
        prompt_template = target.prompt_template or self.prompt_template
        if not prompt_template:
            prompt_template = (
                "目标昵称：{target_alias}\n"
                "目标 QQ：{target_qq}\n"
                "群号：{group_id}\n"
                "回复风格：{reply_style}\n"
                "最近上下文：\n{recent_context}\n\n"
                "目标刚刚说：{sender_message}\n"
                "请生成一条自然回复，不要输出 @，不超过 {max_reply_chars} 字。"
            )

        prompt = self._safe_format(
            prompt_template,
            target_alias=alias,
            target_qq=sender_id,
            group_id=group_id,
            sender_message=sender_message,
            reply_style=reply_style,
            recent_context=recent_context or "（无）",
            max_reply_chars=str(self.max_reply_chars),
        )

        try:
            provider = self._get_provider(event)
            if not provider:
                logger.warning("TargetTalk: no available LLM provider")
                return self.fallback_reply

            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=self.system_prompt or None,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return getattr(response, "completion_text", "") or self.fallback_reply
        except Exception as exc:
            logger.warning("TargetTalk: LLM reply failed: %s", exc)
            return self.fallback_reply

    def _get_provider(self, event: AiocqhttpMessageEvent):
        provider = None
        if self.provider_id:
            try:
                provider = self.context.get_provider_by_id(self.provider_id)
            except Exception as exc:
                logger.warning(
                    "TargetTalk: provider_id=%s not available: %s",
                    self.provider_id,
                    exc,
                )
        if provider:
            return provider
        try:
            return self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception as exc:
            logger.warning("TargetTalk: get default provider failed: %s", exc)
            return None

    def _message_text(self, event: AiocqhttpMessageEvent) -> str:
        for attr in ("message_str",):
            value = getattr(event, attr, "")
            if isinstance(value, str) and value.strip():
                return value.strip()
        for method in ("get_message_str", "get_message_outline"):
            try:
                value = getattr(event, method)()
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _remember(self, group_id: str, event: AiocqhttpMessageEvent, text: str) -> None:
        if not group_id or self.recent_context_messages <= 0:
            return
        text = (text or "").strip()
        if not text:
            return
        sender = self._sender_name(event) or str(event.get_sender_id() or "")
        self.history[group_id].append(history_entry(sender, text))

    def _recent_context(self, group_id: str) -> str:
        if self.recent_context_messages <= 0:
            return ""
        messages = list(self.history.get(group_id, []))
        if self.recent_context_messages:
            messages = messages[-self.recent_context_messages :]
        return "\n".join(messages)

    def _sender_name(self, event: AiocqhttpMessageEvent) -> str:
        try:
            return str(event.get_sender_name() or "").strip()
        except Exception:
            return ""

    def _in_cooldown(self, key: str, now: float) -> bool:
        last = self.cooldowns.get(key, 0.0)
        return in_cooldown(last, now, self.cooldown_seconds)

    def _in_global_cooldown(self, now: float) -> bool:
        return in_cooldown(
            self.last_global_at,
            now,
            self.global_cooldown_seconds,
        )

    def _matches_any(self, patterns: list[str], text: str) -> bool:
        return matches_any(patterns, text, self._invalid_regex)

    @staticmethod
    def _invalid_regex(pattern: str, exc: re.error) -> None:
        logger.warning("TargetTalk: invalid regex %r: %s", pattern, exc)

    def _load_targets(self, raw_targets: Any) -> dict[str, TargetUser]:
        return load_targets(raw_targets)

    def _clean_reply(self, text: str) -> str:
        return clean_reply(text, self.max_reply_chars)

    def _safe_format(self, template: str, **kwargs: str) -> str:
        try:
            return template.format(**kwargs)
        except Exception as exc:
            logger.warning("TargetTalk: prompt format failed: %s", exc)
            return template

    def _str_list(self, value: Any) -> list[str]:
        return coerce_string_list(value)

    def _str_set(self, value: Any) -> set[str]:
        return set(self._str_list(value))

    def _bool(self, value: Any, default: bool) -> bool:
        return coerce_bool(value, default)

    def _int(self, value: Any, default: int) -> int:
        return coerce_int(value, default)

    def _float_or_none(self, value: Any) -> float | None:
        return float_or_none(value)

    def _clamp_float(
        self, value: Any, default: float, minimum: float, maximum: float
    ) -> float:
        return clamp_float(value, default, minimum, maximum)
