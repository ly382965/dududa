from __future__ import annotations

from typing import Any

from .config import AppConfig
from .fetcher import CampusEventFetcher
from .parser import is_allowed_source_url, parse_event_detail, parse_event_list
from .storage import CampusEventStore


class CampusEventCrawler:
    def __init__(self, config: AppConfig, store: CampusEventStore | None = None):
        self.config = config
        self.store = store or CampusEventStore(config.db_path)
        self.fetcher = CampusEventFetcher(
            base_url=config.base_url,
            user_agent=config.user_agent,
            timeout=config.timeout,
            request_delay=config.request_delay,
        )

    def close(self) -> None:
        self.fetcher.close()

    def check_robots(self) -> dict[str, Any]:
        page = self.fetcher.fetch_robots()
        data = {"url": page.url, "status_code": page.status_code, "sha256": page.sha256, "text": page.text}
        self.store.set_meta("robots_txt", data)
        return data

    def crawl_lists(self, refresh: bool = False) -> dict[str, Any]:
        cached = self.store.get_meta("lists")
        if cached and not refresh:
            return {"ok": True, "cache_status": "hit", "categories": cached}

        summary: list[dict[str, Any]] = []
        for category, path in self.config.category_paths:
            page = self.fetcher.fetch_category(path)
            items = parse_event_list(page.text, self.config.base_url, category=category)
            for item in items:
                self.store.upsert_item(item)
            summary.append(
                {
                    "category": category,
                    "source_url": page.url,
                    "sha256": page.sha256,
                    "count": len(items),
                    "newest": items[0].to_dict() if items else None,
                }
            )

        self.store.set_meta("lists", summary)
        return {
            "ok": True,
            "cache_status": "miss" if cached is None else "refresh",
            "categories": summary,
        }

    def crawl_detail(self, event_id: str, refresh: bool = False) -> dict[str, Any]:
        cached = self.store.get_event(event_id)
        if cached and cached.get("fetched_at") and not refresh:
            return {"ok": True, "cache_status": "hit", "event": cached}

        url = cached["url"] if cached else None
        if url is None:
            return {"ok": False, "error": "event_url_unknown", "event_id": event_id}
        if not is_allowed_source_url(url, self.config.base_url):
            return {"ok": False, "error": "event_source_url_rejected", "event_id": event_id}

        page = self.fetcher.fetch_path(url)
        detail = parse_event_detail(
            page.text,
            self.config.base_url,
            event_id=event_id,
            url=url,
            source_hash=page.sha256,
        )
        self.store.upsert_detail(detail)
        stored = self.store.get_event(event_id)
        return {
            "ok": True,
            "cache_status": "miss",
            "event": stored,
            "source_url": page.url,
            "sha256": page.sha256,
        }
