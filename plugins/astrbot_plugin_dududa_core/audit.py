from __future__ import annotations

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
from typing import Any

from astrbot.api.event import AstrMessageEvent
from dududa.domain.primitives import Sensitivity
from dududa.security.models import RedactionRequest
from dududa.security.redaction import DefaultRedactor

from .config import PLUGIN_DATA_DIR, ensure_dirs


SENSITIVE_KEYS = ("key", "token", "secret", "password", "cookie", "authorization")


class AuditLog:
    def __init__(self, path: Path | None = None):
        ensure_dirs()
        self.path = path or (PLUGIN_DATA_DIR / "audit.jsonl")
        self._redactor = DefaultRedactor(revision="legacy-audit-redactor-v1")
        self._lock = threading.Lock()

    def write(self, event: AstrMessageEvent, action: str, detail: dict[str, Any] | None = None) -> None:
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action,
            "sender": str(event.get_sender_id() or ""),
            "group": str(event.get_group_id() or ""),
            "platform": self._safe_call(event, "get_platform_name"),
            "detail": self._scrub(detail or {}),
        }
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(descriptor, encoded.encode("utf-8"))
            finally:
                os.close(descriptor)

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
        compatible = self._to_json_value(value)
        result = self._redactor.redact(
            RedactionRequest(
                schema_version=1,
                value=compatible,
                sensitivity=Sensitivity.SENSITIVE,
                purpose="legacy_audit",
            )
        )
        return self._to_mutable(result.value)

    def _to_json_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, dict):
            return {str(key): self._to_json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_json_value(item) for item in value]
        if isinstance(value, Path):
            return "[PATH]"
        return f"<{type(value).__name__}>"

    def _to_mutable(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._to_mutable(item) for key, item in value.items()}
        if hasattr(value, "items"):
            return {key: self._to_mutable(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [self._to_mutable(item) for item in value]
        return value

    @staticmethod
    def _safe_call(event: AstrMessageEvent, name: str) -> str:
        try:
            return str(getattr(event, name)() or "")
        except Exception:
            return ""
