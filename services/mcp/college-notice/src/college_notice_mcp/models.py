from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class College:
    key: str
    name: str
    list_url: str
    list_path: str = ""
    base_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "list_url": self.list_url,
            "list_path": self.list_path,
            "base_url": self.base_url,
        }


@dataclass
class CollegeNoticeItem:
    notice_id: str
    college_key: str
    title: str
    url: str
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "college_key": self.college_key,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
        }


@dataclass
class CollegeNoticeDetail:
    notice_id: str
    college_key: str
    title: str
    url: str
    published_at: str | None = None
    content_text: str = ""
    source_hash: str | None = None
    attachments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "college_key": self.college_key,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "content_text": self.content_text,
            "attachments": self.attachments,
            "source_hash": self.source_hash,
        }
