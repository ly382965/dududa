from __future__ import annotations

import argparse
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import TrainingPlanCrawler
from .storage import TrainingPlanStore


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("training-plan-mcp")
    store = TrainingPlanStore(config.db_path)

    def new_crawler() -> TrainingPlanCrawler:
        return TrainingPlanCrawler(config, store=store)

    @mcp.tool()
    def plan_stats() -> dict[str, Any]:
        """Return local cache statistics for USTC public undergraduate program overview data."""
        return store.stats()

    @mcp.tool()
    def get_program_years(refresh: bool = False) -> dict[str, Any]:
        """List the entry-year editions (e.g. 2026) of the public major overview table."""
        crawler = new_crawler()
        try:
            if refresh:
                crawler.crawl_overview(refresh=True)
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": "hit",
                "years": store.list_years(),
                "public_only": True,
            }
        finally:
            crawler.close()

    @mcp.tool()
    def get_majors(year: int | None = None) -> dict[str, Any]:
        """List major rows for one entry year (latest edition when omitted)."""
        if year is None:
            years = store.list_years()
            if years:
                year = years[0]["year"]
        rows = store.majors_by_year(year)
        return {
            "schema_version": 1,
            "ok": True,
            "year": year,
            "colleges": sorted({row["college"] for row in rows}),
            "majors": rows,
            "public_only": True,
        }

    @mcp.tool()
    def get_college_majors(college: str, year: int | None = None) -> dict[str, Any]:
        """Get the majors offered by one college, optionally for a specific entry year."""
        rows = store.majors_by_college(college, year=year)
        return {
            "schema_version": 1,
            "ok": True,
            "college": college,
            "year": year,
            "majors": rows,
            "public_only": True,
        }

    @mcp.tool()
    def search_majors(query: str, year: int | None = None, limit: int = 30) -> dict[str, Any]:
        """Search majors by keyword (name, college, department, or program code)."""
        query = query.strip()
        if not query:
            return {"schema_version": 1, "ok": False, "error": "empty_query", "majors": []}
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "year": year,
            "majors": store.search_majors(query, year=year, limit=limit),
            "public_only": True,
        }

    @mcp.tool()
    def list_colleges() -> dict[str, Any]:
        """List the distinct colleges present in the cached program overview."""
        return {
            "schema_version": 1,
            "ok": True,
            "colleges": store.colleges(),
            "public_only": True,
        }

    @mcp.tool()
    def refresh_programs() -> dict[str, Any]:
        """Re-fetch the public major overview page and rebuild the cache."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_overview(refresh=True)
            return {"schema_version": 1, **result, "public_only": True}
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
    parser = argparse.ArgumentParser(description="Run the training plan MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--base-url", default=None, help="Base URL.")
    parser.add_argument("--page-path", default=None, help="Path of the overview page.")
    parser.add_argument("--request-delay", type=float, default=None, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        page_path=args.page_path,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    mcp = create_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])