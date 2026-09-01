from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .crawler import CalendarCrawler
from .storage import CalendarStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USTC academic calendar crawler utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path. Default: data/academic-calendar.sqlite3")
    parser.add_argument("--base-url", default=None, help="Base URL. Default: https://www.teach.ustc.edu.cn")
    parser.add_argument("--request-delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show local cache stats.")
    sub.add_parser("robots", help="Fetch robots.txt and save it in metadata.")

    listing = sub.add_parser("listing", help="List published academic calendar terms.")
    listing.add_argument("--refresh", action="store_true", help="Re-fetch the listing page.")

    refresh = sub.add_parser("refresh", help="Fetch one term detail page and update cache.")
    refresh.add_argument("term", nargs="?", help="Term name or numeric id; latest listing is used when omitted.")

    get = sub.add_parser("get", help="Show one cached term.")
    get.add_argument("term", nargs="?", help="Term name or numeric id; latest listing is used when omitted.")

    search = sub.add_parser("search", help="Search cached events by keyword.")
    search.add_argument("query", help="Keyword, e.g. 开学 or 假期.")
    search.add_argument("--limit", type=int, default=20)

    events = sub.add_parser("events", help="Show cached events on a date.")
    events.add_argument("date", nargs="?", default="today", help="YYYY-MM-DD, default today.")

    export = sub.add_parser("export", help="Export cached terms as JSONL.")
    export.add_argument("--output", default="data/academic_calendar.jsonl")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    store = CalendarStore(config.db_path)
    crawler = CalendarCrawler(config, store=store)
    try:
        if args.command == "stats":
            emit(store.stats())
        elif args.command == "robots":
            emit(crawler.check_robots())
        elif args.command == "listing":
            emit(crawler.crawl_listing(refresh=args.refresh))
        elif args.command == "refresh":
            emit(crawler.crawl_term(args.term, refresh=True))
        elif args.command == "get":
            term_id = crawler.resolve_term_id(args.term)
            emit(store.get_term(term_id) if term_id is not None else {"ok": False, "error": "term_not_found"})
        elif args.command == "search":
            emit(store.search_events(args.query, limit=args.limit))
        elif args.command == "events":
            target = args.date
            emit(store.get_events_on(target))
        elif args.command == "export":
            emit(store.export_jsonl(Path(args.output)))
    finally:
        crawler.close()


if __name__ == "__main__":
    main()