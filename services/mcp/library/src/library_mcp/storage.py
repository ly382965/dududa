from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import HoursRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus TEXT NOT NULL,
    location TEXT NOT NULL,
    service TEXT NOT NULL,
    weekday TEXT,
    weekend TEXT,
    phone TEXT,
    source_hash TEXT,
    fetched_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(campus, location, service)
);
CREATE INDEX IF NOT EXISTS idx_hours_campus ON hours(campus);
CREATE INDEX IF NOT EXISTS idx_hours_service ON hours(service);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
"""


class LibraryStore:
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
        import json

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), self._now()),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        import json

        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def replace_hours(self, rows: list[HoursRow], source_hash: str | None = None) -> dict[str, Any]:
        now = self._now()
        with self.connect() as conn:
            conn.execute("DELETE FROM hours")
            conn.executemany(
                """
                INSERT INTO hours(campus, location, service, weekday, weekend, phone, source_hash, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.campus,
                        row.location,
                        row.service,
                        row.weekday,
                        row.weekend,
                        row.phone,
                        source_hash,
                        now,
                        now,
                    )
                    for row in rows
                ],
            )
        campuses: dict[str, int] = {}
        for row in rows:
            campuses[row.campus] = campuses.get(row.campus, 0) + 1
        return {"rows": len(rows), "campuses": campuses}

    def all_hours(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT campus, location, service, weekday, weekend, phone FROM hours ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def by_campus(self, campus: str) -> list[dict[str, Any]]:
        needle = f"%{campus}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT campus, location, service, weekday, weekend, phone FROM hours
                WHERE campus LIKE ? ORDER BY id
                """,
                (needle,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        needle = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT campus, location, service, weekday, weekend, phone FROM hours
                WHERE service LIKE ? OR location LIKE ? ORDER BY id LIMIT ?
                """,
                (needle, needle, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM hours").fetchone()["c"]
            campuses = conn.execute(
                "SELECT campus, COUNT(*) AS c FROM hours GROUP BY campus ORDER BY c DESC"
            ).fetchall()
            latest = conn.execute("SELECT MAX(fetched_at) AS t FROM hours").fetchone()["t"]
        return {
            "hours_rows": total,
            "campuses": [dict(row) for row in campuses],
            "last_fetched_at": latest,
        }
