from __future__ import annotations

import unittest

from ustc_campus_mcp.calendar import TeachingCalendarClient
from ustc_campus_mcp.server import create_mcp
from ustc_campus_mcp.shuttle import ShuttleClient
from ustc_campus_mcp.young import YoungClient


class UstcCampusContractTests(unittest.TestCase):
    def test_each_registry_service_has_only_approved_read_tools(self) -> None:
        self.assertEqual(
            {tool.name for tool in create_mcp("academic")._tool_manager.list_tools()},
            {
                "catalog_get_program",
                "catalog_list_semesters",
                "catalog_search_exams",
                "catalog_search_lessons",
                "catalog_search_programs",
                "teaching_calendar_get",
            },
        )
        self.assertEqual(
            {tool.name for tool in create_mcp("shuttle")._tool_manager.list_tools()},
            {"shuttle_current_schedule", "shuttle_search_trips"},
        )
        self.assertEqual(
            {tool.name for tool in create_mcp("young")._tool_manager.list_tools()},
            {
                "young_connection_status",
                "young_get_activity",
                "young_list_facets",
                "young_list_my_activities",
                "young_search_activities",
            },
        )

    def test_calendar_uses_article_table_instead_of_stale_widget_json(self) -> None:
        parsed = TeachingCalendarClient.parse(
            """
            <html><h1>2026年秋季学期</h1>
            <script>window.teachCalendarData={calendarData:[{start:'2019-1-1'}]}</script>
            <article><table class="calendar"><tbody>
              <tr><td>八</td><td></td><td>21</td><td>新生报到</td></tr>
              <tr><td>秋1</td><td>30</td><td>老生开学注册</td></tr>
            </tbody></table></article></html>
            """
        )
        self.assertEqual(parsed["events"][0], {"date": "2026-08-21", "week": "", "event": "新生报到"})
        self.assertNotIn("2019", repr(parsed))

    def test_young_missing_secret_and_shuttle_aliases_are_explicit(self) -> None:
        self.assertEqual(YoungClient("", "").status()["authentication"], "missing_secret")
        self.assertEqual(ShuttleClient._station("高新校区"), "hightech")


if __name__ == "__main__":
    unittest.main()
