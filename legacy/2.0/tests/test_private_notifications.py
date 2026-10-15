from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_dududa_notify.notifications import (
    DeliveryStore,
    Notification,
    deliver,
    fetch_snapshot,
    seminar_notifications,
)
from astrbot_plugin_dududa_notify.seminar_client import create_seminar_client

PLUGIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "apps/astrbot-plugins/astrbot_plugin_dududa_notify"
)
RECIPIENT = "123456789"


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "deliveries.sqlite3"
        self.store = DeliveryStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.send = AsyncMock(return_value="1001")

    async def run_delivery(self, items, *, recipient=RECIPIENT, limit=5):
        return await deliver(
            self.store,
            self.send,
            source="seminar-radar",
            platform_id="qq",
            recipient=recipient,
            notifications=items,
            limit=limit,
        )

    async def test_successful_delivery_survives_restart(self):
        items = [Notification("report:1", "seminar one")]
        self.assertEqual(await self.run_delivery(items), 1)
        self.store.close()
        self.store = DeliveryStore(self.path)
        self.assertEqual(await self.run_delivery(items), 0)
        self.send.assert_awaited_once_with(RECIPIENT, "seminar one")

    async def test_failed_delivery_retries_without_repeating_successful_items(self):
        items = [Notification("1", "first"), Notification("2", "second")]
        self.send.side_effect = ["1001", RuntimeError("offline"), "1002"]
        with self.assertRaises(RuntimeError):
            await self.run_delivery(items)
        self.assertEqual(await self.run_delivery(items), 1)
        self.assertEqual(
            [call.args[1] for call in self.send.await_args_list],
            ["first", "second", "second"],
        )

    async def test_missing_acknowledgement_does_not_mark_delivered(self):
        self.send.return_value = ""
        with self.assertRaisesRegex(RuntimeError, "not_acknowledged"):
            await self.run_delivery([Notification("1", "first")])
        self.send.return_value = "1002"
        self.assertEqual(await self.run_delivery([Notification("1", "first")]), 1)

    async def test_message_limit_leaves_remaining_items_for_next_poll(self):
        items = [Notification(str(index), f"report {index}") for index in range(4)]
        self.assertEqual(await self.run_delivery(items, limit=2), 2)
        self.assertEqual(await self.run_delivery(items, limit=2), 2)
        self.assertEqual(await self.run_delivery(items, limit=2), 0)
        self.assertEqual(self.send.await_count, 4)

    async def test_delivery_history_is_per_recipient(self):
        items = [Notification("1", "first")]
        await self.run_delivery(items)
        self.assertEqual(await self.run_delivery(items, recipient="987654321"), 1)

    async def test_cancellation_terminates_query_process(self):
        started = asyncio.Event()

        async def communicate():
            started.set()
            await asyncio.Event().wait()

        process = SimpleNamespace(
            communicate=communicate,
            returncode=None,
            kill=lambda: None,
            wait=AsyncMock(),
        )
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            task = asyncio.create_task(
                fetch_snapshot(Path("/python"), "/credentials", 45)
            )
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        process.wait.assert_awaited_once()


class SeminarFormattingTests(unittest.TestCase):
    def report(self, report_id, *, available=True, preferred=True):
        return {
            "id": report_id,
            "title": "A [CQ:at,qq=all] seminar",
            "available": available,
            "preferred": preferred,
            "speaker": "Speaker",
            "time": "2026-10-01 14:00",
            "location": "Campus",
            "deadline": "2026-10-01 12:00",
            "remaining": 10,
        }

    def test_filters_and_empty_result_subscription(self):
        snapshot = {
            "fetched_at": "2026-09-10T20:00:00+08:00",
            "available_count": 2,
            "recommended_count": 1,
            "reports": [
                self.report("1"),
                self.report("2", preferred=False),
                self.report("3", available=False),
            ],
        }
        items = seminar_notifications(snapshot, preferred_only=True, interval=15)
        self.assertEqual([item.id for item in items], ["subscription", "report:1"])
        self.assertIn("2026-10-01 12:00", items[1].text)
        self.assertIn("[CQ:at,qq=all]", items[1].text)
        items = seminar_notifications(snapshot, preferred_only=False, interval=15)
        self.assertEqual(
            [item.id for item in items], ["subscription", "report:1", "report:2"]
        )
        snapshot["reports"] = []
        self.assertEqual(
            len(seminar_notifications(snapshot, preferred_only=True, interval=15)), 1
        )


class SeminarQueryOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_list_queries_use_stable_unique_order(self):
        query = AsyncMock(return_value={"rows": []})

        class FakeSeminarClient:
            def __init__(self, session):
                self.session = session

            async def _query(self, url, action, data):
                return await query(url, action, data)

        module = ModuleType("seminar_radar.client")
        module.SeminarClient = FakeSeminarClient
        with patch.dict(sys.modules, {"seminar_radar.client": module}):
            client = create_seminar_client("test-session")
        data = {
            "*order": "-BGSJ",
            "pageNumber": "11",
            "pageSize": "100",
            "querySetting": "[]",
        }
        await client._query("/list", "wxbgbgdz", data)
        query.assert_awaited_once_with("/list", "wxbgbgdz", {**data, "*order": "-BGBM"})
        self.assertEqual(data["*order"], "-BGSJ")
        await client._query("/detail", "xsbgfbbddz", data)
        self.assertIs(query.await_args.args[2], data)

    async def test_upstream_query_failure_is_not_hidden(self):
        class FakeSeminarClient:
            def __init__(self, session):
                pass

            async def _query(self, *args):
                raise RuntimeError("incomplete list")

        module = ModuleType("seminar_radar.client")
        module.SeminarClient = FakeSeminarClient
        with patch.dict(sys.modules, {"seminar_radar.client": module}):
            client = create_seminar_client("test-session")
        with self.assertRaisesRegex(RuntimeError, "incomplete list"):
            await client._query("/list", "wxbgbgdz", {"*order": "-BGSJ"})


def load_plugin():
    class FakeStar:
        def __init__(self, context):
            self.context = context
            self.logger = logging.getLogger("test-notifications")

    star_module = ModuleType("astrbot.api.star")
    star_module.Context = object
    star_module.Star = FakeStar
    star_module.StarTools = SimpleNamespace()
    star_module.register = lambda *args: lambda cls: cls
    event_module = ModuleType("astrbot.api.event")
    event_module.AstrMessageEvent = object
    event_module.filter = SimpleNamespace(
        EventMessageType=SimpleNamespace(PRIVATE_MESSAGE=1),
        event_message_type=lambda *args, **kwargs: lambda function: function,
    )
    spec = importlib.util.spec_from_file_location(
        "astrbot_plugin_dududa_notify._test_main", PLUGIN_ROOT / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"astrbot.api.star": star_module, "astrbot.api.event": event_module},
    ):
        spec.loader.exec_module(module)
    return module.DududaNotifyPlugin


class PrivatePlatformTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_configured_recipient_and_private_text_action(self):
        call_action = AsyncMock(return_value={"message_id": 42})
        platform = SimpleNamespace(
            meta=lambda: SimpleNamespace(id="qq", name="aiocqhttp"),
            get_client=lambda: SimpleNamespace(call_action=call_action),
        )
        context = SimpleNamespace(
            platform_manager=SimpleNamespace(get_insts=lambda: [platform])
        )
        plugin = load_plugin()(context, {})
        plugin.platform_id = "qq"
        plugin.recipients = (RECIPIENT,)
        self.assertEqual(await plugin._send_private(RECIPIENT, "[CQ:at,qq=all]"), "42")
        call_action.assert_awaited_once_with(
            "send_private_msg",
            user_id=int(RECIPIENT),
            message=[{"type": "text", "data": {"text": "[CQ:at,qq=all]"}}],
        )
        with self.assertRaisesRegex(ValueError, "not_authorized"):
            await plugin._send_private("987654321", "should not send")
        plugin.platform_id = "another-bot"
        with self.assertRaisesRegex(RuntimeError, "platform_unavailable"):
            await plugin._send_private(RECIPIENT, "should not send")
        self.assertEqual(call_action.await_count, 1)

    async def test_disabled_or_empty_recipient_configuration_never_starts(self):
        plugin = load_plugin()(SimpleNamespace(), {})
        await plugin.initialize()
        self.assertIsNone(plugin.task)
        plugin.config = {"enabled": True, "platform_id": "qq", "recipients": []}
        with self.assertRaisesRegex(ValueError, "recipients_required"):
            await plugin.initialize()
        self.assertIsNone(plugin.task)
        plugin.config["recipients"] = RECIPIENT
        with self.assertRaisesRegex(TypeError, "must_be_a_list"):
            await plugin.initialize()


if __name__ == "__main__":
    unittest.main()
