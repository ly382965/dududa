from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import CollegeNoticeDetail, CollegeNoticeItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    notice_id TEXT PRIMARY KEY,
    college_key TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    content_text TEXT NOT NULL DEFAULT '',
    attachments_json TEXT NOT NULL DEFAULT '[]',
    source_hash TEXT,
    fetched_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notices_college ON notices(college_key);
CREATE INDEX IF NOT EXISTS idx_notices_pub ON notices(published_at);
CREATE INDEX IF NOT EXISTS idx_notices_title ON notices(title);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
"""


class CollegeNoticeStore:
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
            conn.executescript(SCHEMA)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def set_meta(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), self._now()),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def upsert_item(self, item: CollegeNoticeItem) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notices(notice_id, college_key, title, url, published_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(notice_id) DO UPDATE SET
                    college_key=excluded.college_key,
                    title=excluded.title,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    updated_at=excluded.updated_at
                """,
                (item.notice_id, item.college_key, item.title, item.url, item.published_at, now),
            )

    def upsert_detail(self, detail: CollegeNoticeDetail) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notices(notice_id, college_key, title, url, published_at,
                                    content_text, attachments_json, source_hash, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(notice_id) DO UPDATE SET
                    college_key=excluded.college_key,
                    title=excluded.title,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    content_text=excluded.content_text,
                    attachments_json=excluded.attachments_json,
                    source_hash=excluded.source_hash,
                    fetched_at=excluded.fetched_at,
                    updated_at=excluded.updated_at
                """,
                (
                    detail.notice_id,
                    detail.college_key,
                    detail.title,
                    detail.url,
                    detail.published_at,
                    detail.content_text,
                    json.dumps(detail.attachments, ensure_ascii=False, separators=(",", ":")),
                    detail.source_hash,
                    now,
                    now,
                ),
            )

    def get_notice(self, notice_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM notices WHERE notice_id = ?", (notice_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
        return item

    def list_notices(
        self, college_key: str | None = None, limit: int = 50, detail_only: bool = False
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        sql = "SELECT * FROM notices"
        where: list[str] = []
        params: list[Any] = []
        if college_key:
            where.append("college_key = ?")
            params.append(college_key)
        if detail_only:
            where.append("content_text != ''")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(published_at, updated_at) DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
            result.append(item)
        return result

    def search(self, query: str, college_key: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        needle = f"%{query}%"
        sql = "SELECT * FROM notices WHERE (title LIKE ? OR content_text LIKE ?)"
        params: list[Any] = [needle, needle]
        if college_key:
            sql += " AND college_key = ?"
            params.append(college_key)
        sql += " ORDER BY COALESCE(published_at, updated_at) DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
            result.append(item)
        return result

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM notices").fetchone()["c"]
            details = conn.execute("SELECT COUNT(*) AS c FROM notices WHERE content_text != ''").fetchone()["c"]
            colleges = conn.execute(
                "SELECT college_key, COUNT(*) AS c FROM notices GROUP BY college_key ORDER BY c DESC"
            ).fetchall()
            latest = conn.execute(
                "SELECT MAX(COALESCE(published_at, updated_at)) AS t FROM notices"
            ).fetchone()["t"]
        return {
            "db_path": str(self.db_path),
            "notices_known": total,
            "notices_detail_fetched": details,
            "colleges": [dict(row) for row in colleges],
            "latest_at": latest,
        }
