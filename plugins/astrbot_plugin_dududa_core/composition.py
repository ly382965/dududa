from __future__ import annotations

from typing import Any

from astrbot.api import logger

from .audit import AuditLog
from .config import PLUGIN_DATA_DIR, ensure_dirs, load_json
from .course import ICourseClient
from .permissions import PermissionManager


def initialize_plugin(plugin: Any, config: dict | None = None) -> None:
    plugin.config = config or {}
    plugin.enabled = bool(plugin.config.get("enabled", True))
    ensure_dirs()
    plugin.perms = PermissionManager(plugin.config)
    plugin.audit = AuditLog()
    plugin.icourse = ICourseClient()
    plugin.pending = {}
    plugin.course_refresh_at = {}
    plugin.user_state_path = PLUGIN_DATA_DIR / "user_state.json"
    plugin.group_state_path = PLUGIN_DATA_DIR / "group_state.json"
    plugin.user_state = load_json(plugin.user_state_path, {})
    plugin.group_state = load_json(plugin.group_state_path, {})
    logger.info("DududaCore loaded: enabled=%s", plugin.enabled)
