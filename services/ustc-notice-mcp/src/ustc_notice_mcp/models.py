from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NoticeItem:
    notice_id: int
    title: str
    url: str
    published_at: str | None = None
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.notice_id,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "category": self.category,
        }


@dataclass
class NoticeDetail:
    notice_id: int
    title: str
    url: str
    published_at: str | None = None
    last_modified: str | None = None
    category: str | None = None
    content_text: str = ""
    content_html: str = ""
    attachments: list[dict[str, str]] = field(default_factory=list)
    source_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.notice_id,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "last_modified": self.last_modified,
            "category": self.category,
            "content_text": self.content_text,
            "attachments": self.attachments,
        }