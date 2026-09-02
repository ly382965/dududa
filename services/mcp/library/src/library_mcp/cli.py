from __future__ import annotations

import argparse
import json
from typing import Any

from .config import AppConfig
from .crawler import LibraryCrawler
from .storage import LibraryStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USTC library opening hours crawler utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--base-url", default=None, help="Base URL.")
    parser.add_argument("--hours-path", default=None, help="Path of the opening hours page.")
    parser.add_argument("--request-delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="Show local cache stats.")
    sub.add_parser("robots", help="Fetch robots.txt and save it in metadata.")

    refresh = sub.add_parser("refresh", help="Fetch the opening hours page and rebuild the cache.")
    refresh.add_argument("--refresh", action="store_true", help="Force re-fetch.")

    hours = sub.add_parser("hours", help="List cached opening hours.")
    hours.add_argument("--campus", default=None, help="Filter by campus, e.g. 东区.")

    search = sub.add_parser("search", help="Search opening hours by keyword.")
    search.add_argument("query", help="Keyword, e.g. 自习室.")
    search.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        hours_path=args.hours_path,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    store = LibraryStore(config.db_path)
    crawler = LibraryCrawler(config, store=store)
    try:
        if args.command == "stats":
            emit(store.stats())
        elif args.command == "robots":
            emit(crawler.check_robots())
        elif args.command == "refresh":
            emit(crawler.crawl_hours(refresh=True))
        elif args.command == "hours":
            if args.campus:
                emit(store.by_campus(args.campus))
            else:
                emit(store.all_hours())
        elif args.command == "search":
            emit(store.search(args.query, limit=args.limit))
    finally:
        crawler.close()


if __name__ == "__main__":
    main()