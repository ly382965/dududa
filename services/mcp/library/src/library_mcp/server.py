from __future__ import annotations

import argparse
import sys
from typing import Any
from urllib.parse import urljoin, urlsplit

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .storage import LibraryStore

_MAX_QUERY_LENGTH = 120
_MAX_RESULT_LIMIT = 30


def _source_url(config: AppConfig) -> str:
    value = urljoin(config.base_url.rstrip("/") + "/", config.hours_path.lstrip("/"))
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "lib.ustc.edu.cn"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("invalid library source URL")
    return value


def _bounded_text(value: object, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _public_item(value: dict[str, Any]) -> dict[str, str | None]:
    return {
        "campus": _bounded_text(value.get("campus"), 32),
        "location": _bounded_text(value.get("location"), 240),
        "service": _bounded_text(value.get("service"), 500),
        "weekday": _bounded_text(value.get("weekday"), 160) or None,
        "weekend": _bounded_text(value.get("weekend"), 160) or None,
        "phone": _bounded_text(value.get("phone"), 80) or None,
    }


def create_mcp(config: AppConfig) -> FastMCP:
    """Create the cache-only, model-safe library-hours transport."""

    source_url = _source_url(config)
    mcp = FastMCP("library-mcp")
    store = LibraryStore(config.db_path)

    @mcp.tool()
    def library_hours_public_query(
        query: str,
        campus: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Query cached public USTC library opening hours without refreshing."""

        query = query.strip()
        campus = campus.strip()
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError("query must contain at most 120 characters")
        if len(campus) > 32:
            raise ValueError("campus must contain at most 32 characters")
        if not 1 <= limit <= _MAX_RESULT_LIMIT:
            raise ValueError("limit must be between 1 and 30")
        values = store.search(query, limit=100) if query else store.all_hours()
        if campus:
            values = [item for item in values if campus in str(item.get("campus") or "")]
        items = [_public_item(item) for item in values[:limit]]
        return {
            "schema_version": 1,
            "ok": store.stats()["hours_rows"] > 0,
            "query": query,
            "campus": campus or None,
            "items": items,
            "returned": len(items),
            "source": "ustc-library-opening-hours-cache",
            "source_url": source_url,
            "fetched_at": store.stats()["last_fetched_at"],
            "freshness_note": "官网日常开放时间，不代表假期、考试周或临时调整；请以最新专项公告为准。",
        }

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the cache-only USTC library-hours MCP server over stdio."
    )
    parser.add_argument("--db-path", default=None, help="SQLite cache path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_mcp(AppConfig.from_args(db_path=args.db_path)).run()


if __name__ == "__main__":
    main(sys.argv[1:])
