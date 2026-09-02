from __future__ import annotations

import ast
import json
import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path

from astrbot_plugin_dududa_social import (
    DEFAULT_KEYWORD_RULES,
    ComplimentTarget,
    KeywordRule,
    MoodSeverity,
    SleepLog,
    SocialFeature,
    SocialPolicyConfig,
    SocialScope,
    UserPair,
    VoteState,
    aggregate_sleep,
    append_sleep_log,
    apply_vote_action,
    birthday_matches,
    canonical_pair,
    classify_compliment,
    classify_mood,
    match_keyword,
    parse_birthday,
    rank_interactions,
    record_interaction,
)
from astrbot_plugin_dududa_social.storage import SocialStateStore

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "apps" / "astrbot-plugins" / "astrbot_plugin_dududa_social"


class SocialPolicyTests(unittest.TestCase):
    def test_birthday_parser_is_month_day_and_matches(self) -> None:
        self.assertEqual(parse_birthday("0315"), "03-15")
        self.assertEqual(parse_birthday("3/15"), "03-15")
        self.assertEqual(parse_birthday("315"), "03-15")
        self.assertEqual(parse_birthday("02-29"), "02-29")
        for value in ("20260315", "0230", "1331", "", None):
            self.assertIsNone(parse_birthday(value))
        self.assertEqual(
            birthday_matches({"u1": "03-15", "u2": "12-01", "u3": "bad"}, date(2026, 3, 15)),
            ("u1",),
        )

    def test_scope_and_feature_gates_are_default_deny_and_collision_free(self) -> None:
        group = SocialScope("qq", "bot-1", "group:1", "1")
        other = SocialScope("qq", "bot-1", "group:2", "2")
        self.assertNotEqual(group.key, other.key)
        disabled = SocialPolicyConfig()
        self.assertFalse(disabled.allows(group, SocialFeature.BIRTHDAY))
        self.assertFalse(disabled.allows_scope(group))
        enabled = SocialPolicyConfig(
            enabled=True,
            allowed_groups=frozenset({"1"}),
            enabled_features=frozenset({SocialFeature.BIRTHDAY}),
        )
        self.assertTrue(enabled.allows(group, SocialFeature.BIRTHDAY))
        self.assertTrue(enabled.allows_scope(group))
        self.assertFalse(enabled.allows(other, SocialFeature.BIRTHDAY))
        private = SocialScope("qq", "bot-1", "private:u1")
        self.assertFalse(enabled.allows_scope(private))
        self.assertFalse(enabled.allows(private, SocialFeature.BIRTHDAY))

    def test_sleep_append_deduplicates_date_and_ranks_cross_midnight(self) -> None:
        first = SleepLog("alice", date(2026, 9, 1), time(23, 30))
        duplicate = SleepLog("alice", date(2026, 9, 1), time(23, 55))
        second = SleepLog("alice", date(2026, 9, 2), time(1, 30))
        bob = SleepLog("bob", date(2026, 9, 1), time(22, 0))
        values, recorded = append_sleep_log((), first)
        self.assertTrue(recorded)
        values, recorded = append_sleep_log(values, duplicate)
        self.assertFalse(recorded)
        values, recorded = append_sleep_log(values, second)
        self.assertTrue(recorded)
        values, recorded = append_sleep_log(values, bob)
        self.assertTrue(recorded)
        summaries = aggregate_sleep(values)
        self.assertEqual([item.user_id for item in summaries], ["alice", "bob"])
        self.assertEqual(summaries[0].count, 2)
        self.assertEqual(summaries[0].average_time, time(0, 30))

    def test_vote_requires_creator_or_admin_to_end(self) -> None:
        now = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        started = apply_vote_action(None, "start", "creator", topic="聚餐", now=now)
        self.assertIsInstance(started.state, VoteState)
        joined = apply_vote_action(started.state, "join", "member", now=now)
        self.assertEqual(joined.state.participants, frozenset({"member"}))
        with self.assertRaisesRegex(ValueError, "vote_end_forbidden"):
            apply_vote_action(joined.state, "end", "member", now=now)
        ended = apply_vote_action(joined.state, "end", "creator", now=now)
        self.assertIsNone(ended.state)
        admin_ended = apply_vote_action(joined.state, "end", "admin", is_admin=True, now=now)
        self.assertIsNone(admin_ended.state)

    def test_pair_encoding_does_not_collide_on_underscores(self) -> None:
        left = canonical_pair("a_b", "c")
        right = canonical_pair("a", "b_c")
        self.assertIsInstance(left, UserPair)
        self.assertNotEqual(left.storage_key, right.storage_key)
        counts, pair, count = record_interaction({}, "a_b", "c")
        self.assertEqual((pair, count), (left, 1))
        counts, _, count = record_interaction(counts, "c", "a_b")
        self.assertEqual(count, 2)
        counts, _, _ = record_interaction(counts, "a", "b_c")
        self.assertEqual([item[1] for item in rank_interactions(counts)], [2, 1])

    def test_mood_is_a_signal_and_crisis_never_becomes_casual_reply(self) -> None:
        self.assertEqual(classify_mood("最近有点难受").severity, MoodSeverity.SUPPORT)
        self.assertEqual(classify_mood("压力好大快崩溃").severity, MoodSeverity.ELEVATED)
        crisis = classify_mood("我不想活了")
        self.assertEqual(crisis.severity, MoodSeverity.CRISIS)
        self.assertTrue(crisis.requires_human_support)
        self.assertEqual(classify_mood("今天天气不错").severity, MoodSeverity.NONE)

    def test_compliment_requires_explicit_target_signal(self) -> None:
        self.assertEqual(
            classify_compliment("嘟嘟哒好可爱").target,
            ComplimentTarget.BOT,
        )
        self.assertEqual(
            classify_compliment("老师好厉害").target,
            ComplimentTarget.OTHER,
        )
        self.assertEqual(
            classify_compliment("老师夸嘟嘟哒很可爱").target,
            ComplimentTarget.AMBIGUOUS,
        )
        self.assertEqual(
            classify_compliment("好可爱").target,
            ComplimentTarget.NONE,
        )
        self.assertFalse(classify_compliment("今天下雨").is_compliment)

    def test_keyword_matching_is_longest_first_and_single_char_defaults_off(self) -> None:
        self.assertEqual(match_keyword("今天没早八").keyword, "没早八")
        self.assertIsNone(match_keyword("学区"))
        custom = (*DEFAULT_KEYWORD_RULES, KeywordRule("学", "custom"))
        self.assertEqual(match_keyword("学长", custom).keyword, "学长")


