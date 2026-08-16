from __future__ import annotations

import random
import string
import unittest

from dududa.compatibility.reply_polish import (
    should_merge_forward,
    split_long_piece,
    split_text,
)


class ReplyPolishCompatibilityTests(unittest.TestCase):
    def test_only_explicit_long_above_threshold_uses_merged_forward(self) -> None:
        self.assertTrue(should_merge_forward("long", 601, 600))
        self.assertFalse(should_merge_forward("long", 600, 600))
        self.assertFalse(should_merge_forward("short", 2_000, 600))
        self.assertFalse(should_merge_forward("medium", 2_000, 600))
        self.assertFalse(should_merge_forward(None, 2_000, 600))
        self.assertFalse(should_merge_forward("unknown", 2_000, 600))

    def test_paragraph_sentence_and_tail_golden(self) -> None:
        text = "第一段很短。\n\n第二段也不长！\n\n" + "尾" * 30
        self.assertEqual(
            split_text(text, 12, 3),
            ["第一段很短。", "第二段也不长！", "尾" * 12 + "\n\n" + "尾" * 10],
        )
        self.assertEqual(split_long_piece("一二三四五六", 2), ["一二", "三四", "五六"])

    def test_split_is_deterministic_bounded_and_nonempty(self) -> None:
        rng = random.Random(7)
        alphabet = string.ascii_letters + "。！？\n "
        for _ in range(200):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 500)))
            first = split_text(text, 37, 8)
            second = split_text(text, 37, 8)
            self.assertEqual(first, second)
            self.assertLessEqual(len(first), 8)
            self.assertTrue(all(item for item in first))
            self.assertTrue(all(len(item) <= 74 for item in first))


if __name__ == "__main__":
    unittest.main()
