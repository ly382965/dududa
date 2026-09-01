from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import PlanRow, PlanYear

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_years (
    year INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    discontinued_count INTEGER NOT NULL DEFAULT 0,
    source_hash TEXT,
    fetched_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS program_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    college TEXT NOT NULL,
    dept TEXT,
    major TEXT NOT NULL,
    code TEXT,
    degree TEXT,
    discontinued INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(year) REFERENCES plan_years(year) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rows_year ON program_rows(year);
CREATE INDEX IF NOT EXISTS idx_rows_college ON program_rows(college);
CREATE INDEX IF NOT EXISTS idx_rows_major ON program_rows(major);
CREATE INDEX IF NOT EXISTS idx_rows_code ON program_rows(code);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
"""


class TrainingPlanStore:
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

    @staticmethod
    def _meta_set(conn: sqlite3.Connection, key: str, value: Any, now: str) -> None:
        import json

        conn.execute(
            """
            INSERT INTO meta(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), now),
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

    def replace_year(
        self, year: PlanYear, rows: list[PlanRow], source_hash: str | None = None
    ) -> None:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO plan_years(year, title, discontinued_count, source_hash, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(year) DO UPDATE SET
                    title=excluded.title,
                    discontinued_count=excluded.discontinued_count,
                    source_hash=excluded.source_hash,
                    fetched_at=excluded.fetched_at,
                    updated_at=excluded.updated_at
                """,
                (year.year, year.title, year.discontinued_count, source_hash, now, now),
            )
            conn.execute("DELETE FROM program_rows WHERE year = ?", (year.year,))
            conn.executemany(
                """
                INSERT INTO program_rows(year, college, dept, major, code, degree, discontinued)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (row.year, row.college, row.dept, row.major, row.code, row.degree, int(row.discontinued))
                    for row in rows
                ],
            )

    def replace_all(self, years: list[PlanYear], rows: list[PlanRow], source_hash: str | None = None) -> dict[str, Any]:
        now = self._now()
        with self.connect() as conn:
            conn.execute("DELETE FROM plan_years")
            conn.execute("DELETE FROM program_rows")
            for year in years:
                conn.execute(
                    """
                    INSERT INTO plan_years(year, title, discontinued_count, source_hash, fetched_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (year.year, year.title, year.discontinued_count, source_hash, now, now),
                )
            conn.executemany(
                """
                INSERT INTO program_rows(year, college, dept, major, code, degree, discontinued)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (row.year, row.college, row.dept, row.major, row.code, row.degree, int(row.discontinued))
                    for row in rows
                ],
            )
        counts: dict[int, int] = {}
        for row in rows:
            counts[row.year] = counts.get(row.year, 0) + 1
        return {"years": len(years), "rows": len(rows), "per_year": counts}

    def list_years(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT y.year, y.title, y.discontinued_count, y.fetched_at,
                       (SELECT COUNT(*) FROM program_rows r WHERE r.year = y.year) AS row_count
                FROM plan_years y ORDER BY y.year DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def majors_by_year(self, year: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT year, college, dept, major, code, degree, discontinued FROM program_rows"
        params: list[Any] = []
        if year is not None:
            sql += " WHERE year = ?"
            params.append(year)
        sql += " ORDER BY year DESC, college, dept, id"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def majors_by_college(self, college: str, year: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT year, college, dept, major, code, degree, discontinued FROM program_rows WHERE college = ?"
        params: list[Any] = [college]
        if year is not None:
            sql += " AND year = ?"
            params.append(year)
        sql += " ORDER BY year DESC, dept, id"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def search_majors(self, query: str, year: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
        needle = f"%{query}%"
        sql = (
            "SELECT year, college, dept, major, code, degree, discontinued FROM program_rows "
            "WHERE major LIKE ? OR college LIKE ? OR dept LIKE ? OR code LIKE ?"
        )
        params: list[Any] = [needle, needle, needle, needle]
        if year is not None:
            sql += " AND year = ?"
            params.append(year)
        sql += " ORDER BY year DESC, college LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def colleges(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT college FROM program_rows ORDER BY college"
            ).fetchall()
        return [{"college": row["college"]} for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            years = conn.execute("SELECT COUNT(*) AS c FROM plan_years").fetchone()["c"]
            rows = conn.execute("SELECT COUNT(*) AS c FROM program_rows").fetchone()["c"]
            colleges = conn.execute("SELECT COUNT(DISTINCT college) AS c FROM program_rows").fetchone()["c"]
            majors = conn.execute(
                "SELECT COUNT(DISTINCT major || '|' || college) AS c FROM program_rows"
            ).fetchone()["c"]
            latest = conn.execute("SELECT MAX(fetched_at) AS t FROM plan_years").fetchone()["t"]
            latest_year = conn.execute("SELECT MAX(year) AS y FROM plan_years").fetchone()["y"]
        return {
            "db_path": str(self.db_path),
            "years": years,
            "rows": rows,
            "colleges": colleges,
            "distinct_majors": majors,
            "latest_year": latest_year,
            "last_fetched_at": latest,
        }