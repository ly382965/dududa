from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for service in ("campus-events", "college-notice", "training-plan"):
    sys.path.insert(0, str(ROOT / "services/mcp" / service / "src"))

from campus_events_mcp.parser import _resolve_date
from campus_events_mcp.models import EventItem
from campus_events_mcp.storage import CampusEventStore
from college_notice_mcp.config import AppConfig
from college_notice_mcp.parser import parse_notice_list
from training_plan_mcp.parser import parse_overview


class PublicSourceRegressionTests(unittest.TestCase):
    def test_full_year_is_preserved_and_month_day_rolls_back(self):
        self.assertEqual(_resolve_date("2026-09-04", date(2026, 9, 4)), "2026-09-04")
        self.assertEqual(_resolve_date("2024/02/29", date(2026, 9, 4)), "2024-02-29")
        self.assertEqual(_resolve_date("12-31", date(2026, 1, 1)), "2025-12-31")
        self.assertIsNone(_resolve_date("2026-02-30", date(2026, 9, 4)))

    def test_aggregate_cannot_erase_specific_category_or_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = CampusEventStore(Path(temporary) / "events.db")
            store.upsert_item(EventItem("1360/1", "教学", "title", "https://www.ustc.edu.cn/info/1360/1.htm", "2026-09-04"))
            store.upsert_item(EventItem("1360/1", "综合", "title", "https://www.ustc.edu.cn/info/1360/1.htm", None))
            item = store.list_events(limit=1)[0]
            self.assertEqual(item["category"], "教学")
            self.assertEqual(item["published_at"], "2026-09-04")

    def test_physics_keeps_undated_notice_but_excludes_sidebar(self):
        college = next(item for item in AppConfig().colleges if item.key == "physics")
        html = '<a href="/2026/0730/c3584a123456/page.htm">暑假通知</a><a href="/2020/0101/c999a123456/page.htm">热点新闻</a>'
        items = parse_notice_list(html, college)
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0].published_at)

    def test_old_program_table_without_tbody_and_fullwidth_code(self):
        html = '<table class="table2"><caption>2013级本科专业设置一览</caption><tr><td>学院（1）</td><td>数学系</td><td>数学</td><td>070101（理）</td></tr></table>'
        years, rows = parse_overview(html, "https://www.teach.ustc.edu.cn")
        self.assertEqual(years[0].year, 2013)
        self.assertEqual(rows[0].code, "070101")
        self.assertEqual(rows[0].degree, "理")


if __name__ == "__main__":
    unittest.main()
