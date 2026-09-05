from __future__ import annotations

import unittest
from datetime import datetime, timezone

from astrbot_plugin_dududa_core.adapters.capability_planner import (
    YOUNG_ACTIVITY_CAPABILITY_ID,
    YOUNG_FACETS_CAPABILITY_ID,
    YOUNG_INTENT_CAPABILITIES,
    YOUNG_SEARCH_CAPABILITY_ID,
    YOUNG_STATUS_CAPABILITY_ID,
    _declared_arguments,
    _requested_result_limit,
    _young_capability,
    _young_state,
    _young_time_window,
    supports_production_query_schema,
)


class YoungCapabilityPlannerTests(unittest.TestCase):
    def test_standard_intents_select_four_read_capabilities(self) -> None:
        self.assertEqual(
            YOUNG_INTENT_CAPABILITIES,
            {
                "ustc.young.activity.search": YOUNG_SEARCH_CAPABILITY_ID,
                "ustc.young.activity.get": YOUNG_ACTIVITY_CAPABILITY_ID,
                "ustc.young.facets.list": YOUNG_FACETS_CAPABILITY_ID,
                "ustc.young.connection.status": YOUNG_STATUS_CAPABILITY_ID,
            },
        )
        for intent_id, capability_id in YOUNG_INTENT_CAPABILITIES.items():
            with self.subTest(intent_id=intent_id):
                self.assertEqual(_young_capability((intent_id,)), capability_id)
        self.assertIsNone(_young_capability(("ustc.young.activities.mine",)))

    def test_relative_dates_use_shanghai_calendar(self) -> None:
        observed_at = datetime(2026, 8, 29, 1, 30, tzinfo=timezone.utc)

        self.assertEqual(
            _young_time_window("今天有什么二课", observed_at),
            ("2026-08-29T00:00:00", "2026-08-29T23:59:59"),
        )
        self.assertEqual(
            _young_time_window("未来三天有哪些活动", observed_at),
            ("2026-08-29T09:30:00", "2026-08-31T23:59:59"),
        )
        self.assertEqual(
            _young_time_window("周末二课哪个学时最多", observed_at),
            ("2026-08-29T00:00:00", "2026-08-30T23:59:59"),
        )
        self.assertIsNone(
            _young_time_window("哪些活动今天报名截止", observed_at)
        )

    def test_history_and_schema_projection_are_bounded(self) -> None:
        self.assertEqual(_young_state("最近一周已经结束的活动"), "history")
        self.assertEqual(_young_state("今天还能报名的活动"), "applying")
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "state": {"type": "string"},
                "limit": {"type": "integer"},
            },
        }
        self.assertEqual(
            _declared_arguments(
                schema,
                {"query": "人工智能", "state": "applying", "limit": 50},
            ),
            {"query": "人工智能", "state": "applying", "limit": 50},
        )
        self.assertTrue(
            supports_production_query_schema(YOUNG_SEARCH_CAPABILITY_ID, schema)
        )

    def test_explicit_result_count_narrows_but_never_widens_default(self) -> None:
        self.assertEqual(_requested_result_limit("最多列 3 项", 8), 3)
        self.assertEqual(_requested_result_limit("列出前五场", 8), 5)
        self.assertEqual(_requested_result_limit("只列出 20 条", 8), 8)
        self.assertEqual(_requested_result_limit("未来三天有哪些活动", 8), 8)
        self.assertEqual(_requested_result_limit("列出当前二课活动", 8), 8)

    def test_ranked_top_results_keep_the_bounded_candidate_set(self) -> None:
        self.assertEqual(
            _requested_result_limit("把当前二课按报名填充率排序，列出前三项。", 20),
            20,
        )
        self.assertEqual(_requested_result_limit("列出学时最高的三项", 20), 20)


if __name__ == "__main__":
    unittest.main()
