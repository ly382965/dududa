"""Host admission and tool/observer boundaries for the opt-in relationship system."""

import tempfile
import time
import unittest
import uuid
from pathlib import Path

from dududa_v3.config import Settings
from dududa_v3.features import affinity
from dududa_v3.features.base import Ctx, Inbound, Observer, Reply, Tool
from dududa_v3.runtime import Runtime
from test_runtime import ROOT, OmpDouble

ACCOUNT = "qq-100001"
GROUP = ACCOUNT + ":group:200001"
USER = "300001"


class AffinityAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.model = OmpDouble()
        self.runtime = Runtime(Settings(root=ROOT, state_dir=Path(self.directory.name),
                                        allowed_scopes=(f"{ACCOUNT}/{GROUP}",)), self.model)
        self.book = affinity.Ledger(self.runtime.store)

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    def request(self, text, **changes):
        return {"account_id": ACCOUNT, "conversation_id": GROUP, "user_id": USER,
                "message_id": uuid.uuid4().hex, "text": text, "source": "qq", **changes}

    async def execute(self, text, **changes):
        run = await self.runtime.submit(self.request(text, **changes))
        return await self.runtime.wait(run["run_id"])

    def score(self, value):
        self.book.set(USER, value, "test-admin", time.time())

    async def test_daily_bonus_does_not_bypass_entertainment_gate_but_utility_remains(self):
        self.score(-50)
        refused = await self.execute("/画图 一只猫")
        self.assertEqual(refused["reason"], "affinity_entertainment_blocked")
        self.assertEqual(refused["actions"][0], {"type": "mention", "user_id": USER})
        self.assertGreater(self.book.score(USER), -50)
        self.assertEqual(self.model.calls, [])
        self.score(-50)
        utility = await self.execute("/时间")
        self.assertEqual(utility["status"], "completed")
        self.assertEqual(utility["command"], "time")
        self.assertEqual(self.model.calls, [])

    async def test_tool_execution_checks_affinity_and_current_task_switch(self):
        async def generate(ctx, _args):
            ctx.store.kv_set("test", "generated", True)
            return {"generated": True}

        self.runtime.registry.tool(Tool("test_draw", "test image side effect", {"type": "object"},
                                        generate, task="image_generation"))
        request = self.request("请帮我画图", mentioned=True)
        session = self.runtime.store.session("test-tool-scope")
        run, _ = self.runtime.store.create_run(session["id"], request)
        ctx = Ctx(self.runtime, Inbound.from_request(request), session["id"], run["run_id"], addressed=True)
        self.score(-50)
        _, failed = await self.runtime._call_tool(ctx, "test_draw", {})
        self.assertTrue(failed)
        self.assertIsNone(self.runtime.store.kv_get("test", "generated"))
        self.score(80)
        self.runtime.store.set_switch("image_generation", False, "test-admin")
        _, failed = await self.runtime._call_tool(ctx, "test_draw", {})
        self.assertTrue(failed)
        self.assertIsNone(self.runtime.store.kv_get("test", "generated"))
        self.runtime.store.set_switch("image_generation", True, "test-admin")
        _, failed = await self.runtime._call_tool(ctx, "test_draw", {})
        self.assertFalse(failed)
        self.assertTrue(self.runtime.store.kv_get("test", "generated"))

    async def test_negative_sender_does_not_disable_group_observers(self):
        async def cat(ctx):
            return Reply().reaction(ctx.inbound.message_id, "66")

        async def repeat(_ctx):
            return Reply.of_text("全群复读仍然有效")

        self.runtime.registry.observers = [Observer("cat_hearts", cat), Observer("repeater", repeat)]
        self.score(-50)
        result = await self.execute("未叫到机器人的普通发言")
        self.assertEqual(result["actions"], [{"type": "text", "text": "全群复读仍然有效"}])
        self.assertEqual(self.model.calls, [])
        self.score(0)
        result = await self.execute("另一条普通发言")
        self.assertEqual([action["type"] for action in result["actions"]], ["reaction", "text"])

    async def test_hard_refusal_is_rate_limited_but_owned_memory_deletion_is_not(self):
        self.score(-100)
        self.runtime.limiter.limits["group"] = 1
        first = await self.execute("/时间")
        self.assertEqual(first["text"], affinity.HARD_REFUSAL)
        await self.execute("/时间")
        third = await self.execute("/时间")
        self.assertEqual((third["status"], third["reason"]), ("ignored", "rate_limited"))
        with self.runtime.store.connect() as db:
            session_id = db.execute("SELECT session_id FROM runs WHERE id=?", (first["run_id"],)).fetchone()[0]
        mine = self.runtime.store.remember(session_id, USER, "我的资料")
        others = self.runtime.store.remember(session_id, "300002", "他人的资料")
        await self.execute(f"/忘记 {others}")
        await self.execute(f"/忘记 {mine}")
        remaining = self.runtime.store.memories(session_id)
        self.assertEqual([item["id"] for item in remaining], [others])
        self.assertEqual(self.model.calls, [])

if __name__ == "__main__":
    unittest.main()
