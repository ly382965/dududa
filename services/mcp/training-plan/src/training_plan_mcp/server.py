from __future__ import annotations

import argparse
import sys
from typing import Any
from urllib.parse import urljoin, urlsplit

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .storage import TrainingPlanStore

_MAX_QUERY_LENGTH = 160
_MAX_RESULT_LIMIT = 30


def _source_url(config: AppConfig) -> str:
    value = urljoin(config.base_url.rstrip("/") + "/", config.page_path.lstrip("/"))
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.teach.ustc.edu.cn"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("invalid training-plan source URL")
    return value


def _bounded_text(value: object, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _public_item(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "year": int(value["year"]),
        "college": _bounded_text(value.get("college"), 200),
        "department": _bounded_text(value.get("dept"), 200) or None,
        "major": _bounded_text(value.get("major"), 200),
        "code": _bounded_text(value.get("code"), 32) or None,
        "degree": _bounded_text(value.get("degree"), 32) or None,
        "discontinued": bool(value.get("discontinued")),
    }


def create_mcp(config: AppConfig) -> FastMCP:
    """Create the cache-only, model-safe training-program transport."""

    source_url = _source_url(config)
    mcp = FastMCP("training-plan-mcp")
    store = TrainingPlanStore(config.db_path)

    @mcp.tool()
    def training_programs_public_query(
        query: str,
        year: int | None = None,
        college: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Query the cached public USTC college/major/program-code overview."""

        query = query.strip()
        college = college.strip()
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError("query must contain at most 160 characters")
        if len(college) > 200:
            raise ValueError("college must contain at most 200 characters")
        if year is not None and not 2010 <= year <= 2100:
            raise ValueError("year must be between 2010 and 2100")
        if not 1 <= limit <= _MAX_RESULT_LIMIT:
            raise ValueError("limit must be between 1 and 30")

        if query:
            values = store.search_majors(query, year=year, limit=_MAX_RESULT_LIMIT)
        elif college:
            values = store.majors_by_college(college, year=year)
        else:
            values = store.majors_by_year(year)
        if college:
            values = [item for item in values if item.get("college") == college]
        items = [_public_item(item) for item in values[:limit]]
        return {
            "schema_version": 1,
            "ok": bool(store.list_years()),
            "query": query,
            "year": year,
            "college": college or None,
            "items": items,
            "returned": len(items),
            "source": "ustc-training-program-overview-cache",
            "source_url": source_url,
            "fetched_at": store.stats()["last_fetched_at"],
            "freshness_note": "官方分年份本科专业设置一览；不是个人培养计划，停招状态未逐项核验，请查原表。",
        }

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the cache-only USTC training-program MCP server over stdio."
    )
    parser.add_argument("--db-path", default=None, help="SQLite cache path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_mcp(AppConfig.from_args(db_path=args.db_path)).run()


if __name__ == "__main__":
    main(sys.argv[1:])
