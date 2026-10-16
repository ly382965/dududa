from __future__ import annotations

import argparse
import json
from typing import Any

from .config import AppConfig
from .crawler import CampusEventCrawler
from .storage import CampusEventStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USTC campus events crawler utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--base-url", default=None, help="Base URL.")
    parser.add_argument("--request-delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="Show local cache stats.")
    sub.add_parser("robots", help="Fetch robots.txt and save it in metadata.")
    sub.add_parser("categories", help="List tracked categories.")

    lists = sub.add_parser("lists", help="Fetch the notice aggregate pages into the cache.")
    lists.add_argument("--refresh", action="store_true", help="Force re-fetch.")

    detail = sub.add_parser("detail", help="Fetch one notice detail page into the cache.")
    detail.add_argument("event_id", help="Event id, e.g. 1360/25272.")
    detail.add_argument("--refresh", action="store_true", help="Force re-fetch.")

    search = sub.add_parser("search", help="Search cached notices by keyword.")
    search.add_argument("query", help="Keyword.")
    search.add_argument("--category", default=None)
    search.add_argument("--limit", type=int, default=20)

    listcmd = sub.add_parser("list", help="List cached notices.")
    listcmd.add_argument("--category", default=None)
    listcmd.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    store = CampusEventStore(config.db_path)
    crawler = CampusEventCrawler(config, store=store)
    try:
        if args.command == "stats":
            emit(store.stats())
        elif args.command == "robots":
            emit(crawler.check_robots())
        elif args.command == "categories":
            emit([{"category": c, "source_path": p} for c, p in config.category_paths])
        elif args.command == "lists":
            emit(crawler.crawl_lists(refresh=args.refresh))
        elif args.command == "detail":
            emit(crawler.crawl_detail(args.event_id, refresh=args.refresh))
        elif args.command == "search":
            emit(store.search(args.query, category=args.category, limit=args.limit))
        elif args.command == "list":
            emit(store.list_events(category=args.category, limit=args.limit))
    finally:
        crawler.close()


if __name__ == "__main__":
    main()