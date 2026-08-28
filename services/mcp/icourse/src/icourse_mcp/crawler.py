from __future__ import annotations

import math
from typing import Any

from .config import AppConfig
from .fetcher import ICourseFetcher
from .models import CourseListItem
from .parser import (
    find_exact_user_reference,
    parse_course_detail,
    parse_list_page,
    parse_review_search_page,
    parse_site_rankings_page,
    parse_site_stats_page,
    parse_user_reviews_page,
)
from .storage import ICourseStore


class ICourseCrawler:
    def __init__(self, config: AppConfig, store: ICourseStore | None = None):
        self.config = config
        self.store = store or ICourseStore(config.db_path)
        self.fetcher = ICourseFetcher(
            base_url=config.base_url,
            user_agent=config.user_agent,
            timeout=config.timeout,
            request_delay=config.request_delay,
        )

    def close(self) -> None:
        self.fetcher.close()

    def check_robots(self) -> dict[str, Any]:
        page = self.fetcher.fetch_robots()
        data = {"url": page.url, "status_code": page.status_code, "sha256": page.sha256, "text": page.text}
        self.store.set_meta("robots_txt", data)
        return data

    def crawl_course(self, course_id: int, sort_by: str = "upvote") -> dict[str, Any]:
        page = self.fetcher.fetch_course_detail(course_id, sort_by=sort_by)
        course = parse_course_detail(page.text, self.config.base_url, course_id)
        self.store.upsert_course(course, source_hash=page.sha256)
        return {
            "course_id": course.id,
            "name": course.name,
            "url": course.url,
            "public_reviews": len(course.reviews),
            "site_review_count": course.review_count_site,
            "missing_review_count_estimate": course.missing_review_count_estimate,
            "sha256": page.sha256,
        }

    def crawl_courses(
        self,
        start_page: int = 1,
        end_page: int | None = None,
        per_page: int = 50,
        max_courses: int | None = None,
        detail: bool = True,
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        start_page = max(1, start_page)
        per_page = max(1, min(per_page, 100))
        if end_page is not None:
            end_page = max(start_page, end_page)
        if max_courses is not None:
            max_courses = max(1, max_courses)

        first_page = self.fetcher.fetch_course_list(start_page, per_page=per_page, sort_by=sort_by)
        parsed = parse_list_page(first_page.text, self.config.base_url)
        total_courses = parsed.get("total_courses")
        computed_end_page = end_page
        if computed_end_page is None:
            computed_end_page = start_page
            if max_courses is not None:
                computed_end_page = start_page + math.ceil(max_courses / per_page) - 1

        pages_done = 0
        list_items_seen = 0
        details_done = 0
        errors: list[dict[str, Any]] = []

        def handle_list_items(items_raw: list[dict[str, Any]]) -> bool:
            nonlocal list_items_seen, details_done
            for item_raw in items_raw:
                if max_courses is not None and list_items_seen >= max_courses:
                    return False
                item = CourseListItem(
                    id=item_raw["id"],
                    name=item_raw["name"],
                    url=item_raw["url"],
                    teachers=item_raw.get("teachers") or [],
                    term_text=item_raw.get("term_text"),
                    rating_average=item_raw.get("rating_average"),
                    review_count=item_raw.get("review_count"),
                    difficulty=item_raw.get("difficulty"),
                    homework=item_raw.get("homework"),
                    grading=item_raw.get("grading"),
                    gain=item_raw.get("gain"),
                )
                self.store.upsert_course_list_item(item)
                list_items_seen += 1
                if detail:
                    try:
                        self.crawl_course(item.id)
                        details_done += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append({"course_id": item.id, "error": str(exc)})
            return True

        pages_done += 1
        should_continue = handle_list_items(parsed.get("items", []))
        page_no = start_page + 1
        while should_continue and page_no <= computed_end_page:
            try:
                page = self.fetcher.fetch_course_list(page_no, per_page=per_page, sort_by=sort_by)
                parsed_page = parse_list_page(page.text, self.config.base_url)
                pages_done += 1
                should_continue = handle_list_items(parsed_page.get("items", []))
            except Exception as exc:  # noqa: BLE001
                errors.append({"page": page_no, "error": str(exc)})
            page_no += 1

        return {
            "pages_done": pages_done,
            "courses_from_list": list_items_seen,
            "course_details_crawled": details_done,
            "total_courses_on_site": total_courses,
            "errors": errors,
            "db_stats": self.store.stats(),
            "public_only": True,
        }

    def search_site_courses(
        self,
        query: str,
        pages: int = 1,
        max_courses: int | None = 20,
        detail: bool = False,
        detail_limit: int = 3,
        sort_by: str = "upvote",
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return {"ok": False, "error": "empty_query", "items": [], "public_only": True}
        pages = max(1, min(pages, 5))
        if max_courses is not None:
            max_courses = max(1, min(max_courses, 100))
        detail_limit = max(0, min(detail_limit, 10))

        pages_done = 0
        items_seen = 0
        details_done = 0
        errors: list[dict[str, Any]] = []
        total_courses = None
        item_ids: list[int] = []
        found_items: list[dict[str, Any]] = []

        for page_no in range(1, pages + 1):
            if max_courses is not None and items_seen >= max_courses:
                break
            try:
                page = self.fetcher.fetch_course_search(query, page=page_no)
                parsed = parse_list_page(page.text, self.config.base_url)
                if total_courses is None:
                    total_courses = parsed.get("total_courses")
                pages_done += 1
                items = parsed.get("items", [])
                if not items:
                    break
                for item_raw in items:
                    if max_courses is not None and items_seen >= max_courses:
                        break
                    item = CourseListItem(
                        id=item_raw["id"],
                        name=item_raw["name"],
                        url=item_raw["url"],
                        teachers=item_raw.get("teachers") or [],
                        term_text=item_raw.get("term_text"),
                        rating_average=item_raw.get("rating_average"),
                        review_count=item_raw.get("review_count"),
                        difficulty=item_raw.get("difficulty"),
                        homework=item_raw.get("homework"),
                        grading=item_raw.get("grading"),
                        gain=item_raw.get("gain"),
                    )
                    self.store.upsert_course_list_item(item)
                    item_ids.append(item.id)
                    found_items.append(item.to_dict())
                    items_seen += 1
                    if detail and details_done < detail_limit:
                        try:
                            self.crawl_course(item.id, sort_by=sort_by)
                            details_done += 1
                        except Exception as exc:  # noqa: BLE001
                            errors.append({"course_id": item.id, "error": str(exc)})
                if total_courses is not None and items_seen >= total_courses:
                    break
            except Exception as exc:  # noqa: BLE001
                errors.append({"page": page_no, "error": str(exc)})
                break

        return {
            "ok": not errors or items_seen > 0,
            "query": query,
            "pages_done": pages_done,
            "courses_from_search": items_seen,
            "course_details_crawled": details_done,
            "total_courses_on_site": total_courses,
            "course_ids": item_ids,
            "items": found_items,
            "errors": errors,
            "db_stats": self.store.stats(),
            "public_only": True,
        }

    def query_site_courses(self, query: str, limit: int = 20) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return {"total": 0, "items": [], "source": "live_site_course_search"}
        limit = max(1, min(limit, 50))
        page = self.fetcher.fetch_course_search(query, per_page=50)
        parsed = parse_list_page(page.text, self.config.base_url)
        items = [_public_course_list_item(item) for item in parsed.get("items", [])]
        return {
            "query": query,
            "total": int(parsed.get("total_courses") or len(items)),
            "items": items[:limit],
            "source": "live_site_course_search",
            "public_only": True,
        }

    def get_site_course(
        self,
        course_id: int,
        *,
        include_reviews: bool = True,
        sort_by: str = "upvote",
    ) -> dict[str, Any]:
        page = self.fetcher.fetch_course_detail(course_id, sort_by=sort_by)
        course = parse_course_detail(page.text, self.config.base_url, course_id)
        return course.to_dict(include_reviews=include_reviews)

    def get_site_reviews(
        self,
        course_id: int,
        *,
        term: str | None = None,
        rating: int | None = None,
        sort_by: str = "upvote",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        course = self.get_site_course(
            course_id,
            include_reviews=True,
            sort_by=sort_by,
        )
        reviews = [
            item for item in course.get("reviews", []) if isinstance(item, dict)
        ]
        if term:
            reviews = [item for item in reviews if item.get("term") == term]
        if rating is not None:
            accepted = {rating * 2 - 1, rating * 2}
            reviews = [item for item in reviews if item.get("rating_10") in accepted]
        # The public detail endpoint already applies its documented sort order.
        return reviews[: max(1, min(limit, 200))]

    def search_site_teachers(self, query: str, limit: int = 20) -> dict[str, Any]:
        courses = self.query_site_courses(query, limit=50)
        teachers: dict[str, dict[str, Any]] = {}
        for course in courses["items"]:
            for teacher in course.get("teachers", []):
                name = str(teacher.get("name") or "").strip()
                if not name or name == "未知":
                    continue
                key = _normalized_text(name)
                item = teachers.setdefault(
                    key,
                    {
                        "teacher_id": None,
                        "name": name,
                        "course_count": 0,
                        "review_count": 0,
                        "rating_average": None,
                        "departments": [],
                        "courses": [],
                        "_rating_total": 0.0,
                        "_rating_weight": 0,
                    },
                )
                item["course_count"] += 1
                review_count = int(course.get("review_count_site") or 0)
                item["review_count"] += review_count
                rating = course.get("rating_average")
                if isinstance(rating, (int, float)):
                    weight = max(1, review_count)
                    item["_rating_total"] += float(rating) * weight
                    item["_rating_weight"] += weight
                item["courses"].append(course)
        for item in teachers.values():
            if item["_rating_weight"]:
                item["rating_average"] = round(
                    item["_rating_total"] / item["_rating_weight"],
                    2,
                )
            item.pop("_rating_total", None)
            item.pop("_rating_weight", None)
        ranked = sorted(
            teachers.values(),
            key=lambda item: (-item["review_count"], item["name"].casefold()),
        )
        return {
            "query": query,
            "total": len(ranked),
            "items": ranked[: max(1, min(limit, 30))],
            "source": "live_site_course_search",
            "public_only": True,
        }

    def search_site_reviews(
        self,
        query: str,
        limit: int = 20,
        *,
        user_lookup: bool = False,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return {"total": 0, "items": [], "source": "live_site", "public_only": True}
        limit = max(1, min(limit, 30))
        search_page = self.fetcher.fetch_review_search(
            query,
            per_page=min(50, max(limit, 10)),
        )
        search_result = parse_review_search_page(search_page.text, self.config.base_url)
        user = _exact_review_author(search_result, query)
        if user is None and user_lookup:
            rankings = self.fetcher.fetch_site_rankings()
            user = find_exact_user_reference(rankings.text, query)
        if user is None and user_lookup:
            for course_id in _review_course_ids(search_result)[:3]:
                detail = self.fetcher.fetch_course_detail(course_id)
                user = find_exact_user_reference(detail.text, query)
                if user is not None:
                    break
        if user is not None:
            user_id = int(user["user_id"])
            reviews_page = self.fetcher.fetch_user_reviews(user_id)
            result = parse_user_reviews_page(
                reviews_page.text,
                self.config.base_url,
                user_id,
            )
            profile = result.get("profile") or {}
            if _normalized_text(profile.get("author_display")) != _normalized_text(query):
                return {
                    "query": query,
                    "total": 0,
                    "items": [],
                    "source": "live_site_user_not_found",
                    "public_only": True,
                }
            result["items"] = result["items"][:limit]
            result.update(
                {
                    "query": query,
                    "source": "live_site_user_reviews",
                    "search_result_total": search_result["total"],
                    "public_only": True,
                }
            )
            return result
        if user_lookup:
            return {
                "query": query,
                "total": 0,
                "items": [],
                "source": "live_site_user_not_found",
                "public_only": True,
            }
        return {
            "query": query,
            "total": search_result["total"],
            "items": search_result["items"][:limit],
            "source": "live_site_review_search",
            "public_only": True,
        }

    def get_site_rankings(self) -> dict[str, Any]:
        page = self.fetcher.fetch_site_rankings()
        result = parse_site_rankings_page(page.text, self.config.base_url)
        result["public_only"] = True
        return result

    def get_site_statistics(self) -> dict[str, Any]:
        page = self.fetcher.fetch_site_stats()
        result = parse_site_stats_page(page.text)
        result["public_only"] = True
        return result

    def crawl_latest_reviews(self, pages: int = 1, per_page: int = 10, max_courses: int | None = None) -> dict[str, Any]:
        pages = max(1, min(pages, 20))
        per_page = max(1, min(per_page, 50))
        seen: set[int] = set()
        details_done = 0
        errors: list[dict[str, Any]] = []

        for page_no in range(1, pages + 1):
            try:
                page = self.fetcher.fetch_latest_reviews(page_no, per_page=per_page)
                for course_id in self.fetcher.extract_course_ids(page.text):
                    if course_id in seen:
                        continue
                    if max_courses is not None and len(seen) >= max_courses:
                        break
                    seen.add(course_id)
                    try:
                        self.crawl_course(course_id, sort_by="pubtime_desc")
                        details_done += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append({"course_id": course_id, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                errors.append({"page": page_no, "error": str(exc)})

        return {
            "latest_pages_done": pages,
            "unique_courses_found": len(seen),
            "course_details_crawled": details_done,
            "errors": errors,
            "db_stats": self.store.stats(),
            "public_only": True,
        }


def _normalized_text(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _public_course_list_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "name": item["name"],
        "url": item["url"],
        "teachers": [
            {"id": None, "name": name, "dept": None}
            for name in item.get("teachers", [])
        ],
        "term_text": item.get("term_text"),
        "courseries": item.get("courseries"),
        "dept": item.get("dept"),
        "course_type": item.get("course_type"),
        "join_type": item.get("join_type"),
        "teaching_type": item.get("teaching_type"),
        "course_level": item.get("course_level"),
        "credit": item.get("credit"),
        "rating_average": item.get("rating_average"),
        "review_count_site": item.get("review_count"),
        "visible_review_count": item.get("visible_review_count"),
        "missing_review_count_estimate": item.get("missing_review_count_estimate"),
        "difficulty": item.get("difficulty"),
        "homework": item.get("homework"),
        "grading": item.get("grading"),
        "gain": item.get("gain"),
    }


def _exact_review_author(result: dict[str, Any], query: str) -> dict[str, Any] | None:
    for item in result.get("items", []):
        if (
            _normalized_text(item.get("author_display")) == _normalized_text(query)
            and item.get("user_id") is not None
        ):
            return {
                "user_id": int(item["user_id"]),
                "author_display": item.get("author_display"),
            }
    return None


def _review_course_ids(result: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for item in result.get("items", []):
        course_id = item.get("course_id")
        if isinstance(course_id, int) and course_id not in values:
            values.append(course_id)
    return values
