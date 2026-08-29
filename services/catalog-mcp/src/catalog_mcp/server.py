from __future__ import annotations

import argparse
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .fetcher import CatalogFetcher
from .storage import CatalogStore


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("catalog-mcp")
    store = CatalogStore(config.db_path)

    @mcp.tool()
    def catalog_stats() -> dict[str, Any]:
        """Return local cache statistics for the public USTC course-catalog data."""
        return store.stats()

    @mcp.tool()
    def catalog_semesters(limit: int = 8) -> dict[str, Any]:
        """List recent USTC semesters available from the public catalog API, newest first."""
        fetcher = CatalogFetcher(config)
        try:
            semesters = fetcher.semesters()
        finally:
            fetcher.close()
        store.upsert_semesters(semesters)
        recent = semesters[:limit]
        return {
            "ok": True,
            "semesters": [
                {
                    "id": s.get("id"),
                    "code": s.get("code"),
                    "name": s.get("nameZh"),
                    "start": s.get("start"),
                    "end": s.get("end"),
                }
                for s in recent
            ],
            "hint": "Pass the returned id to catalog_sync to cache that semester's lessons.",
        }

    @mcp.tool()
    def catalog_sync(semester: int) -> dict[str, Any]:
        """Fetch and cache the full public lesson list for one semester id from catalog.ustc.edu.cn.

        Call catalog_semesters first to obtain a valid semester id. This caches class
        timetables, venues and capacities into the local SQLite store.
        """
        fetcher = CatalogFetcher(config)
        try:
            lessons = fetcher.lesson_list_for_teach(semester)
        finally:
            fetcher.close()
        count = store.replace_semester_lessons(semester, lessons)
        return {"ok": True, "semester": semester, "cached_lessons": count}

    @mcp.tool()
    def catalog_open(query: str, semester: int | None = None, limit: int = 8) -> dict[str, Any]:
        """Search cached public course openings for class timetable and capacity.

        query may be a course code (e.g. '022063' or '022063.01') or a course
        keyword (Chinese or English name). Returns limitCount (capacity),
        stdCount (enrolled), timetables, venues and teachers. Requires the
        semester to have been synced via catalog_sync.
        """
        if not query or not query.strip():
            return {"ok": False, "error": "empty_query"}
        results = store.search(query.strip(), semester=semester if semester and semester > 0 else None, limit=limit)
        return {
            "ok": True,
            "query": query,
            "semester": semester,
            "count": len(results),
            "results": results,
        }

    @mcp.tool()
    def catalog_course_search(keyword: str, limit: int = 10) -> dict[str, Any]:
        """Search the public catalog for course records (not cached; hits the API live)."""
        fetcher = CatalogFetcher(config)
        try:
            hits = fetcher.course_search(keyword)
        finally:
            fetcher.close()
        return {"ok": True, "keyword": keyword, "count": len(hits), "results": hits[:limit]}

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the catalog MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path. Default: data/catalog.sqlite3")
    parser.add_argument("--base-url", default=None, help="Base URL. Default: https://catalog.ustc.edu.cn")
    parser.add_argument("--request-delay", type=float, default=None, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        timeout=args.timeout,
        request_delay=args.request_delay,
    )
    mcp = create_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])
