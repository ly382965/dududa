from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from dududa.errors import ErrorCategory, error

from .repository import InMemoryMemoryRepository
from .serialization import record_from_dict, record_to_dict


class JsonMemoryRepository(InMemoryMemoryRepository):
    """Atomic Memory v2 JSON adapter; legacy JSON is quarantined and never overwritten."""

    def __init__(self, path: Path, selector_verifier: object, **kwargs: object) -> None:
        self.path = path
        self.quarantined_legacy_count = 0
        self._legacy_source = False
        super().__init__(
            selector_verifier, repository_revision="memory-json-v1", **kwargs
        )
        self._load()

    async def _after_write_locked(self) -> None:
        if self._legacy_source:
            raise error(
                "legacy_memory_json_is_read_only",
                ErrorCategory.CONFLICT,
                "memory.migration_required",
            )
        self._persist()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            raise error(
                "invalid_memory_json",
                ErrorCategory.VALIDATION,
                "memory.unavailable",
            ) from None
        if not isinstance(value, Mapping) or value.get("schema_version") != 1:
            self._legacy_source = True
            self.quarantined_legacy_count = _legacy_count(value)
            return
        records = value.get("records")
        if not isinstance(records, list):
            raise error(
                "invalid_memory_json_records",
                ErrorCategory.VALIDATION,
                "memory.unavailable",
            )
        self.seed(record_from_dict(item) for item in records)

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "repository_revision": "memory-json-v1",
            "records": [
                record_to_dict(record)
                for record in sorted(
                    self._records.values(), key=lambda item: item.memory_id
                )
            ],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError:
            raise error(
                "memory_json_temporary_create_failed",
                ErrorCategory.CONFLICT,
                "memory.unavailable",
            ) from None
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except BaseException as caught:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            if isinstance(caught, Exception):
                raise error(
                    "memory_json_atomic_write_failed",
                    ErrorCategory.EXTERNAL,
                    "memory.unavailable",
                ) from None
            raise


def _legacy_count(value: object) -> int:
    if not isinstance(value, Mapping):
        return 1
    count = 0
    for item in value.values():
        if isinstance(item, Mapping) and isinstance(item.get("memories"), list):
            count += len(item["memories"])
    return count or len(value)
