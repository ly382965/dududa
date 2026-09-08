from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

ICOURSE_DB_DEFAULT = "/AstrBot/data/icourse-cache/icourse.sqlite3"
SEARCH_BASE = "https://icourse.club"

REVIEW_INTENT_RE = r"(评价|评课|怎么样|口碑|推荐吗|值得|好评|差评|大神|老师怎么样|质量|打分|心得)"


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _fetch(url: str, timeout: int = 25) -> str:
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _search_online(keyword: str) -> list[tuple[str, str]]:
    import urllib.parse

    url = SEARCH_BASE + "/search/?q=" + urllib.parse.quote(keyword)
    html = _fetch(url)
    pairs = re.findall(r'href="/course/(\d+)/"[^>]*>([^<]{2,60})<', html)
    return [(cid, name.strip()) for cid, name in pairs if cid and name]


def _parse_course_page(html: str) -> dict[str, Any]:
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = _strip_html(title_match.group(1))[:60] if title_match else ""
    summary: dict[str, str] = {}
    for match in re.finditer(r"<h3>(.*?)</h3>\s*<p>(.*?)</p>", html, re.S):
        head = _strip_html(match.group(1))
        body = _strip_html(match.group(2))
        if body and len(body) >= 15:
            summary[head] = body
    reviews: list[dict[str, Any]] = []
    blocks = re.findall(r'<div class="ud-pd-sm[^"]*review[^"]*"[^>]*>(.*?)</div>', html, re.S)
    if not blocks:
        blocks = re.findall(r'<div[^>]*class="[^"]*review-item[^"]*"[^>]*>(.*?)</div>', html, re.S)
    for block in blocks[:12]:
        text = _strip_html(block)
        if len(text) < 10:
            continue
        rating_match = re.search(r"(\d{1,2}(?:\.\d)?)\s*分", text)
        reviews.append(
            {
                "rating": float(rating_match.group(1)) if rating_match else None,
                "content": text[:400],
            }
        )
    return {"title": title, "summary": summary, "reviews": reviews}


def _fetch_course_online(course_id: str, title: str = "") -> dict[str, Any]:
    try:
        html = _fetch(SEARCH_BASE + "/course/" + course_id + "/")
    except Exception:
        return {"title": title, "summary": {}, "reviews": []}
    data = _parse_course_page(html)
    if title and not data["title"]:
        data["title"] = title
    return data


def search_reviews(query: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else Path(ICOURSE_DB_DEFAULT)
    search = re.sub(r"[\s，。！？、；:：()（）*·评价评课口碑怎么样]+", "", query)
    if not search:
        return []
    if path.exists():
        local = _search_local(path, search)
        if local:
            return local
    try:
        pairs = _search_online(search)
        results: list[dict[str, Any]] = []
        for cid, name in pairs[:4]:
            data = _fetch_course_online(cid, name)
            results.append(
                {
                    "course_name": data["title"] or name,
                    "teachers": _parse_teacher_name(name),
                    "dept": "",
                    "summary": data["summary"],
                    "reviews": data["reviews"],
                }
            )
        return results
    except Exception:
        return []


def _parse_teacher_name(name: str) -> list[str]:
    match = re.search(r"（(.+?)）", name)
    if not match:
        return []
    return [t.strip() for t in match.group(1).split(",") if t.strip()] or []


def _search_local(path: Path, search: str) -> list[dict[str, Any]]:
    import time

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, name, teachers_json, dept FROM courses WHERE name LIKE ? LIMIT 6",
            ("%" + search + "%",),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT DISTINCT c.id, c.name, c.teachers_json, c.dept "
                "FROM courses c JOIN course_teachers ct ON c.id=ct.course_id "
                "JOIN teachers t ON t.id=ct.teacher_id "
                "WHERE t.name LIKE ? LIMIT 4",
                ("%" + search + "%",),
            ).fetchall()
        results = []
        for cid, name, teachers_json, dept in rows:
            teachers: list[str] = []
            if teachers_json:
                try:
                    teachers = [
                        t.get("name") for t in json.loads(teachers_json) if t.get("name")
                    ]
                except (ValueError, TypeError):
                    teachers = []
            reviews = conn.execute(
                "SELECT author_display, is_anonymous, term, rating_10, difficulty, "
                "homework, grading, gain, content_html "
                "FROM reviews WHERE course_id=? ORDER BY id DESC LIMIT 20",
                (cid,),
            ).fetchall()
            items = [
                {
                    "author": ("匿名" if anon else (author or "匿名")),
                    "term": term or "",
                    "rating": rating,
                    "difficulty": difficulty,
                    "homework": homework,
                    "grading": grading,
                    "gain": gain,
                    "content": _strip_html(content),
                }
                for author, anon, term, rating, difficulty, homework, grading, gain, content in reviews
            ]
            results.append(
                {
                    "course_name": name,
                    "teachers": teachers,
                    "dept": dept or "",
                    "summary": {},
                    "reviews": items,
                }
            )
        return results
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def format_review_answer(results: list[dict[str, Any]], query: str) -> str:
    if not results:
        return "没有查到「" + query + "」的评课数据。"
    lines: list[str] = []
    for result in results[:3]:
        teachers = "、".join(result["teachers"]) or "未知教师"
        summary = result.get("summary") or {}
        reviews = result.get("reviews") or []
        lines.append(
            "·" + result["course_name"] + "（" + teachers + "）"
        )
        if summary:
            for key in ("总结", "综合评价", "教学水平"):
                if key in summary:
                    lines.append("  " + summary[key][:200])
                    break
            keys = [k for k in ("教学水平", "课程内容", "作业和辅导", "考试与给分", "资源分享")
                    if k in summary and k != ("总结" if "总结" in summary else "综合评价")]
            for k in keys[:3]:
                lines.append("  · " + k + "：" + summary[k][:150])
        if reviews:
            ratings = [r.get("rating") for r in reviews if r.get("rating") is not None]
            if ratings:
                avg = round(sum(ratings) / len(ratings), 1)
                lines.append("  （" + str(len(reviews)) + " 条点评，均分 " + str(avg) + "/10）")
            for r in reviews[:2]:
                line = "  - " + str(r.get("author", "")) + "(" + str(r.get("term", "")) + ")"
                if r.get("rating") is not None:
                    line += " 评分" + str(r["rating"]) + " 难度" + str(r.get("difficulty", "?")) \
                        + " 给分" + str(r.get("grading", "?")) + " 收获" + str(r.get("gain", "?"))
                content = r.get("content", "")
                if content:
                    line += "\n    " + content[:120]
                lines.append(line)
        if not summary and not reviews:
            lines.append("  （暂无可公开的点评数据）")
    return "\n".join(lines)


__all__ = [
    "REVIEW_INTENT_RE",
    "search_reviews",
    "format_review_answer",
]
