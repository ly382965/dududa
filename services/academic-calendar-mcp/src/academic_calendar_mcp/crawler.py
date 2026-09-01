from __future__ import annotations

from typing import Any

from .config import AppConfig
from .fetcher import AcademicCalendarFetcher
from .parser import parse_listing, parse_term_detail
from .storage import CalendarStore


class CalendarCrawler:
    def __init__(self, config: AppConfig, store: CalendarStore | None = None):
        self.config = config
        self.store = store or CalendarStore(config.db_path)
        self.fetcher = AcademicCalendarFetcher(
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

    def crawl_listing(self, refresh: bool = False) -> dict[str, Any]:
        cached = self.store.get_meta("listing")
        if cached and not refresh:
            return {"ok": True, "cache_status": "hit", "terms": cached}

        page = self.fetcher.fetch_listing()
        listings = parse_listing(page.text, self.config.base_url)
        for listing in listings:
            self.store.upsert_term_listing(listing)
        payload = [listing.to_dict() for listing in listings]
        self.store.set_meta("listing", payload)
        self.store.set_meta("listing_source_hash", page.sha256)
        return {
            "ok": True,
            "cache_status": "miss" if cached is None else "refresh",
            "terms": payload,
            "source_url": page.url,
            "sha256": page.sha256,
        }

    def resolve_term_id(self, name_or_id: str | int | None) -> int | None:
        if name_or_id is not None:
            text = str(name_or_id)
            if text.isdigit():
                return int(text)
            term = self.store.get_term(text)
            if term:
                return term["id"]
        listing = self.store.get_meta("listing") or []
        if not listing:
            self.crawl_listing()
            listing = self.store.get_meta("listing") or []
        if not listing:
            return None
        if name_or_id is not None:
            for item in listing:
                if item["name"] == str(name_or_id):
                    return item["term_id"]
            return None
        return int(listing[0]["term_id"])

    def crawl_term(self, name_or_id: str | int | None = None, refresh: bool = False) -> dict[str, Any]:
        term_id = self.resolve_term_id(name_or_id)
        if term_id is None:
            return {
                "ok": False,
                "error": "term_not_found",
                "hint": "Call refresh listing first or pass an existing term name/id.",
                "cache_status": "unknown",
            }

        cached_term = self.store.get_term(term_id)
        if cached_term and cached_term.get("fetched_at") and not refresh:
            return {
                "ok": True,
                "cache_status": "hit",
                "term": self._summary(cached_term),
            }

        page = self.fetcher.fetch_term_detail(term_id)
        term = parse_term_detail(page.text, self.config.base_url, source_hash=page.sha256)
        published_at = None
        cached_term = self.store.get_term(term_id)
        if cached_term:
            published_at = cached_term.get("published_at")
        self.store.upsert_term(term, source_hash=page.sha256, published_at=published_at)
        stored = self.store.get_term(term_id)
        return {
            "ok": True,
            "cache_status": "miss",
            "term": self._summary(stored) if stored else term.to_dict(),
            "source_url": page.url,
            "sha256": page.sha256,
        }

    def list_cached(self) -> dict[str, Any]:
        terms = self.store.list_terms()
        listing = self.store.get_meta("listing") or []
        latest = listing[0] if listing else None
        return {
            "ok": True,
            "cache_status": "hit",
            "terms": terms,
            "latest_listing": latest,
        }

    def _summary(self, term: dict[str, Any] | None) -> dict[str, Any]:
        if not term:
            return {"term_id": None}
        return {
            "term_id": term["id"],
            "name": term["name"],
            "url": term["url"],
            "published_at": term.get("published_at"),
            "notes": term.get("notes", []),
            "event_count": len(term.get("events", [])),
        }