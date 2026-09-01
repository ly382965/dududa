from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "https://notifai-api.enthusjast.cc/api"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_ITEMS = 100


def normalize_base_url(value: str) -> str:
    """Validate and normalize a configured API base URL."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("base URL must be a non-empty string")
    url = value.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("base URL must use http or https and include a host")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("base URL must not contain credentials, query parameters, or fragments")
    return url


@dataclass(frozen=True)
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_items: int = DEFAULT_MAX_ITEMS

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        if not 1 <= float(self.timeout) <= 120:
            raise ValueError("timeout must be between 1 and 120 seconds")
        if not 1 <= int(self.max_items) <= 500:
            raise ValueError("max_items must be between 1 and 500")
        object.__setattr__(self, "timeout", float(self.timeout))
        object.__setattr__(self, "max_items", int(self.max_items))

    @classmethod
    def from_args(
        cls,
        base_url: str | None = None,
        timeout: float | None = None,
        max_items: int | None = None,
    ) -> AppConfig:
        configured_timeout = os.environ.get("NOTIFAI_API_TIMEOUT_SECONDS")
        if timeout is None and configured_timeout:
            timeout = float(configured_timeout)
        configured_max_items = os.environ.get("NOTIFAI_MAX_ITEMS")
        if max_items is None and configured_max_items:
            max_items = int(configured_max_items)
        return cls(
            base_url=base_url or os.environ.get("NOTIFAI_API_BASE_URL", DEFAULT_BASE_URL),
            timeout=DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout,
            max_items=DEFAULT_MAX_ITEMS if max_items is None else max_items,
        )
