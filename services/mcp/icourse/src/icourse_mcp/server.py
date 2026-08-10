from __future__ import annotations

import argparse
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import ICourseCrawler
from .storage import ICourseStore


def create_mcp(config: AppConfig) -> FastMCP:
    store = ICourseStore(config.db_path)
    crawler: ICourseCrawler | None = None

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        nonlocal crawler
        crawler = ICourseCrawler(config, store=store)
        try:
            yield {"crawler": crawler}
        finally:
            crawler.close()
            crawler = None

    def current_crawler() -> ICourseCrawler:
        if crawler is None:
            raise RuntimeError("icourse crawler lifespan is not active")
        return crawler

    mcp = FastMCP("icourse-mcp", lifespan=lifespan)

    @mcp.tool()
    def icourse_stats() -> dict[str, Any]:
        """Return local database statistics for the iCourse public-data cache."""
        return store.stats()

    @mcp.tool()
    def search_courses(
        query: str | None = None,
        teacher: str | None = None,
        dept: str | None = None,
        course_type: str | None = None,
        min_rating: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search cached public course records from icourse.club."""
        return store.search_courses(
            query=query,
            teacher=teacher,
            dept=dept,
            course_type=course_type,
            min_rating=min_rating,
            limit=limit,
            offset=offset,
        )

    @mcp.tool()
    def get_course(
        course_id: int, include_reviews: bool = True, refresh: bool = False
    ) -> dict[str, Any]:
        """Get one cached course. Set refresh=true to fetch its public page first."""
        if refresh:
            current_crawler().crawl_course(course_id)
        course = store.get_course(course_id, include_reviews=include_reviews)
        if not course:
            return {
                "ok": False,
                "error": "course_not_found_in_cache",
                "hint": "Call crawl_course(course_id) first, or crawl a course-list page.",
                "course_id": course_id,
            }
        return {"ok": True, "course": course, "public_only": True}

    @mcp.tool()
    def get_reviews(
        course_id: int,
        term: str | None = None,
        rating: int | None = None,
        sort_by: str = "upvote",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get cached public reviews for one course, optionally filtered by term or 1-5 star rating."""
        return {
            "ok": True,
            "course_id": course_id,
            "reviews": store.get_reviews(
                course_id, term=term, rating=rating, sort_by=sort_by, limit=limit
            ),
            "public_only": True,
        }

    @mcp.tool()
    def crawl_course(course_id: int, sort_by: str = "upvote") -> dict[str, Any]:
        """Fetch and cache one public course detail page from icourse.club."""
        return current_crawler().crawl_course(course_id, sort_by=sort_by)

    @mcp.tool()
    def crawl_courses(
        start_page: int = 1,
        end_page: int | None = None,
        per_page: int = 50,
        max_courses: int | None = 50,
        detail: bool = False,
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        """Crawl course-list pages. Defaults are conservative; set detail=true for detail pages."""
        return current_crawler().crawl_courses(
            start_page=start_page,
            end_page=end_page,
            per_page=per_page,
            max_courses=max_courses,
            detail=detail,
            sort_by=sort_by,
        )

    @mcp.tool()
    def search_site_courses(
        query: str,
        pages: int = 1,
        max_courses: int | None = 20,
        detail: bool = False,
        detail_limit: int = 3,
        sort_by: str = "upvote",
    ) -> dict[str, Any]:
        """Search public icourse.club course pages online, cache results, optionally fetch top details."""
        return current_crawler().search_site_courses(
            query=query,
            pages=pages,
            max_courses=max_courses,
            detail=detail,
            detail_limit=detail_limit,
            sort_by=sort_by,
        )

    @mcp.tool()
    def crawl_latest_reviews(
        pages: int = 1, per_page: int = 10, max_courses: int | None = 20
    ) -> dict[str, Any]:
        """Refresh courses appearing in the public latest-reviews feed."""
        return current_crawler().crawl_latest_reviews(
            pages=pages,
            per_page=per_page,
            max_courses=max_courses,
        )

    @mcp.tool()
    def check_robots() -> dict[str, Any]:
        """Fetch and cache robots.txt from icourse.club for audit purposes."""
        return current_crawler().check_robots()

    @mcp.tool()
    def export_dataset(
        output_path: str = "data/icourse_courses.jsonl", include_reviews: bool = True
    ) -> dict[str, Any]:
        """Export cached course records to JSONL."""
        return store.export_jsonl(Path(output_path), include_reviews=include_reviews)

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the iCourse MCP server over stdio."
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite database path. Default: data/icourse.sqlite3",
    )
    parser.add_argument(
        "--base-url", default=None, help="Base URL. Default: https://icourse.club"
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=None,
        help="Delay between requests in seconds.",
    )
    parser.add_argument(
        "--timeout", type=float, default=None, help="HTTP timeout in seconds."
    )
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
