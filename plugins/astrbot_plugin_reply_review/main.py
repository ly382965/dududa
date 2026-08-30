from __future__ import annotations

import json
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register

_NAME = "astrbot_plugin_reply_review"


def _chain_plain_text(chain: list) -> str:
    parts = []
    for comp in chain or []:
        if isinstance(comp, Plain):
            parts.append(comp.text or "")
    return "".join(parts).strip()


@register(_NAME, "mmdustc", "发言审查：检查 bot 回复是否符合语境，不符合则改写后再发", "0.1.0")
class ReplyReview(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.min_chars = int(self.config.get("min_chars", 2))
        self.max_chars = int(self.config.get("max_chars", 2000))
        self.temperature = float(self.config.get("temperature", 0.4))
        # 豁免规则：命中这些固定内容的发言不审查（天气、提醒等）
        default_skip = [
            "这里是嘟嘟哒的天气预报",
            "出门记得看天气",
            "好的，我会在",
            "设置提醒失败",
            "提醒你",
            "别忘了",
            "已取消这个提醒",
            "没有找到这个提醒",
            "缺少关键信息",
        ]
        self.skip_patterns = list(self.config.get("skip_patterns", default_skip) or [])
        logger.info("ReplyReview loaded: enabled=%s", self.enabled)

    @filter.on_decorating_result()
    async def review_reply(self, event: AstrMessageEvent) -> None:
        if not self.enabled:
            return
        try:
            result = event.get_result()
            if not result or not result.chain:
                return
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReplyReview get_result failed: %s", exc)
            return

        text = _chain_plain_text(result.chain)
        if not text or len(text) < self.min_chars:
            return
        if len(text) > self.max_chars:
            return
        # 豁免名单：命中固定内容特征（天气、提醒等）就不审查
        if any(p in text for p in self.skip_patterns):
            return

        context = self._get_context(event)
        reviewed = await self._review(context, text)
        if not reviewed or reviewed == text:
            return
        # 用改写后的内容替换纯文本链
        result.chain = [Plain(reviewed)]
        try:
            result.use_t2i(False)
            result.use_markdown(False)
        except Exception:  # noqa: BLE001
            pass
        logger.info("ReplyReview: rewrote reply (%d -> %d chars)", len(text), len(reviewed))

    @staticmethod
    def _get_context(event: AstrMessageEvent) -> str:
        try:
            msg = getattr(event, "message_str", "") or ""
        except Exception:
            msg = ""
        if not msg:
            try:
                msg = event.get_message_outline() or ""
            except Exception:
                msg = ""
        try:
            session = getattr(event, "session", None)
            if session is None:
                session = getattr(event, "message_obj", None)
        except Exception:
            session = None
        group_id = ""
        try:
            group_id = str(event.get_group_id())
        except Exception:
            pass
        return f"群:{group_id} 用户消息:{msg}"

    async def _review(self, context: str, reply: str) -> str | None:
        prompt = (
            f"上下文：{context}\n"
            f"机器人准备发送的回复：{reply}\n\n"
            "请检查这条回复是否符合作息上下文语境（话题是否对得上、语气是否合适、"
            "有没有答非所问或自说自话、有没有说了不该说的）。\n"
            "如果回复完全合适，请原样返回这条回复，不要改动任何字；\n"
            "如果不合适，请改写这条回复，让它更贴合上下文、更自然，但保留原本要表达的核心意思和事实，"
            "不要添加新的虚假信息，风格上贴近一个可爱、聪明的少女（嘟嘟哒）。\n"
            "只输出最终的回复内容本身，不要任何解释、引号、前缀或 Markdown。"
        )
        try:
            provider = self.context.get_using_provider()
            if not provider:
                return None
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt="你是发言审查器，负责让机器人回复更贴合语境。",
                max_tokens=400,
                temperature=self.temperature,
            )
            content = (getattr(response, "completion_text", "") or "").strip().strip('"“”')
            return content or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReplyReview LLM failed: %s", exc)
            return None
