#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from local_recs_mcp.storage import RecommendationStore  # noqa: E402

SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")


def log(msg: str) -> None:
    """打印到 stderr, 避免污染 stdio 的 JSON-RPC 通道。"""
    print(msg, file=sys.stderr, flush=True)


def auto_seed_if_empty(db_path: str) -> None:
    """若数据库为空且存在种子文件, 自动导入种子数据。"""
    store = RecommendationStore(db_path)
    stats = store.stats()
    if stats["recs_total"] > 0:
        log(f"[auto-seed] skip (already {stats['recs_total']} records)")
        return
    import json

    for fname in ("food.jsonl", "activity.jsonl", "study.jsonl"):
        path = os.path.join(SEED_DIR, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                store.upsert(
                    kind=item.get("kind", "food"),
                    name=item.get("name", ""),
                    detail=item.get("detail", ""),
                    location=item.get("location", ""),
                    score=float(item.get("score", 4.0)),
                    proximity=item.get("proximity", ""),
                    tags=item.get("tags"),
                    source=item.get("source", "seed"),
                )
        log(f"[auto-seed] imported {fname}")


def main(argv: list[str] | None = None) -> None:
    from local_recs_mcp.server import main as server_main

    db_path = "/AstrBot/data/local-recs-cache/local-recs.sqlite3"
    if argv:
        try:
            idx = argv.index("--db-path")
            if idx + 1 < len(argv):
                db_path = argv[idx + 1]
        except ValueError:
            pass
    try:
        auto_seed_if_empty(db_path)
    except Exception as e:  # 不影响服务启动
        log(f"[auto-seed] skipped: {e}")
    server_main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])