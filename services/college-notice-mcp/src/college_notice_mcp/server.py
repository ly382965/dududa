from __future__ import annotations

import argparse
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import CollegeNoticeCrawler
from .storage import CollegeNoticeStore


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("college-notice-mcp")
    store = CollegeNoticeStore(config.db_path)

    def new_crawler() -> CollegeNoticeCrawler:
        return CollegeNoticeCrawler(config, store=store)

    @mcp.tool()
    def college_notice_stats() -> dict[str, Any]:
        """Return local cache statistics for USTC college public notice data."""
        return store.stats()

    @mcp.tool()
    def list_colleges() -> dict[str, Any]:
        """List configured USTC college notice sources."""
        return {
            "schema_version": 1,
            "ok": True,
            "colleges": [college.to_dict() for college in config.colleges],
        }

    @mcp.tool()
    def refresh_lists(college_key: str | None = None) -> dict[str, Any]:
        """Re-fetch the public notice listing pages for all (or one) college."""
        crawler = new_crawler()
        try:
            return crawler.crawl_lists(college_key=college_key, refresh=True)
        finally:
            crawler.close()

    @mcp.tool()
    def get_notices(college_key: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Get the newest public college notices from the local cache."""
        limit = max(1, min(limit, 100))
        notices = store.list_notices(college_key=college_key, limit=limit)
        return {
            "schema_version": 1,
            "ok": True,
            "cache_status": "hit",
            "college_key": college_key,
            "notices": notices,
            "public_only": True,
        }

    @mcp.tool()
    def get_notice_detail(notice_id: str, refresh: bool = False) -> dict[str, Any]:
        """Fetch (or read cached) full text of one college notice by its id."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_detail(notice_id, refresh=refresh)
            if not result.get("ok"):
                return {"schema_version": 1, **result}
            notice = result["notice"]
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": result.get("cache_status", "unknown"),
                "notice": {
                    k: notice.get(k)
                    for k in ("notice_id", "college_key", "title", "url", "published_at", "content_text", "attachments")
                },
                "public_only": True,
            }
        finally:
            crawler.close()

    @mcp.tool()
    def search_notices(query: str, college_key: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search cached public college notices by keyword across title and body."""
        query = query.strip()
        if not query:
            return {"schema_version": 1, "ok": False, "error": "empty_query", "notices": []}
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "college_key": college_key,
            "notices": store.search(query, college_key=college_key, limit=limit),
            "public_only": True,
        }

    @mcp.tool()
    def check_robots(college_key: str | None = None) -> dict[str, Any]:
        """Fetch and cache robots.txt from the configured college sites for audit."""
        crawler = new_crawler()
        try:
            return crawler.check_robots(college_key=college_key)
        finally:
            crawler.close()

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the USTC college notice MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--request-delay", type=float, default=None, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds.")
    parser.add_argument("--colleges-json", default=None, help='JSON list of college source configs, e.g. [{"key":"math",...}]')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        request_delay=args.request_delay,
        timeout=args.timeout,
        colleges_json=args.colleges_json,
    )
    mcp = create_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])
