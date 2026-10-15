from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent

from .config import load_plugin_config, save_json, str_set


@dataclass
class PendingAction:
    action: str
    requester: str
    expires_at: float
    payload: dict[str, Any]


class CoreLifecycleMixin:
    async def _handle_controlled_rollout(self, event: AstrMessageEvent) -> None:
        if not getattr(self, "enabled", False):
            return
        if self._matches_registered_command(event):
            return
        bridge = getattr(self, "rollout_bridge", None)
        proactive = getattr(self, "proactive_talk", None)
        if proactive is not None and await proactive.maybe_handle(event):
            return
        if bridge is not None:
            await bridge.handle(event)

    @staticmethod
    def _matches_registered_command(event: AstrMessageEvent) -> bool:
        get_extra = getattr(event, "get_extra", None)
        if not callable(get_extra):
            return False
        return bool(get_extra("handlers_parsed_params", {}))

    async def terminate(self) -> None:
        if getattr(self, "_dududa_runtime_terminated", False):
            return
        apply_service = getattr(self, "_dududa_runtime_config_apply", None)
        if apply_service is not None:
            await apply_service.begin_shutdown()
        bridge = getattr(self, "rollout_bridge", None)
        self.proactive_talk = None
        assembly = getattr(self, "runtime_assembly", None)
        first_error: BaseException | None = None
        health_task = getattr(self, "_dududa_model_health_task", None)
        if health_task is not None:
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
            except BaseException as exc:
                first_error = exc
            self._dududa_model_health_task = None
        if bridge is not None:
            try:
                await bridge.close()
            except BaseException as exc:
                first_error = exc
            else:
                self.rollout_bridge = None
        if assembly is not None:
            try:
                await assembly.close()
            except BaseException as exc:
                first_error = first_error or exc
            else:
                self.runtime_assembly = None
        icourse = getattr(self, "icourse", None)
        if apply_service is not None and self.rollout_bridge is None and self.runtime_assembly is None:
            try:
                await apply_service.close()
            except BaseException as exc:
                first_error = first_error or exc
        if icourse is not None:
            try:
                await icourse.close()
            except BaseException as exc:
                first_error = first_error or exc
            else:
                self.icourse = None
        unified_mcp = getattr(self, "unified_mcp_client", None)
        if unified_mcp is not None:
            try:
                await unified_mcp.close()
            except BaseException as exc:
                first_error = first_error or exc
            else:
                self.unified_mcp_client = None
        pending_cleanup = tuple(getattr(self, "_dududa_runtime_cleanup_assemblies", ()))
        failed_cleanup: list[object] = []
        for candidate in reversed(pending_cleanup):
            try:
                await candidate.close()
            except BaseException as exc:
                first_error = first_error or exc
                failed_cleanup.append(candidate)
        self._dududa_runtime_cleanup_assemblies = list(reversed(failed_cleanup))
        self._dududa_runtime_terminated = (
            getattr(self, "rollout_bridge", None) is None
            and getattr(self, "runtime_assembly", None) is None
            and getattr(self, "icourse", None) is None
            and getattr(self, "unified_mcp_client", None) is None
            and not self._dududa_runtime_cleanup_assemblies
            and not getattr(apply_service, "pending_cleanup", ())
        )
        if self._dududa_runtime_terminated:
            self._dududa_runtime_initialized = False
        if first_error is not None:
            raise first_error

    def _blocked(self, event: AstrMessageEvent) -> str | None:
        if not self.enabled:
            return "嘟嘟哒核心插件暂时关闭。"
        if self.perms.is_muted(event):
            return "你现在不能调用嘟嘟哒。"
        group_muted = str_set(self._group_record(event).get("muted_users", []))
        if self._sender(event) in group_muted:
            return "你在本群暂时不能调用嘟嘟哒。"
        return None

    def _sender(self, event: AstrMessageEvent) -> str:
        return str(event.get_sender_id() or "")

    def _group(self, event: AstrMessageEvent) -> str:
        return str(event.get_group_id() or "")

    def _require_admin(self, event: AstrMessageEvent) -> str | None:
        blocked = self._blocked(event)
        if blocked:
            return blocked
        if not self.perms.is_admin(event):
            return "这个指令需要管理员权限。"
        return None

    def _require_owner(self, event: AstrMessageEvent) -> str | None:
        blocked = self._blocked(event)
        if blocked:
            return blocked
        if not self.perms.is_owner(event):
            return "这个指令需要 owner 权限。"
        return None

    def _save_user_state(self) -> None:
        save_json(self.user_state_path, self.user_state)

    def _save_group_state(self) -> None:
        save_json(self.group_state_path, self.group_state)

    def _reload_permissions(self) -> None:
        from .permissions import PermissionManager

        disk_config = load_plugin_config()
        if disk_config:
            self.config = disk_config
            self.perms = PermissionManager(self.config)

    def _user_record(self, event: AstrMessageEvent) -> dict[str, Any]:
        user_id = self._sender(event)
        return self.user_state.setdefault(
            user_id,
            {"memory_enabled": True, "memories": [], "style": ""},
        )

    def _group_record(self, event: AstrMessageEvent) -> dict[str, Any]:
        group_id = self._group(event) or "private"
        return self.group_state.setdefault(
            group_id,
            {"mode": "normal", "reply_rate": 100},
        )

    def _new_confirmation(
        self, event: AstrMessageEvent, action: str, payload: dict[str, Any]
    ) -> str:
        token = secrets.token_hex(3).upper()
        self.pending[token] = PendingAction(
            action=action,
            requester=self._sender(event),
            expires_at=time.time() + 300,
            payload=payload,
        )
        self.audit.write(event, "confirm_requested", {"action": action})
        return token
