from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest.mock import patch

from icourse_mcp.config import AppConfig
from icourse_mcp.server import create_mcp


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

    def close(self) -> None:
        self.close_calls += 1


class _ForbiddenCrawler:
    instances: ClassVar[list[_ForbiddenCrawler]] = []

    def __init__(self, config, store) -> None:
        self.config = config
        self.store = store
        self.calls: list[tuple[str, int]] = []
        self.close_calls = 0
        self.instances.append(self)

    def search_site_reviews(self, query: str, limit: int):
        self.calls.append((query, limit))
        return {"total": 0, "items": [], "source": "live_site_review_search"}

    def __getattr__(self, name: str):
        if name.startswith(("crawl", "search", "check", "fetch")):
            raise AssertionError(f"read-only Capability touched crawler method: {name}")
        raise AttributeError(name)

    def close(self) -> None:
        self.close_calls += 1


class _LiveReviewCrawler:
    instances: ClassVar[list[_LiveReviewCrawler]] = []

    def __init__(self, config, store) -> None:
        self.calls: list[tuple[str, int]] = []
        self.close_calls = 0
        self.instances.append(self)

    def search_site_reviews(self, query: str, limit: int):
        self.calls.append((query, limit))
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
                [("萌萌哒mmd", 10)],
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

    async def test_approved_capability_uses_live_read_for_review_queries(self) -> None:
        with TemporaryDirectory() as temporary:
            _ForbiddenCrawler.instances.clear()
            config = AppConfig(db_path=Path(temporary) / "icourse.sqlite3")
            with patch("icourse_mcp.server.ICourseCrawler", _ForbiddenCrawler):
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
                    self.assertEqual(stats["courses"], 0)
                    self.assertEqual(search["items"], [])
                    self.assertFalse(course["ok"])
                    self.assertEqual(reviews["reviews"], [])
                self.assertEqual(len(_ForbiddenCrawler.instances), 1)
                self.assertEqual(
                    _ForbiddenCrawler.instances[0].calls,
                    [("fixture", 20), ("fixture", 20)],
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
                            ("crawl_course", 2),
                            ("check_robots", None),
                        ],
                    )
                    self.assertEqual(_Crawler.instances[0].close_calls, 0)
                self.assertEqual(_Crawler.instances[0].close_calls, 1)


if __name__ == "__main__":
    unittest.main()
