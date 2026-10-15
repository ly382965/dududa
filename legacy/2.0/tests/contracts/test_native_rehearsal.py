from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_dududa_core.native_rehearsal import (
    RehearsalHistoryClient,
    native_input,
)


class NativeRehearsalTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_simulated_history_is_replaced_and_qq_actions_use_real_client(
        self,
    ):
        client = SimpleNamespace(call_action=AsyncMock(return_value={"message_id": 42}))
        scoped = RehearsalHistoryClient(client, "123", "456")
        scoped.messages = [{"message_id": 1}, {"message_id": 2}]
        self.assertEqual(
            await scoped.call_action("get_group_msg_history", group_id=456, count=1),
            {"messages": [{"message_id": 2}]},
        )
        client.call_action.assert_not_awaited()
        result = await scoped.call_action(
            "send_group_msg", group_id=456, message="结果"
        )
        self.assertEqual(result, {"message_id": 42})
        client.call_action.assert_awaited_once_with(
            action="send_group_msg", group_id=456, message="结果"
        )

    async def test_native_conversion_keeps_sender_group_and_no_mention(self):
        async def call(action, **kwargs):
            return (
                {"user_id": 123} if action == "get_login_info" else [{"user_id": 789}]
            )

        client = SimpleNamespace(call_action=call)
        adapter = SimpleNamespace(
            meta=lambda: SimpleNamespace(name="aiocqhttp"),
            get_client=lambda: client,
            convert_message=AsyncMock(return_value="converted"),
            create_event=lambda message: SimpleNamespace(message=message),
        )
        plugin = SimpleNamespace(
            context=SimpleNamespace(get_platform_inst=lambda value: adapter)
        )
        source = SimpleNamespace(get_self_id=lambda: "123", get_group_id=lambda: "456")
        row = {
            "id": "1001",
            "senderId": "789",
            "senderName": "九鸟",
            "content": "我重视证明",
        }
        native = await native_input(plugin, {"platformId": "test"}, source, [row])
        with patch(
            "astrbot_plugin_dududa_core.web_runtime._onebot_event_from_payload",
            side_effect=lambda raw: raw,
        ):
            event = await native.event(row, 0)
        raw = adapter.convert_message.await_args.args[0]
        self.assertEqual(
            (raw["self_id"], raw["group_id"], raw["user_id"]), (123, 456, 789)
        )
        self.assertEqual(raw["sender"]["card"], "九鸟")
        self.assertFalse(event.is_at_or_wake_command)
        self.assertEqual(
            await event.bot.call_action("get_group_msg_history", group_id=456),
            {"messages": [raw]},
        )
        with self.assertRaisesRegex(ValueError, "sender_not_group_member"):
            await native_input(
                plugin, {"platformId": "test"}, source, [{**row, "senderId": "999"}]
            )
