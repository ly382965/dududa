"""New question-table 96–99 controls, using existing side-effect-free fakes."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from astrbot_plugin_dududa_core.adapters.agent_policy import GroupProactiveTalkPolicy
from astrbot_plugin_dududa_core.adapters.proactive_talk import ProactiveTalkController

from tests.contracts.test_proactive_talk import (
    _Bridge,
    _Clock,
    _Event,
    _History,
    _ProactiveEvent,
)


def controller(*, enabled=True, probability=100, cooldown=60, maximum=2, random_value=0):
    policy = GroupProactiveTalkPolicy(enabled, probability, cooldown, maximum, "compact", "natural")
    history, bridge, clock = _History(), _Bridge(), _Clock()
    value = ProactiveTalkController(
        bridge, SimpleNamespace(proactive_talk_policy=lambda **kwargs: policy),
        history=history, random_value=lambda: random_value, monotonic=clock,
        event_factory=_ProactiveEvent,
    )
    return value, history, bridge, clock


class ProactiveQuestionAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_or_zero_probability_is_silent_for_repeated_chat(self) -> None:
        for enabled, probability in ((False, 100), (True, 0)):
            with self.subTest(enabled=enabled, probability=probability):
                value, history, bridge, _ = controller(enabled=enabled, probability=probability)
                for _ in range(20):
                    self.assertFalse(await value.maybe_handle(_Event()))
                self.assertEqual(history.calls, [])
                self.assertEqual(bridge.calls, [])

    async def test_probability_does_not_require_every_message_to_reply(self) -> None:
        value, _, bridge, _ = controller(probability=2, random_value=0.5)
        self.assertFalse(await value.maybe_handle(_Event()))
        self.assertEqual(bridge.calls, [])

    async def test_cooldown_hourly_limit_and_window_expiry(self) -> None:
        value, _, bridge, clock = controller()
        self.assertTrue(await value.maybe_handle(_Event()))
        clock.value += 59.999
        self.assertFalse(await value.maybe_handle(_Event()))
        clock.value += 0.001
        self.assertTrue(await value.maybe_handle(_Event()))
        clock.value += 60
        self.assertFalse(await value.maybe_handle(_Event()))
        clock.value += 3540
        self.assertTrue(await value.maybe_handle(_Event()))
        self.assertEqual(len(bridge.calls), 3)

    async def test_ineligible_event_never_enters_proactive_runtime(self) -> None:
        for text, mention in (("有个问题想问", True), ("/help", False), ("嗯", False)):
            with self.subTest(text=text, mention=mention):
                value, _, bridge, _ = controller()
                event = _Event()
                event.message_str, event.is_at_or_wake_command = text, mention
                self.assertFalse(await value.maybe_handle(event))
                self.assertEqual(bridge.calls, [])

    async def test_insufficient_material_does_not_generate_a_guess(self) -> None:
        value, history, bridge, _ = controller()
        history.lines = ("成员1：有人知道这个问题吗？我先把材料找出来。",)
        self.assertFalse(await value.maybe_handle(_Event()))
        self.assertEqual(bridge.calls, [])


if __name__ == "__main__":
    unittest.main()
