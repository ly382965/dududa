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
        msg = ""
        try:
            msg = event.get_message_str() or ""
        except Exception:
            pass
        if not msg:
            try:
                msg = event.get_message_outline() or ""
            except Exception:
                pass
        group_id = ""
        try:
            group_id = str(event.get_group_id())
        except Exception:
            pass
        sender = ""
        try:
            sender = str(event.get_sender_name() or "")
        except Exception:
            pass
        return f"群:{group_id} 用户:{sender} 用户消息:{msg}"

    async def _review(self, context: str, reply: str) -> str | None:
        prompt = (
            f"上下文：{context}\n"
            f"机器人准备发送的回复：{reply}\n\n"
            "请检查这条回复有没有明显的问题。\n"
            "只在以下情况才需要改写：\n"
            "1. 回复明显答非所问（上下文问课程/老师，回复却在说完全不相关的事）；\n"
            "2. 回复里有事实错误或编造的信息；\n"
            "3. 回复语气冒犯、说了不该说的话；\n"
            "4. 回复明显机械、混乱、不像一句正常的话。\n\n"
            "注意：\n"
            "- 上下文信息可能不完整（比如只有一个名字），不要因为\"觉得信息少\"就改回复；\n"
            "- 如果回复本身是一段通顺、合理、自洽的内容（例如在介绍某位老师、某门课），即使你"
            "无法完全确认它和上下文的关系，也要原样返回，不要改动；\n"
            "- 大多数情况下应该原样返回。\n\n"
            "如果回复没有上述问题，请原样返回这条回复，不要改动任何字；\n"
            "如果确实有问题，请改写，保留原本要表达的核心意思和事实，风格贴近可爱聪明的嘟嘟哒。\n"
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
