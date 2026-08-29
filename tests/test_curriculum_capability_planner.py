from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from astrbot_plugin_dududa_core.adapters.capability_planner import (
    CURRICULUM_INTENT_OPERATIONS,
    _curriculum_operation,
    _curriculum_operation_from_goal,
    _curriculum_query_term,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "fixtures" / "mcp" / "curriculum-v2-native-message-cases.json"


class CurriculumCapabilityPlannerTests(unittest.TestCase):
    def test_thirty_native_messages_define_eight_consistent_operations(self) -> None:
        cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]

        self.assertEqual(len(cases), 30)
        self.assertEqual([item["case_id"] for item in cases], list(range(1, 31)))
        self.assertEqual(set(CURRICULUM_INTENT_OPERATIONS.values()), {
            "overview",
            "program",
            "course",
            "change",
            "comparison",
            "substitution",
            "shared",
            "history",
        })
        for case in cases[:26]:
            with self.subTest(case_id=case["case_id"]):
                self.assertEqual(
                    _curriculum_operation((case["intent_id"],)),
                    case["expected_operation"],
                )

    def test_native_entities_project_to_bounded_curriculum_queries(self) -> None:
        cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
        ignored = frozenset({"培养方案", "培养计划", "课程体系"})

        for case in cases[:26]:
            request = SimpleNamespace(
                query=SimpleNamespace(
                    entity_terms=tuple(case["entity_terms"]),
                    natural_language_goal=case["question"],
                )
            )
            with self.subTest(case_id=case["case_id"]):
                self.assertEqual(
                    _curriculum_query_term(
                        request,
                        ignored,
                        case["expected_operation"],
                    ),
                    case["expected_query"],
                )

    def test_category_fallback_classifies_explicit_curriculum_questions(self) -> None:
        examples = {
            "培养方案快照更新到哪天？": "overview",
            "2026级计算机培养方案多少学分？": "program",
            "培养方案里的 MATH1003 是什么课？": "course",
            "计算机2025到2026培养方案有什么变化？": "change",
            "普通主修和强基培养方案有什么区别？": "comparison",
            "MATH1003能替代001003吗？": "substitution",
            "培养方案里哪些课被最多专业共同使用？": "shared",
            "计算机培养方案最早出现在哪一级？": "history",
        }
        for question, operation in examples.items():
            with self.subTest(question=question):
                self.assertEqual(
                    _curriculum_operation_from_goal(question),
                    operation,
                )


if __name__ == "__main__":
    unittest.main()
