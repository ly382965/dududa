from __future__ import annotations

import argparse
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import CampusEventCrawler
from .storage import CampusEventStore


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("campus-events-mcp")
    store = CampusEventStore(config.db_path)

    def new_crawler() -> CampusEventCrawler:
        return CampusEventCrawler(config, store=store)

    @mcp.tool()
    def event_stats() -> dict[str, Any]:
        """Return local cache statistics for USTC public campus notice aggregates."""
        return store.stats()

    @mcp.tool()
    def list_categories() -> dict[str, Any]:
        """List the school-notice aggregate categories this service tracks."""
        return {
            "schema_version": 1,
            "ok": True,
            "categories": [
                {"category": category, "source_path": path} for category, path in config.category_paths
            ],
        }

    @mcp.tool()
    def refresh_lists(only_refresh: bool = False) -> dict[str, Any]:
        """Re-fetch the public notice aggregate pages (teaching/research/admin)."""
        crawler = new_crawler()
        try:
            return crawler.crawl_lists(refresh=only_refresh)
        finally:
            crawler.close()

    @mcp.tool()
    def get_events(category: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Get the newest public campus notices from the cache; category may be 教学/科研/管理."""
        limit = max(1, min(limit, 100))
        events = store.list_events(category=category, limit=limit)
        return {
            "schema_version": 1,
            "ok": True,
            "cache_status": "hit",
            "category": category,
            "events": events,
            "public_only": True,
        }

    @mcp.tool()
    def get_event_detail(event_id: str, refresh: bool = False) -> dict[str, Any]:
        """Fetch (or read cached) full text of one school notice by id like '1360/25272'."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_detail(event_id, refresh=refresh)
            if not result.get("ok"):
                return {"schema_version": 1, **result}
            event = result["event"]
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": result.get("cache_status", "unknown"),
                "event": {
                    k: event.get(k)
                    for k in ("event_id", "category", "title", "url", "published_at", "content_text", "attachments")
                },
                "public_only": True,
            }
        finally:
            crawler.close()

    @mcp.tool()
    def search_events(query: str, category: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Search cached public campus notices by keyword across title and body."""
        query = query.strip()
        if not query:
            return {"schema_version": 1, "ok": False, "error": "empty_query", "events": []}
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "category": category,
            "events": store.search(query, category=category, limit=limit),
            "public_only": True,
        }

    @mcp.tool()
    def check_robots() -> dict[str, Any]:
        """Fetch and cache robots.txt from ustc.edu.cn for audit purposes."""
        crawler = new_crawler()
        try:
            return crawler.check_robots()
        finally:
            crawler.close()

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the USTC campus events MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--base-url", default=None, help="Base URL.")
    parser.add_argument("--request-delay", type=float, default=None, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    mcp = create_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])