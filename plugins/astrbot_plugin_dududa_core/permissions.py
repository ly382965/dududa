from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from astrbot.api.event import AstrMessageEvent

from .config import load_astrbot_config, str_set


@dataclass(frozen=True)
class Actor:
    qq: str
    group_id: str
    is_platform_admin: bool


class PermissionManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config or {}
        self.owners = str_set(self.config.get("owners", []))
        self.global_admins = str_set(self.config.get("global_admins", []))
        self.trusted_users = str_set(self.config.get("trusted_users", []))
        self.muted_users = str_set(self.config.get("muted_users", []))
        self.group_admins = self._load_group_admins(self.config.get("group_admins", {}))

        if not self.owners:
            astrbot_cfg = load_astrbot_config()
            self.owners = str_set(astrbot_cfg.get("admins_id", []))

    def actor(self, event: AstrMessageEvent) -> Actor:
        try:
            is_admin = bool(event.is_admin())
        except Exception:
            is_admin = False
        return Actor(
            qq=str(event.get_sender_id() or ""),
            group_id=str(event.get_group_id() or ""),
            is_platform_admin=is_admin,
        )

    def role(self, event: AstrMessageEvent) -> str:
        actor = self.actor(event)
        if actor.qq in self.muted_users:
            return "muted_user"
        if actor.qq in self.owners:
            return "owner"
        if actor.qq in self.global_admins:
            return "admin"
        if actor.group_id and actor.qq in self.group_admins.get(actor.group_id, set()):
            return "admin"
        if actor.is_platform_admin:
            return "admin"
        if actor.qq in self.trusted_users:
            return "trusted_user"
        return "normal_user"

    def is_owner(self, event: AstrMessageEvent) -> bool:
        return self.role(event) == "owner"

    def is_admin(self, event: AstrMessageEvent) -> bool:
        return self.role(event) in {"owner", "admin"}

    def is_trusted(self, event: AstrMessageEvent) -> bool:
        return self.role(event) in {"owner", "admin", "trusted_user"}

    def is_muted(self, event: AstrMessageEvent) -> bool:
        return self.role(event) == "muted_user"

    @staticmethod
    def _load_group_admins(value: Any) -> dict[str, set[str]]:
        if isinstance(value, str):
            try:
                value = json.loads(value or "{}")
            except json.JSONDecodeError:
                value = {}
        if not isinstance(value, dict):
            return {}
        result: dict[str, set[str]] = {}
        for group_id, users in value.items():
            result[str(group_id)] = str_set(users)
        return result
