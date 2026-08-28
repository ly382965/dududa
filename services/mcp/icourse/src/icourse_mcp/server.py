from __future__ import annotations

import argparse
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import ICourseCrawler
from .storage import ICourseStore


def create_mcp(config: AppConfig) -> FastMCP:
    store = ICourseStore(config.db_path)
    crawler: ICourseCrawler | None = None

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        nonlocal crawler
        crawler = ICourseCrawler(config, store=store)
        try:
            yield {"crawler": crawler}
        finally:
            crawler.close()
            crawler = None

    def current_crawler() -> ICourseCrawler:
        if crawler is None:
            raise RuntimeError("icourse crawler lifespan is not active")
        return crawler

    def live_review_query(query: str, limit: int) -> dict[str, Any]:
        return current_crawler().search_site_reviews(query, limit=limit)

    mcp = FastMCP("icourse-mcp", lifespan=lifespan)

    @mcp.tool()
    def icourse_stats() -> dict[str, Any]:
        """Return local database statistics for the iCourse public-data cache."""
        return store.stats()

    @mcp.tool()
    def search_courses(
        query: str | None = None,
        teacher: str | None = None,
        dept: str | None = None,
        course_type: str | None = None,
        min_rating: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search cached public course records from icourse.club."""
        return store.search_courses(
            query=query,
            teacher=teacher,
            dept=dept,
            course_type=course_type,
            min_rating=min_rating,
            limit=limit,
            offset=offset,
        )

    @mcp.tool()
    def get_course(
        course_id: int, include_reviews: bool = True, refresh: bool = False
    ) -> dict[str, Any]:
        """Get one cached course. Set refresh=true to fetch its public page first."""
        if refresh:
            current_crawler().crawl_course(course_id)
        course = store.get_course(course_id, include_reviews=include_reviews)
        if not course:
            return {
                "ok": False,
                "error": "course_not_found_in_cache",
                "hint": "Call crawl_course(course_id) first, or crawl a course-list page.",
                "course_id": course_id,
            }
        return {"ok": True, "course": course, "public_only": True}

    @mcp.tool()
    def get_reviews(
        course_id: int,
        term: str | None = None,
        rating: int | None = None,
        sort_by: str = "upvote",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get cached public reviews for one course, optionally filtered by term or 1-5 star rating."""
        return {
            "ok": True,
            "course_id": course_id,
            "reviews": store.get_reviews(
                course_id, term=term, rating=rating, sort_by=sort_by, limit=limit
            ),
            "public_only": True,
        }

    @mcp.tool()
    def icourse_public_query(
        query: str,
        operation: str = "course",
        goal: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Run one bounded read-only query over public iCourse data."""
        normalized = query.strip()
        natural_goal = (goal or query).strip()
        limit = max(1, min(limit, 30))
        if operation == "review":
            live_result = live_review_query(normalized, limit)
            return {
                "schema_version": 1,
                "operation": operation,
                "query": normalized,
                "public_only": True,
                "result": _public_review_result(live_result),
            }
        if operation == "teacher":
            return {
                "schema_version": 1,
                "operation": operation,
                "query": normalized,
                "public_only": True,
                "result": _public_teacher_result(
                    store.search_teachers(normalized, limit=limit)
                ),
            }
        if operation == "ranking":
            return {
                "schema_version": 1,
                "operation": operation,
                "query": normalized,
                "public_only": True,
                "result": _public_ranking_result(
                    store.get_rankings(limit=limit),
                    natural_goal,
                    limit=limit,
                ),
            }
        if operation == "stats":
            return {
                "schema_version": 1,
                "operation": operation,
                "query": normalized,
                "public_only": True,
                "result": _public_stats_result(store.get_site_statistics()),
            }
        filters = _course_filters(natural_goal)
        text_query = normalized
        if normalized == natural_goal and filters:
            text_query = ""
        result = store.query_courses(
            query=text_query or None,
            limit=limit,
            **filters,
        )
        if text_query and not result.get("total"):
            live_result = live_review_query(normalized, limit)
            if live_result.get("total"):
                return {
                    "schema_version": 1,
                    "operation": "review",
                    "query": normalized,
                    "public_only": True,
                    "result": _public_review_result(live_result),
                }
        return {
            "schema_version": 1,
            "operation": "course",
            "query": normalized,
            "public_only": True,
            "result": _public_course_result(result),
        }

    @mcp.tool()
    def crawl_course(course_id: int, sort_by: str = "upvote") -> dict[str, Any]:
        """Fetch and cache one public course detail page from icourse.club."""
        return current_crawler().crawl_course(course_id, sort_by=sort_by)

    @mcp.tool()
    def crawl_courses(
        start_page: int = 1,
        end_page: int | None = None,
        per_page: int = 50,
        max_courses: int | None = 50,
        detail: bool = False,
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        """Crawl course-list pages. Defaults are conservative; set detail=true for detail pages."""
        return current_crawler().crawl_courses(
            start_page=start_page,
            end_page=end_page,
            per_page=per_page,
            max_courses=max_courses,
            detail=detail,
            sort_by=sort_by,
        )

    @mcp.tool()
    def search_site_courses(
        query: str,
        pages: int = 1,
        max_courses: int | None = 20,
        detail: bool = False,
        detail_limit: int = 3,
        sort_by: str = "upvote",
    ) -> dict[str, Any]:
        """Search public icourse.club course pages online, cache results, optionally fetch top details."""
        return current_crawler().search_site_courses(
            query=query,
            pages=pages,
            max_courses=max_courses,
            detail=detail,
            detail_limit=detail_limit,
            sort_by=sort_by,
        )

    @mcp.tool()
    def crawl_latest_reviews(
        pages: int = 1, per_page: int = 10, max_courses: int | None = 20
    ) -> dict[str, Any]:
        """Refresh courses appearing in the public latest-reviews feed."""
        return current_crawler().crawl_latest_reviews(
            pages=pages,
            per_page=per_page,
            max_courses=max_courses,
        )

    @mcp.tool()
    def check_robots() -> dict[str, Any]:
        """Fetch and cache robots.txt from icourse.club for audit purposes."""
        return current_crawler().check_robots()

    @mcp.tool()
    def export_dataset(
        output_path: str = "data/icourse_courses.jsonl", include_reviews: bool = True
    ) -> dict[str, Any]:
        """Export cached course records to JSONL."""
        return store.export_jsonl(Path(output_path), include_reviews=include_reviews)

    return mcp


def _public_course_item(item: dict[str, Any]) -> dict[str, Any]:
    projected = _select(
        item,
        "id",
        "name",
        "courseries",
        "term_text",
        "rating_average",
        "review_count_site",
        "visible_review_count",
        "difficulty",
        "homework",
        "grading",
        "gain",
        "credit",
        "dept",
        "course_type",
        "course_level",
        "teaching_type",
    )
    teachers = item.get("teachers")
    if isinstance(teachers, list):
        projected["teachers"] = [
            _public_teacher_ref(value)
            for value in teachers
            if isinstance(value, dict)
        ]
    normalized = item.get("normalized_rating")
    if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
        projected["normalized_rating"] = normalized
    return projected


def _public_review_item(
    item: dict[str, Any],
    *,
    excerpt_characters: int,
) -> dict[str, Any]:
    projected = _select(
        item,
        "id",
        "course_id",
        "course_name",
        "course_rating_average",
        "author_display",
        "is_anonymous",
        "term",
        "rating_10",
        "publish_time",
        "update_time",
        "upvote_count",
        "comment_count",
        "difficulty",
        "homework",
        "grading",
        "gain",
    )
    text = item.get("content_text")
    if isinstance(text, str):
        if not item.get("content_is_excerpt"):
            projected["content_length"] = len(text)
        projected["content_text"] = _excerpt(text, excerpt_characters)
    teachers = item.get("course_teachers")
    if isinstance(teachers, list):
        projected["course_teachers"] = [
            _public_teacher_ref(value)
            for value in teachers
            if isinstance(value, dict)
        ]
    return projected


def _public_teacher_item(item: dict[str, Any]) -> dict[str, Any]:
    projected = _select(
        item,
        "teacher_id",
        "name",
        "course_count",
        "review_count",
        "rating_average",
        "departments",
    )
    courses = item.get("courses")
    if isinstance(courses, list):
        projected["courses"] = [
            _select(
                value,
                "id",
                "name",
                "term_text",
                "rating_average",
                "review_count_site",
                "difficulty",
                "homework",
                "grading",
                "gain",
            )
            for value in courses[:10]
            if isinstance(value, dict)
        ]
    return projected


def _public_course_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": int(result.get("total") or 0),
        "items": [
            _public_course_item(item)
            for item in result.get("items", [])
            if isinstance(item, dict)
        ],
    }


def _public_review_result(result: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "total": int(result.get("total") or 0),
        "items": [
            _public_review_item(item, excerpt_characters=320)
            for item in result.get("items", [])
            if isinstance(item, dict)
        ],
    }
    aggregates = result.get("aggregates")
    if isinstance(aggregates, dict):
        projected["aggregates"] = aggregates
    if isinstance(result.get("source"), str):
        projected["source"] = result["source"]
    return projected


def _public_teacher_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": int(result.get("total") or 0),
        "items": [
            _public_teacher_item(item)
            for item in result.get("items", [])
            if isinstance(item, dict)
        ],
    }


def _public_ranking_result(
    result: dict[str, Any],
    goal: str,
    *,
    limit: int,
) -> dict[str, Any]:
    projected = {
        "source": result.get("source", "local_public_cache"),
        "coverage": _public_coverage(result.get("coverage")),
        "formula": result.get("formula", {}),
    }
    course_keys: list[str] = []
    review_keys: list[str] = []
    if any(term in goal for term in ("最高", "最好", "推荐")):
        course_keys.append("top_courses")
    if any(term in goal for term in ("最低", "最差", "最不", "不受欢迎")):
        course_keys.append("low_courses")
    if "热门" in goal:
        course_keys.append("popular_courses")
    if "点赞" in goal:
        review_keys.append("top_reviews")
    if "最长" in goal:
        review_keys.append("longest_reviews")
    if not course_keys and not review_keys:
        course_keys = ["top_courses", "low_courses", "popular_courses"]
        review_keys = ["top_reviews"]
        limit = min(limit, 5)
    for key in dict.fromkeys(course_keys):
        projected[key] = [
            _public_course_item(item)
            for item in result.get(key, [])[:limit]
            if isinstance(item, dict)
        ]
    for key in dict.fromkeys(review_keys):
        projected[key] = [
            _public_review_item(item, excerpt_characters=240)
            for item in result.get(key, [])[:limit]
            if isinstance(item, dict)
        ]
    return projected


def _public_stats_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": result.get("source", "local_public_cache"),
        "coverage": _public_coverage(result.get("coverage")),
        "average_review_rating": result.get("average_review_rating"),
        "course_rating_distribution": result.get("course_rating_distribution", []),
        "review_rating_distribution": result.get("review_rating_distribution", []),
        "review_timeline": result.get("review_timeline", []),
    }


def _public_coverage(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _select(
        value,
        "courses",
        "courses_with_detail",
        "public_reviews",
        "last_detail_crawled_at",
        "last_list_crawled_at",
    )


def _select(item: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: item[key] for key in keys if key in item}


def _public_teacher_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "dept": item.get("dept"),
    }


def _excerpt(value: str, maximum_characters: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= maximum_characters:
        return normalized
    return normalized[: maximum_characters - 6].rstrip() + "[内容截断]"


def _course_filters(goal: str) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    rating_match = re.search(
        r"(?:评分\s*)?(\d+(?:\.\d+)?)\s*分?\s*(?:以上|起)",
        goal,
    )
    if rating_match:
        filters["min_rating"] = float(rating_match.group(1))
    reviews_match = re.search(
        r"(?:点评|评论)\s*(?:至少|不少于)\s*(\d+)|至少\s*(\d+)\s*(?:条|个)(?:点评|评论)",
        goal,
    )
    if reviews_match:
        filters["min_reviews"] = int(next(value for value in reviews_match.groups() if value))
    credit_match = re.search(r"([一二两三四五六\d](?:\.\d+)?)\s*学分", goal)
    if credit_match:
        numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6}
        raw = credit_match.group(1)
        filters["credit"] = float(numbers.get(raw, raw))
    term_match = re.search(r"(20\d{2}[秋春夏])", goal)
    if term_match:
        filters["term"] = term_match.group(1)
    if any(term in goal for term in ("计算机学院", "计院")):
        filters["dept"] = "计算机"
    if "通识" in goal:
        filters["course_type"] = "通识"
    if any(term in goal for term in ("作业少", "作业不要太多", "作业不多")):
        filters["homework"] = "很少"
    if any(term in goal for term in ("给分好", "给分不要差")):
        filters["grading"] = "超好"
    if any(term in goal for term in ("有收获", "很有收获", "能学到东西", "真正学懂")):
        filters["gain"] = "很多"
    if any(term in goal for term in ("比较难", "难一点", "累是累")):
        filters["difficulty"] = "困难"
    if any(term in goal for term in ("评分最低", "最不推荐")):
        filters["sort_by"] = "rating_asc"
    elif any(term in goal for term in ("评论多", "点评多", "热门")):
        filters["sort_by"] = "reviews_desc"
    elif any(term in goal for term in ("最近", "最新")):
        filters["sort_by"] = "latest"
    return filters


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the iCourse MCP server over stdio."
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite database path. Default: data/icourse.sqlite3",
    )
    parser.add_argument(
        "--base-url", default=None, help="Base URL. Default: https://icourse.club"
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=None,
        help="Delay between requests in seconds.",
    )
    parser.add_argument(
        "--timeout", type=float, default=None, help="HTTP timeout in seconds."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = AppConfig.from_args(
        db_path=args.db_path,
        base_url=args.base_url,
        request_delay=args.request_delay,
        timeout=args.timeout,
    )
    mcp = create_mcp(config)
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])
