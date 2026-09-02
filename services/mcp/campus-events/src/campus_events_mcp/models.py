from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EventItem:
    event_id: str
    category: str
    title: str
    url: str
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category": self.category,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
        }


@dataclass
class EventDetail:
    event_id: str
    category: str
    title: str
    url: str
    published_at: str | None = None
    content_text: str = ""
    source_hash: str | None = None
    attachments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category": self.category,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "content_text": self.content_text,
            "attachments": self.attachments,
            "source_hash": self.source_hash,
        }