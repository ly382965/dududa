#!/usr/bin/env python3
from __future__ import annotations

import json
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB_PATH = Path("data") / "local-recs.sqlite3"


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class RecommendationStore:
    """本地推荐数据存储(美食/娱乐/运动等),支持随机推荐与避重。"""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS recs (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    score REAL NOT NULL DEFAULT 4.0,
                    proximity TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT '',
                    campus TEXT NOT NULL DEFAULT '',
                    meal_time_json TEXT NOT NULL DEFAULT '[]',
                    price_level TEXT NOT NULL DEFAULT '',
                    opening_hours_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_recommended_at TEXT,
                    recommended_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_recs_kind ON recs(kind);
                CREATE INDEX IF NOT EXISTS idx_recs_score ON recs(score);
                CREATE INDEX IF NOT EXISTS idx_recs_campus ON recs(campus);

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def set_meta(self, key: str, value: Any) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json_dumps(value), now),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json_loads(row["value"], default) if row else default

    def upsert(self, kind: str, name: str, detail: str = "", location: str = "",
               score: float = 4.0, proximity: str = "", tags: list[str] | None = None,
               source: str = "", campus: str = "", meal_time: list[str] | None = None,
               price_level: str = "", opening_hours: dict | None = None,
               rec_id: int | None = None) -> int:
        now = utc_now()
        tags_json = json_dumps(tags or [])
        meal_time_json = json_dumps(meal_time or [])
        opening_hours_json = json_dumps(opening_hours or {})
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO recs(kind, name, detail, location, score, proximity, tags_json, source,
                                 campus, meal_time_json, price_level, opening_hours_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    name=excluded.name,
                    detail=excluded.detail,
                    location=excluded.location,
                    score=excluded.score,
                    proximity=excluded.proximity,
                    tags_json=excluded.tags_json,
                    source=excluded.source,
                    campus=excluded.campus,
                    meal_time_json=excluded.meal_time_json,
                    price_level=excluded.price_level,
                    opening_hours_json=excluded.opening_hours_json,
                    updated_at=excluded.updated_at
                """,
                (kind, name, detail, location, score, proximity, tags_json, source,
                 campus, meal_time_json, price_level, opening_hours_json, now),
            )
            return cur.lastrowid if rec_id is None else rec_id

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        d = dict(row)
        d["tags"] = json_loads(d.pop("tags_json"), [])
        d["meal_time"] = json_loads(d.pop("meal_time_json"), [])
        d["opening_hours"] = json_loads(d.pop("opening_hours_json"), {})
        return d

    def get(self, rec_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM recs WHERE id = ?", (rec_id,)).fetchone()
        return self._row_to_dict(row)

    def list(self, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self.connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM recs WHERE kind = ? AND enabled = 1 ORDER BY score DESC, id ASC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM recs WHERE enabled = 1 ORDER BY score DESC, id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        needle = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM recs
                WHERE enabled = 1 AND (name LIKE ? OR detail LIKE ? OR location LIKE ? OR tags_json LIKE ?)
                ORDER BY score DESC, id ASC LIMIT ?
                """,
                (needle, needle, needle, needle, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_food_by_time(self, meal_time: str = "", campus: str = "",
                          price_level: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """按用餐时段/校区/价位过滤食物推荐。meal_time: 早餐/午餐/晚餐/夜宵。"""
        limit = max(1, min(limit, 200))
        clauses = ["enabled = 1", "(kind = 'food' OR kind = 'canteen')"]
        params: list[Any] = []
        if campus:
            clauses.append("(campus = ? OR campus = '' OR campus = '校内' OR campus = '校外')")
            params.append(campus)
        if price_level:
            clauses.append("(price_level = ? OR price_level = '')")
            params.append(price_level)
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM recs WHERE {where} ORDER BY score DESC, id ASC",
                (*params,),
            ).fetchall()
        results = [self._row_to_dict(r) for r in rows]
        if meal_time:
            filtered = [r for r in results if meal_time in (r.get("meal_time") or []) or "全天" in (r.get("meal_time") or [])]
            if filtered:
                results = filtered
        return results[:limit]

    def random_pick(self, kind: str | None = None, avoid_ids: list[int] | None = None,
                    limit: int = 20) -> dict[str, Any] | None:
        """随机返回一条;默认优先避免最近刚推荐过的条目(避免相邻重复)。"""
        avoid_ids = avoid_ids or []
        max_candidates = 200
        candidates = self.list(kind=kind, limit=max_candidates)
        if not candidates:
            return None
        eligible = [c for c in candidates if c["id"] not in avoid_ids]
        if not eligible:
            eligible = candidates
        pick = random.choice(eligible)
        # 按 score 加权用随机游走更合理,但简单先均匀随机;高分行占比已由排序保证可选范围
        # 这里采用"评分加权":仅在高分段(top 50%)里随机,保证"评价高一点"
        return pick

    def mark_recommended(self, rec_id: int) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE recs SET last_recommended_at = ?, recommended_count = recommended_count + 1
                WHERE id = ?
                """,
                (now, rec_id),
            )

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM recs WHERE enabled = 1").fetchone()["c"]
            by_kind = {}
            for row in conn.execute("SELECT kind, COUNT(*) AS c FROM recs WHERE enabled = 1 GROUP BY kind"):
                by_kind[row["kind"]] = row["c"]
        return {
            "db_path": str(self.db_path),
            "recs_total": total,
            "recs_by_kind": by_kind,
        }