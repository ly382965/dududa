from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest.mock import patch

from icourse_mcp.config import AppConfig
from icourse_mcp.server import _user_lookup_requested, create_mcp
from icourse_mcp.storage import ICourseStore


class _Crawler:
    instances: ClassVar[list[_Crawler]] = []

    def __init__(self, config, store) -> None:
        self.config = config
        self.store = store
        self.calls: list[tuple[str, object]] = []
        self.close_calls = 0
        self.instances.append(self)

    def crawl_course(self, course_id, sort_by="upvote"):
        self.calls.append(("crawl_course", course_id))
        return {"ok": True, "course_id": course_id}

    def check_robots(self):
        self.calls.append(("check_robots", None))
        return {"ok": True}

    def get_site_course(self, course_id, *, include_reviews=True, sort_by="upvote"):
        self.calls.append(("get_site_course", course_id))
        return {"id": course_id, "name": "fixture"}

    def close(self) -> None:
        self.close_calls += 1


class _ForbiddenCrawler:
    instances: ClassVar[list[_ForbiddenCrawler]] = []

    def __init__(self, config, store) -> None:
        self.config = config
        self.store = store
        self.calls: list[tuple[str, object]] = []
        self.close_calls = 0
        self.instances.append(self)

    def query_site_courses(self, query: str, limit: int):
        self.calls.append(("course", (query, limit)))
        return {
            "total": 1,
            "items": [{"id": 1, "name": "fixture", "url": "https://icourse.club/course/1/"}],
            "source": "live_site_course_search",
        }

    def search_site_reviews(self, query: str, limit: int, *, user_lookup: bool = False):
        self.calls.append(("review", (query, limit, user_lookup)))
        return {"total": 0, "items": [], "source": "live_site_review_search"}

    def search_site_teachers(self, query: str, limit: int):
        self.calls.append(("teacher", (query, limit)))
        return {
            "total": 1,
            "items": [
                {
                    "name": "测试教师",
                    "course_count": 1,
                    "review_count": 3,
                    "courses": [
                        {
                            "id": 1,
                            "name": "fixture",
                            "review_count_site": 3,
                        }
                    ],
                }
            ],
            "source": "live_site_course_search",
        }

    def get_site_rankings(self):
        self.calls.append(("ranking", None))
        return {"source": "live_site_rankings"}

    def get_site_statistics(self):
        self.calls.append(("stats", None))
        return {
            "source": "live_site_stats",
            "coverage": {
                "courses": 1,
                "courses_with_detail": 0,
                "public_reviews": 2,
                "last_detail_crawled_at": None,
                "last_list_crawled_at": None,
            },
        }

    def get_site_course(self, course_id, *, include_reviews=True, sort_by="upvote"):
        self.calls.append(
            ("course_detail", (course_id, include_reviews, sort_by))
        )
        return {
            "id": course_id,
            "name": "fixture",
            "teachers": [{"id": 1, "name": "测试教师", "dept": None}],
            "reviews": [
                {
                    "id": 7,
                    "course_id": course_id,
                    "content_text": "讲课清楚，作业适中，期末考试与课堂内容一致。",
                    "rating_10": 9,
                }
            ],
        }

    def get_site_reviews(
        self,
        course_id,
        *,
        term=None,
        rating=None,
        sort_by="upvote",
        limit=50,
    ):
        self.calls.append(
            ("course_reviews", (course_id, term, rating, sort_by, limit))
        )
        return [{"id": 7, "course_id": course_id, "content_text": "live"}]

    def __getattr__(self, name: str):
        if name.startswith(("crawl", "search", "check", "fetch")):
            raise AssertionError(f"read-only Capability touched crawler method: {name}")
        raise AttributeError(name)

    def close(self) -> None:
        self.close_calls += 1


class _LiveReviewCrawler:
    instances: ClassVar[list[_LiveReviewCrawler]] = []

    def __init__(self, config, store) -> None:
        self.calls: list[tuple[str, object]] = []
        self.close_calls = 0
        self.instances.append(self)

    def query_site_courses(self, query: str, limit: int):
        self.calls.append(("course", (query, limit)))
        return {"total": 0, "items": [], "source": "live_site_course_search"}

    def search_site_reviews(self, query: str, limit: int, *, user_lookup: bool = False):
        self.calls.append(("review", (query, limit, user_lookup)))
        return {
            "total": 83,
            "source": "live_site_user_reviews",
            "profile": {"user_id": 7858, "author_display": "萌萌哒mmd"},
            "items": [
                {
                    "id": 103403,
                    "course_id": 24186,
                    "course_name": "数理逻辑基础（侯嘉慧）",
                    "author_display": "萌萌哒mmd",
                    "content_text": "公开点评摘要",
                }
            ],
        }

    def close(self) -> None:
        self.close_calls += 1


class ICourseServerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_bare_ascii_username_query_enables_user_lookup(self) -> None:
        self.assertTrue(
            _user_lookup_requested("查询评课社区wanglulu", "wanglulu")
        )
        self.assertFalse(
            _user_lookup_requested("评课社区搜索 Python 点评", "Python")
        )

    async def test_course_zero_hit_uses_live_review_author_result(self) -> None:
        with TemporaryDirectory() as temporary:
            _LiveReviewCrawler.instances.clear()
            config = AppConfig(db_path=Path(temporary) / "icourse.sqlite3")
            with patch("icourse_mcp.server.ICourseCrawler", _LiveReviewCrawler):
                mcp = create_mcp(config)
                async with mcp._mcp_server.lifespan(mcp._mcp_server):
                    result = await mcp._tool_manager.call_tool(
                        "icourse_public_query",
                        {"query": "萌萌哒mmd", "operation": "course", "limit": 10},
                    )

            self.assertEqual(result["operation"], "review")
            self.assertEqual(result["result"]["total"], 83)
            self.assertEqual(result["result"]["source"], "live_site_user_reviews")
            self.assertEqual(len(result["result"]["items"]), 1)
            self.assertEqual(
                _LiveReviewCrawler.instances[0].calls,
                [
                    ("course", ("萌萌哒mmd", 50)),
                    ("review", ("萌萌哒mmd", 10, False)),
                ],
            )

    async def test_course_operation_returns_matching_public_review_author(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "icourse.sqlite3"
            config = AppConfig(db_path=database)
            with patch("icourse_mcp.server.ICourseCrawler", _LiveReviewCrawler):
                mcp = create_mcp(config)
                async with mcp._mcp_server.lifespan(mcp._mcp_server):
                    result = await mcp._tool_manager.call_tool(
                        "icourse_public_query",
                        {"query": "萌萌哒mmd", "operation": "review"},
                    )

            self.assertEqual(result["operation"], "review")
            self.assertEqual(result["result"]["total"], 83)
            self.assertEqual(
                result["result"]["items"][0]["author_display"],
                "萌萌哒mmd",
            )

    async def test_recommendation_includes_live_review_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            _ForbiddenCrawler.instances.clear()
            config = AppConfig(db_path=Path(temporary) / "icourse.sqlite3")
            with patch("icourse_mcp.server.ICourseCrawler", _ForbiddenCrawler):
                mcp = create_mcp(config)
                async with mcp._mcp_server.lifespan(mcp._mcp_server):
                    result = await mcp._tool_manager.call_tool(
                        "icourse_public_query",
                        {
                            "query": "fixture",
                            "operation": "teacher",
                            "goal": "推荐 fixture 老师",
                        },
                    )

        self.assertEqual(result["result"]["review_sampled_course_count"], 1)
        self.assertEqual(
            result["result"]["review_evidence"][0]["course_teachers"][0]["name"],
            "测试教师",
        )
        self.assertEqual(
            result["result"]["review_evidence"][0]["samples"][0]["content_text"],
            "讲课清楚，作业适中，期末考试与课堂内容一致。",
        )

    async def test_all_approved_read_capabilities_bypass_local_cache(self) -> None:
        with TemporaryDirectory() as temporary:
            _ForbiddenCrawler.instances.clear()
            config = AppConfig(db_path=Path(temporary) / "icourse.sqlite3")
            cache_error = AssertionError("model capability read local iCourse cache")
            with (
                patch("icourse_mcp.server.ICourseCrawler", _ForbiddenCrawler),
                patch.object(ICourseStore, "stats", side_effect=cache_error),
                patch.object(ICourseStore, "search_courses", side_effect=cache_error),
                patch.object(ICourseStore, "get_course", side_effect=cache_error),
                patch.object(ICourseStore, "get_reviews", side_effect=cache_error),
            ):
                mcp = create_mcp(config)
                async with mcp._mcp_server.lifespan(mcp._mcp_server):
                    stats = await mcp._tool_manager.call_tool("icourse_stats", {})
                    search = await mcp._tool_manager.call_tool(
                        "search_courses",
                        {"query": "fixture"},
                    )
                    course = await mcp._tool_manager.call_tool(
                        "get_course",
                        {"course_id": 1, "refresh": False},
                    )
                    reviews = await mcp._tool_manager.call_tool(
                        "get_reviews",
                        {"course_id": 1},
                    )
                    for operation in ("course", "review", "teacher", "ranking", "stats"):
                        public_query = await mcp._tool_manager.call_tool(
                            "icourse_public_query",
                            {"query": "fixture", "operation": operation},
                        )
                        self.assertEqual(public_query["operation"], operation)
                    self.assertEqual(stats["courses"], 1)
                    self.assertEqual(search["items"][0]["id"], 1)
                    self.assertTrue(course["ok"])
                    self.assertEqual(reviews["reviews"][0]["content_text"], "live")
                self.assertEqual(len(_ForbiddenCrawler.instances), 1)
                self.assertEqual(
                    _ForbiddenCrawler.instances[0].calls,
                    [
                        ("stats", None),
                        ("course", ("fixture", 50)),
                        ("course_detail", (1, True, "upvote")),
                        ("course_reviews", (1, None, None, "upvote", 50)),
                        ("course", ("fixture", 50)),
                        ("review", ("fixture", 20, False)),
                        ("teacher", ("fixture", 20)),
                        ("ranking", None),
                        ("stats", None),
                    ],
                )
                self.assertEqual(_ForbiddenCrawler.instances[0].close_calls, 1)

    async def test_one_crawler_and_limiter_survive_all_tool_calls(self) -> None:
        with TemporaryDirectory() as temporary:
            _Crawler.instances.clear()
            config = AppConfig(db_path=Path(temporary) / "icourse.sqlite3")
            with patch("icourse_mcp.server.ICourseCrawler", _Crawler):
                mcp = create_mcp(config)
                async with mcp._mcp_server.lifespan(mcp._mcp_server):
                    await mcp._tool_manager.call_tool(
                        "crawl_course",
                        {"course_id": 1},
                    )
                    await mcp._tool_manager.call_tool(
                        "get_course",
                        {"course_id": 2, "refresh": True},
                    )
                    await mcp._tool_manager.call_tool("check_robots", {})
                    self.assertEqual(len(_Crawler.instances), 1)
                    self.assertEqual(
                        _Crawler.instances[0].calls,
                        [
                            ("crawl_course", 1),
                            ("get_site_course", 2),
                            ("check_robots", None),
                        ],
                    )
                    self.assertEqual(_Crawler.instances[0].close_calls, 0)
                self.assertEqual(_Crawler.instances[0].close_calls, 1)


if __name__ == "__main__":
    unittest.main()
