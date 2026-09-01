from __future__ import annotations

import argparse
import json
from typing import Any

from .config import AppConfig
from .crawler import TrainingPlanCrawler
from .storage import TrainingPlanStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USTC undergraduate program overview crawler utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--base-url", default=None, help="Base URL.")
    parser.add_argument("--page-path", default=None, help="Path of the overview page.")
    parser.add_argument("--request-delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="Show local cache stats.")
    sub.add_parser("robots", help="Fetch robots.txt and save it in metadata.")

    refresh = sub.add_parser("refresh", help="Fetch the overview page and rebuild the cache.")
    refresh.add_argument("--refresh", action="store_true", help="Force re-fetch (default when not cached).")

    years = sub.add_parser("years", help="List cached entry years.")
    years.add_argument("--refresh", action="store_true", help="Force re-fetch first.")

    majors = sub.add_parser("majors", help="List majors, optionally filtered by entry year.")
    majors.add_argument("--year", type=int, default=None)

    college = sub.add_parser("college", help="List majors of one college.")
    college.add_argument("name", help="College name, e.g. 数学科学学院.")
    college.add_argument("--year", type=int, default=None)

    search = sub.add_parser("search", help="Search majors by keyword.")
    search.add_argument("query", help="Keyword, e.g. 计算机 or 070301.")
    search.add_argument("--year", type=int, default=None)
    search.add_argument("--limit", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        page_path=args.page_path,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    store = TrainingPlanStore(config.db_path)
    crawler = TrainingPlanCrawler(config, store=store)
    try:
        if args.command == "stats":
            emit(store.stats())
        elif args.command == "robots":
            emit(crawler.check_robots())
        elif args.command == "refresh":
            emit(crawler.crawl_overview(refresh=True))
        elif args.command == "years":
            if args.refresh:
                crawler.crawl_overview(refresh=True)
            emit(store.list_years())
        elif args.command == "majors":
            year = args.year
            if year is None:
                years = store.list_years()
                year = years[0]["year"] if years else None
            emit(store.majors_by_year(year))
        elif args.command == "college":
            emit(store.majors_by_college(args.name, year=args.year))
        elif args.command == "search":
            emit(store.search_majors(args.query, year=args.year, limit=args.limit))
    finally:
        crawler.close()


if __name__ == "__main__":
    main()