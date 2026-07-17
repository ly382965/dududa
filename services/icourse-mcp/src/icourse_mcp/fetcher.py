from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


COURSE_ID_RE = re.compile(r"/course/(\d+)/")


@dataclass
class FetchedPage:
    url: str
    status_code: int
    text: str
    sha256: str


class ICourseFetcher:
    def __init__(self, base_url: str, user_agent: str, timeout: float = 30.0, request_delay: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.request_delay = max(0.0, request_delay)
        self._last_request_at = 0.0
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

    def close(self) -> None:
        self.client.close()

    def _sleep_if_needed(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.request_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def fetch_path(self, path: str, params: dict[str, object] | None = None) -> FetchedPage:
        self._sleep_if_needed()
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        response = self.client.get(url, params=params)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        text = response.text
        return FetchedPage(
            url=str(response.url),
            status_code=response.status_code,
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        )

    def fetch_robots(self) -> FetchedPage:
        return self.fetch_path("/robots.txt")

    def fetch_course_list(self, page: int = 1, per_page: int = 50, sort_by: str | None = None) -> FetchedPage:
        params: dict[str, object] = {"page": page, "per_page": per_page}
        if sort_by:
            params["sort_by"] = sort_by
        return self.fetch_path("/course/", params=params)

    def fetch_search_token(self) -> str:
        self._sleep_if_needed()
        url = urljoin(self.base_url + "/", "/api/search/token".lstrip("/"))
        response = self.client.post(
            url,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        data = response.json()
        token = data.get("token")
        if not data.get("ok") or not token:
            raise RuntimeError("icourse search token unavailable")
        return str(token)

    def fetch_course_search(self, query: str, page: int = 1) -> FetchedPage:
        token = self.fetch_search_token()
        return self.fetch_path("/search/", params={"q": query, "token": token, "page": page})

    def fetch_course_detail(self, course_id: int, sort_by: str = "upvote") -> FetchedPage:
        return self.fetch_path(f"/course/{course_id}/", params={"sort_by": sort_by})

    def fetch_latest_reviews(self, page: int = 1, per_page: int = 10) -> FetchedPage:
        return self.fetch_path("/latest_reviews", params={"page": page, "per_page": per_page})

    @staticmethod
    def extract_course_ids(html: str) -> list[int]:
        ids: list[int] = []
        seen: set[int] = set()
        for match in COURSE_ID_RE.finditer(html):
            course_id = int(match.group(1))
            if course_id not in seen:
                seen.add(course_id)
                ids.append(course_id)
        return ids
