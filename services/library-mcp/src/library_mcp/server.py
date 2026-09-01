from __future__ import annotations

import argparse
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import LibraryCrawler
from .storage import LibraryStore


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("library-mcp")
    store = LibraryStore(config.db_path)

    def new_crawler() -> LibraryCrawler:
        return LibraryCrawler(config, store=store)

    @mcp.tool()
    def library_stats() -> dict[str, Any]:
        """Return local cache statistics for USTC library public opening hours."""
        return store.stats()

    @mcp.tool()
    def get_opening_hours(campus: str | None = None) -> dict[str, Any]:
        """Return USTC library opening hours from the local cache, optionally filtered by campus (e.g. 东区/西区/高新区)."""
        if campus:
            rows = store.by_campus(campus)
        else:
            rows = store.all_hours()
        return {
            "schema_version": 1,
            "ok": True,
            "campus": campus,
            "rows": rows,
            "public_only": True,
        }

    @mcp.tool()
    def search_hours(query: str, limit: int = 20) -> dict[str, Any]:
        """Search library opening hours by service/location keyword, e.g. 自习室, 服务台."""
        query = query.strip()
        if not query:
            return {"schema_version": 1, "ok": False, "error": "empty_query", "rows": []}
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "rows": store.search(query, limit=limit),
            "public_only": True,
        }

    @mcp.tool()
    def refresh_hours() -> dict[str, Any]:
        """Re-fetch the public library opening hours page and update the cache."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_hours(refresh=True)
            return {"schema_version": 1, **result, "public_only": True}
        finally:
            crawler.close()

    @mcp.tool()
    def check_robots() -> dict[str, Any]:
        """Fetch and cache robots.txt from lib.ustc.edu.cn for audit purposes."""
        crawler = new_crawler()
        try:
            return crawler.check_robots()
        finally:
            crawler.close()

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the USTC library MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--base-url", default=None, help="Base URL.")
    parser.add_argument("--hours-path", default=None, help="Path of the opening hours page.")
    parser.add_argument("--request-delay", type=float, default=None, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        hours_path=args.hours_path,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    mcp = create_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])