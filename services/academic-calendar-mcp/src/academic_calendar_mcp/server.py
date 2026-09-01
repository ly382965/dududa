from __future__ import annotations

import argparse
import datetime
import re
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import CalendarCrawler
from .storage import CalendarStore


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("academic-calendar-mcp")
    store = CalendarStore(config.db_path)

    def new_crawler() -> CalendarCrawler:
        return CalendarCrawler(config, store=store)

    def _valid_date(value: str | None) -> str:
        if value is None or value == "today":
            return datetime.date.today().isoformat()
        if not DATE_RE.match(value):
            raise ValueError("date must be YYYY-MM-DD or 'today'")
        return value

    @mcp.tool()
    def calendar_stats() -> dict[str, Any]:
        """Return local cache statistics for USTC public academic calendar data."""
        return store.stats()

    @mcp.tool()
    def list_terms(refresh: bool = False) -> dict[str, Any]:
        """List known academic terms. Set refresh=true to re-fetch the public calendar listing."""
        crawler = new_crawler()
        try:
            if refresh:
                crawler.crawl_listing(refresh=True)
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": "hit",
                "terms": crawler.list_cached()["terms"],
                "public_only": True,
            }
        finally:
            crawler.close()

    @mcp.tool()
    def get_term(term_name: str, refresh: bool = False) -> dict[str, Any]:
        """Get the full public academic calendar for one term, e.g. '2026年秋季学期'."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_term(term_name, refresh=refresh)
            if not result.get("ok"):
                return result
            term = store.get_term(result["term"]["term_id"])
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": result.get("cache_status", "unknown"),
                "term": term,
                "public_only": True,
                "source_refs": [
                    {
                        "source": "https://www.teach.ustc.edu.cn/calendar",
                        "observed_at": term["updated_at"] if term else None,
                    }
                ],
            }
        finally:
            crawler.close()

    @mcp.tool()
    def get_current_term(refresh: bool = False) -> dict[str, Any]:
        """Return the term in progress today, plus today's scheduled events if any."""
        crawler = new_crawler()
        try:
            if refresh:
                crawler.crawl_listing(refresh=True)
                crawler.crawl_term(refresh=True)
            today = datetime.date.today().isoformat()
            term = store.get_current_term(today)
            if not term:
                return {
                    "schema_version": 1,
                    "ok": False,
                    "error": "term_not_in_cache",
                    "hint": "Run list_terms(refresh=true) and get_term for the current term first.",
                    "today": today,
                }
            events_today = [item for item in term["events"] if item["date"] == today]
            weeks = sorted({item["week_label"] for item in term["events"] if item["week_label"]})
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": "hit",
                "today": today,
                "term_name": term["name"],
                "term_url": term["url"],
                "notes": term["notes"],
                "events_today": events_today,
                "week_labels": weeks,
                "public_only": True,
            }
        finally:
            crawler.close()

    @mcp.tool()
    def get_events(date: str = "today") -> dict[str, Any]:
        """Get scheduled public events on a specific date across cached terms."""
        target = _valid_date(date)
        events = store.get_events_on(target)
        return {
            "schema_version": 1,
            "ok": True,
            "date": target,
            "events": events,
            "public_only": True,
        }

    @mcp.tool()
    def search_events(query: str, limit: int = 20) -> dict[str, Any]:
        """Search cached public calendar events by keyword, e.g. 开学, 假期, 考试."""
        query = query.strip()
        if not query:
            return {"schema_version": 1, "ok": False, "error": "empty_query", "events": []}
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "events": store.search_events(query, limit=limit),
            "public_only": True,
        }

    @mcp.tool()
    def refresh_term(term_name: str) -> dict[str, Any]:
        """Re-fetch one term's public calendar page and update the cache."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_term(term_name, refresh=True)
            if not result.get("ok"):
                return result
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": "refresh",
                "term": result["term"],
                "source_url": result.get("source_url"),
                "sha256": result.get("sha256"),
                "public_only": True,
            }
        finally:
            crawler.close()

    @mcp.tool()
    def check_robots() -> dict[str, Any]:
        """Fetch and cache robots.txt from teach.ustc.edu.cn for audit purposes."""
        crawler = new_crawler()
        try:
            return crawler.check_robots()
        finally:
            crawler.close()

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the academic calendar MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path. Default: data/academic-calendar.sqlite3")
    parser.add_argument("--base-url", default=None, help="Base URL. Default: https://www.teach.ustc.edu.cn")
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