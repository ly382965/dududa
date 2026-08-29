from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager

from ustc_campus_mcp.calendar import TeachingCalendarClient
from ustc_campus_mcp.server import create_mcp
from ustc_campus_mcp.shuttle import ShuttleClient
from ustc_campus_mcp.young import YoungClient


class UstcCampusContractTests(unittest.TestCase):
    def test_each_registry_service_has_only_approved_read_tools(self) -> None:
        self.assertEqual(
            {tool.name for tool in create_mcp("academic")._tool_manager.list_tools()},
            {
                "catalog_list_semesters",
                "catalog_search_exams",
                "catalog_search_lessons",
                "teaching_calendar_get",
            },
        )
        self.assertEqual(
            {
                tool.name
                for tool in create_mcp("curriculum")._tool_manager.list_tools()
            },
            {"curriculum_public_query"},
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

    def test_young_activity_is_not_applyable_when_capacity_is_full(self) -> None:
        class Activity:
            def __init__(self) -> None:
                self.id = "activity-1"
                self.data = {
                    "itemName": "测试讲座",
                    "itemStatus": 26,
                    "itemCategory": "0",
                    "applyNum": 100,
                    "peopleNum": 100,
                    "booleanRegistration": 0,
                }

            @property
            def status(self):
                return type("Status", (), {"text": "报名中"})()

        result = YoungClient._activity(Activity())

        self.assertEqual(result["capacity"], {"registered": 100, "limit": 100})
        self.assertFalse(result["can_apply"])

    def test_young_upstream_failure_is_a_visible_read_observation(self) -> None:
        class UnavailableYoungClient(YoungClient):
            @asynccontextmanager
            async def _service(self):
                raise RuntimeError("private upstream detail")
                yield

        result = asyncio.run(
            UnavailableYoungClient("service", "secret").search_activities(limit=1)
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["available"])
        self.assertEqual(result["error"], "young_authentication_or_upstream_failed")
        self.assertEqual(result["items"], [])
        self.assertNotIn("private upstream detail", repr(result))


if __name__ == "__main__":
    unittest.main()
