from __future__ import annotations

"""Contract tests for the optional library-hours MCP service."""

import stat
import tempfile
import unittest
from pathlib import Path

from library_mcp.config import AppConfig
from library_mcp.parser import parse_opening_hours
from library_mcp.server import create_mcp
from library_mcp.storage import LibraryStore

FIXTURE = """
<table>
  <tr><th>校区</th><th>业务地点</th><th>业务内容</th><th>周一</th><th>周五</th><th>周六</th><th>周日</th><th>联系电话</th></tr>
  <tr><td rowspan="2">东区</td><td rowspan="2">一楼</td><td>借阅</td><td>08:00</td><td>22:00</td><td>09:00</td><td>18:00</td><td>123</td></tr>
  <tr><td>自习</td><td>07:00</td><td>23:00</td><td>08:00</td><td>22:00</td><td>456</td></tr>
</table>
"""


class LibraryContractTests(unittest.TestCase):
    def test_rowspans_and_time_ranges_survive_cache_projection(self) -> None:
        rows = parse_opening_hours(FIXTURE, "https://lib.ustc.edu.cn")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].location, "一楼")
        self.assertEqual(rows[1].service, "自习")
        self.assertEqual(rows[1].weekday, "07:00-23:00")

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "library.sqlite3"
            LibraryStore(database).replace_hours(rows, source_hash="fixture")
            mcp = create_mcp(AppConfig(db_path=database))
            tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
            self.assertEqual(set(tools), {"library_hours_public_query"})
            result = tools["library_hours_public_query"].fn(
                query="自习", campus="东区", limit=2
            )
            self.assertEqual(result["returned"], 1)
            self.assertEqual(result["items"][0]["weekend"], "08:00-22:00")
            self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

    def test_non_ustc_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(base_url="https://example.com")


if __name__ == "__main__":
    unittest.main()
