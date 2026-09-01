#!/usr/bin/env python3
"""高德地图 POI 抓取脚本：搜科大附近15km餐饮，导入 local-recs-mcp 数据库。

用法：
  python fetch_amap_poi.py --key 2bcd735137ffc3f1d886a57a4e0f0ce3
  python fetch_amap_poi.py --key XXX --radius 15000 --import
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

AMAP_KEY = ""
AMAP_BASE = "https://restapi.amap.com/v3/place/around"

# 科大各校区坐标 (lng, lat)
CAMPUS_CENTERS = {
    "东区": (117.2644, 31.8447),
    "西区": (117.2466, 31.8405),
    "中区": (117.2555, 31.8426),
    "南区": (117.2700, 31.8300),
    "高新区": (117.1500, 31.8200),
}

# 餐饮类型代码（高德 POI type）
# 050000 餐饮服务
# 050100 中餐厅
# 050200 外国餐厅
# 050300 快餐厅
# 050400 饮料/甜品/咖啡
# 050500 茶艺馆
# 050600 面包糕点
# 050900 其他餐饮
FOOD_TYPES = "050000"

MAX_PAGES = 25  # 高德每页最多25条，最多100页，我们取25页=625条
PAGE_SIZE = 25


def fetch_pois(center: tuple[float, float], radius: int, page: int = 1) -> dict[str, Any]:
    """调用高德周边搜索 API。"""
    url = (
        f"{AMAP_BASE}?key={AMAP_KEY}"
        f"&location={center[0]},{center[1]}"
        f"&types={FOOD_TYPES}"
        f"&radius={radius}"
        f"&offset={PAGE_SIZE}"
        f"&page={page}"
        f"&sortrule=distance"
        f"&extensions=base"
    )
    req = Request(url, headers={"User-Agent": "dududa/1.0"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def calc_distance_km(center: tuple[float, float], poi_location: str) -> float:
    """粗略计算距离（km）。"""
    try:
        lng, lat = map(float, poi_location.split(","))
        dx = (lng - center[0]) * 111 * 0.85  # 经度修正
        dy = (lat - center[1]) * 111
        return round((dx**2 + dy**2) ** 0.5, 2)
    except Exception:
        return 99.0


def infer_campus(poi_adname: str, poi_address: str) -> str:
    """根据地址推断校区归属。"""
    text = f"{poi_adname}{poi_address}"
    if "肥西" in text:
        return "肥西路"
    if "蜀山" in text:
        return "西区"
    if "包河" in text:
        return "东区"
    if "庐江" in text or "高新" in text:
        return "高新区"
    return "校外"


def infer_price(tags: str, name: str) -> str:
    """根据标签/名称推断价位。"""
    expensive_kw = ["自助", "烤肉", "日料", "料理", "牛排", "海鲜"]
    cheap_kw = ["小吃", "摊", "煎饼", "粥", "面", "粉", "饼"]
    for kw in expensive_kw:
        if kw in name or kw in tags:
            return "略贵"
    for kw in cheap_kw:
        if kw in name or kw in tags:
            return "平价"
    return "中档"


def fetch_all_campuses(radius: int = 15000) -> list[dict[str, Any]]:
    """抓取所有校区附近的餐饮 POI。"""
    all_pois: dict[str, dict[str, Any]] = {}  # id -> poi, 去重

    for campus_name, center in CAMPUS_CENTERS.items():
        print(f"正在抓取 {campus_name} 附近 {radius}m 餐饮...")
        for page in range(1, MAX_PAGES + 1):
            try:
                result = fetch_pois(center, radius, page)
            except Exception as exc:
                print(f"  第 {page} 页失败：{exc}")
                break

            if result.get("status") != "1":
                print(f"  API 错误：{result.get('info')}")
                break

            pois = result.get("pois") or []
            if not pois:
                break

            for poi in pois:
                poi_id = poi.get("id", "")
                if poi_id and poi_id not in all_pois:
                    poi["campus"] = campus_name
                    poi["distance_km"] = calc_distance_km(center, poi.get("location", "0,0"))
                    all_pois[poi_id] = poi

            if len(pois) < PAGE_SIZE:
                break
            time.sleep(0.15)  # 限速

        print(f"  {campus_name} 完成，累计 {len(all_pois)} 条")

    return list(all_pois.values())


def convert_to_recs(pois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将高德 POI 转为 local-recs 格式。"""
    recs = []
    seen_names: set[str] = set()

    for poi in pois:
        name = poi.get("name", "").strip()
        if not name or name in seen_names:
            continue

        # 过滤太远的（>15km）
        dist = poi.get("distance_km", 99)
        if dist > 15:
            continue

        # 过滤明显非餐饮的
        typecode = poi.get("typecode", "")
        if not typecode.startswith("050"):
            continue

        tags_raw = poi.get("type", "")
        atag = poi.get("atag", "")
        tel = poi.get("tel", "")
        address = poi.get("address", "")
        adname = poi.get("adname", "")

        campus = poi.get("campus", "校外")
        price = infer_price(tags_raw, name)
        detail_parts = []
        if atag:
            detail_parts.append(f"招牌：{atag[:60]}")
        if tel and tel != []:
            detail_parts.append(f"电话：{tel}")
        if address:
            detail_parts.append(address)
        if dist < 99:
            detail_parts.append(f"距{campus}约{dist}km")

        rec = {
            "kind": "food",
            "name": name,
            "detail": "；".join(detail_parts)[:200],
            "location": f"{adname}{address}".strip("[]") if address else adname,
            "score": 4.0,  # 高德无评分，默认4.0
            "proximity": f"距{campus}约{dist}km" if dist < 99 else "",
            "tags": [t.strip() for t in tags_raw.split(";") if t.strip()][:5],
            "source": "高德地图POI",
            "campus": campus,
            "meal_time": ["午餐", "晚餐"],
            "price_level": price,
        }
        recs.append(rec)
        seen_names.add(name)

    return recs


