"""BB subscriptions isolate credentials, task state, commands and scheduling."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from dududa_v3.config import Settings
from dududa_v3.features import notify
from dududa_v3.features.base import Ctx, Delegate, FeatureError, Inbound, Sender
from dududa_v3.runtime import Runtime

OWNER, OTHER, BOT = "300001", "300002", "qq-100001"
COURSE = {
    "id": "bb_1_1", "name": "课程", "kind": "blackboard", "year": 2026,
    "url": "https://www.bb.ustc.edu.cn/webapps/blackboard/content/listContent.jsp?course_id=_1_1&content_id=_2_1",
}


def snapshot(title):
    return {"catalog": [dict(COURSE)], "courses": [{
        "id": COURSE["id"], "status": "ok", "materials": [],
        "tasks": [{"id": "assignment-1", "title": title, "description": "独立的课程任务",
                   "url": COURSE["url"], "deadline": None, "precision": "unknown", "submitted": None}],
    }]}


class BlackboardAccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        accounts = [
            {"id": "PB_ONE", "recipient": OWNER, "credentials_file": str(root / "one.toml"), "term": "2026FA"},
            {"id": "PB_TWO", "recipient": OTHER, "credentials_file": str(root / "two.toml"), "term": "2026FA"},
        ]
        cfg = {"enabled": True, "seminar_enabled": True, "account_id": BOT,
               "recipients": [OWNER], "homework_recipient": OWNER,
               "courses_enabled": True, "course_sources": [dict(COURSE)], "blackboard_accounts": accounts}
        self.runtime = Runtime(Settings(
            root=Path(__file__).resolve().parents[2], state_dir=root,
            allowed_scopes=tuple(f"{BOT}/{BOT}:private:{user}" for user in (OWNER, OTHER)),
            admins=(OWNER,), features={"notify": cfg},
        ))
        self.notify = notify.service(notify.JobCtx(self.runtime))
        self.legacy = self.notify.courses
        self.one = self.notify.blackboard_accounts["PB_ONE"]
        self.two = self.notify.blackboard_accounts["PB_TWO"]
        for service, title in ((self.legacy, "SA任务"), (self.one, "PB_ONE任务"), (self.two, "PB_TWO任务")):
            service.query = AsyncMock(return_value=snapshot(title))
            await service.poll()

    async def asyncTearDown(self):
        for service in (self.legacy, self.one, self.two):
            service.close()
        self.notify.store.close()
        await self.runtime.close()
        self.tmp.cleanup()

    async def command(self, user, body, *, group=False):
        inbound = Inbound(
            account_id=BOT, conversation_id=f"{BOT}:group:123" if group else f"{BOT}:private:{user}",
            message_id="command-1", text=body, sender=Sender(id=user),
        )
        return await notify.course_command(Ctx(runtime=self.runtime, inbound=inbound, session_id=0, run_id="test"))

    def done(self, service):
        return service.db.execute("SELECT done FROM tasks WHERE number=1").fetchone()[0]

    async def test_bb_recipient_does_not_receive_original_account_seminars(self):
        bb_notice = "BB course update"
        await self.two.send_text(bb_notice)
        lectures = {
            "total": 1, "available_count": 1, "recommended_count": 1, "fetched_at": "now",
            "reports": [{"id": "R1", "title": "owner-seminar", "available": True,
                         "preferred": True, "remaining": 3}],
        }
        with patch.object(notify, "fetch_snapshot", AsyncMock(return_value=lectures)):
            await self.notify.poll_seminar(force=True)
        with self.runtime.store.connect() as db:
            rows = db.execute("SELECT conversation_id,actions FROM outbox ORDER BY id").fetchall()
        delivered = {}
        for conversation, actions in rows:
            delivered.setdefault(conversation, []).extend(
                action["text"] for action in json.loads(actions) if action["type"] == "text")
        self.assertEqual(delivered[f"{BOT}:private:{OTHER}"], [bb_notice])
        self.assertTrue(any("owner-seminar" in text for text in delivered[f"{BOT}:private:{OWNER}"]))
        self.assertEqual(set(delivered), {f"{BOT}:private:{OWNER}", f"{BOT}:private:{OTHER}"})

    async def test_bb_recipient_still_requires_private_scope_authorization(self):
        root = Path(self.tmp.name) / "unauthorized"
        config = {
            "enabled": True, "seminar_enabled": False, "account_id": BOT,
            "recipients": [OWNER],
            "blackboard_accounts": [{
                "id": "PB_OUTSIDE", "recipient": OTHER,
                "credentials_file": str(root / "credentials.toml"), "term": "2026FA",
            }],
        }
        runtime = Runtime(Settings(
            state_dir=root, allowed_scopes=(f"{BOT}/{BOT}:private:{OWNER}",),
            features={"notify": config},
        ))
        try:
            with self.assertRaises(FeatureError):
                notify.service(notify.JobCtx(runtime))
        finally:
            await runtime.close()

    async def test_profile_selection_and_qualified_ids_do_not_modify_another_account(self):
        await self.command(OWNER, "课程 PB_ONE 完成 C1")
        self.assertEqual((self.done(self.legacy), self.done(self.one), self.done(self.two)), (0, 1, 0))
        await self.command(OWNER, "课程 完成 C1")
        self.assertEqual((self.done(self.legacy), self.done(self.one), self.done(self.two)), (1, 1, 0))
        await self.command(OTHER, "课程 完成 PB_TWO:C1")
        self.assertEqual((self.done(self.legacy), self.done(self.one), self.done(self.two)), (1, 1, 1))
        await self.command(OWNER, "课程 恢复 PB_ONE:C1")
        self.assertEqual((self.done(self.legacy), self.done(self.one), self.done(self.two)), (1, 0, 1))

    async def test_cross_recipient_group_and_mismatched_namespace_cannot_complete_tasks(self):
        for user, text, group in (
            (OTHER, "课程 PB_ONE 完成 C1", False),
            (OTHER, "课程 完成 PB_ONE:C1", False),
            (OWNER, "课程 PB_ONE 完成 C1", True),
            (OWNER, "课程 PB_ONE 完成 PB_TWO:C1", False),
        ):
            await self.command(user, text, group=group)
            self.assertEqual((self.done(self.legacy), self.done(self.one), self.done(self.two)), (0, 0, 0))
        response = await self.command(OTHER, "课程 PB_ONE 状态")
        self.assertIsInstance(response, Delegate)

    async def test_disabling_bb_does_not_disable_original_owner_courses(self):
        self.runtime.store.set_switch(notify.BLACKBOARD, False, OWNER)
        response = await self.command(OWNER, "课程 完成 PB_ONE:C1")
        self.assertIsInstance(response, Delegate)
        await self.command(OWNER, "课程 完成 C1")
        self.assertEqual((self.done(self.legacy), self.done(self.one)), (1, 0))

    async def test_bb_query_rejects_school_write_operations(self):
        with self.assertRaises(FeatureError):
            await self.notify.blackboard_query(
                {"operation": "submit"}, credentials_file="/does-not-exist", profile="PB_ONE", term="2026FA")

    async def test_slow_bb_poll_does_not_block_original_course_poll(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked_query(_request):
            entered.set()
            await release.wait()
            return snapshot("PB_ONE新任务")

        self.one.query = blocked_query
        self.legacy.query = AsyncMock(return_value=snapshot("SA更新后的任务"))
        for service in (self.legacy, self.one, self.two):
            service.daily = AsyncMock()
        task = asyncio.create_task(self.notify.poll_blackboard(force=True))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            await asyncio.wait_for(self.notify.poll_courses(force=True), 3)
            row = self.legacy.db.execute("SELECT payload FROM tasks WHERE number=1").fetchone()
            self.assertEqual(json.loads(row[0])["title"], "SA更新后的任务")
            self.assertFalse(task.done())
        finally:
            release.set()
            await task


if __name__ == "__main__":
    unittest.main()
