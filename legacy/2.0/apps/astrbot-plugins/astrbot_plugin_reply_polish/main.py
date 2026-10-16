from __future__ import annotations

from typing import Iterable

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Node, Nodes, Plain
from astrbot.api.star import Context, Star, register
from dududa.compatibility.reply_polish import (
    ANSWER_PROFILE_EVENT_KEY,
    should_merge_forward,
    split_long_piece,
    split_text,
)


@register(
    "astrbot_plugin_reply_polish",
    "mmdustc",
    "Dududa 1.0 长文本合并转发兼容层（2.0 默认关闭）",
    "0.2.0",
)
class ReplyPolishPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        config = config or {}
        self.min_chars = int(config.get("min_chars", 600))
        self.chunk_chars = int(config.get("chunk_chars", 520))
        self.max_nodes = int(config.get("max_nodes", 8))
        self.bot_name = str(config.get("bot_name", "AstrBot"))
        self.bot_uin = str(config.get("bot_uin", "0"))
        self.enable_forward = bool(config.get("enable_forward", False))

    @filter.on_decorating_result()
    async def forward_long_plain_reply(self, event: AstrMessageEvent) -> None:
        if not self.enable_forward:
            return
        if not self._is_qq_group_event(event):
            return

        result = event.get_result()
        if not result or not result.chain:
            return

        plain_parts: list[str] = []
        for comp in result.chain:
            if not isinstance(comp, Plain):
                return
            plain_parts.append(comp.text or "")

        text = "".join(plain_parts).strip()
        answer_profile = event.get_extra(ANSWER_PROFILE_EVENT_KEY, None)
        if not should_merge_forward(answer_profile, len(text), self.min_chars):
            return

        chunks = list(self._split_text(text, self.chunk_chars, self.max_nodes))
        if not chunks:
            return

        nodes = [
            Node(
                name=self.bot_name,
                uin=self.bot_uin,
                content=[Plain(chunk)],
            )
            for chunk in chunks
        ]
        result.chain = [Nodes(nodes)]
        result.use_t2i(False)
        result.use_markdown(False)
        logger.info(
            "ReplyPolish: converted long reply to merged forward, chars=%d nodes=%d",
            len(text),
            len(nodes),
        )

    def _is_qq_group_event(self, event: AstrMessageEvent) -> bool:
        try:
            if event.get_platform_name() != "aiocqhttp":
                return False
            return bool(event.get_group_id())
        except Exception:
            return False

    def _split_text(
        self, text: str, chunk_chars: int, max_nodes: int
    ) -> Iterable[str]:
        return split_text(text, chunk_chars, max_nodes)

    def _split_long_piece(self, text: str, chunk_chars: int) -> list[str]:
        return split_long_piece(text, chunk_chars)
