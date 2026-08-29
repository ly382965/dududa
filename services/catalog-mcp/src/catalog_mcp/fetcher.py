from __future__ import annotations

import time
from typing import Any

import httpx

from .config import AppConfig


class CatalogFetcher:
    """Thin, polite HTTP client for catalog.ustc.edu.cn public open-data API."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._last = 0.0
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
            follow_redirects=True,
            headers={"User-Agent": "dududa-catalog-mcp/0.1 (public open-data)"},
        )

    def _throttle(self) -> None:
        delay = self.config.request_delay - (time.monotonic() - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._throttle()
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def post_json(self, path: str, body: dict[str, Any]) -> Any:
        self._throttle()
        resp = self._client.post(path, json=body)
        resp.raise_for_status()
        return resp.json()

    def semesters(self) -> list[dict[str, Any]]:
        data = self.get_json("/api/teach/semester/list")
        return sorted(data, key=lambda s: s.get("start") or "", reverse=True)

    def course_search(self, keyword: str) -> list[dict[str, Any]]:
        data = self.get_json("/api/teach/course/search", params={"keyword": keyword})
        return list(data or [])

    def lesson_list_for_teach(self, semester: int) -> list[dict[str, Any]]:
        data = self.get_json(f"/api/teach/lesson/list-for-teach/{int(semester)}")
        return list(data or [])

    def close(self) -> None:
        self._client.close()
