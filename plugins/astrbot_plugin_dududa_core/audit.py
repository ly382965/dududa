from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.api.event import AstrMessageEvent

from .config import PLUGIN_DATA_DIR, ensure_dirs


SENSITIVE_KEYS = ("key", "token", "secret", "password", "cookie", "authorization")


class AuditLog:
    def __init__(self, path: Path | None = None):
        ensure_dirs()
        self.path = path or (PLUGIN_DATA_DIR / "audit.jsonl")

    def write(self, event: AstrMessageEvent, action: str, detail: dict[str, Any] | None = None) -> None:
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action,
            "sender": str(event.get_sender_id() or ""),
            "group": str(event.get_group_id() or ""),
            "platform": self._safe_call(event, "get_platform_name"),
            "detail": self._scrub(detail or {}),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 100)) :]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def _scrub(self, value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if any(part in str(key).lower() for part in SENSITIVE_KEYS):
                    out[key] = "[REDACTED]" if item else item
                else:
                    out[key] = self._scrub(item)
            return out
        if isinstance(value, list):
            return [self._scrub(item) for item in value]
        return value

    @staticmethod
    def _safe_call(event: AstrMessageEvent, name: str) -> str:
        try:
            return str(getattr(event, name)() or "")
        except Exception:
            return ""