class SocialStorageTests(unittest.TestCase):
    def test_storage_is_persistent_and_scope_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "social.sqlite3"
            scope_a = SocialScope("qq", "bot-1", "group:100", "100")
            scope_b = SocialScope("qq", "bot-1", "group:200", "200")
            now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
            with SocialStateStore(path) as store:
                self.assertEqual(store.set_birthday(scope_a, "u1", "0315", at=now), "03-15")
                self.assertEqual(store.list_birthdays(scope_b), {})
                self.assertEqual(store.list_birthdays(scope_a), {"u1": "03-15"})
                transition = store.apply_vote(scope_a, "start", "u1", topic="聚餐", now=now)
                self.assertEqual(transition.state.topic, "聚餐")
                pair, count = store.record_interaction(scope_a, "a_b", "c", at=now)
                self.assertEqual((pair.storage_key, count), (canonical_pair("a_b", "c").storage_key, 1))
                self.assertEqual(store.rank_interactions(scope_b), ())
            with SocialStateStore(path) as reopened:
                self.assertEqual(reopened.list_birthdays(scope_a), {"u1": "03-15"})
                self.assertEqual(reopened.get_vote(scope_a).topic, "聚餐")
                self.assertEqual(reopened.rank_interactions(scope_a)[0][1], 1)

    def test_storage_rejects_forbidden_vote_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scope = SocialScope("qq", "bot-1", "group:1", "1")
            with SocialStateStore(Path(directory) / "social.sqlite3") as store:
                store.apply_vote(scope, "start", "creator", topic="主题")
                with self.assertRaisesRegex(ValueError, "vote_end_forbidden"):
                    store.apply_vote(scope, "end", "member")


class SocialPluginSurfaceTests(unittest.TestCase):
    def test_metadata_and_schema_are_default_off(self) -> None:
        metadata = (PLUGIN / "metadata.yaml").read_text(encoding="utf-8")
        schema = json.loads((PLUGIN / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertIn("version: v2.0.0", metadata)
        self.assertFalse(schema["enabled"]["default"])
        self.assertEqual(schema["group_allowlist"]["default"], [])
        self.assertFalse(schema["allow_private"]["default"])
        self.assertFalse(schema["features"]["items"]["mood"]["default"])

    def test_main_registers_commands_only_and_has_no_transport_or_scheduler(self) -> None:
        tree = ast.parse((PLUGIN / "main.py").read_text(encoding="utf-8"))
        source = (PLUGIN / "main.py").read_text(encoding="utf-8")
        decorators = [
            ast.unparse(decorator)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for decorator in node.decorator_list
        ]
        self.assertIn("filter.command_group('dududa-social')", decorators)
        self.assertTrue(any("command(" in item for item in decorators))
        self.assertNotIn("event_message_type", source)
        self.assertNotIn("McpClient", source)
        self.assertNotIn("Scheduler", source)
        self.assertNotIn("text_chat", source)
        self.assertNotIn("event.send", source)
        self.assertIn("self.policy.allows_scope(scope)", source)


if __name__ == "__main__":
    unittest.main()
