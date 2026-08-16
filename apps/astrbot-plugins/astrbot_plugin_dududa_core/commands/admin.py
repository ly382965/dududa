from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr

from ..config import (
    ASTRBOT_CONFIG_PATH,
    load_astrbot_config,
    load_plugin_config,
    save_astrbot_config,
    save_plugin_config,
    str_set,
)
from ..lifecycle import PendingAction


class CoreAdminCommands:
    async def admin_status(self, event: AstrMessageEvent):
        """查看管理状态"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        cfg = load_astrbot_config()
        yield event.plain_result(
            "管理状态\n"
            f"default_provider_id: {cfg.get('provider_settings', {}).get('default_provider_id')}\n"
            f"owner_count: {len(self.perms.owners)}\n"
            f"global_admin_count: {len(self.perms.global_admins)}\n"
            f"pending_confirmations: {len(self.pending)}\n"
            f"audit_log: {self.audit.path}"
        )
        event.stop_event()

    async def admin_plugins(self, event: AstrMessageEvent):
        """查看插件列表"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        plugins_dir = Path(__file__).resolve().parents[2]
        names = sorted(p.name for p in plugins_dir.iterdir() if p.is_dir())
        yield event.plain_result(
            "已安装插件：\n" + "\n".join(f"- {name}" for name in names)
        )
        event.stop_event()

    async def admin_mcp(
        self, event: AstrMessageEvent, action: str = "list", name: str | None = None
    ):
        """管理 MCP"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        if action == "test":
            target = str(name or "icourse").strip().lower()
            if target != "icourse":
                yield event.plain_result(f"未知 MCP Server：{target}")
                event.stop_event()
                return
            tools = await self.icourse.list_tools()
            yield event.plain_result(
                "MCP icourse 已批准传输工具：\n"
                + "\n".join(f"- {tool}" for tool in tools)
            )
        else:
            mode = getattr(self, "icourse_mode", "unavailable")
            yield event.plain_result(f"MCP 列表：\n- icourse：{mode}")
        event.stop_event()

    async def admin_group(
        self, event: AstrMessageEvent, action: str, value: str | None = None
    ):
        """设置 Dududa 2.0 群模式和回复概率。"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        if action == "meme-rate":
            yield event.plain_result(
                "Dududa 2.0 已停用自动表情包概率配置；现有旧配置保留但不再修改。"
            )
            event.stop_event()
            return
        rec = self._group_record(event)
        if action == "mode" and value in {"quiet", "normal", "active"}:
            rec["mode"] = value
        elif action == "reply-rate" and value and value.isdigit():
            rec["reply_rate"] = max(0, min(100, int(value)))
        else:
            yield event.plain_result(
                "用法：/admin group mode <quiet|normal|active> 或 reply-rate <0-100>"
            )
            event.stop_event()
            return
        self._save_group_state()
        self.audit.write(event, "admin_group", {"action": action, "value": value})
        yield event.plain_result(f"已更新本群设置：{rec}")
        event.stop_event()

    async def admin_user(self, event: AstrMessageEvent, action: str, qq: str):
        """限制或解除用户"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        group_id = self._group(event)
        if not group_id:
            yield event.plain_result(
                "群级禁用请在群聊中执行；全局禁用请由 owner 使用 /admin permission grant <QQ> muted。"
            )
            event.stop_event()
            return
        rec = self._group_record(event)
        muted = str_set(rec.get("muted_users", []))
        if action == "mute":
            muted.add(str(qq))
            msg = f"已在本群限制 {qq} 调用嘟嘟哒。"
        elif action == "unmute":
            muted.discard(str(qq))
            msg = f"已解除 {qq} 在本群的调用限制。"
        else:
            yield event.plain_result(
                "用法：/admin user mute <QQ> 或 /admin user unmute <QQ>"
            )
            event.stop_event()
            return
        rec["muted_users"] = sorted(muted)
        self._save_group_state()
        self.audit.write(
            event,
            "admin_user",
            {"action": action, "target": qq, "group_scope": group_id},
        )
        yield event.plain_result(msg)
        event.stop_event()

    async def admin_memory(self, event: AstrMessageEvent, action: str):
        """管理记忆"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        if action == "summary":
            total = sum(
                len(v.get("memories", []))
                for v in self.user_state.values()
                if isinstance(v, dict)
            )
            yield event.plain_result(
                f"嘟嘟哒核心轻量记忆：用户 {len(self.user_state)} 个，条目 {total} 条。Iris 记忆请在 Iris 面板查看。"
            )
        elif action == "clear-short":
            token = self._new_confirmation(event, "memory_clear_short", {})
            yield event.plain_result(
                f"该操作会清理嘟嘟哒核心临时确认队列。请回复 /confirm {token}"
            )
        else:
            yield event.plain_result(
                "用法：/admin memory summary 或 /admin memory clear-short"
            )
        event.stop_event()

    async def admin_logs(
        self, event: AstrMessageEvent, action: str = "errors", value: str | None = None
    ):
        """查看脱敏日志摘要"""
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        limit = 10
        if action == "tail":
            owner_err = self._require_owner(event)
            if owner_err:
                yield event.plain_result(owner_err)
                event.stop_event()
                return
            if value and value.isdigit():
                limit = max(1, min(50, int(value)))
        elif action != "errors":
            yield event.plain_result(
                "用法：/admin logs errors 或 /admin logs tail <行数>"
            )
            event.stop_event()
            return
        records = self.audit.tail(limit)
        if not records:
            yield event.plain_result("审计日志暂无记录。")
        else:
            lines = [
                f"- {r.get('time')} {r.get('action')} sender={r.get('sender')} group={r.get('group')}"
                for r in records
            ]
            yield event.plain_result("最近审计：\n" + "\n".join(lines))
        event.stop_event()

    async def admin_backup(self, event: AstrMessageEvent, action: str = "create"):
        """创建配置备份"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        token = self._new_confirmation(event, "backup_create", {"action": action})
        yield event.plain_result(f"将备份 AstrBot 主配置。请回复 /confirm {token}")
        event.stop_event()

    async def admin_restart(self, event: AstrMessageEvent, service: str):
        """重启服务提示"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        if service not in {"astrbot", "napcat"}:
            yield event.plain_result(
                "只能申请重启 astrbot 或 napcat。NapCat 不会由 QQ 命令直接重启。"
            )
            event.stop_event()
            return
        token = self._new_confirmation(event, "restart", {"service": service})
        yield event.plain_result(
            f"重启 {service} 是高风险操作。请回复 /confirm {token}"
        )
        event.stop_event()

    async def admin_model(
        self,
        event: AstrMessageEvent,
        action: str = "route",
        scene: str | None = None,
        model: str | None = None,
    ):
        """查看模型路由"""
        if action == "set":
            err = self._require_owner(event)
            if err:
                yield event.plain_result(err)
                event.stop_event()
                return
            if not scene or not model:
                yield event.plain_result(
                    "用法：/admin model set <default|image> <模型ID>"
                )
                event.stop_event()
                return
            if scene not in {"default", "image"}:
                yield event.plain_result("当前只支持设置 default 或 image 场景。")
                event.stop_event()
                return
            token = self._new_confirmation(
                event, "model_set", {"scene": scene, "model": model}
            )
            yield event.plain_result(
                f"切换 {scene} 模型到 {model} 需要确认。请回复 /confirm {token}"
            )
            event.stop_event()
            return
        err = self._require_admin(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        cfg = load_astrbot_config()
        yield event.plain_result(
            "模型路由\n"
            f"默认：{cfg.get('provider_settings', {}).get('default_provider_id')}\n"
            "文本/工具：openai/gpt-5.5\n"
            "图像生成：gpt-image-2，可用但较慢。"
        )
        event.stop_event()

    async def admin_permission(
        self, event: AstrMessageEvent, action: str, qq: str, role: str
    ):
        """修改全局权限"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        role_key = role.strip().lower()
        if action not in {"grant", "revoke"} or role_key not in {
            "owner",
            "admin",
            "trusted",
            "muted",
        }:
            yield event.plain_result(
                "用法：/admin permission <grant|revoke> <QQ> <owner|admin|trusted|muted>"
            )
            event.stop_event()
            return
        token = self._new_confirmation(
            event,
            "permission_change",
            {"action": action, "qq": str(qq), "role": role_key},
        )
        yield event.plain_result(f"全局权限变更需要确认。请回复 /confirm {token}")
        event.stop_event()

    async def admin_broadcast(self, event: AstrMessageEvent, content: GreedyStr):
        """申请群发"""
        err = self._require_owner(event)
        if err:
            yield event.plain_result(err)
            event.stop_event()
            return
        text = str(content).strip()
        if not text:
            yield event.plain_result("用法：/admin broadcast <内容>")
            event.stop_event()
            return
        token = self._new_confirmation(event, "broadcast", {"chars": len(text)})
        yield event.plain_result(
            f"群发是高风险操作，已记录摘要但不会回显原文。请回复 /confirm {token}"
        )
        event.stop_event()

    async def confirm(self, event: AstrMessageEvent, token: str):
        """确认高风险操作"""
        pending = self.pending.get(token.upper())
        if not pending:
            yield event.plain_result("没有找到这个确认 token。")
            event.stop_event()
            return
        if pending.requester != self._sender(event):
            yield event.plain_result("只有操作发起者可以确认。")
            event.stop_event()
            return
        if time.time() > pending.expires_at:
            self.pending.pop(token.upper(), None)
            yield event.plain_result("确认 token 已过期。")
            event.stop_event()
            return
        msg = self._execute_pending(event, pending)
        self.pending.pop(token.upper(), None)
        self.audit.write(event, "confirm_executed", {"action": pending.action})
        yield event.plain_result(msg)
        event.stop_event()

    async def cancel(self, event: AstrMessageEvent, token: str):
        """取消高风险操作"""
        pending = self.pending.get(token.upper())
        if not pending:
            yield event.plain_result("没有找到这个确认 token。")
        elif pending.requester != self._sender(event):
            yield event.plain_result("只有操作发起者可以取消。")
        else:
            self.pending.pop(token.upper(), None)
            self.audit.write(event, "confirm_cancelled", {"action": pending.action})
            yield event.plain_result("已取消。")
        event.stop_event()

    def _execute_pending(self, event: AstrMessageEvent, pending: PendingAction) -> str:
        if pending.action == "memory_clear_short":
            self.pending.clear()
            return "已清理嘟嘟哒核心临时确认队列。"
        if pending.action == "backup_create":
            backup = ASTRBOT_CONFIG_PATH.with_suffix(
                f".json.bak_dududa_{int(time.time())}"
            )
            backup.write_bytes(ASTRBOT_CONFIG_PATH.read_bytes())
            return f"已创建配置备份：{backup.name}"
        if pending.action == "permission_change":
            return self._apply_permission_change(pending.payload)
        if pending.action == "model_set":
            return self._apply_model_set(pending.payload)
        if pending.action == "broadcast":
            return "群发确认已记录。为避免误发，当前 QQ 指令不会直接群发；请在后台按审计记录人工执行。"
        if pending.action == "restart":
            service = pending.payload.get("service")
            return f"重启 {service} 的确认已记录。容器重启需要宿主机执行 ./manage.sh restart {service}，不会在 QQ 内直接执行。"
        return "确认完成，但该动作还没有执行器。"

    def _apply_permission_change(self, payload: dict[str, Any]) -> str:
        action = str(payload.get("action") or "")
        qq = str(payload.get("qq") or "")
        role = str(payload.get("role") or "")
        key_by_role = {
            "owner": "owners",
            "admin": "global_admins",
            "trusted": "trusted_users",
            "muted": "muted_users",
        }
        key = key_by_role.get(role)
        if action not in {"grant", "revoke"} or not qq or not key:
            return "权限变更参数无效，未执行。"
        cfg = load_plugin_config() or dict(self.config)
        values = str_set(cfg.get(key, []))
        if action == "grant":
            values.add(qq)
        else:
            values.discard(qq)
        cfg[key] = sorted(values)
        save_plugin_config(cfg)
        self._reload_permissions()
        label = "授予" if action == "grant" else "撤销"
        return f"已{label} {qq} 的 {role} 权限。"

    def _apply_model_set(self, payload: dict[str, Any]) -> str:
        scene = str(payload.get("scene") or "")
        model = str(payload.get("model") or "")
        if scene == "image" and model:
            cfg = load_plugin_config() or dict(self.config)
            cfg["image_model_id"] = model
            save_plugin_config(cfg)
            self.config = cfg
            return f"已将 image 场景模型记录为 {model}。"
        if scene == "default" and model:
            astrbot_cfg = load_astrbot_config()
            provider_ids = {
                str(item.get("id"))
                for item in astrbot_cfg.get("provider", [])
                if isinstance(item, dict) and item.get("id")
            }
            if model not in provider_ids:
                return f"未找到 provider：{model}，未切换默认模型。"
            backup = ASTRBOT_CONFIG_PATH.with_suffix(
                f".json.bak_model_set_{int(time.time())}"
            )
            backup.write_bytes(ASTRBOT_CONFIG_PATH.read_bytes())
            astrbot_cfg.setdefault("provider_settings", {})["default_provider_id"] = (
                model
            )
            save_astrbot_config(astrbot_cfg)
            cfg = load_plugin_config() or dict(self.config)
            cfg["default_model_id"] = model
            save_plugin_config(cfg)
            self.config = cfg
            return f"已将默认模型配置为 {model}；如未即时生效，请重启 AstrBot。"
        return "模型切换参数无效，未执行。"
