from __future__ import annotations

from typing import Any

from .config import AppConfig
from .fetcher import UstcNoticeFetcher
from .parser import parse_notice_detail, parse_notice_list
from .storage import NoticeStore


class NoticeCrawler:
    def __init__(self, config: AppConfig, store: NoticeStore | None = None):
        self.config = config
        self.store = store or NoticeStore(config.db_path)
        self.fetcher = UstcNoticeFetcher(
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

    def crawl_list(self, refresh: bool = False, max_pages: int = 1) -> dict[str, Any]:
        cached = self.store.get_meta("list")
        if cached and not refresh:
            return {"ok": True, "cache_status": "hit", "notices": cached}

        pages_fetched = 0
        total_items: list[dict[str, Any]] = []
        last_sha = ""
        for page in range(1, max(max_pages, 1) + 1):
            page_obj = self.fetcher.fetch_notice_list_page(page)
            items = parse_notice_list(page_obj.text, self.config.base_url)
            pages_fetched += 1
            last_sha = page_obj.sha256
            for item in items:
                self.store.upsert_notice(item)
            payload = [item.to_dict() for item in items]
            total_items.extend(payload)
            # 只有首页有 next 链接时继续抓下一页；抓不满 max_pages 就停
            if page >= 1:
                import re
                if not re.search(
                    r'class="[^"]*next[^"]*"[^>]*href="[^"]*page/(\d+)"',
                    page_obj.text,
                ):
                    break
            if len(items) == 0:
                break

        self.store.set_meta("list", total_items)
        self.store.set_meta("list_source_hash", last_sha)
        return {
            "ok": True,
            "cache_status": "miss" if cached is None else "refresh",
            "notices": total_items,
            "pages_fetched": pages_fetched,
            "source_url": self.fetcher.fetch_notice_list_page(1).url,
            "sha256": last_sha,
        }

    def crawl_detail(self, notice_id: int, refresh: bool = False) -> dict[str, Any]:
        cached = self.store.get_notice(notice_id)
        if cached and cached.get("fetched_at") and not refresh:
            return {
                "ok": True,
                "cache_status": "hit",
                "notice": self._summary(cached),
            }

        page = self.fetcher.fetch_notice_detail(notice_id)
        detail = parse_notice_detail(page.text, self.config.base_url, source_hash=page.sha256)
        if detail is None:
            return {"ok": False, "error": "notice_not_found", "notice_id": notice_id, "cache_status": "unknown"}
        self.store.upsert_notice_detail(detail)
        stored = self.store.get_notice(notice_id)
        return {
            "ok": True,
            "cache_status": "miss",
            "notice": self._summary(stored) if stored else detail.to_dict(),
            "source_url": page.url,
            "sha256": page.sha256,
        }

    def _summary(self, notice: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": notice["id"],
            "title": notice["title"],
            "url": notice["url"],
            "published_at": notice.get("published_at"),
            "last_modified": notice.get("last_modified"),
            "category": notice.get("category"),
            "content_text": notice.get("content_text", ""),
            "attachments": notice.get("attachments", []),
        }