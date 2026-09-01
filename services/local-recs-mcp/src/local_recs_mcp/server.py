from __future__ import annotations

import argparse
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .storage import RecommendationStore


def _high_score_pool(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """筛选评分较高的条目池。取评分 >= 分值中位数 的子集(至少保留一条)。"""
    if not items:
        return []
    scores = sorted(i["score"] for i in items)
    median = scores[len(scores) // 2]
    high = [i for i in items if i["score"] >= median]
    return high or items


_CAMPUS_COORDS = {
    "东区": (117.2644, 31.8447),
    "西区": (117.2466, 31.8405),
    "中区": (117.2555, 31.8426),
    "南区": (117.2700, 31.8300),
    "肥西路": (117.2510, 31.8420),
}


def _auto_meal_time() -> str:
    """根据当前时间推断用餐时段。"""
    import datetime
    hour = datetime.datetime.now().hour
    if 5 <= hour < 10:
        return "早餐"
    elif 10 <= hour < 14:
        return "午餐"
    elif 17 <= hour < 21:
        return "晚餐"
    elif hour >= 21 or hour < 5:
        return "夜宵"
    return "午餐"


def _generate_map_link(item: dict[str, Any] | None = None, campus: str = "") -> str:
    """生成高德地图可交互链接。"""
    if item:
        name = item.get("name", "")
        return f"https://uri.amap.com/search?keyword={name}&city=340100"
    center = _CAMPUS_COORDS.get(campus, _CAMPUS_COORDS["东区"])
    return f"https://uri.amap.com/search?keyword=美食&center={center[0]},{center[1]}&radius=15000&city=340100"


def create_mcp(config: AppConfig) -> FastMCP:
    mcp = FastMCP("local-recs-mcp")
    store = RecommendationStore(config.db_path)

    @mcp.tool()
    def recs_stats() -> dict[str, Any]:
        """Return local recommendation cache statistics."""
        return store.stats()

    @mcp.tool()
    def random_recommendation(kind: str = "food", exclude_ids: list[int] | None = None) -> dict[str, Any]:
        """Return one random recommendation (default food). High-scored entries are preferred.
        Pass exclude_ids (e.g. the previously recommended id) to avoid repeating the same place.

        kind can be:
          - 'food':      food around campus (食堂窗口/小吃/餐厅 with a concrete dish)
          - 'activity':  fun activities (video game, board game, script-kill, KTV, sports venue)
          - 'study':     exam revision suggestion (a subject based on calendar)
        """
        exclude_ids = exclude_ids or []
        items = store.list(kind=kind, limit=200)
        if not items:
            return {"schema_version": 1, "ok": False, "error": "no_recommendations", "kind": kind}

        pool = _high_score_pool(items)
        eligible = [i for i in pool if i["id"] not in exclude_ids]
        if not eligible:
            eligible = pool
        import random as _random

        pick = _random.choice(eligible)
        store.mark_recommended(pick["id"])
        entry = dict(pick)
        return {
            "schema_version": 1,
            "ok": True,
            "recommendation": entry,
            "hint": "Reply with a short, concrete, friendly suggestion like '桃李苑食堂的铁板意面(黑椒味)'.",
        }

    @mcp.tool()
    def random_recommendations(kind: str = "activity", n: int = 5, exclude_ids: list[int] | None = None) -> dict[str, Any]:
        """Return a random sample of up to n recommendations (default activity). High-scored entries preferred.
        Use for picking a random activity/game/sport/topic. Each returned item composes: name + detail."""
        exclude_ids = exclude_ids or []
        items = store.list(kind=kind, limit=500)
        if not items:
            return {"schema_version": 1, "ok": False, "error": "no_recommendations", "kind": kind}

        pool = _high_score_pool(items)
        import random as _random

        candidates = [i for i in pool if i["id"] not in exclude_ids] or pool
        k = min(max(n, 1), len(candidates))
        picked = _random.sample(candidates, k)
        for item in picked:
            store.mark_recommended(item["id"])
        return {
            "schema_version": 1,
            "ok": True,
            "kind": kind,
            "recommendations": picked,
            "hint": "Pick ONE of these and phrase it as a concrete suggestion.",
        }

    @mcp.tool()
    def random_food(meal_time: str = "", campus: str = "", price_level: str = "",
                    exclude_ids: list[int] | None = None) -> dict[str, Any]:
        """Recommend what to eat based on time of day and campus.

        meal_time: 早餐/午餐/晚餐/夜宵, empty = auto-detect from current time.
        campus: 东区/西区/中区/南区/肥西路/校外, empty = no filter.
        price_level: 平价/中档/略贵, empty = no filter.

        Thursday special: recommends KFC (疯狂星期四) for lunch/dinner.
        Returns a recommendation with a map link.
        """
        import datetime
        import random as _random

        if not meal_time:
            meal_time = _auto_meal_time()

        exclude_ids = exclude_ids or []
        today = datetime.date.today()
        is_thursday = today.weekday() == 3

        # 周四午餐/晚餐：优先推荐肯德基疯狂星期四
        if is_thursday and meal_time in ("午餐", "晚餐"):
            kfc_results = store.search("肯德基", limit=5)
            kfc_results = [r for r in kfc_results if r["id"] not in exclude_ids]
            if kfc_results:
                pick = _random.choice(kfc_results)
                store.mark_recommended(pick["id"])
                return {
                    "schema_version": 1,
                    "ok": True,
                    "recommendation": pick,
                    "meal_time": meal_time,
                    "is_thursday": True,
                    "map_link": _generate_map_link(pick),
                    "hint": "今天是星期四！肯德基疯狂星期四，快去薅羊毛！",
                }

        items = store.list_food_by_time(
            meal_time=meal_time, campus=campus, price_level=price_level, limit=100
        )
        if not items:
            items = store.list(kind="food", limit=100)
        if not items:
            return {"schema_version": 1, "ok": False, "error": "no_recommendations"}

        pool = _high_score_pool(items)
        eligible = [i for i in pool if i["id"] not in exclude_ids]
        if not eligible:
            eligible = pool

        pick = _random.choice(eligible)
        store.mark_recommended(pick["id"])

        # 如果是食堂，附带营业时间
        opening = pick.get("opening_hours") or {}

        return {
            "schema_version": 1,
            "ok": True,
            "recommendation": pick,
            "meal_time": meal_time,
            "is_thursday": is_thursday,
            "opening_hours": opening,
            "map_link": _generate_map_link(pick),
            "hint": "回复一个可爱的推荐，包含店名、位置和一句话推荐理由。如果是食堂可以提一下营业时间。",
        }

    @mcp.tool()
    def generate_food_map(campus: str = "") -> dict[str, Any]:
        """Generate an interactive Amap link for food near USTC (15km radius).

        campus: 东区/西区/中区/南区/肥西路, empty = 东区 as center.
        """
        link = _generate_map_link(campus=campus)
        return {
            "schema_version": 1,
            "ok": True,
            "campus": campus or "东区",
            "map_link": link,
        }

    @mcp.tool()
    def search_place(keyword: str, city: str = "合肥") -> dict[str, Any]:
        """Search a place by keyword using Amap POI API.

        keyword: place name, e.g. '老乡鸡金寨路店' or '科大东区'.
        city: city name (default 合肥).
        Returns top 3 matches with name, address, phone, location, and a map link.
        """
        import os
        import json as _json
        from urllib.request import Request, urlopen
        from urllib.parse import quote

        api_key = os.environ.get("AMAP_API_KEY", "")
        if not api_key:
            return {"schema_version": 1, "ok": False, "error": "no_amap_key",
                    "hint": "Set AMAP_API_KEY environment variable."}

        url = (
            f"https://restapi.amap.com/v3/place/text"
            f"?key={api_key}&keywords={quote(keyword)}"
            f"&city={quote(city)}&citylimit=true&offset=3&page=1&extensions=base"
        )
        try:
            req = Request(url, headers={"User-Agent": "dududa/1.0"})
            with urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"schema_version": 1, "ok": False, "error": str(exc)}

        if data.get("status") != "1":
            return {"schema_version": 1, "ok": False, "error": data.get("info", "unknown")}

        pois = data.get("pois") or []
        results = []
        for poi in pois[:3]:
            name = poi.get("name", "")
            address = poi.get("address", "")
            adname = poi.get("adname", "")
            tel = poi.get("tel", "")
            location = poi.get("location", "")
            location_str = f"{adname}{address}".strip("[]") if address else adname
            map_link = ""
            if location:
                lng, lat = (location.split(",") + ["", ""])[:2]
                map_link = f"https://uri.amap.com/marker?position={lng},{lat}&name={quote(name)}"
            results.append({
                "name": name,
                "address": location_str,
                "tel": tel if tel and tel != "[]" else "",
                "location": location,
                "map_link": map_link,
            })

        return {
            "schema_version": 1,
            "ok": True,
            "keyword": keyword,
            "results": results,
        }

    @mcp.tool()
    def add_recommendation(
        kind: str,
        name: str,
        detail: str = "",
        location: str = "",
        score: float = 4.0,
        proximity: str = "",
        tags: list[str] | None = None,
        source: str = "manual",
        campus: str = "",
        meal_time: list[str] | None = None,
        price_level: str = "",
        opening_hours: dict | None = None,
    ) -> dict[str, Any]:
        """Add or update one recommendation entry (e.g. a new food place or activity). kind: food/activity/study/canteen."""
        rec_id = store.upsert(
            kind=kind,
            name=name,
            detail=detail,
            location=location,
            score=score,
            proximity=proximity,
            tags=tags,
            source=source,
            campus=campus,
            meal_time=meal_time,
            price_level=price_level,
            opening_hours=opening_hours,
        )
        return {
            "schema_version": 1,
            "ok": True,
            "id": rec_id,
            "recommendation": store.get(rec_id),
        }

    @mcp.tool()
    def list_recommendations(kind: str | None = None, limit: int = 50) -> dict[str, Any]:
        """List recommendations, optionally filtered by kind."""
        return {
            "schema_version": 1,
            "ok": True,
            "recommendations": store.list(kind=kind, limit=limit),
        }

    @mcp.tool()
    def search_recommendations(query: str, limit: int = 20) -> dict[str, Any]:
        """Search recommendations by keyword (name/detail/location/tags)."""
        return {
            "schema_version": 1,
            "ok": True,
            "query": query,
            "recommendations": store.search(query, limit=limit),
        }

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local recommendations MCP server over stdio.")
    parser.add_argument("--db-path", default=None, help="SQLite database path. Default: data/local-recs.sqlite3")
    args = parser.parse_args(argv)
    config = AppConfig.from_args(db_path=args.db_path)
    mcp = create_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])