from __future__ import annotations

from typing import Any

from .config import AppConfig
from .fetcher import TrainingPlanFetcher
from .parser import parse_overview
from .storage import TrainingPlanStore


class TrainingPlanCrawler:
    def __init__(self, config: AppConfig, store: TrainingPlanStore | None = None):
        self.config = config
        self.store = store or TrainingPlanStore(config.db_path)
        self.fetcher = TrainingPlanFetcher(
            base_url=config.base_url,
            user_agent=config.user_agent,
            timeout=config.timeout,
            request_delay=config.request_delay,
            page_path=config.page_path,
        )

    def close(self) -> None:
        self.fetcher.close()

    def check_robots(self) -> dict[str, Any]:
        page = self.fetcher.fetch_robots()
        data = {"url": page.url, "status_code": page.status_code, "sha256": page.sha256, "text": page.text}
        self._set_meta("robots_txt", data)
        return data

    def crawl_overview(self, refresh: bool = False) -> dict[str, Any]:
        meta = self.store.get_meta("overview")
        cached_years = self.store.list_years()
        if cached_years and not refresh:
            return {"ok": True, "cache_status": "hit", "years": cached_years}

        page = self.fetcher.fetch_overview()
        years, rows = parse_overview(page.text, self.config.base_url, source_hash=page.sha256)
        if not years or not rows:
            return {"ok": False, "error": "no_plan_tables_found", "source_url": page.url}
        summary = self.store.replace_all(years, rows, source_hash=page.sha256)
        self._set_meta("overview", {"latest_year": max(y.year for y in years), "sha256": page.sha256})
        self._set_meta("overview_source", {"url": page.url, "sha256": page.sha256})
        return {
            "ok": True,
            "cache_status": "miss" if meta is None else "refresh",
            "source_url": page.url,
            "sha256": page.sha256,
            **summary,
        }

    def _set_meta(self, key: str, value: Any) -> None:
        import json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), now),
            )
