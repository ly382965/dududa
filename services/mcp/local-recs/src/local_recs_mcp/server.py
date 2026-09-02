from __future__ import annotations

import argparse
import random
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .storage import RecommendationStore

_KINDS = frozenset({"food", "canteen", "activity", "study"})
_MEAL_TIMES = frozenset({"", "早餐", "午餐", "晚餐", "夜宵"})
_PRICE_LEVELS = frozenset({"", "平价", "中档", "略贵"})
_MAX_QUERY_LENGTH = 120
_MAX_RESULT_LIMIT = 10


def _bounded_text(value: object, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _public_item(value: dict[str, Any]) -> dict[str, Any]:
    tags = [
        _bounded_text(item, 80)
        for item in value.get("tags") or ()
        if str(item or "").strip()
    ][:12]
    meal_times = [
        _bounded_text(item, 16)
        for item in value.get("meal_time") or ()
        if str(item or "").strip()
    ][:8]
    raw_hours = value.get("opening_hours")
    opening_hours = {
        _bounded_text(key, 24): _bounded_text(item, 80)
        for key, item in (
            list(raw_hours.items())[:16] if isinstance(raw_hours, dict) else ()
        )
    }
    return {
        "id": int(value["id"]),
        "kind": _bounded_text(value.get("kind"), 24),
        "name": _bounded_text(value.get("name"), 240),
        "detail": _bounded_text(value.get("detail"), 800),
        "location": _bounded_text(value.get("location"), 240),
        "score": float(value.get("score") or 0),
        "proximity": _bounded_text(value.get("proximity"), 160),
        "tags": tags,
        "source": _bounded_text(value.get("source"), 120),
        "campus": _bounded_text(value.get("campus"), 32),
        "meal_time": meal_times,
        "price_level": _bounded_text(value.get("price_level"), 32),
        "opening_hours": opening_hours,
    }


def _eligible(
    values: list[dict[str, Any]],
    *,
    kind: str,
    campus: str,
    meal_time: str,
    price_level: str,
    excluded: frozenset[int],
) -> list[dict[str, Any]]:
    result = []
    for item in values:
        if int(item.get("id") or 0) in excluded:
            continue
        if kind and item.get("kind") != kind:
            continue
        if campus and item.get("campus") not in {campus, "校内", "校外"}:
            continue
        meal_times = item.get("meal_time") or ()
        if meal_time and meal_time not in meal_times and "全天" not in meal_times:
            continue
        if price_level and item.get("price_level") not in {price_level, ""}:
            continue
        result.append(item)
    return result


def _high_score_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    scores = sorted(float(item.get("score") or 0) for item in items)
    median = scores[len(scores) // 2]
    return [item for item in items if float(item.get("score") or 0) >= median]


def create_mcp(
    config: AppConfig,
    *,
    rng: random.Random | None = None,
) -> FastMCP:
    """Create a read-only local recommendation transport."""

    mcp = FastMCP("local-recs-mcp")
    store = RecommendationStore(config.db_path)
    chooser = rng or random.SystemRandom()

    @mcp.tool()
    def local_recommendations_public_query(
        query: str,
        kind: str = "",
        campus: str = "",
        meal_time: str = "",
        price_level: str = "",
        limit: int = 3,
        exclude_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded random sample from the curated local recommendation data."""

        query = query.strip()
        kind = kind.strip().casefold()
        campus = campus.strip()
        meal_time = meal_time.strip()
        price_level = price_level.strip()
        excluded_values = exclude_ids or []
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError("query must contain at most 120 characters")
        if kind and kind not in _KINDS:
            raise ValueError("unsupported kind")
        if len(campus) > 32:
            raise ValueError("campus must contain at most 32 characters")
        if meal_time not in _MEAL_TIMES:
            raise ValueError("unsupported meal_time")
        if price_level not in _PRICE_LEVELS:
            raise ValueError("unsupported price_level")
        if not 1 <= limit <= _MAX_RESULT_LIMIT:
            raise ValueError("limit must be between 1 and 10")
        if len(excluded_values) > 50 or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in excluded_values
        ):
            raise ValueError("exclude_ids must contain at most 50 positive integers")

        values = store.search(query, limit=100) if query else store.list(limit=500)
        if query and not values:
            values = store.list(limit=500)
        values = _eligible(
            values,
            kind=kind,
            campus=campus,
            meal_time=meal_time,
            price_level=price_level,
            excluded=frozenset(excluded_values),
        )
        pool = _high_score_pool(values)
        selected = chooser.sample(pool, min(limit, len(pool))) if pool else []
        items = [_public_item(item) for item in selected]
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "kind": kind or None,
            "campus": campus or None,
            "meal_time": meal_time or None,
            "price_level": price_level or None,
            "items": items,
            "returned": len(items),
            "source": "dududa-curated-local-recommendations-v1",
        }

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the read-only local recommendations MCP server over stdio."
    )
    parser.add_argument("--db-path", default=None, help="SQLite cache path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_mcp(AppConfig.from_args(db_path=args.db_path)).run()


if __name__ == "__main__":
    main(sys.argv[1:])
