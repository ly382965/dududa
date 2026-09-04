"""Real plugin handlers with fake AstrBot/events; no real network or QQ sends."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_sub2api_readonly.policy import resolve_plugin_policy
from dududa.control_plane.plugin_policy import group_plugin_enabled

from tests.test_arc_compatibility import MAIN as ARC
from tests.test_arc_compatibility import FakeEvent, fixture_song

ROOT = Path(__file__).resolve().parents[1] / "apps/astrbot-plugins"


class Plain:
    type = "Plain"

    def __init__(self, text):
        self.text = text


class Image:
    @classmethod
    def fromBase64(cls, value):
        return SimpleNamespace(image=value)


def load_handler(package, filename):
    def decorator(*args, **kwargs):
        return lambda fn: fn

    def command_group(*args, **kwargs):
        def register(fn):
            fn.command = decorator
            return fn

        return register

    names = [
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.api.star",
        "astrbot.api.message_components",
        "astrbot.core",
        "astrbot.core.star",
        "astrbot.core.star.filter",
        "astrbot.core.star.filter.command",
        "astrbot.core.star.filter.event_message_type",
        "astrbot.core.message",
        "astrbot.core.message.components",
        "astrbot.core.platform",
        "astrbot.core.config",
        "astrbot.core.config.astrbot_config",
        "astrbot.core.star.context",
    ]
    modules = {name: ModuleType(name) for name in names}
    modules["astrbot.api"].logger = logging.getLogger("group-plugin-test")
    modules["astrbot.api.event"].AstrMessageEvent = FakeEvent
    modules["astrbot.api.event"].filter = SimpleNamespace(
        event_message_type=decorator,
        command_group=command_group,
        EventMessageType=SimpleNamespace(ALL="all"),
    )

    class Star:
        def __init__(self, context):
            self.context = context

    modules["astrbot.api.star"].Context = object
    modules["astrbot.api.star"].Star = Star
    modules["astrbot.api.star"].register = decorator
    modules["astrbot.core"].AstrBotConfig = dict
    modules["astrbot.core.config.astrbot_config"].AstrBotConfig = dict
    modules["astrbot.core.star.context"].Context = object
    modules["astrbot.core.platform"].AstrMessageEvent = FakeEvent
    modules["astrbot.core.star.filter.command"].GreedyStr = str
    modules[
        "astrbot.core.star.filter.event_message_type"
    ].EventMessageType = SimpleNamespace(GROUP_MESSAGE="group")
    for name in ("astrbot.api.message_components", "astrbot.core.message.components"):
        modules[name].Image, modules[name].Plain = Image, Plain
        modules[name].BaseMessageComponent, modules[name].Face = (
            object,
            type("Face", (), {}),
        )
        modules[name].Node, modules[name].Nodes = object, object
    name = f"{package}._group_test_{filename}"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / package / f"{filename}.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**modules, name: module}):
        spec.loader.exec_module(module)
    return module


EMOJI = load_handler("astrbot_plugin_emoji_kitchen", "emoji")
REREAD = load_handler("astrbot_plugin_reread", "main")
SUB2 = load_handler("astrbot_plugin_sub2api_readonly", "main")


class GroupPluginControlsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "policy.json"
        self.environment = patch.dict(
            "os.environ", {"DUDUDA_AGENT_POLICY_PATH": str(self.path)}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        REREAD.StateManager._group_states.clear()
        self.records = {}
        self.set_policy()

    def set_policy(self, mode="off", *, bot="707", group="101", enabled=True):
        account = f"qq-{bot}"
        conversation = f"{account}:group:{group}"
        self.records[conversation] = {
            "scope": {"accountId": account, "conversationId": conversation},
            "enabled": enabled,
            "plugins": {
                key: mode
                for key in (
                    "emoji.kitchen",
                    "arc.compat",
                    "social.reread.auto",
                    "sub2api.auto_query",
                )
            },
        }
        self.path.write_text(json.dumps({"schemaVersion": 1, "policies": self.records}))

    def event(
        self, *, group="101", account="707", sender="202", message="/emoji 😀 😭"
    ):
        event = FakeEvent(message, group=group, account=account, sender=sender)
        event.is_at_or_wake_command = False
        event.get_messages = lambda: [Plain("repeat")]
        return event

    def emoji(self):
        plugin = EMOJI.EmojiKitchenCommands()
        plugin.config = {"enabled": True}
        plugin._emoji_kitchen_service_instance = SimpleNamespace(
            compose=AsyncMock(return_value=SimpleNamespace(image_bytes=b"fixture"))
        )
        return plugin

    def reread(self):
        return REREAD.RereadPlugin(
            object(),
            {
                "enabled": True,
                "group_whitelist": [],
                "need_different": True,
                "thresholds": {"Plain": 2},
                "reread_prob": 1,
                "interrupt_prob": 0,
            },
        )

    async def test_exact_scope_and_all_enabled_modes(self):
        for mode in ("auto", "on", "locked"):
            self.set_policy(mode)
            self.assertTrue(
                group_plugin_enabled("emoji.kitchen", bot_id="707", group_id="101")
            )
            for bot, group in (("708", "101"), ("707", "102"), ("707", "")):
                self.assertFalse(
                    group_plugin_enabled("emoji.kitchen", bot_id=bot, group_id=group)
                )
        self.set_policy("on", enabled=False)
        self.assertFalse(
            group_plugin_enabled("emoji.kitchen", bot_id="707", group_id="101")
        )
        self.set_policy(["on"])
        self.assertFalse(
            group_plugin_enabled("emoji.kitchen", bot_id="707", group_id="101")
        )
        self.path.write_text("{")
        self.assertFalse(
            group_plugin_enabled("emoji.kitchen", bot_id="707", group_id="101")
        )
        self.path.unlink()
        self.assertFalse(
            group_plugin_enabled("emoji.kitchen", bot_id="707", group_id="101")
        )

    async def test_emoji_disabled_or_other_scope_has_no_fetch_or_response(self):
        plugin = self.emoji()
        for event in (
            self.event(),
            self.event(group="102"),
            self.event(account="708"),
            self.event(group=""),
        ):
            self.assertEqual([item async for item in plugin.emoji(event, "😀 😭")], [])
            event.send.assert_not_called()
        plugin._emoji_kitchen_service_instance.compose.assert_not_called()

    async def test_emoji_enabled_once_and_disabled_while_composing(self):
        plugin = self.emoji()
        self.set_policy("on")
        self.assertEqual(
            len([item async for item in plugin.emoji(self.event(), "😀 😭")]), 1
        )
        plugin._emoji_kitchen_service_instance.compose.assert_awaited_once()

        async def disable(_):
            self.set_policy("off")
            return SimpleNamespace(image_bytes=b"fixture")

        plugin._emoji_kitchen_service_instance.compose.side_effect = disable
        self.assertEqual(
            [item async for item in plugin.emoji(self.event(), "😀 😭")], []
        )

    async def test_reread_off_is_silent_and_on_uses_same_account_group(self):
        plugin = self.reread()
        for sender in ("201", "202", "203"):
            event = self.event(sender=sender)
            await plugin.reread_handle(event)
            event.send.assert_not_called()
        self.set_policy("on")
        first, second = self.event(sender="201"), self.event(sender="202")
        await plugin.reread_handle(first)
        await plugin.reread_handle(second)
        first.send.assert_not_called()
        second.send.assert_awaited_once()

    async def test_reread_counters_do_not_cross_accounts(self):
        plugin = self.reread()
        self.set_policy("on")
        self.set_policy("on", bot="708")
        for bot, sender in (("707", "201"), ("708", "202")):
            event = self.event(account=bot, sender=sender)
            await plugin.reread_handle(event)
            event.send.assert_not_called()

    async def test_arc_gate_keeps_host_allowlist_and_b50_disabled(self):
        plugin = ARC.ArcB50AssetPlugin(
            object(),
            {
                "compatibility_enabled": True,
                "allowed_group_ids": ["101"],
                "b50_enabled": False,
            },
        )
        plugin._songs = Mock(
            return_value=SimpleNamespace(search=lambda _: [fixture_song()])
        )
        event = FakeEvent("/arc info fixture")
        self.assertEqual([item async for item in plugin.arc_info(event, "fixture")], [])
        plugin._songs.assert_not_called()
        self.set_policy("on")
        self.assertEqual(
            len([item async for item in plugin.arc_info(event, "fixture")]), 1
        )
        self.set_policy("on", group="102")
        self.assertEqual(
            [
                item
                async for item in plugin.arc_info(
                    FakeEvent("/arc info fixture", group="102"), "fixture"
                )
            ],
            [],
        )
        b50 = FakeEvent("/arc b50")
        result = [item async for item in plugin.arc_b50(b50)]
        self.assertIn("查分暂未启用", result[0])
        b50.bot.send_private.assert_not_called()

    async def test_arc_disable_during_chart_render_suppresses_response(self):
        self.set_policy("on")
        plugin = ARC.ArcB50AssetPlugin(
            object(), {"compatibility_enabled": True, "allowed_group_ids": ["101"]}
        )
        plugin._songs = Mock(
            return_value=SimpleNamespace(search=lambda _: [fixture_song()])
        )

        async def disable(*_):
            self.set_policy("off")
            return Path("/fixture/chart.png")

        plugin._renderer = Mock(
            return_value=SimpleNamespace(render=AsyncMock(side_effect=disable))
        )
        result = [
            item
            async for item in plugin.arc_chart(
                FakeEvent("/arc chart fixture"), "fixture"
            )
        ]
        self.assertEqual(result, [])

    async def test_standalone_without_web_store_keeps_global_config(self):
        with patch.dict("os.environ", {"DUDUDA_AGENT_POLICY_PATH": ""}):
            plugin = self.emoji()
            self.assertEqual(
                len([item async for item in plugin.emoji(self.event(), "😀 😭")]), 1
            )
            plugin.config["enabled"] = False
            self.assertEqual(
                [item async for item in plugin.emoji(self.event(), "😀 😭")], []
            )

    async def test_sub2_policy_requires_boolean_master_enable(self):
        for enabled in (False, None, "false", 0):
            self.set_policy("on", enabled=enabled)
            decision = resolve_plugin_policy(
                policy_path=str(self.path),
                account_id="qq-707",
                conversation_id="qq-707:group:101",
                plugin_id="sub2api.auto_query",
                fallback_enabled=True,
            )
            self.assertFalse(decision.enabled)

    async def test_sub2_command_rechecks_policy_after_request(self):
        plugin = SUB2.Sub2APIReadonlyPlugin(
            object(), {"enabled": True, "group_whitelist": ["101"]}
        )
        client = SimpleNamespace(
            get_stats=AsyncMock(return_value={}),
            get_user_ranking=AsyncMock(return_value=[]),
        )
        plugin.client = client
        self.assertEqual([item async for item in plugin.today(self.event())], [])
        client.get_stats.assert_not_called()
        self.set_policy("on")
        with patch.object(SUB2, "format_today", return_value="fixture"):
            self.assertEqual(
                [item async for item in plugin.today(self.event())], ["fixture"]
            )

            async def disable():
                self.set_policy("off")
                return {}

            client.get_stats.side_effect = disable
            self.assertEqual([item async for item in plugin.today(self.event())], [])

    async def test_arc_queued_image_is_suppressed_but_cleanup_continues(self):
        plugin = ARC.ArcB50AssetPlugin(
            object(), {"compatibility_enabled": True, "allowed_group_ids": ["101"]}
        )
        plugin._phase = "b50"
        plugin._finish_after_result = Mock(return_value=object())
        plugin._spawn = Mock()
        request = SimpleNamespace(
            event=self.event(), user_id="202", friend_code="123456789"
        )
        await plugin._receive(request, FakeEvent("", components=[ARC.Image("fixture")]))
        request.event.send.assert_not_called()
        self.assertEqual(plugin._phase, "result_grace")
        plugin._spawn.assert_called_once()
