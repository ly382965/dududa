from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "cli" / "napcat_history_replay.py"
SPEC = importlib.util.spec_from_file_location("napcat_history_replay", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NapCatHistoryReplayTests(unittest.TestCase):
    def test_log_parser_uses_full_message_and_classifies_group_only_record(
        self,
    ) -> None:
        ids = MODULE.OpaqueIds()
        line = (
            "2026-08-14T09:23:22.925566614Z 08-14 17:23:22 [info] "
            "嘟嘟哒 | 接收 <- 群聊 [测试群(123456)] [测试用户(777777)] "
            "@嘟嘟哒 (999999) 请详细比较一下？ [图片]\n"
        )
        message, error = MODULE.parse_log_line(
            line,
            bot_ids={"999999"},
            ids=ids,
            sequence=1,
        )
        self.assertIsNone(error)
        self.assertIsNotNone(message)
        self.assertEqual(
            message.timestamp,
            datetime(2026, 8, 14, 9, 23, 22, 925566, tzinfo=timezone.utc),
        )
        self.assertTrue(message.direct_mention)
        self.assertEqual(message.attachment_kinds, (MODULE.AttachmentKind.IMAGE,))

        group_only, group_error = MODULE.parse_log_line(
            "2026-08-14T09:23:23Z x 接收 <- 群聊 [测试群(123456)]\n",
            bot_ids={"999999"},
            ids=ids,
            sequence=2,
        )
        self.assertIsNone(group_only)
        self.assertEqual(group_error, "missing_sender_or_content")

    def test_gateway_reader_paginates_and_deduplicates_without_persisting_payload(
        self,
    ) -> None:
        pages = {
            "/api/workspace?refresh=1": {
                "accounts": [
                    {"id": "qq-999999", "botId": "999999"},
                    {"id": "qq-888888", "botId": "888888"},
                ],
                "conversations": [
                    {
                        "type": "group",
                        "accountId": "qq-999999",
                        "peerId": "123456",
                    },
                    {
                        "type": "group",
                        "accountId": "qq-888888",
                        "peerId": "654321",
                    },
                ],
            },
            "limit=100": {
                "messages": [self._gateway_message("m2", 2_000)],
                "hasMoreBefore": True,
                "beforeCursor": "cursor-1",
            },
            "before=cursor-1": {
                "messages": [
                    self._gateway_message("m1", 1_000),
                    self._gateway_message("m2", 2_000),
                ],
                "hasMoreBefore": False,
            },
        }

        def fetch(url: str):
            if "/api/workspace?refresh=1" in url:
                return pages["/api/workspace?refresh=1"]
            if "before=cursor-1" in url:
                return pages["before=cursor-1"]
            return pages["limit=100"]

        messages, stats, bot_ids, labels, groups = MODULE.load_gateway_history(
            "http://127.0.0.1:5173",
            ids=MODULE.OpaqueIds(),
            allowed_bot_ids={"999999"},
            request_json=fetch,
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(stats.duplicate_records, 1)
        self.assertEqual(stats.pages, 2)
        self.assertEqual(bot_ids, {"999999"})
        self.assertFalse(labels)
        self.assertEqual(groups, 1)

    def test_pipeline_report_contains_aggregates_not_message_content_or_ids(
        self,
    ) -> None:
        message = MODULE.ReplayMessage(
            source="test",
            account_ref="account-1",
            message_ref="message-1",
            group_ref="group-1",
            sender_ref="sender-1",
            bot_ref="bot-1",
            timestamp=datetime(2026, 8, 14, tzinfo=timezone.utc),
            text="private-test-phrase 请详细解释？",
            direct_mention=True,
            replies_to_bot=False,
            self_authored=False,
            attachment_kinds=(),
        )
        replay = asyncio.run(MODULE.ReplayPipeline().replay((message,)))
        self.assertEqual(replay.attempted, 1)
        self.assertEqual(replay.envelope_valid, 1)
        self.assertEqual(replay.perception_valid, 1)
        self.assertEqual(replay.social_valid, 1)
        self.assertEqual(replay.tier_valid, 1)
        self.assertEqual(replay.response_plan_valid, 1)
        self.assertFalse(replay.failures)

        report = MODULE.build_report(
            docker_stats=MODULE.SourceStats(records_seen=1, records_loaded=1),
            gateway_stats=MODULE.SourceStats(),
            replay_stats=replay,
            ids=MODULE.OpaqueIds(),
            gateway_group_count=0,
        )
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("private-test-phrase", serialized)
        self.assertNotIn("123456", serialized)

    @staticmethod
    def _gateway_message(message_id: str, timestamp_ms: int) -> dict[str, object]:
        return {
            "messageId": message_id,
            "senderId": "777777",
            "content": "测试消息",
            "timestampMs": timestamp_ms,
            "mine": False,
            "segments": [{"type": "text", "text": "测试消息"}],
        }


if __name__ == "__main__":
    unittest.main()
