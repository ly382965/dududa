from __future__ import annotations

import argparse
import sys
from typing import Any
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .storage import CampusEventStore

_ALLOWED_SOURCE_HOST = "www.ustc.edu.cn"
_CATEGORIES = frozenset({"综合", "教学", "科研", "管理"})
_MAX_QUERY_LENGTH = 200
_MAX_RESULT_LIMIT = 20
_MAX_TEXT_LENGTH = 1_600
_MAX_URL_LENGTH = 2_048


def _bounded_text(value: object, maximum: int = _MAX_TEXT_LENGTH) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _source_url(value: object) -> str:
    text = str(value or "").strip()
    if len(text) > _MAX_URL_LENGTH:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or parsed.hostname != _ALLOWED_SOURCE_HOST
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return text


def _public_item(value: dict[str, Any]) -> dict[str, Any]:
    attachments: list[dict[str, str]] = []
    for raw in value.get("attachments") or ():
        if not isinstance(raw, dict):
            continue
        url = _source_url(raw.get("url"))
        if url:
            attachments.append(
                {"name": _bounded_text(raw.get("name"), 240), "url": url}
            )
        if len(attachments) >= 10:
            break
    return {
        "event_id": _bounded_text(value.get("event_id"), 160),
        "category": _bounded_text(value.get("category"), 32),
        "title": _bounded_text(value.get("title"), 500),
        "published_at": _bounded_text(value.get("published_at"), 64),
        "summary": _bounded_text(value.get("content_text")),
        "source_url": _source_url(value.get("url")),
        "attachments": attachments,
        "observed_at": _bounded_text(value.get("fetched_at"), 64),
    }


def create_mcp(config: AppConfig) -> FastMCP:
    """Create the cache-only, model-safe campus events transport."""

    mcp = FastMCP("campus-events-mcp")
    store = CampusEventStore(config.db_path)

    @mcp.tool()
    def campus_events_public_query(
        query: str,
        category: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search the bounded local cache of public USTC homepage notices.

        This tool never refreshes the cache. Cache updates remain an operator CLI
        action and are not exposed over MCP.
        """

        query = query.strip()
        category = category.strip()
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError("query must contain at most 200 characters")
        if category and category not in _CATEGORIES:
            raise ValueError("unsupported category")
        if not 1 <= limit <= _MAX_RESULT_LIMIT:
            raise ValueError("limit must be between 1 and 20")
        values = (
            store.search(query, category=category or None, limit=limit)
            if query
            else store.list_events(category=category or None, limit=limit)
        )
        items = [_public_item(item) for item in values]
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "category": category or None,
            "items": items,
            "returned": len(items),
            "source": "ustc-homepage-notices-cache",
        }

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the cache-only USTC campus-events MCP server over stdio."
    )
    parser.add_argument("--db-path", default=None, help="SQLite cache path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_mcp(AppConfig.from_args(db_path=args.db_path)).run()


if __name__ == "__main__":
    main(sys.argv[1:])
