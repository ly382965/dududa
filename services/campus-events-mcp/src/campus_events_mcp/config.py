from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://www.ustc.edu.cn"
DEFAULT_HOME_PATH = "/tzgg.htm"
DEFAULT_DB_PATH = Path("data") / "campus-events.sqlite3"

# 学校主页"通知公告"栏目聚合页：首页（综合）与三类子栏目
DEFAULT_CATEGORY_PATHS: dict[str, str] = {
    "综合": "/tzgg.htm",
    "教学": "/tzgg/jxltz.htm",
    "科研": "/tzgg/kyltz.htm",
    "管理": "/tzgg/glltz.htm",
}


@dataclass(frozen=True)
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    db_path: Path = DEFAULT_DB_PATH
    request_delay: float = 1.0
    timeout: float = 30.0
    home_path: str = DEFAULT_HOME_PATH
    category_paths: tuple[tuple[str, str], ...] = field(
        default_factory=lambda: tuple(sorted(DEFAULT_CATEGORY_PATHS.items()))
    )
    user_agent: str = (
        "campus-events-mcp/0.1 (+https://www.ustc.edu.cn/tzgg.htm "
        "public anonymous fetcher; contact: local-user)"
    )

    @classmethod
    def from_args(
        cls,
        db_path: str | None = None,
        base_url: str | None = None,
        home_path: str | None = None,
        request_delay: float | None = None,
        timeout: float | None = None,
    ) -> "AppConfig":
        return cls(
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            db_path=Path(db_path or DEFAULT_DB_PATH),
            home_path=home_path or DEFAULT_HOME_PATH,
            request_delay=1.0 if request_delay is None else request_delay,
            timeout=30.0 if timeout is None else timeout,
        )