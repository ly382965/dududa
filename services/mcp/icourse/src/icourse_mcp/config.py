from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://icourse.club"
DEFAULT_DB_PATH = Path("data") / "icourse.sqlite3"


@dataclass(frozen=True)
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    db_path: Path = DEFAULT_DB_PATH
    request_delay: float = 1.0
    timeout: float = 30.0
    user_agent: str = (
        "icourse-mcp/0.1 (+https://icourse.club public anonymous fetcher; "
        "contact: local-user)"
    )

    @classmethod
    def from_args(
        cls,
        db_path: str | None = None,
        base_url: str | None = None,
        request_delay: float | None = None,
        timeout: float | None = None,
    ) -> "AppConfig":
        return cls(
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            db_path=Path(db_path or DEFAULT_DB_PATH),
            request_delay=1.0 if request_delay is None else request_delay,
            timeout=30.0 if timeout is None else timeout,
        )
