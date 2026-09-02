from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


@dataclass
class FetchedPage:
    url: str
    status_code: int
    text: str
    sha256: str


class LibraryFetcher:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout: float = 30.0,
        request_delay: float = 1.0,
        hours_path: str = "/?p=5916",
    ):
        self.base_url = base_url.rstrip("/")
        self.hours_path = hours_path
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

    def fetch_path(self, path: str) -> FetchedPage:
        self._sleep_if_needed()
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        response = self.client.get(url)
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

    def fetch_hours(self) -> FetchedPage:
        return self.fetch_path(self.hours_path)