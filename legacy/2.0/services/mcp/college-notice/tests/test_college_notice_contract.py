from __future__ import annotations

"""Contract tests for the optional college-notice MCP service."""

import stat
import tempfile
import unittest
from pathlib import Path

from college_notice_mcp.config import AppConfig
from college_notice_mcp.models import CollegeNoticeDetail
from college_notice_mcp.parser import notice_id_from_url, parse_notice_list
from college_notice_mcp.server import _source_url, create_mcp
from college_notice_mcp.storage import CollegeNoticeStore


class CollegeNoticeContractTests(unittest.TestCase):
    def test_list_parser_accepts_compact_and_segmented_webplus_dates(self) -> None:
        college = AppConfig().colleges[0]
        html = """
        <ul>
          <li><a href="/2026/0901/c100a200/page.htm">紧凑日期</a><span>2026-09-01</span></li>
          <li><a href="/2026/09/02/c_101a_201/page.htm">分段日期</a><span>2026-09-02</span></li>
        </ul>
        """
        items = parse_notice_list(html, college)
        self.assertEqual(
            [item.notice_id for item in items],
            ["2026/0901/c100a200", "2026/09/02/c_101a_201"],
        )
        self.assertEqual(
            notice_id_from_url(
                "https://math.ustc.edu.cn/2026/09/02/c_101a_201/page.htm?x=1"
            ),
            "2026/09/02/c_101a_201",
        )

    def test_list_parser_rejects_external_detail_urls(self) -> None:
        college = AppConfig().colleges[0]
        html = """
        <a href="https://evil.example/2026/09/01/c_1a_2/page.htm">外部通知</a>
        <a href="/2026/09/01/c_3a_4/page.htm">学院通知</a><span>2026-09-01</span>
        """
        items = parse_notice_list(html, college)
        self.assertEqual([item.notice_id for item in items], ["2026/09/01/c_3a_4"])

    def test_source_url_projection_rejects_malformed_or_oversized_values(self) -> None:
        self.assertEqual(_source_url("https://[malformed"), "")
        self.assertEqual(_source_url("https://math.ustc.edu.cn/" + "x" * 2_049), "")

    def test_transport_exposes_only_allowlisted_cache_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "notices.sqlite3"
            store = CollegeNoticeStore(database)
            store.upsert_detail(
                CollegeNoticeDetail(
                    notice_id="math:1",
                    college_key="math",
                    title="数学学院公开通知",
                    url="https://math.ustc.edu.cn/2026/09/01/c1a1/page.htm",
                    published_at="2026-09-01",
                    content_text="学术报告",
                    attachments=[
                        {"name": "议程", "url": "https://math.ustc.edu.cn/a.pdf"},
                        {"name": "外站", "url": "https://example.com/a.pdf"},
                    ],
                )
            )
            mcp = create_mcp(AppConfig(db_path=database))
            tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
            self.assertEqual(set(tools), {"college_notices_public_query"})
            result = tools["college_notices_public_query"].fn(
                query="报告", college_key="math", limit=1
            )
            self.assertEqual(result["returned"], 1)
            self.assertEqual(len(result["items"][0]["attachments"]), 1)
            self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

            with self.assertRaises(ValueError):
                tools["college_notices_public_query"].fn(
                    query="", college_key="unknown"
                )


if __name__ == "__main__":
    unittest.main()
