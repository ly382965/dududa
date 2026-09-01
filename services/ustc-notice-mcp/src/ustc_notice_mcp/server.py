from __future__ import annotations

import argparse
import re
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import NoticeCrawler
from .storage import NoticeStore


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("ustc-notice-mcp")
    store = NoticeStore(config.db_path)

    def new_crawler() -> NoticeCrawler:
        return NoticeCrawler(config, store=store)

    @mcp.tool()
    def notice_stats() -> dict[str, Any]:
        """Return local cache statistics for USTC public notices from the Office of Academic Affairs."""
        return store.stats()

    @mcp.tool()
    def list_notices(limit: int = 20, refresh: bool = False, max_pages: int = 1) -> dict[str, Any]:
        """List recent public notices from the USTC Office of Academic Affairs. Set refresh=true to re-fetch;
        max_pages controls how many listing pages to crawl (1 = newest page only)."""
        crawler = new_crawler()
        try:
            if refresh:
                crawler.crawl_list(refresh=True, max_pages=max_pages)
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": "hit",
                "notices": store.list_notices(limit=limit),
                "public_only": True,
            }
        finally:
            crawler.close()

    @mcp.tool()
    def get_notice(notice_id: int, refresh: bool = False) -> dict[str, Any]:
        """Get the full text of one public notice by its numeric id (see list_notices/search_notices for ids)."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_detail(notice_id, refresh=refresh)
            if not result.get("ok"):
                return result
            notice = store.get_notice(notice_id)
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": result.get("cache_status", "unknown"),
                "notice": notice,
                "public_only": True,
                "source_refs": [
                    {
                        "source": "https://www.teach.ustc.edu.cn/notice/notice-info/{id}.html".format(id=notice_id),
                        "observed_at": notice["fetched_at"] if notice else None,
                    }
                ],
            }
        finally:
            crawler.close()

    @mcp.tool()
    def search_notices(query: str, limit: int = 20, refresh: bool = False, max_pages: int = 1) -> dict[str, Any]:
        """Search USTC Office of Academic Affairs notices by keyword (title or full text), e.g. 选课, 考试, 竞赛.
        Set refresh=true to re-fetch the latest notice list (max_pages pages) before searching. Use
        get_notice(id, refresh=true) to fetch the full text of any matched notice."""
        query = (query or "").strip()
        if refresh:
            crawler = new_crawler()
            try:
                crawler.crawl_list(refresh=True, max_pages=max(max_pages, 1))
            finally:
                crawler.close()
        if not query:
            return {"schema_version": 1, "ok": False, "error": "empty_query", "notices": []}
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "notices": store.search_notices(query, limit=limit),
            "public_only": True,
            "hint": "Match by title or full text. Call get_notice(id, refresh=true) to pull the latest body for any id.",
        }

    @mcp.tool()
    def refresh_notice(notice_id: int) -> dict[str, Any]:
        """Re-fetch one public notice page and update the cache."""
        crawler = new_crawler()
        try:
            result = crawler.crawl_detail(notice_id, refresh=True)
            if not result.get("ok"):
                return result
            return {
                "schema_version": 1,
                "ok": True,
                "cache_status": "refresh",
                "notice": result["notice"],
                "source_url": result.get("source_url"),
                "sha256": result.get("sha256"),
                "public_only": True,
            }
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
    parser = argparse.ArgumentParser(description="Run the USTC notice MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path. Default: data/ustc-notice.sqlite3")
    parser.add_argument("--base-url", default=None, help="Base URL. Default: https://www.teach.ustc.edu.cn")
    parser.add_argument("--request-delay", type=float, default=None, help="Delay between requests in seconds.")
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout in seconds.")
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