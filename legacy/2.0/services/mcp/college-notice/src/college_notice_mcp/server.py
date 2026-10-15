from __future__ import annotations

import argparse
import sys
from typing import Any
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .storage import CollegeNoticeStore

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
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".ustc.edu.cn")
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
        "notice_id": _bounded_text(value.get("notice_id"), 200),
        "college_key": _bounded_text(value.get("college_key"), 64),
        "title": _bounded_text(value.get("title"), 500),
        "published_at": _bounded_text(value.get("published_at"), 64),
        "summary": _bounded_text(value.get("content_text")),
        "source_url": _source_url(value.get("url")),
        "attachments": attachments,
        "observed_at": _bounded_text(value.get("fetched_at") or value.get("updated_at"), 64),
    }


def create_mcp(config: AppConfig) -> FastMCP:
    """Create the cache-only, model-safe college notice transport."""

    mcp = FastMCP("college-notice-mcp")
    store = CollegeNoticeStore(config.db_path)
    college_keys = frozenset(college.key for college in config.colleges)

    @mcp.tool()
    def college_notices_public_query(
        query: str,
        college_key: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search a bounded local cache of public USTC college notices.

        This tool never crawls or refreshes an upstream site. Cache updates are
        available only through the operator CLI.
        """

        query = query.strip()
        college_key = college_key.strip().casefold()
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError("query must contain at most 200 characters")
        if college_key and college_key not in college_keys:
            raise ValueError("unsupported college_key")
        if not 1 <= limit <= _MAX_RESULT_LIMIT:
            raise ValueError("limit must be between 1 and 20")
        values = (
            store.search(query, college_key=college_key or None, limit=limit)
            if query
            else store.list_notices(college_key=college_key or None, limit=limit)
        )
        items = [_public_item(item) for item in values]
        return {
            "schema_version": 1,
            "ok": store.stats()["notices_known"] > 0,
            "query": query,
            "college_key": college_key or None,
            "items": items,
            "returned": len(items),
            "source": "ustc-college-notices-cache",
            "source_url": None,
            "fetched_at": store.stats()["last_fetched_at"],
            "freshness_note": "数学、计算机、物理学院公开列表缓存；各条目附官网链接，非全校所有学院。",
        }

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the cache-only USTC college-notice MCP server over stdio."
    )
    parser.add_argument("--db-path", default=None, help="SQLite cache path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_mcp(AppConfig.from_args(db_path=args.db_path)).run()


if __name__ == "__main__":
    main(sys.argv[1:])
