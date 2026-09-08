"""Synthetic events only: importing/testing this module never connects to QQ."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_arc_proxy.catalog import ChartInfo, SongInfo, SongStore
from astrbot_plugin_arc_proxy.chart_renderer import (
    UnsupportedChartError,
    parse_chart_query,
)
from astrbot_plugin_arc_proxy.logic import (
    SHANGHAI,
    estimated_completion_time,
    quota_release_time,
)
from astrbot_plugin_arc_proxy.storage import BindingStore

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "apps/astrbot-plugins/astrbot_plugin_arc_proxy"
FIXTURE_CODE = "123456789"
PRIVATE_ERROR = "TEST_SECRET_DO_NOT_LOG private.example.invalid/member"


class Plain:
    def __init__(self, text):
        self.text = text


class Image:
    def __init__(self, file):
        self.file = file

    @classmethod
    def fromFileSystem(cls, path):
        return cls(path)


class At:
    def __init__(self, qq):
        self.qq = qq


class FakeEvent:
    def __init__(
        self,
        message="/arc b50",
        *,
        group="101",
        sender="202",
        account="707",
        components=(),
        bot=None,
    ):
        self.message_str = message
        self.group = group
        self.sender = sender
        self.account = account
        self.message_obj = SimpleNamespace(message=list(components))
        self.bot = bot or SimpleNamespace(send_private=AsyncMock())
        self.send = AsyncMock()
        self.stopped = False

    def get_group_id(self):
        return self.group

    def get_sender_id(self):
        return self.sender

    def get_self_id(self):
        return self.account

    def stop_event(self):
        self.stopped = True

    def plain_result(self, text):
        return text

    def chain_result(self, components):
        return components

    @staticmethod
    async def send_message(*, bot, message_chain, is_group, session_id):
        await bot.send_private(message_chain, is_group, session_id)


def _load_with_fake_framework():
    def decorator(*args, **kwargs):
        return lambda item: item

    def group_decorator(*args, **kwargs):
        def decorate(fn):
            fn.command = decorator
            return fn

        return decorate

    class Star:
        def __init__(self, context):
            self.context = context

    modules = {}
    for name in (
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.api.star",
        "astrbot.api.message_components",
        "astrbot.core",
        "astrbot.core.star",
        "astrbot.core.star.filter",
        "astrbot.core.star.filter.command",
        "astrbot.core.platform",
        "astrbot.core.platform.sources",
        "astrbot.core.platform.sources.aiocqhttp",
        "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event",
    ):
        modules[name] = ModuleType(name)
    modules["astrbot.api"].logger = logging.getLogger("arc-compat-test")
    event = modules["astrbot.api.event"]
    event.AstrMessageEvent = FakeEvent
    event.MessageChain = list
    event.filter = SimpleNamespace(
        command_group=group_decorator,
        platform_adapter_type=decorator,
        event_message_type=decorator,
        PlatformAdapterType=SimpleNamespace(AIOCQHTTP="qq"),
        EventMessageType=SimpleNamespace(PRIVATE_MESSAGE="private"),
    )
    star = modules["astrbot.api.star"]
    star.Context, star.Star, star.register = object, Star, decorator
    components = modules["astrbot.api.message_components"]
    components.At, components.Image, components.Plain = At, Image, Plain
    modules["astrbot.core.star.filter.command"].GreedyStr = str
    modules[
        "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event"
    ].AiocqhttpMessageEvent = FakeEvent
    name = "astrbot_plugin_arc_proxy._compat_test_main"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**modules, name: module}):
        spec.loader.exec_module(module)
    return module


MAIN = _load_with_fake_framework()


def fixture_song():
    return SongInfo(
        "fixture-song",
        1,
        "Fixture Song",
        "Artist",
        "120",
        "Light",
        "1.0",
        "2026-01-01",
        "Pack",
        Path("/fixture/cover.jpg"),
        (ChartInfo(0, 3.0, 100, "Designer"), ChartInfo(2, 9.0, 500, "Designer")),
    )


class ArcCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {
            "compatibility_enabled": True,
            "b50_enabled": True,
            "allowed_group_ids": ["101"],
            "upstream_bot_id": "303",
            "state_root": self.temp.name,
        }
        self.plugin = MAIN.ArcB50AssetPlugin(object(), self.config)
        self.plugin.bindings = Mock(get=Mock(return_value=FIXTURE_CODE), set=Mock())
        self.plugin.songs = Mock(search=Mock(return_value=[fixture_song()]))
        self.plugin.chart_renderer = SimpleNamespace(
            render=AsyncMock(return_value=Path("/fixture/chart.jpg"))
        )
        self.bot = SimpleNamespace(send_private=AsyncMock())

    async def asyncTearDown(self):
        await self.plugin.terminate()
        self.temp.cleanup()

    def event(self, message="/arc b50", **kwargs):
        return FakeEvent(message, bot=self.bot, **kwargs)

    def reply(self, message="ack", **kwargs):
        return self.event(message, group="", sender="303", **kwargs)

    async def collect(self, method, event, *args):
        return [item async for item in method(event, *args)]

    async def reach_query(self, event=None):
        event = event or self.event()
        await self.collect(self.plugin.arc_b50, event)
        await self.plugin.watch_upstream(self.reply())
        await self.plugin.watch_upstream(self.reply())
        return event

    async def test_disabled_or_unauthorized_commands_do_nothing(self):
        for command, argument in (
            ("bind", FIXTURE_CODE),
            ("b50", None),
            ("info", "Fixture"),
            ("chart", "Fixture"),
        ):
            for group, sender, enabled, message in (
                ("999", "202", True, f"/arc {command}"),
                ("", "202", True, f"/arc {command}"),
                ("101", "707", True, f"/arc {command}"),
                ("101", "202", False, f"/arc {command}"),
                ("101", "202", True, "normal group conversation"),
            ):
                with self.subTest(
                    command=command, group=group, enabled=enabled, message=message
                ):
                    self.plugin.compatibility_enabled = enabled
                    event = self.event(message, group=group, sender=sender)
                    self.assertEqual(
                        await self.collect(
                            getattr(self.plugin, "arc_" + command),
                            event,
                            *([] if argument is None else [argument]),
                        ),
                        [],
                    )
                    self.assertFalse(event.stopped)
        self.plugin.bindings.set.assert_not_called()
        self.plugin.bindings.get.assert_not_called()
        self.plugin.songs.search.assert_not_called()
        self.bot.send_private.assert_not_awaited()

    async def test_default_off_and_enabled_startup_have_no_storage_or_send(self):
        for config in ({}, self.config, {"enabled": True}):
            with (
                patch.object(MAIN, "BindingStore") as store,
                patch.object(MAIN, "SongStore") as songs,
            ):
                plugin = MAIN.ArcB50AssetPlugin(object(), config)
                self.assertIsNone(plugin.bindings)
                self.assertIsNone(plugin.songs)
                store.assert_not_called()
                songs.assert_not_called()
                await plugin.terminate()
        self.bot.send_private.assert_not_awaited()

    async def test_schema_defaults_and_astrbot_loader_keyword_injection(self):
        schema = json.loads((PLUGIN_ROOT / "_conf_schema.json").read_text())
        config = {key: item["default"] for key, item in schema.items()}
        default = MAIN.ArcB50AssetPlugin(context=object(), config=config)
        self.assertFalse(default.enabled)
        self.assertFalse(default.compatibility_enabled)
        self.assertFalse(default.b50_enabled)
        await default.terminate()
        config.update(self.config)
        plugin = MAIN.ArcB50AssetPlugin(context=object(), config=config)
        self.assertTrue(plugin.compatibility_enabled)
        self.assertTrue(plugin.b50_enabled)
        self.assertFalse(plugin.enabled)
        self.assertEqual(plugin.allowed_group_ids, frozenset({"101"}))
        self.assertEqual(plugin.upstream_bot_id, "303")
        self.assertEqual(plugin.catalog_root, Path(self.temp.name) / "catalog")
        self.assertEqual(plugin.assets_root, Path(self.temp.name) / "import")
        self.assertEqual(
            plugin.renderer_assets_root, Path(self.temp.name) / "renderer-assets"
        )
        await plugin.terminate()

    async def test_b50_off_rejects_before_binding_lookup_or_any_upstream_call(self):
        self.plugin.b50_enabled = False
        event = self.event()
        result = await self.collect(self.plugin.arc_b50, event)
        self.assertIn("查分暂未启用", result[0])
        self.assertTrue(event.stopped)
        self.plugin.bindings.get.assert_not_called()
        self.bot.send_private.assert_not_awaited()
        self.assertIsNone(self.plugin._active)
        self.assertFalse(self.plugin._pending)

    async def test_b50_off_keeps_bind_info_and_chart_available(self):
        self.plugin.b50_enabled = False
        result = await self.collect(
            self.plugin.arc_bind, self.event("/arc bind"), FIXTURE_CODE
        )
        self.assertEqual(result, ["好友码已保存。"])
        for command in ("info", "chart"):
            result = await self.collect(
                getattr(self.plugin, "arc_" + command),
                self.event("/arc " + command),
                "Fixture",
            )
            self.assertIsInstance(result[0][0], Image)
        self.bot.send_private.assert_not_awaited()

    async def test_bind_valid_code_is_local_and_invalid_input_is_not_stored(self):
        event = self.event("/arc bind " + FIXTURE_CODE)
        self.assertEqual(
            await self.collect(self.plugin.arc_bind, event, FIXTURE_CODE),
            ["好友码已保存。"],
        )
        self.plugin.bindings.set.assert_called_once_with("202", FIXTURE_CODE)
        for value in (
            "",
            "123",
            "12345678x",
            "１２３４５６７８９",
            FIXTURE_CODE + "\n/a unbind",
        ):
            result = await self.collect(self.plugin.arc_bind, event, value)
            self.assertIn("用法", result[0])
        self.plugin.bindings.set.assert_called_once()
        self.bot.send_private.assert_not_awaited()

    async def test_bind_and_lookup_exceptions_do_not_reveal_private_data(self):
        self.plugin.bindings.set.side_effect = RuntimeError(PRIVATE_ERROR)
        self.plugin.bindings.get.side_effect = RuntimeError(PRIVATE_ERROR)
        for command, args in (("bind", [FIXTURE_CODE]), ("b50", [])):
            result = await self.collect(
                getattr(self.plugin, "arc_" + command),
                self.event("/arc " + command),
                *args,
            )
            self.assertIn("arc_binding_unavailable", result[0])
            self.assertNotIn(PRIVATE_ERROR, result[0])
        self.bot.send_private.assert_not_awaited()

    async def test_b50_missing_configuration_and_missing_binding_do_not_send(self):
        self.plugin.upstream_bot_id = ""
        self.assertIn(
            "arc_upstream_unconfigured",
            (await self.collect(self.plugin.arc_b50, self.event()))[0],
        )
        self.plugin.upstream_bot_id = "303"
        for value in (None, "unvalidated legacy binding"):
            self.plugin.bindings.get.return_value = value
            self.assertIn(
                "/arc bind", (await self.collect(self.plugin.arc_b50, self.event()))[0]
            )
        self.bot.send_private.assert_not_awaited()

    async def test_b50_keeps_serial_protocol_and_forwards_only_image_to_origin(self):
        event = await self.reach_query()
        sent = [call.args[0][0].text for call in self.bot.send_private.await_args_list]
        self.assertEqual(sent, ["/a unbind", "/a bind " + FIXTURE_CODE, "/ab50"])
        self.assertTrue(
            all(
                call.args[1:] == (False, "303")
                for call in self.bot.send_private.await_args_list
            )
        )
        await self.plugin.watch_upstream(
            self.reply("已加入查询队列，预计 1 分 2 秒后查询完毕")
        )
        self.assertEqual(self.plugin._phase, "result_wait")
        event.send.reset_mock()
        result_image = Image("synthetic-result")
        await self.plugin.watch_upstream(
            self.reply(
                "private upstream text", components=[Plain(PRIVATE_ERROR), result_image]
            )
        )
        chain = event.send.await_args.args[0]
        self.assertEqual(chain[0].qq, "202")
        self.assertEqual(chain[1:], [result_image])
        self.assertEqual(self.plugin._phase, "result_grace")
        await self.plugin.watch_upstream(self.reply("", components=[result_image]))
        event.send.assert_awaited_once()

    async def test_private_reply_requires_matching_upstream_account_and_phase(self):
        event = self.event()
        await self.collect(self.plugin.arc_b50, event)
        for reply in (
            self.event("ack", group="", sender="404"),
            self.event("ack", group="101", sender="303"),
            self.reply("ack", account="808"),
            self.reply("", components=[Image("old-image")]),
        ):
            await self.plugin.watch_upstream(reply)
        self.assertEqual(self.plugin._phase, "unbind")
        self.bot.send_private.assert_awaited_once()
        event.send.assert_not_awaited()

    async def test_bounded_queue_and_duplicate_requests(self):
        self.plugin.queue_capacity = 2
        await self.collect(self.plugin.arc_b50, self.event())
        result = await self.collect(self.plugin.arc_b50, self.event())
        self.assertIn("已有 B50", result[0])
        await self.collect(self.plugin.arc_b50, self.event(sender="203"))
        result = await self.collect(self.plugin.arc_b50, self.event(sender="204"))
        self.assertIn("队列已满", result[0])
        self.assertEqual(len(self.plugin._pending), 1)
        self.bot.send_private.assert_awaited_once()

    async def test_binding_failure_never_queries_previous_account_or_next_user(self):
        for failure in ("绑定失败", "错误的好友码", "invalid friend code"):
            with self.subTest(failure=failure):
                self.plugin._paused = False
                await self.collect(self.plugin.arc_b50, self.event())
                await self.plugin.watch_upstream(self.reply("解绑成功"))
                await self.collect(self.plugin.arc_b50, self.event(sender="203"))
                before = self.bot.send_private.await_count
                await self.plugin.watch_upstream(self.reply(failure))
                self.assertTrue(self.plugin._paused)
                self.assertIsNone(self.plugin._active)
                self.assertFalse(self.plugin._pending)
                self.assertEqual(before, self.bot.send_private.await_count)
                await self.plugin.watch_upstream(
                    self.reply("", components=[Image("late")])
                )
                self.assertEqual(before, self.bot.send_private.await_count)

    async def test_idle_upstream_reply_is_consumed_without_a_reply(self):
        event = self.reply("unsolicited upstream message")
        await self.plugin.watch_upstream(event)
        self.assertTrue(event.stopped)
        event.send.assert_not_awaited()
        self.bot.send_private.assert_not_awaited()

    async def test_successful_grace_advances_pending_request(self):
        await self.reach_query()
        await self.collect(self.plugin.arc_b50, self.event(sender="203"))
        active = self.plugin._active
        self.plugin._phase = "result_grace"
        with patch.object(MAIN.asyncio, "sleep", new=AsyncMock()):
            await self.plugin._finish_after_result(active)
        self.assertEqual(self.plugin._active.user_id, "203")
        self.assertEqual(self.plugin._phase, "unbind")
        self.assertEqual(self.bot.send_private.await_count, 4)

    async def test_timeout_clears_queue_and_late_image_never_reaches_next_user(self):
        first = await self.reach_query()
        second = self.event(sender="203")
        await self.collect(self.plugin.arc_b50, second)
        self.plugin.request_timeout = 0
        await self.plugin._expire(self.plugin._active)
        self.assertTrue(self.plugin._paused)
        self.assertIsNone(self.plugin._active)
        self.assertFalse(self.plugin._pending)
        first.send.reset_mock()
        second.send.reset_mock()
        before = self.bot.send_private.await_count
        await self.plugin.watch_upstream(self.reply("", components=[Image("late")]))
        self.assertIn("已暂停", (await self.collect(self.plugin.arc_b50, second))[0])
        self.assertEqual(before, self.bot.send_private.await_count)
        first.send.assert_not_awaited()
        second.send.assert_not_awaited()

    async def test_uncertain_send_pauses_and_redacts_errors(self):
        self.bot.send_private.side_effect = RuntimeError(PRIVATE_ERROR)
        event = self.event()
        with self.assertLogs("arc-compat-test", level="WARNING") as logs:
            result = await self.collect(self.plugin.arc_b50, event)
        self.assertTrue(self.plugin._paused)
        self.assertNotIn(PRIVATE_ERROR, repr(result) + repr(logs.output))
        self.assertIn("已暂停", result[0])

    async def test_transport_deadline_cancels_stalled_send_and_pauses(self):
        async def stalled_send(*args):
            await asyncio.sleep(3600)

        self.bot.send_private.side_effect = stalled_send
        self.plugin.transport_timeout = 0.001
        result = await self.collect(self.plugin.arc_b50, self.event())
        self.assertTrue(self.plugin._paused)
        self.assertIn("已暂停", result[0])
        self.bot.send_private.assert_awaited_once()

    async def test_quota_wait_retries_same_request_without_rebinding(self):
        event = await self.reach_query()
        release = datetime.now(SHANGHAI) + timedelta(minutes=10)
        await self.plugin.watch_upstream(
            self.reply(
                f"当前时段的查分配额已用尽，下次释放时间：{release:%Y-%m-%d %H:%M:%S}"
            )
        )
        self.assertEqual(self.plugin._phase, "quota_wait")
        before = self.bot.send_private.await_count
        await self.plugin.watch_upstream(
            self.reply("ignore", components=[Image("late")])
        )
        self.assertEqual(before, self.bot.send_private.await_count)
        await self.plugin._retry_at(self.plugin._active, datetime.now(SHANGHAI))
        self.assertEqual(self.bot.send_private.await_args.args[0][0].text, "/ab50")
        self.assertEqual(self.plugin._phase, "b50")
        self.assertIn("预计可查分时间", event.send.await_args.args[0][1].text)

    async def test_info_returns_local_cover_and_chart_returns_requested_or_highest(
        self,
    ):
        result = await self.collect(
            self.plugin.arc_info, self.event("/arc info Fixture"), "Fixture"
        )
        self.assertIsInstance(result[0][0], Image)
        self.assertIn("Fixture Song", result[0][1].text)
        for query, difficulty in (
            ("Fixture pst", 0),
            ("Fixture", 2),
            ("Fixture FTR", 2),
        ):
            result = await self.collect(
                self.plugin.arc_chart, self.event("/arc chart " + query), query
            )
            self.assertIsInstance(result[0][0], Image)
            self.assertEqual(
                self.plugin.chart_renderer.render.await_args.args[1].rating_class,
                difficulty,
            )
        self.bot.send_private.assert_not_awaited()

    async def test_local_query_failures_are_bounded_and_redacted(self):
        for command in ("info", "chart"):
            method = getattr(self.plugin, "arc_" + command)
            for value in ("", "x" * 201, "x\nsecret"):
                self.assertIn(
                    "用法",
                    (await self.collect(method, self.event("/arc " + command), value))[
                        0
                    ],
                )
            self.plugin.songs.search.return_value = []
            self.assertIn(
                "未找到",
                (await self.collect(method, self.event("/arc " + command), "missing"))[
                    0
                ],
            )
            self.plugin.songs.search.return_value = [fixture_song(), fixture_song()]
            self.assertIn(
                "多个曲目",
                (await self.collect(method, self.event("/arc " + command), "Fixture"))[
                    0
                ],
            )
            self.plugin.songs.search.side_effect = RuntimeError(PRIVATE_ERROR)
            result = await self.collect(
                method, self.event("/arc " + command), "Fixture"
            )
            self.assertIn("不可用", result[0])
            self.assertNotIn(PRIVATE_ERROR, result[0])
            self.plugin.songs.search.side_effect = None

    async def test_chart_missing_difficulty_encrypted_and_renderer_error(self):
        event = self.event("/arc chart Fixture")
        self.assertIn(
            "没有对应",
            (await self.collect(self.plugin.arc_chart, event, "Fixture byd"))[0],
        )
        self.plugin.chart_renderer.render.side_effect = UnsupportedChartError(
            PRIVATE_ERROR
        )
        self.assertIn(
            "加密格式", (await self.collect(self.plugin.arc_chart, event, "Fixture"))[0]
        )
        self.plugin.chart_renderer.render.side_effect = RuntimeError(PRIVATE_ERROR)
        result = await self.collect(self.plugin.arc_chart, event, "Fixture")
        self.assertIn("arc_chart_unavailable", result[0])
        self.assertNotIn(PRIVATE_ERROR, result[0])

    async def test_terminate_cancels_tasks_without_sending_and_is_idempotent(self):
        await self.reach_query()
        tasks = tuple(self.plugin._tasks)
        before = self.bot.send_private.await_count
        await self.plugin.terminate()
        await self.plugin.terminate()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(before, self.bot.send_private.await_count)
        self.assertFalse(self.plugin._pending)


class ArcStorageAndLogicTests(unittest.TestCase):
    def test_binding_store_preserves_legacy_schema_without_exporting_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE bindings (user_id TEXT PRIMARY KEY, friend_code TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO bindings VALUES (?, ?)", ("202", FIXTURE_CODE)
                )
            store = BindingStore(path)
            self.assertEqual(store.get("202"), FIXTURE_CODE)
            store.set("202", "987654321")
            self.assertEqual(store.get("202"), "987654321")
            self.assertIsNone(store.get("203"))

    def test_all_legacy_difficulty_aliases_and_malformed_timestamps(self):
        for index, alias in enumerate(("pst", "prs", "ftr", "byd", "etr")):
            self.assertEqual(parse_chart_query("Fixture " + alias), ("Fixture", index))
            self.assertEqual(
                parse_chart_query("Fixture " + str(index)), ("Fixture", index)
            )
        self.assertIsNone(parse_chart_query(""))
        self.assertIsNone(
            quota_release_time(
                "当前时段的查分配额已用尽，下次释放时间：2026-99-99 99:99:99"
            )
        )
        self.assertIsNone(
            estimated_completion_time(
                "预计 " + "9" * 100 + " 分后查询完毕", datetime.now(SHANGHAI)
            )
        )

    def test_catalog_build_search_alias_initialism_and_read_real_sqlite_with_synthetic_assets(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets, data = root / "import", root / "catalog"
            assets.mkdir()
            data.mkdir()
            songdir = assets / "fixture-song"
            songdir.mkdir()
            (songdir / "base.jpg").write_bytes(b"fixture")
            (assets / "songlist").write_text(
                json.dumps(
                    {
                        "songs": [
                            {
                                "id": "fixture-song",
                                "idx": 1,
                                "title_localized": {"en": "Fixture Song"},
                                "artist": "Artist",
                                "bpm": "120",
                                "date": 0,
                                "set": "single",
                                "difficulties": [
                                    {"ratingClass": 2, "chartDesigner": "Designer"}
                                ],
                            }
                        ]
                    }
                )
            )
            (assets / "packlist").write_text(json.dumps({"packs": []}))
            for name, content in {
                "chart_stats_base.json": [
                    {
                        "id": "fixture-song",
                        "charts": [None, None, {"constant": 9, "notes": 100}],
                    }
                ],
                "chart_overrides.json": {},
                "aliases_base.json": [
                    {"id": "fixture-song", "alias": ["fixture-alias"]}
                ],
                "extra_aliases.json": {},
            }.items():
                (data / name).write_text(json.dumps(content))
            store = SongStore(root / "songs.sqlite3", assets, data)
            self.assertEqual(store.counts(), (1, 1))
            for query in ("fixture-song", "fixture-alias", "FS", "Fixture"):
                self.assertEqual(store.search(query)[0].song_id, "fixture-song")
            self.assertEqual(store.search("notfound"), [])


if __name__ == "__main__":
    unittest.main()
