from __future__ import annotations

from typing import Any

from .config import AppConfig
from .fetcher import LibraryFetcher
from .parser import parse_opening_hours
from .storage import LibraryStore


class LibraryCrawler:
    def __init__(self, config: AppConfig, store: LibraryStore | None = None):
        self.config = config
        self.store = store or LibraryStore(config.db_path)
        self.fetcher = LibraryFetcher(
            base_url=config.base_url,
            user_agent=config.user_agent,
            timeout=config.timeout,
            request_delay=config.request_delay,
            hours_path=config.hours_path,
        )

    def close(self) -> None:
        self.fetcher.close()

    def check_robots(self) -> dict[str, Any]:
        page = self.fetcher.fetch_robots()
        data = {"url": page.url, "status_code": page.status_code, "sha256": page.sha256, "text": page.text}
        self.store.set_meta("robots_txt", data)
        return data

    def crawl_hours(self, refresh: bool = False) -> dict[str, Any]:
        cached = self.store.get_meta("hours")
        if cached and not refresh:
            return {"ok": True, "cache_status": "hit", **cached}

        page = self.fetcher.fetch_hours()
        rows = parse_opening_hours(page.text, self.config.base_url)
        if not rows:
            return {"ok": False, "error": "no_hours_table_found", "source_url": page.url}
        summary = self.store.replace_hours(rows, source_hash=page.sha256)
        self.store.set_meta("hours", {"source_url": page.url, "sha256": page.sha256, **summary})
        return {
            "ok": True,
            "cache_status": "miss" if cached is None else "refresh",
            "source_url": page.url,
            "sha256": page.sha256,
            **summary,
        }