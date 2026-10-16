from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .crawler import ICourseCrawler
from .storage import ICourseStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="iCourse crawler utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path. Default: data/icourse.sqlite3")
    parser.add_argument("--base-url", default=None, help="Base URL. Default: https://icourse.club")
    parser.add_argument("--request-delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show local cache stats.")
    sub.add_parser("robots", help="Fetch robots.txt and save it in metadata.")

    one = sub.add_parser("crawl-course", help="Fetch one course detail page.")
    one.add_argument("course_id", type=int)
    one.add_argument("--sort-by", default="upvote")

    many = sub.add_parser("crawl-courses", help="Fetch course-list pages and optionally detail pages.")
    many.add_argument("--start-page", type=int, default=1)
    many.add_argument("--end-page", type=int, default=1)
    many.add_argument("--per-page", type=int, default=50)
    many.add_argument("--max-courses", type=int, default=50)
    many.add_argument("--detail", action="store_true")
    many.add_argument("--sort-by", default=None)

    latest = sub.add_parser("crawl-latest", help="Refresh courses from public latest reviews.")
    latest.add_argument("--pages", type=int, default=1)
    latest.add_argument("--per-page", type=int, default=10)
    latest.add_argument("--max-courses", type=int, default=20)

    search = sub.add_parser("search", help="Search local cache.")
    search.add_argument("query", nargs="?")
    search.add_argument("--teacher")
    search.add_argument("--dept")
    search.add_argument("--course-type")
    search.add_argument("--min-rating", type=float)
    search.add_argument("--limit", type=int, default=20)

    get = sub.add_parser("get-course", help="Show one cached course.")
    get.add_argument("course_id", type=int)
    get.add_argument("--no-reviews", action="store_true")

    export = sub.add_parser("export", help="Export cache as JSONL.")
    export.add_argument("--output", default="data/icourse_courses.jsonl")
    export.add_argument("--no-reviews", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    store = ICourseStore(config.db_path)
    crawler = ICourseCrawler(config, store=store)
    try:
        if args.command == "stats":
            emit(store.stats())
        elif args.command == "robots":
            emit(crawler.check_robots())
        elif args.command == "crawl-course":
            emit(crawler.crawl_course(args.course_id, sort_by=args.sort_by))
        elif args.command == "crawl-courses":
            emit(
                crawler.crawl_courses(
                    start_page=args.start_page,
                    end_page=args.end_page,
                    per_page=args.per_page,
                    max_courses=args.max_courses,
                    detail=args.detail,
                    sort_by=args.sort_by,
                )
            )
        elif args.command == "crawl-latest":
            emit(crawler.crawl_latest_reviews(args.pages, args.per_page, args.max_courses))
        elif args.command == "search":
            emit(
                store.search_courses(
                    query=args.query,
                    teacher=args.teacher,
                    dept=args.dept,
                    course_type=args.course_type,
                    min_rating=args.min_rating,
                    limit=args.limit,
                )
            )
        elif args.command == "get-course":
            emit(store.get_course(args.course_id, include_reviews=not args.no_reviews))
        elif args.command == "export":
            emit(store.export_jsonl(Path(args.output), include_reviews=not args.no_reviews))
    finally:
        crawler.close()


if __name__ == "__main__":
    main()