def import_to_db(recs: list[dict[str, Any]], db_path: str) -> int:
    """导入到 local-recs SQLite 数据库。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from local_recs_mcp.storage import RecommendationStore

    store = RecommendationStore(db_path)
    count = 0
    existing = store.list(kind="food", limit=500)
    existing_names = {r["name"] for r in existing}

    for rec in recs:
        if rec["name"] in existing_names:
            continue
        store.upsert(
            kind=rec["kind"],
            name=rec["name"],
            detail=rec["detail"],
            location=rec["location"],
            score=rec["score"],
            proximity=rec["proximity"],
            tags=rec["tags"],
            source=rec["source"],
            campus=rec["campus"],
            meal_time=rec["meal_time"],
            price_level=rec["price_level"],
        )
        count += 1

    return count


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch restaurant POIs from Amap near USTC.")
    parser.add_argument("--key", required=True, help="Amap Web Service API key")
    parser.add_argument("--radius", type=int, default=15000, help="Search radius in meters (default 15000)")
    parser.add_argument("--output", default="amap_pois.jsonl", help="Output JSONL file")
    parser.add_argument("--import-db", action="store_true", help="Import to local-recs database")
    parser.add_argument("--db-path", default=None, help="Database path (default: auto)")
    args = parser.parse_args(argv)

    global AMAP_KEY
    AMAP_KEY = args.key

    # 抓取
    pois = fetch_all_campuses(radius=args.radius)
    print(f"\n去重后共 {len(pois)} 条 POI")

    # 转换
    recs = convert_to_recs(pois)
    print(f"转换后 {len(recs)} 条推荐")

    # 写 JSONL
    out = Path(args.output)
    with out.open("w", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"已写入 {out}")

    # 导入数据库
    if args.import_db:
        db_path = args.db_path or str(
            Path(__file__).resolve().parents[2] / "local-recs-cache" / "local-recs.sqlite3"
        )
        count = import_to_db(recs, db_path)
        print(f"导入数据库 {count} 条（跳过已存在的）")


if __name__ == "__main__":
    main()