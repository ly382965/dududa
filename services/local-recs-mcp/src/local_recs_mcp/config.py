from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB_PATH = Path("data") / "local-recs.sqlite3"


@dataclass(frozen=True)
class AppConfig:
    db_path: Path = DEFAULT_DB_PATH
    user_agent: str = (
        "local-recs-mcp/0.1 (personal USTC campus recommendation fetcher; contact: local-user)"
    )

    @classmethod
    def from_args(
        cls,
        db_path: str | None = None,
    ) -> "AppConfig":
        return cls(db_path=Path(db_path or DEFAULT_DB_PATH))