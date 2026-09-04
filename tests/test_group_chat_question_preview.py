from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ops.cli.run_group_chat_question_preview import (
    ISOLATED,
    questions,
    selected_ids,
    synthetic_context,
    synthetic_window_start,
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

    def test_daytime_window_prefers_ten_oclock(self) -> None:
        now = datetime.fromisoformat("2026-09-04T17:23:45+08:00")
        start = synthetic_window_start(now)
        self.assertEqual(start.isoformat(), "2026-09-04T10:00:00+08:00")
        messages, _ = synthetic_context(21, {}, start)
        self.assertEqual(len(messages), 10)
        self.assertEqual(messages[-1]["timestamp"], "2026-09-04T10:09:00+08:00")

    def test_midnight_and_morning_windows_never_include_future_history(self) -> None:
        cases = (
            ("2026-09-05T00:00:30.123456+08:00", "2026-09-04T23:51:00+08:00"),
            ("2026-09-05T00:08:12+08:00", "2026-09-04T23:59:00+08:00"),
            ("2026-09-05T10:08:59+08:00", "2026-09-05T09:59:00+08:00"),
            ("2026-09-05T10:09:00+08:00", "2026-09-05T10:00:00+08:00"),
        )
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                now = datetime.fromisoformat(timestamp)
                start = synthetic_window_start(now)
                self.assertEqual(start.isoformat(), expected)
                messages, _ = synthetic_context(21, {}, start)
                self.assertEqual(len(messages), 10)
                self.assertEqual(messages[0]["timestamp"], expected)
                self.assertTrue(all(
                    datetime.fromisoformat(row["timestamp"]) <= now
                    for row in messages
                ))

    def test_follow_up_uses_only_earlier_generated_synthetic_answer(self) -> None:
        day = datetime(2026, 9, 4, 2, tzinfo=timezone.utc)
        self.assertEqual(synthetic_context(80, {}, day)[0], [])
        messages, _ = synthetic_context(80, {79: "合成活动方案"}, day)
        self.assertEqual(messages[0]["content"], "合成活动方案")


if __name__ == "__main__":
    unittest.main()
