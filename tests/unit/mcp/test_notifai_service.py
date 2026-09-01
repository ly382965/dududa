from __future__ import annotations

import io
import logging
import sys
import unittest
from pathlib import Path

import httpx

SERVICE_SRC = Path(__file__).resolve().parents[3] / "services" / "mcp" / "notifai" / "src"
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from notifai_mcp.client import NotifAIClient
from notifai_mcp.config import AppConfig
from notifai_mcp.server import create_mcp


def notice_payload(content: str = "通知正文") -> dict[str, object]:
    return {
        "items": [
            {
                "id": "notice-1",
                "title": "校园通知",
                "source": "教务处",
                "categories": ["教学"],
                "publishDate": "2026-08-28",
                "aiSummary": "摘要",
                "deadline": None,
                "targetAudience": "学生",
                "coreAction": "查看通知",
                "originUrl": "https://example.test/notices/1",
                "cleanContent": content,
                "firstSeen": None,
                "lastCrawl": None,
                "attachments": [],
            }
        ],
        "total": 1,
        "nextCursor": None,
    }


class _StubClient:
    def search_notices(self, **_kwargs: object) -> dict[str, object]:
        return notice_payload()


class NotifAIServiceTests(unittest.TestCase):
    def test_search_light_flag_controls_content_projection(self) -> None:
        tool = create_mcp(AppConfig(), client=_StubClient())._tool_manager.get_tool(
            "search_notices"
        )

        light = tool.fn(light=True)
        full = tool.fn(light=False)

        self.assertEqual(light["data"]["items"][0]["cleanContent"], "")
        self.assertIn("content_omitted_in_light_mode", light["warnings"])
        self.assertEqual(full["data"]["items"][0]["cleanContent"], "通知正文")
        self.assertNotIn("content_omitted_in_light_mode", full["warnings"])

    def test_httpx_request_log_does_not_include_query_values(self) -> None:
        sentinel = "private-user-query-123"
        records = io.StringIO()
        handler = logging.StreamHandler(records)
        logger = logging.getLogger("httpx")
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": [], "total": 0}, request=request)

        client = NotifAIClient(
            AppConfig(), transport=httpx.MockTransport(handle)
        )
        try:
            client.search_notices(keyword=sentinel)
        finally:
            client.close()
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        output = records.getvalue()
        self.assertNotIn(sentinel, output)
        self.assertIn("/api/notices", output)
        self.assertNotIn("?keyword=", output)

    def test_max_items_matches_generated_schema_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            AppConfig(max_items=101)


if __name__ == "__main__":
    unittest.main()
