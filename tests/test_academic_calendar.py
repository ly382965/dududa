from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from academic_calendar_mcp.models import CalendarDay, TermCalendar
from academic_calendar_mcp.storage import CalendarStore

try:  # parser requires beautifulsoup4; skip gracefully when unavailable
    from academic_calendar_mcp.parser import parse_listing, parse_term_detail

    HAS_BS4 = True
except ImportError:  # pragma: no cover
    HAS_BS4 = False


def _build_fixture() -> str:
    from datetime import date, timedelta

    events: dict[str, tuple[str | None, bool]] = {
        "2026-08-30": ("老生开学注册", False),
        "2026-08-31": ("老生上课", False),
        "2026-09-25": ("中秋节", True),
        "2026-10-01": ("国庆节", True),
        "2026-10-02": (None, True),
        "2026-10-03": (None, True),
        "2027-01-01": ("元旦", True),
        "2027-01-02": (None, True),
        "2027-01-15": ("秋季学期结束", False),
        "2027-01-16": ("学生寒假开始", False),
        "2027-01-31": ("寒假", False),
        "2027-02-05": ("除夕", False),
        "2027-02-06": ("春节", False),
        "2027-02-21": ("开学注册", False),
        "2027-02-22": ("开始上课", False),
    }
    week_labels: dict[str, str] = {
        "2026-08-30": "秋1",
        "2026-09-27": "秋5",
        "2026-12-27": "秋18",
        "2027-01-10": "秋20",
        "2027-02-21": "春1",
    }
    rows: list[str] = []
    current: date = date(2026, 8, 2)  # Sunday
    end: date = date(2027, 2, 27)
    first_row = True
    while current <= end:
        cells: list[str] = []
        if first_row:
            cells.append('<td rowspan="8">八</td>')
            first_row = False
        cells.append("<td>%s</td>" % week_labels.get(current.isoformat(), ""))
        for offset in range(7):
            day = current + timedelta(days=offset)
            day_no = day.day
            name, is_off = events.get(day.isoformat(), (None, False))
            content = ""
            if name and is_off:
                content = f"{name} <i>*休</i>"
            elif name:
                content = name
            elif is_off:
                content = "<i>*休</i>"
            cells.append(f"<td>{day_no}</td>")
            cells.append(f"<td>{content}</td>")
        rows.append("<tr>%s</tr>" % "".join(cells))
        current += timedelta(days=7)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title> 2026年秋季学期 : 中国科学技术大学教务处</title>
