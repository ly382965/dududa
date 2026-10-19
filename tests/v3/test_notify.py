"""Notify feature port: dedupe, scheduling decisions and submission guards (no network, no worker)."""

import asyncio
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from dududa_v3.config import Settings
from dududa_v3.features import notify
from dududa_v3.features.base import Ctx, Delegate, Inbound, Sender
from dududa_v3.features.notify.homework import CHINA_TIME, HomeworkService
from dududa_v3.features.notify.notifications import (
    DeliveryStore,
    Notification,
    deliver,
    seminar_notifications,
)
from dududa_v3.features.notify.weekly import WeeklyService, is_due
from dududa_v3.runtime import Runtime

OWNER = "300001"
BOT = "qq-100001"


def report(**overrides):
    item = {"id": "R1", "title": "报告", "available": True, "preferred": True, "remaining": 3}
    item.update(overrides)
    return item


class DeliveryDedupeTests(unittest.IsolatedAsyncioTestCase):
    async def test_astrbot_rows_count_as_delivered_for_any_platform_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DeliveryStore(Path(tmp) / "deliveries.sqlite3")
            store.record("seminar-radar", f"test:FriendMessage:{OWNER}", "report:R1", "1")
            sent = []

            async def send(recipient, text):
                sent.append(text)
                return "outbox:x"

            items = [Notification("report:R1", "old"), Notification("report:R2", "new"),
                     Notification("report:R3", "third")]
            count = await deliver(store, send, source="seminar-radar", platform_id="dududa", recipient=OWNER,
                                  notifications=items, limit=1)
            self.assertEqual((count, sent), (1, ["new"]))
            self.assertTrue(store.contains("seminar-radar", OWNER, "report:R2"))
            self.assertFalse(store.contains("seminar-radar", "1", "report:R2"))
            store.close()

    def test_seminar_filters_preferred_and_available(self):
        snapshot = {"available_count": 3, "recommended_count": 1, "fetched_at": "t",
                    "reports": [report(), report(id="R2", preferred=False), report(id="R3", available=False)]}
        ids = [item.id for item in seminar_notifications(snapshot, preferred_only=True, interval=10)]
        self.assertEqual(ids, ["subscription", "report:R1"])
        ids = [item.id for item in seminar_notifications(snapshot, preferred_only=False, interval=10)]
        self.assertEqual(ids, ["subscription", "report:R1", "report:R2"])

    def test_message_keys(self):
        first = notify.message_key("homework", OWNER, "文本", "2026-10-19", None, 1)
        self.assertEqual(first, notify.message_key("homework", OWNER, "文本", "2026-10-19", None, 9))
        self.assertNotEqual(first, notify.message_key("homework", OWNER, "文本", "2026-10-20", None, 1))
        self.assertEqual(notify.message_key("homework", OWNER, "文本", "2026-10-19", "m1", 2), "notify:cmd:m1:2")


class SchedulingTests(unittest.TestCase):
    def test_poll_interval(self):
        self.assertTrue(notify.poll_due(None, 1000, 10))
        self.assertFalse(notify.poll_due(1000, 1000 + 300, 10))
        self.assertTrue(notify.poll_due(1000, 1000 + 600, 10))

    def test_weekly_wakes_at_submission_hour(self):
        now = datetime.now(CHINA_TIME)
        mark = now.replace(hour=20, minute=0, second=0, microsecond=0).timestamp()
        self.assertTrue(notify.weekly_due(mark - 60, mark + 5, 10, 20))
        self.assertFalse(notify.weekly_due(mark + 1, mark + 5, 10, 20))

    def test_weekly_is_due_only_on_report_day_after_hour(self):
        day = datetime(2026, 10, 24, 20, 1, tzinfo=CHINA_TIME)
        item = {"open_week": True, "status": "NOT_SUBMITTED", "report_dates": ["2026-10-24", "2026-10-25"]}
        self.assertTrue(is_due(item, 20, "first", now=day))
        self.assertFalse(is_due(item, 20, "first", now=day - timedelta(hours=1)))
        self.assertFalse(is_due(item, 20, "last", now=day))
        self.assertFalse(is_due({**item, "status": "SUBMITTED"}, 20, "first", now=day))


