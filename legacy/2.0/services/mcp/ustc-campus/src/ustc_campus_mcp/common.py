from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def fetched_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("cn", "nameZh", "name", "text"):
            candidate = value.get(key)
            if candidate is not None:
                return str(candidate)
        return ""
    return str(value)


def contains(value: Any, query: str) -> bool:
    return not query or query.casefold() in text(value).casefold()


def page(items: list[dict[str, Any]], offset: int, limit: int) -> tuple[list[dict[str, Any]], int, int]:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return items[offset : offset + limit], offset, limit
