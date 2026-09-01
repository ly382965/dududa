from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .storage import RecommendationStore


def emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local campus recommendations management utility.")
    parser.add_argument("--db-path", default=None, help="SQLite database path.")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Show local cache stats.")

    add = sub.add_parser("add", help="Add one recommendation.")
    add.add_argument("--kind", required=True, choices=["food", "activity", "study"], help="kind of recommendation")
    add.add_argument("--name", required=True, help="name, e.g. 桃李苑铁板意面")
    add.add_argument("--detail", default="", help="concrete detail, e.g. 黑椒味五花肉铁板意面")
    add.add_argument("--location", default="", help="where, e.g. 肥西路 / 中区食堂")
    add.add_argument("--score", type=float, default=4.0, help="rating, default 4.0")
    add.add_argument("--proximity", default="", help="distance hint, e.g. 距东区西门300米")
    add.add_argument("--tag", action="append", default=[], help="tag, repeatable")
    add.add_argument("--source", default="manual", help="source ref")

    import_json = sub.add_parser("import", help="Import recommendations from JSONL file.")
    import_json.add_argument("file", help="path to JSONL")

    template = sub.add_parser("template", help="Write an empty JSONL template file.")
    template.add_argument("output", help="output path")

    list_cmd = sub.add_parser("list", help="List recommendations.")
    list_cmd.add_argument("--kind", default=None)
    list_cmd.add_argument("--limit", type=int, default=100)

    backfill = sub.add_parser("backfill-meta", help="(reserved) recompute meta from existing rows")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = AppConfig.from_args(db_path=args.db_path)
    store = RecommendationStore(config.db_path)
    if args.command == "stats":
        emit(store.stats())
    elif args.command == "add":
        rec_id = store.upsert(
            kind=args.kind,
            name=args.name,
            detail=args.detail,
            location=args.location,
            score=args.score,
            proximity=args.proximity,
            tags=args.tag,
            source=args.source,
        )
        emit({"ok": True, "id": rec_id, "recommendation": store.get(rec_id)})
    elif args.command == "import":
        count = 0
        with Path(args.file).open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec_id = store.upsert(
                    kind=item.get("kind", "food"),
                    name=item.get("name", ""),
                    detail=item.get("detail", ""),
                    location=item.get("location", ""),
                    score=float(item.get("score", 4.0)),
                    proximity=item.get("proximity", ""),
                    tags=item.get("tags"),
                    source=item.get("source", "import"),
                    campus=item.get("campus", ""),
                    meal_time=item.get("meal_time"),
                    price_level=item.get("price_level", ""),
                    opening_hours=item.get("opening_hours"),
                )
                if rec_id:
                    count += 1
        emit({"ok": True, "imported": count, "file": args.file})
    elif args.command == "template":
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        sample = {
            "kind": "food",
            "name": "示例：肥西路巴蜀人家",
            "detail": "烤鱼 / 辣子鸡，评价高",
            "location": "肥西路",
            "score": 4.6,
            "proximity": "距中区宿舍约400米",
            "tags": ["川菜", "聚餐"],
            "source": "ustcguide",
        }
        out.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")
        emit({"ok": True, "template_written": str(out)})
    elif args.command == "list":
        emit({"recommendations": store.list(kind=args.kind, limit=args.limit)})


if __name__ == "__main__":
    main()