from __future__ import annotations

"""Contract tests for the optional campus-events MCP service."""

import stat
import tempfile
import unittest
from pathlib import Path

from campus_events_mcp.config import AppConfig
from campus_events_mcp.models import EventDetail
from campus_events_mcp.parser import parse_event_list
from campus_events_mcp.server import _source_url, create_mcp
from campus_events_mcp.storage import CampusEventStore


class CampusEventsContractTests(unittest.TestCase):
    def test_list_parser_keeps_per_item_category_when_inferred(self) -> None:
        html = """
        <ul>
          <li><a href="/info/1360/1.htm">教学通知</a><span>2026-09-01</span></li>
          <li><a href="/info/1362/2.htm">科研通知</a><span>2026-09-02</span></li>
        </ul>
        """
        items = parse_event_list(html, "https://www.ustc.edu.cn")
        self.assertEqual([item.category for item in items], ["教学", "科研"])

    def test_list_parser_rejects_external_detail_urls(self) -> None:
        html = """
        <a href="https://evil.example/info/1360/1.htm">外部通知</a>
        <a href="/info/1360/2.htm">校内通知</a>
        """
        items = parse_event_list(html, "https://www.ustc.edu.cn")
        self.assertEqual([item.event_id for item in items], ["1360/2"])

    def test_source_url_projection_rejects_malformed_or_oversized_values(self) -> None:
        self.assertEqual(_source_url("https://[malformed"), "")
        self.assertEqual(_source_url("https://www.ustc.edu.cn/" + "x" * 2_049), "")

    def test_transport_exposes_only_bounded_cache_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "events.sqlite3"
            store = CampusEventStore(database)
            store.upsert_detail(
                EventDetail(
                    event_id="1360/1",
                    category="教学",
                    title="公开教学通知",
                    url="https://www.ustc.edu.cn/info/1360/1.htm",
                    published_at="2026-09-01",
                    content_text="课程安排 " + "甲" * 2_000,
                    attachments=[
                        {"name": "通知附件", "url": "https://www.ustc.edu.cn/file/a.pdf"},
                        {"name": "外站", "url": "https://example.com/a.pdf"},
                    ],
                )
            )
            mcp = create_mcp(AppConfig(db_path=database))
            tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
            self.assertEqual(set(tools), {"campus_events_public_query"})

            result = tools["campus_events_public_query"].fn(
                query="课程", category="教学", limit=1
            )
            self.assertEqual(result["returned"], 1)
            self.assertLessEqual(len(result["items"][0]["summary"]), 1_600)
            self.assertEqual(len(result["items"][0]["attachments"]), 1)
            self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

            with self.assertRaises(ValueError):
                tools["campus_events_public_query"].fn(query="x" * 201)


if __name__ == "__main__":
    unittest.main()
