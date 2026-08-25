from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import Course, CourseListItem, Review, Teacher


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


class ICourseStore:
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
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    teachers_json TEXT NOT NULL DEFAULT '[]',
                    term_text TEXT,
                    term_ids_json TEXT NOT NULL DEFAULT '[]',
                    courseries TEXT,
                    dept TEXT,
                    course_type TEXT,
                    join_type TEXT,
                    teaching_type TEXT,
                    course_level TEXT,
                    credit REAL,
                    homepage TEXT,
                    introduction_html TEXT,
                    introduction_text TEXT,
                    summary_html TEXT,
                    summary_text TEXT,
                    rating_average REAL,
                    review_count_site INTEGER,
                    visible_review_count INTEGER,
                    difficulty TEXT,
                    homework TEXT,
                    grading TEXT,
                    gain TEXT,
                    source_hash TEXT,
                    detail_crawled_at TEXT,
                    list_crawled_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS teachers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    dept TEXT,
                    homepage TEXT,
                    image TEXT,
                    source_url TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS course_teachers (
                    course_id INTEGER NOT NULL,
                    teacher_key TEXT NOT NULL,
                    teacher_id INTEGER,
                    teacher_name TEXT NOT NULL,
                    PRIMARY KEY (course_id, teacher_key),
                    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY,
                    course_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    author_display TEXT,
                    is_anonymous INTEGER NOT NULL DEFAULT 0,
                    term TEXT,
                    rating_10 INTEGER,
                    difficulty TEXT,
                    homework TEXT,
                    grading TEXT,
                    gain TEXT,
                    content_html TEXT,
                    content_text TEXT,
                    publish_time TEXT,
                    update_time TEXT,
                    upvote_count INTEGER,
                    comment_count INTEGER,
                    crawled_at TEXT NOT NULL,
                    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS crawl_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_courses_name ON courses(name);
                CREATE INDEX IF NOT EXISTS idx_courses_dept ON courses(dept);
                CREATE INDEX IF NOT EXISTS idx_courses_rating ON courses(rating_average);
                CREATE INDEX IF NOT EXISTS idx_reviews_course ON reviews(course_id);
                CREATE INDEX IF NOT EXISTS idx_reviews_term ON reviews(term);
                """
            )

    def set_meta(self, key: str, value: Any) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO crawl_meta(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json_dumps(value), now),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM crawl_meta WHERE key = ?", (key,)).fetchone()
        return json_loads(row["value"], default) if row else default

    def upsert_course_list_item(self, item: CourseListItem) -> None:
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM courses WHERE id = ?", (item.id,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE courses
                    SET name=COALESCE(NULLIF(?, ''), name),
                        url=?,
                        teachers_json=CASE
                            WHEN detail_crawled_at IS NULL THEN ?
                            ELSE teachers_json
                        END,
                        term_text=COALESCE(?, term_text),
                        rating_average=COALESCE(?, rating_average),
                        review_count_site=COALESCE(?, review_count_site),
                        difficulty=COALESCE(?, difficulty),
                        homework=COALESCE(?, homework),
                        grading=COALESCE(?, grading),
                        gain=COALESCE(?, gain),
                        list_crawled_at=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        item.name,
                        item.url,
                        json_dumps([{"id": None, "name": name} for name in item.teachers]),
                        item.term_text,
                        item.rating_average,
                        item.review_count,
                        item.difficulty,
                        item.homework,
                        item.grading,
                        item.gain,
                        now,
                        now,
                        item.id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO courses(
                        id, name, url, teachers_json, term_text, rating_average,
                        review_count_site, difficulty, homework, grading, gain,
                        list_crawled_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.name,
                        item.url,
                        json_dumps([{"id": None, "name": name} for name in item.teachers]),
                        item.term_text,
                        item.rating_average,
                        item.review_count,
                        item.difficulty,
                        item.homework,
                        item.grading,
                        item.gain,
                        now,
                        now,
                    ),
                )

    def upsert_course(self, course: Course, source_hash: str | None = None) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO courses(
                    id, name, url, teachers_json, term_text, term_ids_json, courseries,
                    dept, course_type, join_type, teaching_type, course_level, credit,
                    homepage, introduction_html, introduction_text, summary_html, summary_text,
                    rating_average, review_count_site, visible_review_count,
                    difficulty, homework, grading, gain, source_hash, detail_crawled_at,
                    updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    url=excluded.url,
                    teachers_json=excluded.teachers_json,
                    term_text=excluded.term_text,
                    term_ids_json=excluded.term_ids_json,
                    courseries=excluded.courseries,
                    dept=excluded.dept,
                    course_type=excluded.course_type,
                    join_type=excluded.join_type,
                    teaching_type=excluded.teaching_type,
                    course_level=excluded.course_level,
                    credit=excluded.credit,
                    homepage=excluded.homepage,
                    introduction_html=excluded.introduction_html,
                    introduction_text=excluded.introduction_text,
                    summary_html=excluded.summary_html,
                    summary_text=excluded.summary_text,
                    rating_average=excluded.rating_average,
                    review_count_site=excluded.review_count_site,
                    visible_review_count=excluded.visible_review_count,
                    difficulty=excluded.difficulty,
                    homework=excluded.homework,
                    grading=excluded.grading,
                    gain=excluded.gain,
                    source_hash=excluded.source_hash,
                    detail_crawled_at=excluded.detail_crawled_at,
                    updated_at=excluded.updated_at
                """,
                (
                    course.id,
                    course.name,
                    course.url,
                    json_dumps([teacher.to_dict() for teacher in course.teachers]),
                    course.term_text,
                    json_dumps(course.term_ids),
                    course.courseries,
                    course.dept,
                    course.course_type,
                    course.join_type,
                    course.teaching_type,
                    course.course_level,
                    course.credit,
                    course.homepage,
                    course.introduction_html,
                    course.introduction_text,
                    course.summary_html,
                    course.summary_text,
                    course.rating_average,
                    course.review_count_site,
                    course.visible_review_count,
                    course.difficulty,
                    course.homework,
                    course.grading,
                    course.gain,
                    source_hash,
                    now,
                    now,
                ),
            )

            conn.execute("DELETE FROM course_teachers WHERE course_id = ?", (course.id,))
            for teacher in course.teachers:
                self._upsert_teacher_conn(conn, teacher, now)
                teacher_key = str(teacher.id) if teacher.id is not None else teacher.name
                conn.execute(
                    """
                    INSERT OR REPLACE INTO course_teachers(course_id, teacher_key, teacher_id, teacher_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (course.id, teacher_key, teacher.id, teacher.name),
                )

            conn.execute("DELETE FROM reviews WHERE course_id = ?", (course.id,))
            for review in course.reviews:
                self._upsert_review_conn(conn, review, now)

    def _upsert_teacher_conn(self, conn: sqlite3.Connection, teacher: Teacher, now: str) -> None:
        if teacher.id is None:
            return
        conn.execute(
            """
            INSERT INTO teachers(id, name, dept, homepage, image, source_url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                dept=excluded.dept,
                homepage=excluded.homepage,
                image=excluded.image,
                source_url=excluded.source_url,
                updated_at=excluded.updated_at
            """,
            (
                teacher.id,
                teacher.name,
                teacher.dept,
                teacher.homepage,
                teacher.image,
                teacher.source_url,
                now,
            ),
        )

    def _upsert_review_conn(self, conn: sqlite3.Connection, review: Review, now: str) -> None:
        conn.execute(
            """
            INSERT INTO reviews(
                id, course_id, url, author_display, is_anonymous, term, rating_10,
                difficulty, homework, grading, gain, content_html, content_text,
                publish_time, update_time, upvote_count, comment_count, crawled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                course_id=excluded.course_id,
                url=excluded.url,
                author_display=excluded.author_display,
                is_anonymous=excluded.is_anonymous,
                term=excluded.term,
                rating_10=excluded.rating_10,
                difficulty=excluded.difficulty,
                homework=excluded.homework,
                grading=excluded.grading,
                gain=excluded.gain,
                content_html=excluded.content_html,
                content_text=excluded.content_text,
                publish_time=excluded.publish_time,
                update_time=excluded.update_time,
                upvote_count=excluded.upvote_count,
                comment_count=excluded.comment_count,
                crawled_at=excluded.crawled_at
            """,
            (
                review.id,
                review.course_id,
                review.url,
                review.author_display,
                int(review.is_anonymous),
                review.term,
                review.rating_10,
                review.difficulty,
                review.homework,
                review.grading,
                review.gain,
                review.content_html,
                review.content_text,
                review.publish_time,
                review.update_time,
                review.upvote_count,
                review.comment_count,
                now,
            ),
        )

    def get_course(self, course_id: int, include_reviews: bool = True) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
            if not row:
                return None
            course = self._course_row_to_dict(row)
            if include_reviews:
                rows = conn.execute(
                    "SELECT * FROM reviews WHERE course_id = ? ORDER BY COALESCE(upvote_count, 0) DESC, id DESC",
                    (course_id,),
                ).fetchall()
                course["reviews"] = [self._review_row_to_dict(item) for item in rows]
            return course

    def get_reviews(
        self,
        course_id: int,
        term: str | None = None,
        rating: int | None = None,
        sort_by: str = "upvote",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        order_by = {
            "upvote": "COALESCE(upvote_count, 0) DESC, COALESCE(update_time, publish_time, '') DESC",
            "pubtime_desc": "COALESCE(publish_time, '') DESC",
            "pubtime": "COALESCE(publish_time, '') ASC",
            "score_desc": "COALESCE(rating_10, 0) DESC, COALESCE(publish_time, '') DESC",
            "score": "COALESCE(rating_10, 99) ASC, COALESCE(publish_time, '') DESC",
        }.get(sort_by, "COALESCE(upvote_count, 0) DESC, COALESCE(update_time, publish_time, '') DESC")

        clauses = ["course_id = ?"]
        params: list[Any] = [course_id]
        if term:
            clauses.append("term = ?")
            params.append(term)
        if rating:
            clauses.append("rating_10 IN (?, ?)")
            params.extend([2 * rating - 1, 2 * rating])
        params.append(max(1, min(limit, 200)))

        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM reviews WHERE {' AND '.join(clauses)} ORDER BY {order_by} LIMIT ?",
                params,
            ).fetchall()
        return [self._review_row_to_dict(row) for row in rows]

    def search_courses(
        self,
        query: str | None = None,
        teacher: str | None = None,
        dept: str | None = None,
        course_type: str | None = None,
        min_rating: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            like = f"%{query}%"
            clauses.append(
                "(name LIKE ? OR teachers_json LIKE ? OR courseries LIKE ? "
                "OR introduction_text LIKE ? OR summary_text LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        if teacher:
            clauses.append("teachers_json LIKE ?")
            params.append(f"%{teacher}%")
        if dept:
            clauses.append("dept LIKE ?")
            params.append(f"%{dept}%")
        if course_type:
            clauses.append("course_type LIKE ?")
            params.append(f"%{course_type}%")
        if min_rating is not None:
            clauses.append("rating_average >= ?")
            params.append(min_rating)

        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS total FROM courses {where_sql}", params).fetchone()["total"]
            rows = conn.execute(
                f"""
                SELECT * FROM courses
                {where_sql}
                ORDER BY COALESCE(rating_average, 0) DESC,
                         COALESCE(review_count_site, 0) DESC,
                         id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return {"total": total, "items": [self._course_row_to_search_dict(row) for row in rows]}

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            course_count = conn.execute("SELECT COUNT(*) AS c FROM courses").fetchone()["c"]
            detail_count = conn.execute(
                "SELECT COUNT(*) AS c FROM courses WHERE detail_crawled_at IS NOT NULL"
            ).fetchone()["c"]
            review_count = conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()["c"]
            last_detail = conn.execute(
                "SELECT MAX(detail_crawled_at) AS t FROM courses WHERE detail_crawled_at IS NOT NULL"
            ).fetchone()["t"]
            last_list = conn.execute("SELECT MAX(list_crawled_at) AS t FROM courses").fetchone()["t"]
        return {
            "db_path": str(self.db_path),
            "courses": course_count,
            "courses_with_detail": detail_count,
            "public_reviews": review_count,
            "last_detail_crawled_at": last_detail,
            "last_list_crawled_at": last_list,
        }

    def export_jsonl(self, output_path: Path | str, include_reviews: bool = True) -> dict[str, Any]:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with self.connect() as conn, output.open("w", encoding="utf-8") as fh:
            rows = conn.execute("SELECT id FROM courses ORDER BY id").fetchall()
            for row in rows:
                course = self.get_course(row["id"], include_reviews=include_reviews)
                if course:
                    fh.write(json.dumps(course, ensure_ascii=False) + "\n")
                    count += 1
        return {"output_path": str(output), "courses_exported": count, "include_reviews": include_reviews}

    def _course_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        review_count_site = row["review_count_site"]
        visible_review_count = row["visible_review_count"]
        missing = None
        if review_count_site is not None and visible_review_count is not None:
            missing = max(review_count_site - visible_review_count, 0)
        return {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "teachers": json_loads(row["teachers_json"], []),
            "term_text": row["term_text"],
            "term_ids": json_loads(row["term_ids_json"], []),
            "courseries": row["courseries"],
            "dept": row["dept"],
            "course_type": row["course_type"],
            "join_type": row["join_type"],
            "teaching_type": row["teaching_type"],
            "course_level": row["course_level"],
            "credit": row["credit"],
            "homepage": row["homepage"],
            "introduction_html": row["introduction_html"],
            "introduction_text": row["introduction_text"],
            "summary_html": row["summary_html"],
            "summary_text": row["summary_text"],
            "rating_average": row["rating_average"],
            "review_count_site": review_count_site,
            "visible_review_count": visible_review_count,
            "missing_review_count_estimate": missing,
            "difficulty": row["difficulty"],
            "homework": row["homework"],
            "grading": row["grading"],
            "gain": row["gain"],
            "source_hash": row["source_hash"],
            "detail_crawled_at": row["detail_crawled_at"],
            "list_crawled_at": row["list_crawled_at"],
            "updated_at": row["updated_at"],
        }

    def _course_row_to_search_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        review_count_site = row["review_count_site"]
        visible_review_count = row["visible_review_count"]
        missing = None
        if review_count_site is not None and visible_review_count is not None:
            missing = max(review_count_site - visible_review_count, 0)
        return {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "teachers": json_loads(row["teachers_json"], []),
            "term_text": row["term_text"],
            "courseries": row["courseries"],
            "dept": row["dept"],
            "course_type": row["course_type"],
            "join_type": row["join_type"],
            "teaching_type": row["teaching_type"],
            "course_level": row["course_level"],
            "credit": row["credit"],
            "rating_average": row["rating_average"],
            "review_count_site": review_count_site,
            "visible_review_count": visible_review_count,
            "missing_review_count_estimate": missing,
            "difficulty": row["difficulty"],
            "homework": row["homework"],
            "grading": row["grading"],
            "gain": row["gain"],
            "detail_crawled_at": row["detail_crawled_at"],
            "list_crawled_at": row["list_crawled_at"],
        }

    def _review_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "course_id": row["course_id"],
            "url": row["url"],
            "author_display": row["author_display"],
            "is_anonymous": bool(row["is_anonymous"]),
            "term": row["term"],
            "rating_10": row["rating_10"],
            "difficulty": row["difficulty"],
            "homework": row["homework"],
            "grading": row["grading"],
            "gain": row["gain"],
            "content_html": row["content_html"],
            "content_text": row["content_text"],
            "publish_time": row["publish_time"],
            "update_time": row["update_time"],
            "upvote_count": row["upvote_count"],
            "comment_count": row["comment_count"],
            "crawled_at": row["crawled_at"],
        }
