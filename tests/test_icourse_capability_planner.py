from __future__ import annotations

import unittest

from astrbot_plugin_dududa_core.adapters.capability_planner import (
    ICOURSE_INTENT_OPERATIONS,
    _icourse_operation,
    _query_arguments,
)


class ICourseCapabilityPlannerTests(unittest.TestCase):
    def test_standard_intents_project_to_five_operations(self) -> None:
        self.assertEqual(
            ICOURSE_INTENT_OPERATIONS,
            {
                "icourse.course.search": "course",
                "icourse.review.search": "review",
                "icourse.teacher.search": "teacher",
                "icourse.ranking.read": "ranking",
                "icourse.stats.read": "stats",
            },
        )
        for intent_id, operation in ICOURSE_INTENT_OPERATIONS.items():
            with self.subTest(intent_id=intent_id):
                self.assertEqual(_icourse_operation((intent_id,)), operation)
        self.assertEqual(_icourse_operation(("icourse.lookup",)), "course")
        self.assertIsNone(_icourse_operation(("campus.academic.search",)))
        self.assertIsNone(_icourse_operation(()))

    def test_arguments_include_only_fields_declared_by_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "operation": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

        self.assertEqual(
            _query_arguments(
                schema,
                "吴天",
                goal="评课社区查询吴天",
                operation="teacher",
                limit=20,
            ),
            {"query": "吴天", "operation": "teacher"},
        )

if __name__ == "__main__":
    unittest.main()
