from __future__ import annotations

import unittest

from astrbot_plugin_dududa_core.adapters.capability_planner import (
    ICOURSE_INTENT_OPERATIONS,
    _goal_first_query_term,
    _icourse_operation,
    _query_arguments,
    _teacher_query_term,
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

    def test_teacher_operation_prefers_entity_named_as_teacher(self) -> None:
        self.assertEqual(
            _teacher_query_term(
                ("数学分析(B1)", "吴天"),
                "吴天老师的数学分析(B1)怎么样？",
            ),
            "吴天",
        )

    def test_review_operation_prefers_earliest_non_year_subject(self) -> None:
        self.assertEqual(
            _goal_first_query_term(
                ("计算机", "萌萌哒mmd"),
                "萌萌哒mmd评价过哪些计算机课程？",
            ),
            "萌萌哒mmd",
        )
        self.assertEqual(
            _goal_first_query_term(
                ("2026", "萌萌哒mmd"),
                "2026 年萌萌哒mmd写了哪些点评？",
            ),
            "萌萌哒mmd",
        )

if __name__ == "__main__":
    unittest.main()
