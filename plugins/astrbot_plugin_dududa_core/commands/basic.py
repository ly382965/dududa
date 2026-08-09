from __future__ import annotations

from astrbot.api.event import AstrMessageEvent

from ..config import load_astrbot_config
from ..help_menu import module_help


class CoreBasicCommands:
    async def help(self, event: AstrMessageEvent, module: str | None = None):
        """查看嘟嘟哒帮助"""
        if self._blocked(event):
            return
        if (module or "").strip().lower() == "admin" and not self.perms.is_admin(event):
            yield event.plain_result("管理员菜单需要 admin 权限。")
        else:
            yield event.plain_result(module_help(module or ""))
        event.stop_event()

    async def dududa_help(self, event: AstrMessageEvent, module: str | None = None):
        """查看嘟嘟哒帮助"""
        if self._blocked(event):
            return
        yield event.plain_result(module_help(module or ""))
        event.stop_event()

    async def about(self, event: AstrMessageEvent):
        """查看嘟嘟哒介绍"""
        if self._blocked(event):
            return
        yield event.plain_result(
            "嘟嘟哒是萌萌哒维护的 QQ 群聊 Agent，会聊天、查评课、做提醒入口、整理记忆，也会守住隐私和边界。"
        )
        event.stop_event()

    async def ping(self, event: AstrMessageEvent):
        """测试在线状态"""
        if self._blocked(event):
            return
        yield event.plain_result("pong，嘟嘟哒在线。")
        event.stop_event()

    async def status(self, event: AstrMessageEvent):
        """查看可见运行状态"""
        if self._blocked(event):
            return
        cfg = load_astrbot_config()
        default_provider = cfg.get("provider_settings", {}).get(
            "default_provider_id", "未知"
        )
        role = self.perms.role(event)
        group = self._group_record(event)
        icourse_mode = getattr(self, "icourse_mode", "legacy")
        yield event.plain_result(
            "嘟嘟哒状态\n"
            f"角色：{role}\n"
            f"默认模型：{default_provider}\n"
            "多模态：支持，gpt-image-2 可用但较慢\n"
            f"群模式：{group.get('mode')}\n"
            f"评课 MCP：icourse（{icourse_mode}）"
        )
        event.stop_event()

    async def privacy(self, event: AstrMessageEvent):
        """查看隐私说明"""
        yield event.plain_result(
            "隐私边界：不跨群泄露，不公开个人课表/成绩/考试，不保存明文密码。"
            "你可以用 /memory 查看、/forget 删除自己在嘟嘟哒核心插件里的记忆。"
        )
        event.stop_event()
