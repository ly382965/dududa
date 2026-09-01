from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .crawler import NoticeCrawler
from .storage import NoticeStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USTC Office of Academic Affairs notice crawler utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path. Default: data/ustc-notice.sqlite3")
    parser.add_argument("--base-url", default=None, help="Base URL. Default: https://www.teach.ustc.edu.cn")
    parser.add_argument("--request-delay", type=float, default=1.0, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show local cache stats.")
    sub.add_parser("robots", help="Fetch robots.txt and save it in metadata.")

    listing = sub.add_parser("listing", help="Fetch and cache the notice list page.")
    listing.add_argument("--refresh", action="store_true", help="Re-fetch the list page.")

    get = sub.add_parser("get", help="Fetch and cache one notice detail page.")
    get.add_argument("notice_id", type=int, help="Numeric notice id.")

    search = sub.add_parser("search", help="Search cached notices by keyword.")
    search.add_argument("query", help="Keyword, e.g. 选课 or 考试.")
    search.add_argument("--limit", type=int, default=20)

    list_cmd = sub.add_parser("list", help="List cached notices.")
    list_cmd.add_argument("--limit", type=int, default=20)

    export = sub.add_parser("export", help="Export cached notice details as JSONL.")
    export.add_argument("--output", default="data/ustc_notices.jsonl")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    store = NoticeStore(config.db_path)
    crawler = NoticeCrawler(config, store=store)
    try:
        if args.command == "stats":
            emit(store.stats())
        elif args.command == "robots":
            emit(crawler.check_robots())
        elif args.command == "listing":
            emit(crawler.crawl_list(refresh=args.refresh))
        elif args.command == "get":
            emit(crawler.crawl_detail(args.notice_id, refresh=True))
        elif args.command == "search":
            emit(store.search_notices(args.query, limit=args.limit))
        elif args.command == "list":
            emit(store.list_notices(limit=args.limit))
        elif args.command == "export":
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            count = 0
            with output.open("w", encoding="utf-8") as handle:
                for notice in store.list_notices(limit=1000):
                    detail = store.get_notice(notice["id"])
                    if detail and detail.get("fetched_at"):
                        handle.write(json.dumps(detail, ensure_ascii=False) + "\n")
                        count += 1
            emit({"output_path": str(output), "notices_exported": count})
    finally:
        crawler.close()


if __name__ == "__main__":
    main()