from __future__ import annotations

import random

from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr


class CoreCompatibilityCommands:
    async def remind(self, event: AstrMessageEvent, text: GreedyStr):
        """提醒入口"""
        yield event.plain_result("提醒能力由 Better Reminder 处理。请直接说：提醒我 <时间> <内容>。")
        event.stop_event()
    async def reminders(self, event: AstrMessageEvent):
        """查看提醒入口"""
        yield event.plain_result("查看提醒请使用现有命令：/提醒列表 或 /查看提醒。后续会接入统一列表。")
        event.stop_event()

    async def summary(self, event: AstrMessageEvent, scope: str | None = None):
        """群聊总结入口"""
        yield event.plain_result("群聊总结由 ChatSummary v2 提供。当前统一入口已登记，后续会接入原插件命令映射。")
        event.stop_event()

    async def meme(self, event: AstrMessageEvent, keyword: str | None = None):
        """表情包入口"""
        yield event.plain_result("表情包能力由 Meme Manager 提供。可继续使用现有表情包命令；/meme 统一入口已预留。")
        event.stop_event()

    async def fortune(self, event: AstrMessageEvent):
        """今日运势"""
        choices = ["适合写代码", "适合补觉", "适合查评课", "适合把 TODO 拆小", "适合先喝水"]
        yield event.plain_result("今日建议：" + random.choice(choices))
        event.stop_event()

    async def draw(self, event: AstrMessageEvent, topic: GreedyStr):
        """抽签"""
        options = ["可以", "再想想", "先做最小版本", "交给明天的自己", "值得认真试试"]
        yield event.plain_result(f"{topic}：{random.choice(options)}")
        event.stop_event()

    async def poke(self, event: AstrMessageEvent):
        """戳一戳入口"""
        yield event.plain_result("戳一戳能力由 PokePro 提供，统一入口已预留。")
        event.stop_event()

    async def reread(self, event: AstrMessageEvent):
        """复读入口"""
        yield event.plain_result("复读能力由 Reread 提供，统一入口已预留。")
        event.stop_event()
