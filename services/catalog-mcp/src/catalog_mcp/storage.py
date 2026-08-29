from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def _norm(s: str | None) -> str:
    return (s or "").lower().replace(" ", "").replace("　", "")


class CatalogStore:
    """SQLite cache of one or more semesters of public lesson data."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS semesters(
                id INTEGER PRIMARY KEY,
                code TEXT,
                name_zh TEXT,
                start TEXT,
                end TEXT,
                is_last INTEGER
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS lessons(
                semester INTEGER NOT NULL,
                code TEXT,
                course_code TEXT,
                name_zh TEXT,
                name_en TEXT,
                credits REAL,
                period INTEGER,
                periods_per_week INTEGER,
                date_time_place_text TEXT,
                location_time_cn TEXT,
                std_count INTEGER,
                limit_count INTEGER,
                campus_zh TEXT,
                dept_zh TEXT,
                exam_mode_zh TEXT,
                teachers_zh TEXT,
                admin_classes TEXT,
                raw TEXT,
                PRIMARY KEY(semester, code)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lessons_name ON lessons(name_zh)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lessons_course_code ON lessons(course_code)")

    def upsert_semesters(self, semesters: list[dict[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO semesters(id, code, name_zh, start, end, is_last)
                   VALUES(?,?,?,?,?,?)""",
                [
                    (
                        s.get("id"),
                        s.get("code"),
                        s.get("nameZh"),
                        s.get("start"),
                        s.get("end"),
                        1 if s.get("isLast") else 0,
                    )
                    for s in semesters
                ],
            )

    def replace_semester_lessons(self, semester: int, lessons: list[dict[str, Any]]) -> int:
        with self._connect() as conn:
            conn.execute("DELETE FROM lessons WHERE semester = ?", (semester,))
            rows = []
            for l in lessons:
                course = l.get("course") or {}
                teachers = l.get("teacherAssignmentList") or []
                admins = l.get("adminClasses") or []
                date_person = l.get("dateTimePlacePersonText") or {}
                rows.append(
                    (
                        semester,
                        l.get("code"),
                        course.get("code"),
                        course.get("cn"),
                        course.get("en"),
                        l.get("credits"),
                        l.get("period"),
                        l.get("periodsPerWeek"),
                        l.get("dateTimePlaceText"),
                        date_person.get("cn"),
                        l.get("stdCount"),
                        l.get("limitCount"),
                        (l.get("campus") or {}).get("cn"),
                        (l.get("openDepartment") or {}).get("cn"),
                        (l.get("examMode") or {}).get("cn"),
                        ",".join(t.get("cn") or "" for t in teachers),
                        ",".join(a.get("cn") or "" for a in admins),
                        json.dumps(l, ensure_ascii=False),
                    )
                )
            conn.executemany(
                """INSERT OR REPLACE INTO lessons(
                    semester, code, course_code, name_zh, name_en, credits, period,
                    periods_per_week, date_time_place_text, location_time_cn,
                    std_count, limit_count, campus_zh, dept_zh, exam_mode_zh,
                    teachers_zh, admin_classes, raw)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)

    def all_semesters(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM semesters ORDER BY start DESC").fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
            sems = conn.execute(
                "SELECT semester, COUNT(*) AS n FROM lessons GROUP BY semester ORDER BY semester DESC"
            ).fetchall()
            return {"total_lessons": total, "by_semester": [dict(r) for r in sems]}

    def search(self, query: str, semester: int | None = None, limit: int = 10) -> list[dict[str, Any]]:
        q = _norm(query)
        if not q:
            return []
        with self._connect() as conn:
            params: list[Any] = []
            sql = "SELECT * FROM lessons"
            clauses = []
            if semester:
                clauses.append("semester = ?")
                params.append(semester)
            # match by course code or name (zh). english fallback omitted for simplicity.
            clauses.append("(course_code LIKE ? OR name_zh LIKE ? OR code LIKE ? OR name_en LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like, like])
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY semester DESC, course_code LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["raw"] = json.loads(d["raw"])
                except Exception:
                    d["raw"] = None
                out.append(d)
            return out

    def get_by_code(self, code: str, semester: int | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if semester:
                rows = conn.execute(
                    "SELECT * FROM lessons WHERE code = ? AND semester = ?", (code, semester)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM lessons WHERE code = ?", (code,)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["raw"] = json.loads(d["raw"])
                except Exception:
                    d["raw"] = None
                out.append(d)
            return out
