from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mcp" / "dududa-100-native-message-cases.json"


class Dududa100FixtureTests(unittest.TestCase):
    def test_fixture_has_one_hundred_unique_nonempty_questions(self) -> None:
        document = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(document.get("schema_version"), 1)
        cases = document.get("cases")
        self.assertIsInstance(cases, list)
        self.assertEqual(len(cases), 100)
        self.assertEqual(
            [item["case_id"] for item in cases],
            list(range(1, 101)),
        )
        questions = [
            " ".join(str(item["question"]).split()).casefold()
            for item in cases
        ]
        self.assertEqual(len(questions), len(set(questions)))
        self.assertTrue(all(question for question in questions))
        for item in cases:
            self.assertIn(item.get("route"), {"tool", "direct", "boundary", "ignore"})
            self.assertIsInstance(item.get("expected_tool_calls"), int)
            self.assertGreaterEqual(item["expected_tool_calls"], 0)
            self.assertIsInstance(item.get("entity_terms"), list)

    def test_fixture_contains_all_mapped_notifai_tools_and_shuttle_boundary(
        self,
    ) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        tool_names = {item.get("tool_name") for item in cases}
        self.assertTrue(
            {
                "search_notices",
                "get_notice",
                "get_notice_calendar",
                "get_notice_deadlines",
                "list_notice_sources",
                "list_notice_categories",
                "get_notice_stats",
            } <= tool_names
        )
        case_82 = next(item for item in cases if item["case_id"] == 82)
        self.assertNotEqual(case_82["question"], "它还剩几个名额？")
        self.assertEqual(case_82["expected_tool_calls"], 0)

    def test_fixture_records_observed_boundary_and_failure_contracts(self) -> None:
        cases = {
            item["case_id"]: item
            for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        }
        self.assertEqual(cases[4]["expected_action"], "legacy")
        self.assertEqual(cases[5]["expected_action"], "legacy")
        self.assertEqual(cases[70]["expected_tool_name"], "search_notices")
        self.assertEqual(cases[70]["expected_tool_calls"], 1)
        self.assertEqual(cases[80]["expected_runtime_outcome"], "failed")
        self.assertEqual(cases[80]["expected_action"], "canary_completed")
        for case_id in (77, 78):
            self.assertEqual(cases[case_id]["expected_tool_calls"], 0)
        for case_id in range(51, 61):
            self.assertEqual(cases[case_id]["expected_capability_steps"], 1)
        self.assertEqual(cases[86]["expected_capability_steps"], 0)

    def test_case_86_runtime_answers_directly_without_capability_coupling(self) -> None:
        from ops.cli.run_dududa_100_message_benchmark import run

        document = asyncio.run(run(selected={86}))
        result = document["results"][0]
        checkpoint = result["checkpoint"]
        self.assertEqual(checkpoint["social_action"], "direct_reply")
        self.assertFalse(checkpoint["perception_need_tools"])
        self.assertEqual(checkpoint["perception_categories"], [])
        self.assertEqual(checkpoint["tool_plan_steps"], 0)
        self.assertEqual(result["runtime_outcome"], "response")
        self.assertEqual(result["fake_delivery_calls"], 1)
        self.assertEqual(result["mcp_calls"], [])

    def test_shuttle_cases_use_one_builtin_plan_without_mcp(self) -> None:
        from ops.cli.run_dududa_100_message_benchmark import run

        document = asyncio.run(run(selected=set(range(51, 61))))
        for result in document["results"]:
            with self.subTest(case_id=result["case_id"]):
                checkpoint = result["checkpoint"]
                self.assertEqual(result["provider_kind"], "builtin")
                self.assertEqual(
                    checkpoint["tool_plan_capabilities"],
                    ["ustc.shuttle.public-query.v1"],
                )
                self.assertEqual(checkpoint["tool_plan_steps"], 1)
                self.assertEqual(result["mcp_calls"], [])

    def test_cross_provider_case_72_keeps_one_bounded_shuttle_candidate(self) -> None:
        """The boundary answer may inspect one builtin candidate, never two providers."""
        from ops.cli.run_dududa_100_message_benchmark import run

        document = asyncio.run(run(selected={72}))
        result = document["results"][0]
        checkpoint = result["checkpoint"]
        self.assertEqual(result["provider_kind"], "builtin")
        self.assertEqual(
            checkpoint["tool_plan_capabilities"],
            ["ustc.shuttle.public-query.v1"],
        )
        self.assertEqual(checkpoint["tool_plan_steps"], 1)
        self.assertEqual(result["mcp_calls"], [])
        self.assertEqual(result["runtime_outcome"], "response")


if __name__ == "__main__":
    unittest.main()
