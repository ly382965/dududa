from __future__ import annotations

import time

from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr


class CoreMemoryCommands:
    async def remember(self, event: AstrMessageEvent, content: GreedyStr):
        """让嘟嘟哒记住一件事"""
        if self._blocked(event):
            return
        rec = self._user_record(event)
        if not rec.get("memory_enabled", True):
            yield event.plain_result("你的个性化记忆当前是关闭的。")
            event.stop_event()
            return
        text = str(content).strip()
        if not text:
            yield event.plain_result("要记住什么呀？")
            event.stop_event()
            return
        rec.setdefault("memories", []).append({"text": text, "time": int(time.time())})
        self._save_user_state()
        self.audit.write(event, "remember", {"chars": len(text)})
        yield event.plain_result("记住啦。")
        event.stop_event()
    async def forget(self, event: AstrMessageEvent, keyword: GreedyStr):
        """删除自己的相关记忆"""
        rec = self._user_record(event)
        key = str(keyword).strip()
        memories = rec.get("memories", [])
        kept = [item for item in memories if key not in item.get("text", "")]
        removed = len(memories) - len(kept)
        rec["memories"] = kept
        self._save_user_state()
        self.audit.write(event, "forget", {"removed": removed})
        yield event.plain_result(f"已删除 {removed} 条相关记忆。")
        event.stop_event()

    async def memory(self, event: AstrMessageEvent, action: str | None = None):
        """查看或管理自己的记忆"""
        rec = self._user_record(event)
        act = (action or "").strip().lower()
        if act == "off":
            rec["memory_enabled"] = False
            self._save_user_state()
            yield event.plain_result("已关闭你的个性化记忆。")
        elif act == "on":
            rec["memory_enabled"] = True
            self._save_user_state()
            yield event.plain_result("已开启你的个性化记忆。")
        elif act == "export":
            memories = [item.get("text", "") for item in rec.get("memories", [])]
            yield event.plain_result("你的记忆摘要：\n" + ("\n".join(f"- {m}" for m in memories) if memories else "暂无。"))
        else:
            memories = [item.get("text", "") for item in rec.get("memories", [])][-5:]
            style = rec.get("style") or "未设置"
            yield event.plain_result(
                f"记忆开关：{'开' if rec.get('memory_enabled', True) else '关'}\n"
                f"回复偏好：{style}\n"
                + ("最近记忆：\n" + "\n".join(f"- {m}" for m in memories) if memories else "最近记忆：暂无。")
            )
        event.stop_event()

    async def style(self, event: AstrMessageEvent, mode: str):
        """设置回复偏好"""
        if mode not in {"简洁", "详细", "可爱", "认真"}:
            yield event.plain_result("可选风格：简洁、详细、可爱、认真。")
            event.stop_event()
            return
        rec = self._user_record(event)
        rec["style"] = mode
        self._save_user_state()
        yield event.plain_result(f"好，以后我会更偏向「{mode}」一点。")
        event.stop_event()
