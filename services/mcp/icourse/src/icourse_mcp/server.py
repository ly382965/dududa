from __future__ import annotations

import argparse
import logging
import re
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import AppConfig
from .crawler import ICourseCrawler
from .storage import ICourseStore

logger = logging.getLogger(__name__)

_REVIEW_EVIDENCE_COURSE_LIMIT = 7
_REVIEW_SAMPLES_PER_COURSE = 2
_REVIEW_EVIDENCE_SAMPLE_LIMIT = 10
_REVIEW_SAMPLE_CHARACTERS = 200


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

    def live_review_query(
        query: str,
        limit: int,
        *,
        user_lookup: bool = False,
    ) -> dict[str, Any]:
        return current_crawler().search_site_reviews(
            query,
            limit=limit,
            user_lookup=user_lookup,
        )

    mcp = FastMCP("icourse-mcp", lifespan=lifespan)

    @mcp.tool()
    def icourse_stats() -> dict[str, Any]:
        """Return current public site statistics from icourse.club."""
        return current_crawler().get_site_statistics()["coverage"]

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
        """Search current public course records on icourse.club."""
        normalized = (query or teacher or dept or course_type or "").strip()
        result = current_crawler().query_site_courses(normalized, limit=50)
        items = [
            item for item in result.get("items", []) if isinstance(item, dict)
        ]
        if teacher:
            expected = teacher.casefold()
            items = [
                item
                for item in items
                if any(
                    expected in str(value.get("name") or "").casefold()
                    for value in item.get("teachers", [])
                    if isinstance(value, dict)
                )
            ]
        if dept:
            items = [item for item in items if dept in str(item.get("dept") or "")]
        if course_type:
            items = [
                item
                for item in items
                if course_type in str(item.get("course_type") or "")
            ]
        if min_rating is not None:
            items = [
                item
                for item in items
                if float(item.get("rating_average") or 0) >= min_rating
            ]
        offset = max(0, offset)
        limit = max(1, min(limit, 100))
        has_filters = bool(
            teacher or dept or course_type or min_rating is not None
        )
        return {
            "total": (
                len(items)
                if has_filters
                else int(result.get("total") or len(items))
            ),
            "items": items[offset : offset + limit],
        }

    @mcp.tool()
    def get_course(
        course_id: int, include_reviews: bool = True, refresh: bool = False
    ) -> dict[str, Any]:
        """Get one current public course page from icourse.club."""
        course = current_crawler().get_site_course(
            course_id,
            include_reviews=include_reviews,
        )
        return {"ok": True, "course": course, "public_only": True}

    @mcp.tool()
    def get_reviews(
        course_id: int,
        term: str | None = None,
        rating: int | None = None,
        sort_by: str = "upvote",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get current public reviews from one icourse.club course page."""
        return {
            "ok": True,
            "course_id": course_id,
            "reviews": current_crawler().get_site_reviews(
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
        user_lookup = _user_lookup_requested(natural_goal, normalized)
        if operation == "review":
            live_result = live_review_query(
                normalized,
                limit,
                user_lookup=user_lookup,
            )
            return {
                "schema_version": 1,
                "operation": operation,
                "query": normalized,
                "public_only": True,
                "result": _public_review_result(live_result),
            }
        if operation == "teacher":
            teacher_result = current_crawler().search_site_teachers(
                normalized,
                limit=limit,
            )
            if _review_evidence_requested(natural_goal):
                teacher_result = _enrich_teacher_result_with_reviews(
                    current_crawler(),
                    teacher_result,
                )
            return {
                "schema_version": 1,
                "operation": operation,
                "query": normalized,
                "public_only": True,
                "result": _public_teacher_result(teacher_result),
            }
        if operation == "ranking":
            return {
                "schema_version": 1,
                "operation": operation,
                "query": normalized,
                "public_only": True,
                "result": _public_ranking_result(
                    current_crawler().get_site_rankings(),
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
                "result": _public_stats_result(
                    current_crawler().get_site_statistics()
                ),
            }
        filters = _course_filters(natural_goal)
        live_courses = current_crawler().query_site_courses(normalized, limit=50)
        result = _filter_live_course_result(
            live_courses,
            filters,
            limit=limit,
        )
        if not live_courses.get("total"):
            live_result = live_review_query(
                normalized,
                limit,
                user_lookup=user_lookup,
            )
            if live_result.get("total"):
                return {
                    "schema_version": 1,
                    "operation": "review",
                    "query": normalized,
                    "public_only": True,
                    "result": _public_review_result(live_result),
                }
        if _review_evidence_requested(natural_goal):
            result = _enrich_course_result_with_reviews(
                current_crawler(),
                result,
            )
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
        "url",
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
        "url",
        "content_length",
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
    projected = {
        "total": int(result.get("total") or 0),
        "items": [
            _public_course_item(item)
            for item in result.get("items", [])
            if isinstance(item, dict)
        ],
    }
    _project_review_evidence(result, projected)
    if isinstance(result.get("source"), str):
        projected["source"] = result["source"]
    return projected


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
    projected = {
        "total": int(result.get("total") or 0),
        "items": [
            _public_teacher_item(item)
            for item in result.get("items", [])
            if isinstance(item, dict)
        ],
    }
    _project_review_evidence(result, projected)
    if isinstance(result.get("source"), str):
        projected["source"] = result["source"]
    return projected


def _project_review_evidence(
    source: dict[str, Any],
    projected: dict[str, Any],
) -> None:
    groups = source.get("review_evidence")
    if not isinstance(groups, list):
        return
    projected["review_evidence"] = [
        _public_review_evidence_group(item)
        for item in groups[:_REVIEW_EVIDENCE_COURSE_LIMIT]
        if isinstance(item, dict)
    ]
    count = source.get("review_sampled_course_count")
    if isinstance(count, int) and not isinstance(count, bool):
        projected["review_sampled_course_count"] = count


def _public_review_evidence_group(item: dict[str, Any]) -> dict[str, Any]:
    projected = _select(
        item,
        "course_id",
        "course_name",
        "course_rating_average",
    )
    teachers = item.get("course_teachers")
    if isinstance(teachers, list):
        projected["course_teachers"] = [
            _public_teacher_ref(value)
            for value in teachers
            if isinstance(value, dict)
        ]
    samples = item.get("samples")
    projected["samples"] = [
        _public_review_item(value, excerpt_characters=_REVIEW_SAMPLE_CHARACTERS)
        for value in samples or []
        if isinstance(value, dict)
    ]
    return projected


def _review_evidence_requested(goal: str) -> bool:
    compact = "".join(goal.split())
    return any(
        term in compact
        for term in (
            "推荐",
            "评价",
            "评课情况",
            "怎么样",
            "怎么选",
            "如何选",
            "选谁",
            "哪个老师",
            "哪位老师",
            "比较",
            "对比",
            "优缺点",
            "口碑",
            "适合",
        )
    )


def _enrich_course_result_with_reviews(
    crawler: ICourseCrawler,
    result: dict[str, Any],
) -> dict[str, Any]:
    enriched = deepcopy(result)
    courses = [
        item for item in enriched.get("items", []) if isinstance(item, dict)
    ]
    return _attach_review_evidence(crawler, enriched, courses)


def _enrich_teacher_result_with_reviews(
    crawler: ICourseCrawler,
    result: dict[str, Any],
) -> dict[str, Any]:
    enriched = deepcopy(result)
    courses = [
        course
        for teacher in enriched.get("items", [])
        if isinstance(teacher, dict)
        for course in teacher.get("courses", [])
        if isinstance(course, dict)
    ]
    return _attach_review_evidence(crawler, enriched, courses)


def _attach_review_evidence(
    crawler: ICourseCrawler,
    result: dict[str, Any],
    courses: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence_groups: list[dict[str, Any]] = []
    for course in _rank_review_evidence_courses(courses):
        try:
            detail = crawler.get_site_course(
                int(course["id"]),
                include_reviews=True,
                sort_by="upvote",
            )
        except Exception as exc:  # noqa: BLE001 - preserve partial search evidence.
            logger.warning(
                "Unable to read iCourse detail for review evidence: course_id=%s error=%s",
                course.get("id"),
                type(exc).__name__,
            )
            continue
        samples = _representative_review_samples(detail.get("reviews", []))
        if samples:
            evidence_groups.append(
                {
                    "course_id": detail.get("id", course.get("id")),
                    "course_name": detail.get("name", course.get("name")),
                    "course_teachers": detail.get(
                        "teachers",
                        course.get("teachers", []),
                    ),
                    "course_rating_average": detail.get(
                        "rating_average",
                        course.get("rating_average"),
                    ),
                    "samples": samples,
                }
            )

    selected_by_group: list[list[dict[str, Any]]] = [
        [] for _ in evidence_groups
    ]
    selected_count = 0
    for sample_index in range(_REVIEW_SAMPLES_PER_COURSE):
        for group_index, group in enumerate(evidence_groups):
            samples = group["samples"]
            if sample_index < len(samples):
                selected_by_group[group_index].append(samples[sample_index])
                selected_count += 1
            if selected_count >= _REVIEW_EVIDENCE_SAMPLE_LIMIT:
                break
        if selected_count >= _REVIEW_EVIDENCE_SAMPLE_LIMIT:
            break
    result["review_evidence"] = [
        {**group, "samples": selected_by_group[index]}
        for index, group in enumerate(evidence_groups)
        if selected_by_group[index]
    ]
    result["review_sampled_course_count"] = len(evidence_groups)
    return result


def _rank_review_evidence_courses(
    courses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[int, tuple[int, dict[str, Any]]] = {}
    for index, course in enumerate(courses):
        course_id = course.get("id")
        if not isinstance(course_id, int) or isinstance(course_id, bool):
            continue
        review_count = course.get("review_count_site")
        if not isinstance(review_count, int) or review_count < 1:
            continue
        previous = unique.get(course_id)
        if previous is None or review_count > int(
            previous[1].get("review_count_site") or 0
        ):
            unique[course_id] = (index, course)
    ranked = sorted(
        unique.values(),
        key=lambda value: (
            -int(value[1].get("review_count_site") or 0),
            value[0],
        ),
    )
    return [course for _, course in ranked[:_REVIEW_EVIDENCE_COURSE_LIMIT]]


def _representative_review_samples(
    reviews: object,
) -> list[dict[str, Any]]:
    if not isinstance(reviews, list):
        return []
    candidates = [
        item
        for item in reviews
        if isinstance(item, dict)
        and isinstance(item.get("content_text"), str)
        and item["content_text"].strip()
    ]
    if not candidates:
        return []

    selected = [
        max(
            candidates,
            key=lambda item: (
                _review_content_evidence_score(item),
                int(item.get("upvote_count") or 0),
                len(str(item.get("content_text") or "")),
            ),
        )
    ]
    remaining = [item for item in candidates if item is not selected[0]]
    rated = [
        item
        for item in remaining
        if isinstance(item.get("rating_10"), int)
        and not isinstance(item.get("rating_10"), bool)
    ]
    if rated:
        selected.append(
            min(
                rated,
                key=lambda item: (
                    int(item["rating_10"]),
                    -_review_content_evidence_score(item),
                    -int(item.get("upvote_count") or 0),
                ),
            )
        )
    elif remaining:
        selected.append(
            max(
                remaining,
                key=lambda item: (
                    str(item.get("publish_time") or ""),
                    _review_content_evidence_score(item),
                ),
            )
        )
    return selected[:_REVIEW_SAMPLES_PER_COURSE]


def _review_content_evidence_score(review: dict[str, Any]) -> int:
    text = str(review.get("content_text") or "")[:_REVIEW_SAMPLE_CHARACTERS]
    return sum(
        term in text
        for term in (
            "上课",
            "讲课",
            "板书",
            "PPT",
            "作业",
            "实验",
            "小测",
            "期中",
            "期末",
            "考试",
            "给分",
            "收获",
            "难度",
        )
    )


def _public_ranking_result(
    result: dict[str, Any],
    goal: str,
    *,
    limit: int,
) -> dict[str, Any]:
    projected = {"source": result.get("source", "live_site_rankings")}
    coverage = result.get("coverage")
    if isinstance(coverage, dict):
        projected["coverage"] = _public_coverage(coverage)
    formula = result.get("formula")
    if isinstance(formula, dict):
        projected["formula"] = formula
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
    elif any(
        term in goal
        for term in ("推荐", "怎么选", "如何选", "选谁", "哪个老师", "哪位老师")
    ):
        filters["sort_by"] = "reviews_desc"
    return filters


def _filter_live_course_result(
    result: dict[str, Any],
    filters: dict[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    items = [item for item in result.get("items", []) if isinstance(item, dict)]
    sort_by = filters.get("sort_by")
    checks = {key: value for key, value in filters.items() if key != "sort_by"}

    def matches(item: dict[str, Any]) -> bool:
        if "min_rating" in checks and float(item.get("rating_average") or 0) < checks["min_rating"]:
            return False
        if "min_reviews" in checks and int(item.get("review_count_site") or 0) < checks["min_reviews"]:
            return False
        if "credit" in checks and item.get("credit") != checks["credit"]:
            return False
        for key in ("term", "dept", "course_type"):
            expected = checks.get(key)
            if expected is not None and str(expected) not in str(item.get(key) or ""):
                return False
        for key in ("homework", "grading", "gain", "difficulty"):
            expected = checks.get(key)
            if expected is not None and item.get(key) != expected:
                return False
        return True

    filtered = [item for item in items if matches(item)]
    if sort_by == "rating_asc":
        filtered.sort(key=lambda item: float(item.get("rating_average") or 0))
    elif sort_by == "reviews_desc":
        filtered.sort(key=lambda item: int(item.get("review_count_site") or 0), reverse=True)
    elif sort_by == "latest":
        filtered.sort(key=lambda item: str(item.get("term_text") or ""), reverse=True)
    return {
        "total": len(filtered) if checks else int(result.get("total") or len(filtered)),
        "items": filtered[:limit],
        "source": result.get("source", "live_site_course_search"),
    }


def _user_lookup_requested(goal: str, query: str) -> bool:
    if any(term in goal for term in ("用户", "账号", "作者")):
        return True
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{3,63}", query) is None:
        return False
    if any(term in goal for term in ("点评", "评论", "课程", "老师", "教师")):
        return False
    compact = "".join(goal.split()).casefold()
    return "评课社区" in compact and query.casefold() in compact


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
