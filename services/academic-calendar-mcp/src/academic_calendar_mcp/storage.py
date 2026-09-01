from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import CalendarDay, TermCalendar, TermListing


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


class CalendarStore:
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
                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT,
                    base_year INTEGER NOT NULL,
                    notes_json TEXT NOT NULL DEFAULT '[]',
                    source_hash TEXT,
                    fetched_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    week_label TEXT,
                    event_name TEXT,
                    is_off_day INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(term_id) REFERENCES terms(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
                CREATE INDEX IF NOT EXISTS idx_events_name ON events(event_name);
                CREATE INDEX IF NOT EXISTS idx_events_term ON events(term_id);

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

    def upsert_term_listing(self, listing: TermListing) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO terms(id, name, url, published_at, base_year, notes_json, updated_at)
                VALUES (?, ?, ?, ?, ?, '[]', ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    base_year=excluded.base_year,
                    updated_at=excluded.updated_at
                """,
                (
                    listing.term_id,
                    listing.name,
                    listing.url,
                    listing.published_at,
                    self._base_year_from_name(listing.name),
                    now,
                ),
            )

    def upsert_term(
        self,
        term: TermCalendar,
        source_hash: str | None = None,
        published_at: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO terms(id, name, url, published_at, base_year, notes_json, source_hash, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    url=excluded.url,
                    published_at=excluded.published_at,
                    base_year=excluded.base_year,
                    notes_json=excluded.notes_json,
                    source_hash=excluded.source_hash,
                    fetched_at=excluded.fetched_at,
                    updated_at=excluded.updated_at
                """,
                (
                    term.term_id,
                    term.name,
                    term.url,
                    published_at,
                    term.base_year,
                    json_dumps(term.notes),
                    source_hash,
                    now,
                    now,
                ),
            )
            conn.execute("DELETE FROM events WHERE term_id = ?", (term.term_id,))
            for day in term.days:
                self._insert_day_conn(conn, term.term_id, day)

    def _insert_day_conn(self, conn: sqlite3.Connection, term_id: int, day: CalendarDay) -> None:
        conn.execute(
            """
            INSERT INTO events(term_id, date, year, month, day, week_label, event_name, is_off_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                term_id,
                day.date,
                day.year,
                day.month,
                day.day_of_month,
                day.week_label,
                day.event_name,
                int(day.is_off_day),
            ),
        )

    def list_terms(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, url, published_at, fetched_at,
                       (SELECT COUNT(*) FROM events e WHERE e.term_id = terms.id) AS event_count
                FROM terms ORDER BY id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_term(self, name_or_id: str | int) -> dict[str, Any] | None:
        with self.connect() as conn:
            if isinstance(name_or_id, int) or name_or_id.isdigit():
                row = conn.execute("SELECT * FROM terms WHERE id = ?", (int(name_or_id),)).fetchone()
            else:
                row = conn.execute("SELECT * FROM terms WHERE name = ?", (name_or_id,)).fetchone()
            if not row:
                return None
            term = dict(row)
            term["notes"] = json_loads(term.pop("notes_json"), [])
            events = conn.execute(
                "SELECT date, week_label, event_name, is_off_day FROM events WHERE term_id = ? ORDER BY date",
                (term["id"],),
            ).fetchall()
            term["events"] = [
                {
                    "date": event["date"],
                    "week_label": event["week_label"],
                    "event_name": event["event_name"],
                    "is_off_day": bool(event["is_off_day"]),
                }
                for event in events
            ]
            return term

    def get_events_on(self, event_date: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT e.date, e.week_label, e.event_name, e.is_off_day,
                       t.id AS term_id, t.name AS term_name, t.url AS term_url
                FROM events e JOIN terms t ON t.id = e.term_id
                WHERE e.date = ? ORDER BY e.term_id
                """,
                (event_date,),
            ).fetchall()
        return [
            {
                "date": row["date"],
                "week_label": row["week_label"],
                "event_name": row["event_name"],
                "is_off_day": bool(row["is_off_day"]),
                "term_id": row["term_id"],
                "term_name": row["term_name"],
                "term_url": row["term_url"],
            }
            for row in rows
        ]

    def search_events(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        needle = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT e.date, e.week_label, e.event_name, e.is_off_day,
                       t.id AS term_id, t.name AS term_name
                FROM events e JOIN terms t ON t.id = e.term_id
                WHERE e.event_name LIKE ?
                ORDER BY e.date DESC
                LIMIT ?
                """,
                (needle, limit),
            ).fetchall()
        return [
            {
                "date": row["date"],
                "week_label": row["week_label"],
                "event_name": row["event_name"],
                "is_off_day": bool(row["is_off_day"]),
                "term_id": row["term_id"],
                "term_name": row["term_name"],
            }
            for row in rows
        ]

    def get_current_term(self, today: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT t.id, t.name
                FROM terms t JOIN events e ON e.term_id = t.id
                WHERE t.fetched_at IS NOT NULL
                  AND e.date <= ?
                ORDER BY t.id DESC, e.date DESC
                """,
                (today,),
            ).fetchall()
        if not rows:
            return None
        candidate_terms: list[int] = []
        seen: set[int] = set()
        for row in rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                candidate_terms.append(row["id"])
        for term_id in candidate_terms:
            term_events = self.get_term(term_id)
            if not term_events:
                continue
            dates = [item["date"] for item in term_events["events"]]
            if dates and dates[0] <= today <= dates[-1]:
                return term_events
        return None

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            term_count = conn.execute("SELECT COUNT(*) AS c FROM terms").fetchone()["c"]
            fetched_count = conn.execute(
                "SELECT COUNT(*) AS c FROM terms WHERE fetched_at IS NOT NULL"
            ).fetchone()["c"]
            event_count = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
            off_day_count = conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE is_off_day = 1"
            ).fetchone()["c"]
            date_min = conn.execute("SELECT MIN(date) AS d FROM events").fetchone()["d"]
            date_max = conn.execute("SELECT MAX(date) AS d FROM events").fetchone()["d"]
            last_fetch = conn.execute(
                "SELECT MAX(fetched_at) AS t FROM terms WHERE fetched_at IS NOT NULL"
            ).fetchone()["t"]
        return {
            "db_path": str(self.db_path),
            "terms_known": term_count,
            "terms_fetched": fetched_count,
            "dated_events": event_count,
            "off_days": off_day_count,
            "events_date_min": date_min,
            "events_date_max": date_max,
            "last_fetched_at": last_fetch,
        }

    def export_jsonl(self, output_path: Path | str) -> dict[str, Any]:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with self.connect() as conn, output.open("w", encoding="utf-8") as handle:
            rows = conn.execute("SELECT id FROM terms WHERE fetched_at IS NOT NULL ORDER BY id").fetchall()
            for row in rows:
                term = self.get_term(row["id"])
                if term:
                    handle.write(json.dumps(term, ensure_ascii=False) + "\n")
                    count += 1
        return {"output_path": str(output), "terms_exported": count}

    @staticmethod
    def _base_year_from_name(name: str) -> int:
        import re

        match = re.search(r"(\d{4})\s*年", name)
        return int(match.group(1)) if match else 0