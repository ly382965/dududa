from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import EventDetail, EventItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    content_text TEXT NOT NULL DEFAULT '',
    attachments_json TEXT NOT NULL DEFAULT '[]',
    source_hash TEXT,
    fetched_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_pub ON events(published_at);
CREATE INDEX IF NOT EXISTS idx_events_title ON events(title);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
"""


class CampusEventStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.init_schema()
        self.db_path.chmod(0o600)

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

    def upsert_item(self, item: EventItem) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events(event_id, category, title, url, published_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    category=CASE WHEN excluded.category='综合' THEN events.category ELSE excluded.category END,
                    title=excluded.title,
                    url=excluded.url,
                    published_at=COALESCE(excluded.published_at, events.published_at),
                    updated_at=excluded.updated_at
                """,
                (item.event_id, item.category, item.title, item.url, item.published_at, now),
            )

    def upsert_detail(self, detail: EventDetail) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events(event_id, category, title, url, published_at,
                                   content_text, attachments_json, source_hash, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    category=excluded.category,
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
                    detail.event_id,
                    detail.category,
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

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["attachments"] = json.loads(item.pop("attachments_json") or "[]")
        return item

    def list_events(
        self, category: str | None = None, limit: int = 50, detail_only: bool = False
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        sql = "SELECT * FROM events"
        where: list[str] = []
        params: list[Any] = []
        if category:
            where.append("category = ?")
            params.append(category)
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

    def search(self, query: str, category: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        needle = f"%{query}%"
        sql = "SELECT * FROM events WHERE (title LIKE ? OR content_text LIKE ?)"
        params: list[Any] = [needle, needle]
        if category:
            sql += " AND category = ?"
            params.append(category)
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
            observed = conn.execute("SELECT MAX(updated_at) FROM events").fetchone()[0]
            total = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
            details = conn.execute("SELECT COUNT(*) AS c FROM events WHERE content_text != ''").fetchone()["c"]
            categories = conn.execute(
                "SELECT category, COUNT(*) AS c FROM events GROUP BY category ORDER BY c DESC"
            ).fetchall()
            latest = conn.execute(
                "SELECT MAX(COALESCE(published_at, updated_at)) AS t FROM events"
            ).fetchone()["t"]
        return {
            "events_known": total,
            "last_fetched_at": observed,
            "events_detail_fetched": details,
            "categories": [dict(row) for row in categories],
            "latest_at": latest,
        }
