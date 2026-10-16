from __future__ import annotations

from typing import Any

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .emoji import EmojiKitchenCommands


@register(
    "astrbot_plugin_emoji_kitchen",
    "mmdustc",
    "基于 Google Emoji Kitchen 的官方表情合成",
    "1.0.0",
)
class EmojiKitchenPlugin(EmojiKitchenCommands, Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.config = config or {}

    @filter.command("emoji", alias={"表情合成"})
    async def emoji(self, event: AstrMessageEvent, arguments: GreedyStr):
        """合成两个 Unicode Emoji。"""
        async for result in EmojiKitchenCommands.emoji(self, event, arguments):
            yield result
