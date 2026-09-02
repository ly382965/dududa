from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://lib.ustc.edu.cn"
DEFAULT_HOURS_PATH = "/?p=5916"
DEFAULT_DB_PATH = Path("data") / "library.sqlite3"


@dataclass(frozen=True)
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    hours_path: str = DEFAULT_HOURS_PATH
    db_path: Path = DEFAULT_DB_PATH
    request_delay: float = 1.0
    timeout: float = 30.0
    user_agent: str = (
        "library-mcp/0.1 (+https://lib.ustc.edu.cn/?p=5916 public anonymous fetcher; contact: local-user)"
    )

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "lib.ustc.edu.cn"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be the HTTPS USTC library origin")
        if not self.hours_path.startswith("/") or self.hours_path.startswith("//"):
            raise ValueError("hours_path must be origin-relative")
        if not 0 <= self.request_delay <= 60 or not 1 <= self.timeout <= 120:
            raise ValueError("invalid request timing")

    @classmethod
    def from_args(
        cls,
        db_path: str | None = None,
        base_url: str | None = None,
        hours_path: str | None = None,
        request_delay: float | None = None,
        timeout: float | None = None,
    ) -> AppConfig:
        return cls(
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            hours_path=hours_path or DEFAULT_HOURS_PATH,
            db_path=Path(db_path or DEFAULT_DB_PATH),
            request_delay=1.0 if request_delay is None else request_delay,
            timeout=30.0 if timeout is None else timeout,
        )
