from __future__ import annotations

import argparse
import json
from typing import Any

from .config import AppConfig
from .crawler import CollegeNoticeCrawler
from .storage import CollegeNoticeStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USTC college notice crawler utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")
    parser.add_argument("--request-delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument("--colleges-json", default=None, help="JSON list of college source configs.")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="Show local cache stats.")
    sub.add_parser("colleges", help="List configured colleges.")

    lists = sub.add_parser("lists", help="Fetch college notice listing pages into the cache.")
    lists.add_argument("--college", default=None, help="Only refresh one college key.")
    lists.add_argument("--refresh", action="store_true", help="Force re-fetch of listing pages.")

    detail = sub.add_parser("detail", help="Fetch one notice detail page into the cache.")
    detail.add_argument("notice_id", help="Notice id, e.g. 2026/08/12/c1234a567.")
    detail.add_argument("--refresh", action="store_true", help="Force re-fetch.")

    search = sub.add_parser("search", help="Search cached notices by keyword.")
    search.add_argument("query", help="Keyword.")
    search.add_argument("--college", default=None)
    search.add_argument("--limit", type=int, default=20)

    listcmd = sub.add_parser("list", help="List cached notices.")
    listcmd.add_argument("--college", default=None)
    listcmd.add_argument("--limit", type=int, default=20)

    robots = sub.add_parser("robots", help="Fetch robots.txt of configured colleges.")
    robots.add_argument("--college", default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        request_delay=args.request_delay,
        timeout=args.timeout,
        colleges_json=args.colleges_json,
    )
    store = CollegeNoticeStore(config.db_path)
    crawler = CollegeNoticeCrawler(config, store=store)
    try:
        if args.command == "stats":
            emit(store.stats())
        elif args.command == "colleges":
            emit([college.to_dict() for college in config.colleges])
        elif args.command == "lists":
            emit(crawler.crawl_lists(college_key=args.college, refresh=args.refresh))
        elif args.command == "detail":
            emit(crawler.crawl_detail(args.notice_id, refresh=args.refresh))
        elif args.command == "search":
            emit(store.search(args.query, college_key=args.college, limit=args.limit))
        elif args.command == "list":
            emit(store.list_notices(college_key=args.college, limit=args.limit))
        elif args.command == "robots":
            emit(crawler.check_robots(college_key=args.college))
    finally:
        crawler.close()


if __name__ == "__main__":
    main()
