from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import College

DEFAULT_DB_PATH = Path("data") / "college-notice.sqlite3"

DEFAULT_COLLEGES: list[dict[str, Any]] = [
    {
        "key": "math",
        "name": "数学科学学院",
        "list_url": "https://math.ustc.edu.cn/tzgg/list.htm",
        "list_path": "/tzgg/list.htm",
        "base_url": "https://math.ustc.edu.cn",
    },
    {
        "key": "cs",
        "name": "计算机科学与技术学院",
        "list_url": "https://cs.ustc.edu.cn/3054/list.htm",
        "list_path": "/3054/list.htm",
        "base_url": "https://cs.ustc.edu.cn",
    },
    {
        "key": "physics",
        "name": "物理学院",
        "list_url": "https://physics.ustc.edu.cn/3584/list.htm",
        "list_path": "/3584/list.htm",
        "base_url": "https://physics.ustc.edu.cn",
    },
]


@dataclass(frozen=True)
class AppConfig:
    db_path: Path = DEFAULT_DB_PATH
    request_delay: float = 1.0
    timeout: float = 30.0
    colleges: tuple[College, ...] = field(
        default_factory=lambda: tuple(College(**item) for item in DEFAULT_COLLEGES)
    )
    user_agent: str = (
        "college-notice-mcp/0.1 public anonymous fetcher of USTC college notice "
        "listings; contact: local-user"
    )

    def __post_init__(self) -> None:
        keys: set[str] = set()
        for college in self.colleges:
            if not college.key or college.key in keys or len(college.key) > 64:
                raise ValueError("college keys must be unique and bounded")
            keys.add(college.key)
            base = urlsplit(college.base_url)
            listing = urlsplit(college.list_url)
            hostname = (base.hostname or "").casefold()
            if (
                base.scheme != "https"
                or not hostname.endswith(".ustc.edu.cn")
                or base.username is not None
                or base.password is not None
                or base.query
                or base.fragment
                or listing.scheme != "https"
                or (listing.hostname or "").casefold() != hostname
                or listing.username is not None
                or listing.password is not None
            ):
                raise ValueError("college sources must use matching HTTPS USTC hosts")
            if not college.list_path.startswith("/") or college.list_path.startswith("//"):
                raise ValueError("college list paths must be origin-relative")
        if not 0 <= self.request_delay <= 60 or not 1 <= self.timeout <= 120:
            raise ValueError("invalid request timing")

    @classmethod
    def from_args(
        cls,
        db_path: str | None = None,
        request_delay: float | None = None,
        timeout: float | None = None,
        colleges_json: str | None = None,
    ) -> AppConfig:
        colleges = DEFAULT_COLLEGES
        if colleges_json:
            loaded = json.loads(colleges_json)
            if not isinstance(loaded, list):
                raise ValueError("colleges_json must contain a list")
            if loaded:
                colleges = loaded
        return cls(
            db_path=Path(db_path or DEFAULT_DB_PATH),
            request_delay=1.0 if request_delay is None else request_delay,
            timeout=30.0 if timeout is None else timeout,
            colleges=tuple(College(**item) for item in colleges),
        )