<link rel="canonical" href="https://www.teach.ustc.edu.cn/calendar/20135.html" />
</head><body><article>
<ul>
<li>一、秋季学期于 2026 年 8 月 30 日开学注册，8 月 31 日上课。</li>
<li>二、寒假于 2027 年 1 月 16 日开始。</li>
</ul>
<table class="res-wrap table3 calendar">
<thead><tr>
<th>月</th><th>教学周</th>
<th colspan="2">星期日</th><th colspan="2">星期一</th><th colspan="2">星期二</th>
<th colspan="2">星期三</th><th colspan="2">星期四</th><th colspan="2">星期五</th><th colspan="2">星期六</th>
</tr></thead>
<tfoot><tr><td colspan="7">订阅此日历</td><td colspan="6"></td><td colspan="3">下载</td></tr></tfoot>
<tbody>
{''.join(rows)}
</tbody></table>
</article></body></html>
"""


FIXTURE_HTML = _build_fixture()


@unittest.skipUnless(HAS_BS4, "beautifulsoup4 is not installed")
class CalendarParserTests(unittest.TestCase):
    def test_parses_term_identity_and_notes(self) -> None:
        term = parse_term_detail(FIXTURE_HTML, "https://www.teach.ustc.edu.cn")
        self.assertEqual(term.name, "2026年秋季学期")
        self.assertEqual(term.term_id, 20135)
        self.assertEqual(term.base_year, 2026)
        self.assertTrue(any("开学注册" in note for note in term.notes))
        self.assertTrue(any("寒假" in note for note in term.notes))

    def test_reconstructs_cross_month_dates(self) -> None:
        days = {day.date: day for day in parse_term_detail(FIXTURE_HTML, "https://www.teach.ustc.edu.cn").days}
        self.assertEqual(days["2026-08-30"].event_name, "老生开学注册")
        self.assertEqual(days["2026-08-31"].event_name, "老生上课")

        national = days["2026-10-01"]
        self.assertEqual(national.event_name, "国庆节")
        self.assertTrue(national.is_off_day)
        self.assertEqual(national.week_label, "秋5")

    def test_wraps_into_next_year(self) -> None:
        days = {day.date: day for day in parse_term_detail(FIXTURE_HTML, "https://www.teach.ustc.edu.cn").days}
        new_year = days["2027-01-01"]
        self.assertEqual(new_year.event_name, "元旦")
        self.assertTrue(new_year.is_off_day)
        self.assertEqual(new_year.week_label, "秋18")

    def test_february_block_keeps_january_lead_day(self) -> None:
        days = {day.date: day for day in parse_term_detail(FIXTURE_HTML, "https://www.teach.ustc.edu.cn").days}
        self.assertEqual(days["2027-01-31"].event_name, "寒假")
        self.assertEqual(days["2027-02-05"].event_name, "除夕")
        self.assertEqual(days["2027-02-06"].event_name, "春节")
        self.assertNotIn("2027-03-01", days)

    def test_skips_tfoot_and_rejects_invalid_dates(self) -> None:
        days = [day.date for day in parse_term_detail(FIXTURE_HTML, "https://www.teach.ustc.edu.cn").days]
        self.assertNotIn("2027-02-31", days)
        self.assertNotIn("2026-09-01", days)


@unittest.skipUnless(HAS_BS4, "beautifulsoup4 is not installed")
class CalendarListingTests(unittest.TestCase):
    def test_parse_listing_extracts_ids(self) -> None:
        html = (
            '<div class="post"><a href="https://www.teach.ustc.edu.cn/calendar/20135.html">'
            "2026年秋季学期</a><span>2026-05-21</span></div>"
        )
        listings = parse_listing(html, "https://www.teach.ustc.edu.cn")
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].term_id, 20135)
        self.assertEqual(listings[0].name, "2026年秋季学期")
        self.assertEqual(listings[0].published_at, "2026-05-21")


class CalendarStorageTests(unittest.TestCase):
    def test_schema_initializes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "calendar.sqlite3"
            CalendarStore(database)
            with sqlite3.connect(database) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"terms", "events", "meta"} <= tables)

    def test_term_upsert_and_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "calendar.sqlite3"
            store = CalendarStore(database)
            term = TermCalendar(
                term_id=20135,
                name="2026年秋季学期",
                url="https://www.teach.ustc.edu.cn/calendar/20135.html",
                base_year=2026,
                notes=["一、秋季学期于 2026 年 8 月 30 日开学注册。"],
                days=[
                    CalendarDay("2027-01-01", 2027, 1, 1, 5, "秋18", "元旦", True),
                    CalendarDay("2027-02-06", 2027, 2, 6, 6, None, "春节", False),
                ],
            )
            store.upsert_term(term, source_hash="abc")
            by_name = store.get_term("2026年秋季学期")
            self.assertIsNotNone(by_name)
            self.assertEqual(by_name["id"], 20135)
            self.assertIn("元旦", [row["event_name"] for row in by_name["events"]])

            feb = store.get_events_on("2027-02-06")
            self.assertEqual(feb[0]["event_name"], "春节")
            self.assertEqual(feb[0]["term_name"], "2026年秋季学期")

            hits = store.search_events("元旦")
            self.assertEqual(hits[0]["date"], "2027-01-01")

    def test_get_current_term_picks_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "calendar.sqlite3"
            store = CalendarStore(database)
            term = TermCalendar(
                term_id=20135,
                name="2026年秋季学期",
                url="https://www.teach.ustc.edu.cn/calendar/20135.html",
                base_year=2026,
                days=[
                    CalendarDay("2026-08-30", 2026, 8, 30, 7, "秋1", "老生开学注册", False),
                    CalendarDay("2027-02-20", 2027, 2, 20, 6, None, "学生寒假结束", False),
                ],
            )
            store.upsert_term(term)
            current = store.get_current_term("2026-11-11")
            self.assertIsNotNone(current)
            self.assertEqual(current["name"], "2026年秋季学期")
            self.assertIsNone(store.get_current_term("2027-03-01"))


if __name__ == "__main__":
    unittest.main()