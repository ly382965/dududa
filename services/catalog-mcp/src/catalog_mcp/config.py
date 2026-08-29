from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    base_url: str = "https://catalog.ustc.edu.cn"
    db_path: Path = Path("data/catalog.sqlite3")
    timeout: float = 30.0
    request_delay: float = 0.5

    @classmethod
    def from_args(
        cls,
        db_path: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        request_delay: float | None = None,
    ) -> "AppConfig":
        return cls(
            db_path=Path(db_path) if db_path else Path("data/catalog.sqlite3"),
            base_url=base_url or "https://catalog.ustc.edu.cn",
            timeout=timeout if timeout is not None else 30.0,
            request_delay=request_delay if request_delay is not None else 0.5,
        )
