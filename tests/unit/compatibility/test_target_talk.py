from __future__ import annotations

import unittest

from dududa.compatibility.target_talk import (
    TargetUser,
    clean_reply,
    history_entry,
    in_cooldown,
    load_targets,
    safe_format,
    should_handle_message,
    target_enabled_for_group,
)


class TargetTalkCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = TargetUser(
            "10001", "Alice", True, frozenset({"g-1"}), None, "short", ""
        )
        self.kwargs = {
            "enabled": True,
            "group_id": "g-1",
            "sender_id": "10001",
            "self_id": "bot-1",
            "is_at_or_wake_command": False,
            "ignore_at_or_wake_command": True,
            "configured_targets": {"10001": self.target},
            "group_whitelist": frozenset({"g-1"}),
            "text": "hello keyword",
            "minimum_characters": 1,
            "maximum_characters": 500,
            "exclude_patterns": (),
            "trigger_patterns": ("keyword",),
        }

    def test_filter_order_inputs_and_target_group(self) -> None:
        self.assertTrue(should_handle_message(**self.kwargs))
        for change in (
            {"enabled": False},
            {"sender_id": "bot-1"},
            {"group_id": "g-2"},
            {"is_at_or_wake_command": True},
            {"text": "missing"},
            {"exclude_patterns": ("hello",)},
        ):
            values = {**self.kwargs, **change}
            self.assertFalse(should_handle_message(**values))
        self.assertTrue(target_enabled_for_group(self.target, "g-1"))
        self.assertFalse(target_enabled_for_group(self.target, "g-2"))

    def test_target_parsing_cleaning_history_and_cooldown_boundaries(self) -> None:
        targets = load_targets(
            [
                "10001",
                {"qq": "10002", "probability": 2, "group_whitelist": ["g-1"]},
                {"qq": "bad"},
            ]
        )
        self.assertEqual(set(targets), {"10001", "10002"})
        self.assertEqual(targets["10002"].probability, 1.0)
        self.assertEqual(
            clean_reply('回复："[CQ:at,qq=123] 你好世界很长"', 4),
            "你好世界...",
        )
        self.assertEqual(history_entry("Alice", "a\n  b"), "Alice: a b")
        self.assertTrue(in_cooldown(10.0, 19.999, 10))
        self.assertFalse(in_cooldown(10.0, 20.0, 10))
        self.assertFalse(in_cooldown(10.0, 10.0, 0))

    def test_safe_format_failure_returns_original_template(self) -> None:
        self.assertEqual(safe_format("{known}", {"known": "ok"}), ("ok", True))
        self.assertEqual(safe_format("{missing}", {}), ("{missing}", False))


if __name__ == "__main__":
    unittest.main()
