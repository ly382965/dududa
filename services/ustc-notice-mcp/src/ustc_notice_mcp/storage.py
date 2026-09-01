from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import NoticeDetail, NoticeItem


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class NoticeStore:
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
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notices (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT,
                    last_modified TEXT,
                    category TEXT,
                    content_text TEXT NOT NULL DEFAULT '',
                    content_html TEXT NOT NULL DEFAULT '',
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    source_hash TEXT,
                    fetched_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_notices_published ON notices(published_at);
                CREATE INDEX IF NOT EXISTS idx_notices_title ON notices(title);

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

    def upsert_notice(self, notice: NoticeItem) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notices(id, title, url, published_at, category, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    category=excluded.category,
                    updated_at=excluded.updated_at
                """,
                (notice.notice_id, notice.title, notice.url, notice.published_at, notice.category, now),
            )

    def upsert_notice_detail(self, detail: NoticeDetail) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notices(id, title, url, published_at, last_modified, category,
                                    content_text, content_html, attachments_json, source_hash, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    last_modified=excluded.last_modified,
                    category=excluded.category,
                    content_text=excluded.content_text,
                    content_html=excluded.content_html,
                    attachments_json=excluded.attachments_json,
                    source_hash=excluded.source_hash,
                    fetched_at=excluded.fetched_at,
                    updated_at=excluded.updated_at
                """,
                (
                    detail.notice_id,
                    detail.title,
                    detail.url,
                    detail.published_at,
                    detail.last_modified,
                    detail.category,
                    detail.content_text,
                    detail.content_html,
                    json_dumps(detail.attachments),
                    detail.source_hash,
                    now,
                    now,
                ),
            )

    def list_notices(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, url, published_at, category,
                       (fetched_at IS NOT NULL) AS has_detail
                FROM notices ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_notice(self, notice_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
            if not row:
                return None
            notice = dict(row)
            notice["attachments"] = json_loads(notice.pop("attachments_json"), [])
            return notice

    def search_notices(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        needle = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, url, published_at, category,
                       (fetched_at IS NOT NULL) AS has_detail
                FROM notices
                WHERE title LIKE ? OR content_text LIKE ?
                ORDER BY published_at DESC, id DESC
                LIMIT ?
                """,
                (needle, needle, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM notices").fetchone()["c"]
            detailed = conn.execute(
                "SELECT COUNT(*) AS c FROM notices WHERE fetched_at IS NOT NULL"
            ).fetchone()["c"]
            last_fetch = conn.execute(
                "SELECT MAX(fetched_at) AS t FROM notices WHERE fetched_at IS NOT NULL"
            ).fetchone()["t"]
            latest_published = conn.execute(
                "SELECT MAX(published_at) AS d FROM notices WHERE published_at IS NOT NULL"
            ).fetchone()["d"]
        return {
            "db_path": str(self.db_path),
            "notices_known": total,
            "notices_fetched": detailed,
            "latest_published_at": latest_published,
            "last_fetched_at": last_fetch,
        }