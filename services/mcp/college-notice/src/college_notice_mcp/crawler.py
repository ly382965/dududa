from __future__ import annotations

from typing import Any

from .config import AppConfig
from .fetcher import CollegeNoticeFetcher
from .parser import is_allowed_source_url, parse_notice_detail, parse_notice_list
from .storage import CollegeNoticeStore


class CollegeNoticeCrawler:
    def __init__(self, config: AppConfig, store: CollegeNoticeStore | None = None):
        self.config = config
        self.store = store or CollegeNoticeStore(config.db_path)
        self.fetcher = CollegeNoticeFetcher(
            user_agent=config.user_agent,
            timeout=config.timeout,
            request_delay=config.request_delay,
        )

    def close(self) -> None:
        self.fetcher.close()

    def check_robots(self, college_key: str | None = None) -> dict[str, Any]:
        targets = [c for c in self.config.colleges if college_key is None or c.key == college_key]
        results: dict[str, Any] = {}
        for college in targets:
            page = self.fetcher.fetch_robots(college.base_url)
            results[college.key] = {
                "url": page.url,
                "status_code": page.status_code,
                "sha256": page.sha256,
                "text": page.text,
            }
        self.store.set_meta("robots_txt", results)
        return results

    def crawl_lists(self, college_key: str | None = None, refresh: bool = False) -> dict[str, Any]:
        cached = self.store.get_meta("lists")
        if cached and not refresh:
            return {"ok": True, "cache_status": "hit", "colleges": cached}

        targets = [c for c in self.config.colleges if college_key is None or c.key == college_key]
        if not targets:
            return {"ok": False, "error": "college_not_found", "known": [c.key for c in self.config.colleges]}

        summary: list[dict[str, Any]] = []
        for college in targets:
            page = self.fetcher.fetch_list(college.list_url)
            items = parse_notice_list(page.text, college)
            for item in items:
                self.store.upsert_item(item)
            summary.append(
                {
                    "college_key": college.key,
                    "college_name": college.name,
                    "list_url": page.url,
                    "sha256": page.sha256,
                    "count": len(items),
                    "newest": items[0].to_dict() if items else None,
                }
            )

        self.store.set_meta("lists", summary)
        return {
            "ok": True,
            "cache_status": "miss" if cached is None else "refresh",
            "colleges": summary,
        }

    def crawl_detail(self, notice_id: str, refresh: bool = False) -> dict[str, Any]:
        cached = self.store.get_notice(notice_id)
        if cached and cached.get("fetched_at") and not refresh:
            return {"ok": True, "cache_status": "hit", "notice": cached}

        college = self._find_college_for_notice(cached, notice_id)
        if college is None:
            return {"ok": False, "error": "notice_unknown", "hint": "Run crawl_lists first."}

        url = cached["url"] if cached else None
        if url is None:
            return {"ok": False, "error": "notice_url_unknown", "notice_id": notice_id}
        if not is_allowed_source_url(url, college.base_url):
            return {"ok": False, "error": "notice_source_url_rejected", "notice_id": notice_id}

        page = self.fetcher.fetch_url(url)
        detail = parse_notice_detail(
            page.text,
            college,
            notice_id=notice_id,
            url=url,
            source_hash=page.sha256,
        )
        self.store.upsert_detail(detail)
        stored = self.store.get_notice(notice_id)
        return {
            "ok": True,
            "cache_status": "miss",
            "notice": stored,
            "source_url": page.url,
            "sha256": page.sha256,
        }

    def _find_college_for_notice(
        self, cached: dict[str, Any] | None, notice_id: str
    ) -> Any:
        if cached and cached.get("college_key"):
            for college in self.config.colleges:
                if college.key == cached["college_key"]:
                    return college
        for college in self.config.colleges:
            if notice_id.startswith(college.key):
                return college
        return None
