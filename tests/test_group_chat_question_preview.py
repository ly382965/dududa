from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ops.cli.run_group_chat_question_preview import (
    ISOLATED,
    questions,
    selected_ids,
    synthetic_context,
)


class GroupChatQuestionPreviewTests(unittest.TestCase):
    def test_table_preserves_all_one_hundred_questions(self) -> None:
        rows = questions()
        self.assertEqual([row["id"] for row in rows], list(range(1, 101)))
        self.assertTrue(all(row["question"] and row["criterion"] for row in rows))
        self.assertIn("总结这个群今天的讨论", rows[20]["question"])

    def test_fault_and_unmentioned_cases_are_never_live_model_requests(self) -> None:
        self.assertEqual(set(ISOLATED), set(range(93, 100)))

    def test_selection_is_bounded_and_deduplicated(self) -> None:
        self.assertEqual(selected_ids("1,21-23,21"), {1, 21, 22, 23})
        for value in ("0", "101", "100-99"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                selected_ids(value)

    def test_contexts_are_synthetic_bounded_and_preserve_corrections(self) -> None:
        day = datetime(2026, 9, 4, 2, tzinfo=timezone.utc)
        for case_id in range(1, 101):
            messages, _ = synthetic_context(case_id, {}, day)
            self.assertLessEqual(len(messages), 100)
            self.assertLessEqual(sum(len(row["content"]) for row in messages), 36000)
            self.assertEqual(len({row["id"] for row in messages}), len(messages))
            self.assertTrue(all(row["id"].startswith("synthetic-") for row in messages))
        messages, prompt = synthetic_context(32, {}, day)
        self.assertEqual(len(messages), 2)
        self.assertIn("周六晚上八点", messages[-1]["content"])
        self.assertEqual(prompt, "最终几点开会？")

    def test_follow_up_uses_only_earlier_generated_synthetic_answer(self) -> None:
        day = datetime(2026, 9, 4, 2, tzinfo=timezone.utc)
        self.assertEqual(synthetic_context(80, {}, day)[0], [])
        messages, _ = synthetic_context(80, {79: "合成活动方案"}, day)
        self.assertEqual(messages[0]["content"], "合成活动方案")


if __name__ == "__main__":
    unittest.main()
