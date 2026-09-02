from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://www.teach.ustc.edu.cn"
DEFAULT_PAGE_PATH = "/education/239.html"
DEFAULT_DB_PATH = Path("data") / "training-plan.sqlite3"


@dataclass(frozen=True)
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    page_path: str = DEFAULT_PAGE_PATH
    db_path: Path = DEFAULT_DB_PATH
    request_delay: float = 1.0
    timeout: float = 30.0
    user_agent: str = (
        "training-plan-mcp/0.1 (+https://www.teach.ustc.edu.cn/education/239.html "
        "public anonymous fetcher; contact: local-user)"
    )

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.teach.ustc.edu.cn"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be the HTTPS USTC teaching origin")
        if not self.page_path.startswith("/") or self.page_path.startswith("//"):
            raise ValueError("page_path must be origin-relative")
        if not 0 <= self.request_delay <= 60 or not 1 <= self.timeout <= 120:
            raise ValueError("invalid request timing")

    @classmethod
    def from_args(
        cls,
        db_path: str | None = None,
        base_url: str | None = None,
        page_path: str | None = None,
        request_delay: float | None = None,
        timeout: float | None = None,
    ) -> AppConfig:
        return cls(
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            page_path=page_path or DEFAULT_PAGE_PATH,
            db_path=Path(db_path or DEFAULT_DB_PATH),
            request_delay=1.0 if request_delay is None else request_delay,
            timeout=30.0 if timeout is None else timeout,
        )
