from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from astrbot_plugin_dududa_core.adapters.agent_policy import (
    FileScopeAgentPolicyResolver,
)
from astrbot_plugin_dududa_core.adapters.proactive_talk import (
    ProactiveTalkController,
    proactive_prompt,
    project_history_lines,
)
from astrbot_plugin_dududa_core.rollout_bridge import AstrBotBridgeAction
from astrbot_plugin_proactive_chatter.policy import (
    BOT_INTERACTION,
    ECHO_FLOOD,
    proactive_context_skip_reason,
)
from dududa.rollout import CanaryExecutionDisposition

from tests.unit.rollout.helpers import connector


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value


class _History:
    def __init__(self, lines: tuple[str, ...] | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self.lines = lines or (
            "成员1：明天早八",
            "成员2：太痛苦了",
            "成员1：还是得起床",
        )

    async def recent_lines(self, event, *, message_limit, byte_limit):
        self.calls.append((message_limit, byte_limit))
        return self.lines


class _Bridge:
    def __init__(self) -> None:
        self.calls: list[tuple[object, bool]] = []

    async def handle(self, event, *, proactive_group_participation=False):
        self.calls.append((event, proactive_group_participation))
        return SimpleNamespace(
            action=AstrBotBridgeAction.CANARY_COMPLETED,
            canary=SimpleNamespace(
                disposition=CanaryExecutionDisposition.DELIVERED,
            ),
        )


class _Event:
    def __init__(self) -> None:
        self.message_str = "明天真的有早八"
        self.message_obj = SimpleNamespace(
            message_id="message-1",
            message=[Plain(self.message_str)],
            message_str=self.message_str,
            raw_message={
                "message_id": 1,
                "message": [{"type": "text", "data": {"text": self.message_str}}],
                "time": 1_700_000_000,
            },
        )
        self.stopped = False
        self.is_at_or_wake_command = False

    def get_self_id(self):
        return "bot-1"

    def get_sender_id(self):
        return "user-1"

    def get_group_id(self):
        return "group-1"

    def get_messages(self):
        return list(self.message_obj.message)

    def stop_event(self):
        self.stopped = True


class Plain:
    def __init__(self, text: str) -> None:
        self.text = text


class _ProactiveEvent:
    def __init__(self, source: _Event, prompt: str) -> None:
        self._source = source
        self.message_str = prompt
        self.message_obj = SimpleNamespace(
            message_id=f"{source.message_obj.message_id}:proactive",
            message=[Plain(prompt)],
        )

    def get_messages(self):
        return list(self.message_obj.message)


class ProactiveTalkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "agent-policies.json"
        self.path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "policies": {
                        "target": {
                            "scope": {
                                "accountId": "qq-bot-1",
                                "conversationId": "qq-bot-1:group:group-1",
                            },
                            "enabled": True,
                            "answerProfile": {
                                "mode": "locked",
                                "preferred": "long",
                                "allowed": ["long"],
                            },
                            "contextLength": {
                                "mode": "locked",
                                "preferred": "extended",
                                "allowed": ["extended"],
                            },
                            "groupChatStyle": {
                                "mode": "locked",
                                "preferred": "natural",
                                "allowed": ["natural"],
                            },
                            "proactiveTalk": {
                                "probabilityPercent": 8,
                                "cooldownSeconds": 600,
                                "maximumPerHour": 3,
                            },
                            "plugins": {"social.proactive_talk": "locked"},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    async def test_exact_scope_reads_history_and_enters_short_proactive_runtime(
        self,
    ) -> None:
        resolver = FileScopeAgentPolicyResolver(self.path)
        history = _History()
        bridge = _Bridge()
        clock = _Clock()
        controller = ProactiveTalkController(
            bridge,
            resolver,
            history=history,
            random_value=lambda: 0.0,
            monotonic=clock,
            event_factory=_ProactiveEvent,
        )
        event = _Event()

        delivered = await controller.maybe_handle(event)
        repeated = await controller.maybe_handle(_Event())

        self.assertTrue(delivered)
        self.assertFalse(repeated)
        self.assertTrue(event.stopped)
        self.assertEqual(history.calls, [(100, 7_500)])
        self.assertEqual(len(bridge.calls), 1)
        runtime_event, proactive = bridge.calls[0]
        self.assertTrue(proactive)
        self.assertEqual(
            [type(item).__name__ for item in runtime_event.get_messages()],
            ["Plain"],
        )
        self.assertIn("请尽量简短回答", runtime_event.message_str)
        self.assertTrue(runtime_event.message_obj.message_id.endswith(":proactive"))

    def test_policy_locks_long_only_for_ordinary_runtime(self) -> None:
        resolver = FileScopeAgentPolicyResolver(self.path)
        value = connector(group_id="group-1")

        flags = resolver.feature_flags(value)
        proactive = resolver.proactive_talk_policy(
            bot_id="bot-1",
            group_id="group-1",
        )

        self.assertTrue(flags["response_profile.force_long"])
        self.assertFalse(flags["response_profile.force_short"])
        self.assertTrue(proactive.enabled)
        self.assertEqual(proactive.probability_percent, 8)
        self.assertEqual(proactive.cooldown_seconds, 600)
        self.assertEqual(proactive.maximum_per_hour, 3)

    async def test_maximum_controls_allow_a_second_attempt_after_five_seconds(
        self,
    ) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["policies"]["target"]["proactiveTalk"] = {
            "probabilityPercent": 100,
            "cooldownSeconds": 5,
            "maximumPerHour": 500,
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        history = _History()
        bridge = _Bridge()
        clock = _Clock()
        controller = ProactiveTalkController(
            bridge,
            FileScopeAgentPolicyResolver(self.path),
            history=history,
            random_value=lambda: 0.999,
            monotonic=clock,
            event_factory=_ProactiveEvent,
        )

        first = await controller.maybe_handle(_Event())
        clock.value += 4.999
        too_soon = await controller.maybe_handle(_Event())
        clock.value += 0.001
        second = await controller.maybe_handle(_Event())

        self.assertTrue(first)
        self.assertFalse(too_soon)
        self.assertTrue(second)
        self.assertEqual(history.calls, [(100, 7_500), (100, 7_500)])

    def test_legacy_frequency_is_migrated_at_the_read_boundary(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["policies"]["target"]["proactiveTalk"] = {"frequency": "high"}
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        proactive = FileScopeAgentPolicyResolver(self.path).proactive_talk_policy(
            bot_id="bot-1",
            group_id="group-1",
        )

        self.assertEqual(proactive.probability_percent, 20)
        self.assertEqual(proactive.cooldown_seconds, 180)
        self.assertEqual(proactive.maximum_per_hour, 8)

    def test_history_projection_is_ordered_bounded_and_deidentified(self) -> None:
        messages = [
            {
                "time": 3,
                "message_id": 3,
                "group_id": "group-1",
                "user_id": "30003",
                "message": [{"type": "text", "data": {"text": "第三句"}}],
            },
            {
                "time": 1,
                "message_id": 1,
                "group_id": "group-1",
                "user_id": "30001",
                "message": [{"type": "text", "data": {"text": "第一句"}}],
            },
            {
                "time": 2,
                "message_id": 2,
                "group_id": "group-1",
                "user_id": "30002",
                "message": [
                    {"type": "reply", "data": {"id": "1"}},
                    {"type": "text", "data": {"text": "第二句"}},
                ],
            },
        ]

        lines = project_history_lines(
            messages,
            group_id="group-1",
            bot_id="bot-1",
            message_limit=3,
            byte_limit=1_000,
        )

        self.assertEqual(
            lines,
            ("成员1：第一句", "成员2：[回复] 第二句", "成员3：第三句"),
        )
        self.assertNotIn("30001", "".join(lines))

    def test_prompt_is_short_group_level_and_contains_history(self) -> None:
        policy = FileScopeAgentPolicyResolver(self.path).proactive_talk_policy(
            bot_id="bot-1",
            group_id="group-1",
        )
        prompt = proactive_prompt(("成员1：你好", "成员2：晚上好"), policy)

        self.assertIn("不要@任何人", prompt)
        self.assertIn("成员2：晚上好", prompt)
        self.assertIn("群聊表达风格：natural", prompt)

    def test_context_policy_classifies_echo_and_other_bot_interaction(self) -> None:
        self.assertEqual(
            proactive_context_skip_reason(
                ("成员1：+1", "成员2：+1", "成员3：+1")
            ),
            ECHO_FLOOD,
        )
        self.assertEqual(
            proactive_context_skip_reason(
                ("成员1：/签到", "成员2：今日运势", "成员3：/抽签")
            ),
            BOT_INTERACTION,
        )
        self.assertIsNone(
            proactive_context_skip_reason(
                ("成员1：明天早八", "成员2：太痛苦了", "成员1：还是得起床")
            )
        )

    async def test_context_policy_stops_echo_before_entering_runtime(self) -> None:
        history = _History(("成员1：+1", "成员2：+1", "成员3：+1"))
        bridge = _Bridge()
        controller = ProactiveTalkController(
            bridge,
            FileScopeAgentPolicyResolver(self.path),
            history=history,
            random_value=lambda: 0.0,
            event_factory=_ProactiveEvent,
        )

        delivered = await controller.maybe_handle(_Event())

        self.assertFalse(delivered)
        self.assertEqual(history.calls, [(100, 7_500)])
        self.assertEqual(bridge.calls, [])


if __name__ == "__main__":
    unittest.main()