def weekly_item(key="K1"):
    today = datetime.now(CHINA_TIME).date().isoformat()
    return {"key": key, "semester_id": "461", "course": "课", "week_start": today, "week_end": today,
            "status": "NOT_SUBMITTED", "open_week": True, "report_dates": [today], "submitted_at": None}


class WeeklyGuardTests(unittest.IsolatedAsyncioTestCase):
    async def run_poll(self, **flags):
        with tempfile.TemporaryDirectory() as tmp:
            query = AsyncMock(return_value={"semester_id": "461", "can_submit": True, "reports": [weekly_item()]})
            send = AsyncMock()
            service = WeeklyService(tmp, OWNER, query, send, hour=0, **flags)
            service.set_meta("subscription", "first:0")
            await service.poll()
            state = service.db.execute("SELECT state FROM jobs").fetchone()[0]
            service.close()
            return state, [call.args[0]["operation"] for call in query.call_args_list], send

    async def test_dry_run_never_claims(self):
        state, operations, send = await self.run_poll(dry_run=True)
        self.assertEqual((state, operations), ("waiting", ["weekly_list"]))
        send.assert_not_called()

    async def test_switch_off_blocks_with_one_notice(self):
        state, operations, send = await self.run_poll(submit_allowed=False)
        self.assertEqual((state, operations), ("blocked", ["weekly_list"]))
        self.assertIn("自动提交已关闭", send.call_args.args[0])

    async def test_lost_response_becomes_uncertain_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            async def query(request):
                calls.append(request["operation"])
                if request["operation"] == "weekly_submit":
                    raise RuntimeError("lost")
                return {"semester_id": "461", "can_submit": True, "reports": [weekly_item()]}

            service = WeeklyService(tmp, OWNER, query, AsyncMock(), hour=0)
            service.set_meta("subscription", "first:0")
            await service.poll()
            await service.poll()
            self.assertEqual(calls, ["weekly_list", "weekly_submit", "weekly_list"])
            self.assertEqual(service.db.execute("SELECT state FROM jobs").fetchone()[0], "uncertain")
            service.close()


def assignment(minutes_left=2, number_id="A1"):
    deadline = (datetime.now(CHINA_TIME) + timedelta(minutes=minutes_left)).isoformat(timespec="seconds")
    return {"id": number_id, "title": "作业", "course": "高级人工智能", "description": "题目",
            "deadline": deadline, "attachments": [], "requirements_token": "t"}


class HomeworkGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.query = AsyncMock()
        self.service = HomeworkService(self.tmp.name, OWNER, self.query, AsyncMock(), AsyncMock(), AsyncMock(),
                                       render_pdf=AsyncMock(return_value=b"%PDF-1.4"), auto_submit=True)
        self.service.sync([assignment()])
        await self.service.save_draft(1, assignment(), [{"answer": "答", "comment": ""}])
        with self.service.db:
            self.service.db.execute("UPDATE drafts SET delivered=1")

    async def asyncTearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def state(self):
        return self.service.latest(1)["state"]

    async def test_dry_run_refuses_before_claiming(self):
        self.service.dry_run = True
        with self.assertRaisesRegex(ValueError, "dry_run"):
            await self.service.confirm(1, 1)
        self.assertEqual(self.state(), "draft")
        self.query.assert_not_called()
        await self.service.check_deadlines()
        self.query.assert_not_called()

    async def test_automatic_outside_window_refused(self):
        self.service.sync([assignment(minutes_left=30)])
        with self.assertRaisesRegex(ValueError, "自动提交时间窗口"):
            await self.service.confirm(1, 1, automatic=True)
        self.service.auto_submit = False
        self.service.sync([assignment(minutes_left=2)])
        with self.assertRaisesRegex(ValueError, "自动提交时间窗口"):
            await self.service.confirm(1, 1, automatic=True)
        self.query.assert_not_called()

    async def test_expired_assignment_not_submitted(self):
        self.service.sync([assignment(minutes_left=-5)])
        with self.assertRaisesRegex(ValueError, "自动提交时间窗口"):
            await self.service.confirm(1, 1, automatic=True)
        await self.service.check_deadlines()
        self.query.assert_not_called()

    async def test_school_side_existing_answer_returns_draft_state(self):
        self.query.side_effect = ValueError("homework_already_submitted")
        with self.assertRaisesRegex(ValueError, "homework_already_submitted"):
            await self.service.confirm(1, 1)
        self.assertEqual(self.state(), "draft")

    async def test_uncertain_upload_is_only_verified_never_repeated(self):
        self.query.side_effect = asyncio.TimeoutError()
        with self.assertRaises(asyncio.TimeoutError):
            await self.service.confirm(1, 1)
        self.assertEqual(self.state(), "uncertain")
        self.query.reset_mock(side_effect=True)
        self.query.return_value = {"submission_token": "someone-else", "submitted": True}
        with self.assertRaisesRegex(ValueError, "停止重复上传"):
            await self.service.confirm(1, 1)
        self.assertEqual([call.args[0]["operation"] for call in self.query.call_args_list], ["detail"])

    async def test_submitted_version_is_not_resubmitted(self):
        with self.service.db:
            self.service.db.execute("UPDATE drafts SET state='submitted'")
        self.assertIn("不会重复提交", await self.service.confirm(1, 1))
        self.query.assert_not_called()


class FeatureGlueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = {"enabled": True, "recipients": [int(OWNER)], "homework_recipient": OWNER, "seminar_enabled": True,
                  "homework_enabled": True, "homework_auto_submit_enabled": True, "dry_run": True,
                  "account_id": BOT}
        self.runtime = Runtime(Settings(state_dir=Path(self.tmp.name), allowed_scopes=(f"{BOT}/{BOT}:private:{OWNER}",),
                                        admins=(OWNER,), features={"notify": config}))

    async def asyncTearDown(self):
        await self.runtime.close()
        self.tmp.cleanup()

    def outbox(self):
        with self.runtime.store.connect() as db:
            return [(row[0], json.loads(row[1])) for row in db.execute("SELECT conversation_id,actions FROM outbox")]

    async def test_push_dedupes_and_files_use_file_action(self):
        service = notify.service(notify.JobCtx(self.runtime))
        self.assertFalse(service.auto_submit_allowed())  # dry_run wins over config and switches
        await service.send_text(OWNER, "【作业发布或更新】H1")
        await service.send_text(OWNER, "【作业发布或更新】H1")
        pdf = Path(self.tmp.name) / "H1_v1.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        await service.send_file(OWNER, pdf)
        rows = self.outbox()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], f"{BOT}:private:{OWNER}")
        self.assertEqual(rows[1][1][0]["type"], "file")
        self.assertEqual(rows[1][1][0]["name"], "H1_v1.pdf")

    async def test_auto_submit_switch_defaults_to_config(self):
        service = notify.service(notify.JobCtx(self.runtime))
        service.dry_run = False
        self.assertTrue(service.auto_submit_allowed())
        self.runtime.store.set_switch(notify.AUTO_SUBMIT, False, OWNER)
        self.assertFalse(service.auto_submit_allowed())

    async def submit(self, text, conversation, user):
        run = await self.runtime.submit({"account_id": BOT, "conversation_id": conversation, "user_id": user,
                                         "message_id": uuid.uuid4().hex, "text": text, "source": "qq"})
        return await self.runtime.wait(run["run_id"])

    async def test_owner_private_command_and_others_fall_through(self):
        command = next(item for item in self.runtime.registry.commands if "作业" in item.names)
        with patch.object(notify.HomeworkService, "command", AsyncMock(return_value="列表内容")):
            result = await self.submit("作业 列表", f"{BOT}:private:{OWNER}", OWNER)
        self.assertEqual(result["route"], "rule")
        self.assertIn("列表内容", result["text"])
        self.assertIn("等待首次作业检查", result["text"])
        for conversation, user, text in ((f"{BOT}:private:1", "1", "作业 列表"),
                                         (f"{BOT}:group:100", OWNER, "嘟嘟哒 作业 列表"),
                                         (f"{BOT}:private:{OWNER}", OWNER, "作业太多了怎么办")):
            inbound = Inbound(account_id=BOT, conversation_id=conversation, message_id="m", text=text,
                              sender=Sender(id=user))
            outcome = await command.handler(Ctx(runtime=self.runtime, inbound=inbound, session_id=0, run_id="r"))
            self.assertIsInstance(outcome, Delegate, text)


if __name__ == "__main__":
    unittest.main()
