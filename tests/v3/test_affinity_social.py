"""Consent, identity and privacy exercised through the real runtime and SQLite store."""
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from dududa_v3.config import Settings
from dududa_v3.features import affinity, core
from dududa_v3.features.affinity import social
from dududa_v3.features.base import Hook, Registry, Toolkit
from dududa_v3.runtime import Runtime
from test_runtime import ROOT, OmpDouble

ACCOUNT = "qq-10000"
GROUP = ACCOUNT + ":group:100"
GROUP2 = ACCOUNT + ":group:200"
PRIVATE = ACCOUNT + ":private:7"
ADMIN_PRIVATE = ACCOUNT + ":private:42"
OTHER_ACCOUNT = "qq-20000"
OTHER_GROUP = OTHER_ACCOUNT + ":group:100"


def registry():
    result = Registry()
    core.register(result)
    affinity.register(result)
    return result


class SocialHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        patcher = patch("dududa_v3.runtime.load_registry", registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        core._pings.clear()
        scopes = tuple(f"{ACCOUNT}/{conversation}" for conversation in (GROUP, GROUP2, PRIVATE, ADMIN_PRIVATE))
        self.settings = Settings(root=ROOT, state_dir=Path(self.directory.name), admins=("42",),
                                 allowed_scopes=(*scopes, f"{OTHER_ACCOUNT}/{OTHER_GROUP}"),
                                 proactive_scopes=scopes,
                                 rate_limits={"window_seconds": 300, "group": 100, "private": 100},
                                 features={"affinity": {"super_admin": "900001", "render_python": "/nonexistent"}})
        self.omp = OmpDouble()
        self.runtime = Runtime(self.settings, client_factory=self.omp)
        self.book = affinity.ledger(Toolkit(self.runtime))

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    async def say(self, text, *, user="7", conversation=GROUP, account=ACCOUNT, **changes):
        request = {"account_id": account, "conversation_id": conversation, "user_id": user,
                   "message_id": uuid.uuid4().hex, "text": text, "source": "qq",
                   "sender": {"card": f"成员{user}", "role": "member"}, **changes}
        run = await self.runtime.submit(request)
        return await self.runtime.wait(run["run_id"])

    def score(self, value, user="7"):
        now = time.time()
        self.book.daily(user, now)
        self.book.set(user, value, "42", now)

    def rows(self, table):
        with self.runtime.store.connect() as db:
            return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]

    def related(self, user="7"):
        with self.runtime.store.connect() as db:
            return social.established(db, user)

    async def establish(self, *, user="7", conversation=GROUP):
        self.score(85, user)
        await self.say("/闺蜜", user=user, conversation=conversation)
        result = await self.say("/闺蜜 确认", user=user, conversation=conversation)
        self.assertTrue(self.related(user), result)
        return result

    def assert_mention(self, result, user="7", count=1):
        self.assertEqual([item for item in result["actions"] if item["type"] == "mention"],
                         [{"type": "mention", "user_id": user}] * count)

    async def test_exact_threshold_and_entry_score_guard(self):
        self.score(50)
        result = await self.say("/闺蜜")
        self.assertEqual(self.rows("affinity_relationship_pending"), [])
        self.assert_mention(result)
        self.assertEqual(self.omp.calls, [])
        self.score(50.01)
        await self.say("/闺蜜")
        self.assertEqual(len(self.rows("affinity_relationship_pending")), 1)
        self.score(50)
        await self.say("/闺蜜 确认")
        self.assertFalse(self.related())
        # This user has not earned today's +1: the entering 49.99 remains decisive.
        self.book.set("8", 49.99, "42", time.time())
        await self.say("/闺蜜", user="8")
        self.assertGreater(self.book.score("8"), 50)
        self.assertFalse(any(row["user_id"] == "8" for row in self.rows("affinity_relationship_pending")))

    async def test_confirmation_requires_same_user_session_and_account(self):
        self.score(70)
        self.score(70, "8")
        await self.say("/闺蜜")
        await self.say("/闺蜜 确认", user="8")
        await self.say("/闺蜜 确认", conversation=GROUP2)
        await self.say("/闺蜜 确认", conversation=PRIVATE)
        await self.say("/闺蜜 确认", account=OTHER_ACCOUNT, conversation=OTHER_GROUP)
        self.assertFalse(self.related())
        self.assertFalse(self.related("8"))
        result = await self.say("/闺蜜 确认")
        self.assertTrue(self.related())
        self.assert_mention(result)
        self.assertEqual(self.book.score("7"), 70)
        self.assertEqual(self.rows("outbox"), [])
        self.assertEqual(self.rows("affinity_greetings"), [])
        await self.say("/闺蜜", account=OTHER_ACCOUNT, conversation=OTHER_GROUP)
        self.assertEqual(len(self.rows("affinity_relationships")), 1)
        self.assertEqual(self.rows("affinity_relationship_pending"), [])

    async def test_confirmation_rechecks_live_score_after_host_snapshot(self):
        self.score(70)
        await self.say("/闺蜜")

        def drop_during_admission(ctx):
            if ctx.args == "确认":
                self.assertEqual(ctx.affinity_score, 70)
                self.book.set("7", 50, "42", time.time())

        self.runtime.registry.hook(Hook(task="affinity", intercept=drop_during_admission))
        await self.say("/闺蜜 确认")
        self.assertFalse(self.related())
        self.assertEqual(self.book.score("7"), 50)

    async def test_expired_application_cannot_confirm(self):
        self.score(70)
        await self.say("/闺蜜")
        with self.runtime.store.connect() as db:
            db.execute("UPDATE affinity_relationship_pending SET expires_at=?", (time.time() - 1,))
        await self.say("/闺蜜 确认")
        self.assertFalse(self.related())
        self.assertEqual(self.rows("affinity_relationship_pending"), [])

    async def test_natural_consent_is_exact_not_negation_or_quotation(self):
        self.score(70)
        for text in ("嘟嘟哒 不要做闺蜜", "嘟嘟哒 她说做闺蜜", "嘟嘟哒 ‘做闺蜜’", "嘟嘟哒 做闺蜜但别建立关系"):
            await self.say(text)
            self.assertEqual(self.rows("affinity_relationship_pending"), [])
        result = await self.say("嘟嘟哒 我们可以做闺蜜吗？")
        self.assertEqual(len(self.rows("affinity_relationship_pending")), 1)
        self.assertFalse(self.related())
        self.assert_mention(result)

    async def test_private_establishment_never_announces_or_pushes(self):
        result = await self.establish(conversation=PRIVATE)
        self.assert_mention(result, count=0)
        self.assertEqual(self.rows("outbox"), [])
        self.assertEqual(len(self.rows("affinity_relationships")), 1)

    async def test_profile_preferences_and_agreements_are_owner_and_scope_bound(self):
        await self.establish(conversation=PRIVATE)
        for command in ("称呼 私密小名", "特别称呼 私密专称", "保存 偏好 私密的薄荷茶", "保存 约定 私密的周末读书"):
            await self.say("/亲密度 设置 " + command, conversation=PRIVATE)
        private = await self.say("/亲密度 设置 查看", conversation=PRIVATE)
        self.assertIn("私密小名", private["text"])
        self.assertIn("私密的周末读书", private["text"])
        group = await self.say("/亲密度 设置 查看")
        self.assertNotIn("私密", group["text"])
        card = await self.say("/闺蜜 关系卡")
        self.assertNotIn("私密", card["text"])
        await self.say("嘟嘟哒 今天聊什么")
        self.assertNotIn("私密", self.omp.last["text"])
        await self.say("聊点什么", conversation=PRIVATE)
        self.assertIn("私密专称", self.omp.last["text"])
        self.assertIn("私密的薄荷茶", self.omp.last["text"])
        saved_id = self.rows("affinity_preferences")[0]["id"]
        await self.say(f"/亲密度 设置 删除 {saved_id}", user="8", conversation=PRIVATE)
        self.assertEqual(len(self.rows("affinity_preferences")), 2)
        await self.say(f"/亲密度 设置 删除 {saved_id}")
        self.assertEqual(len(self.rows("affinity_preferences")), 2)
        await self.say(f"/亲密度 设置 删除 {saved_id}", conversation=PRIVATE)
        self.assertEqual(len(self.rows("affinity_preferences")), 1)

    async def test_basic_and_special_cards_suspend_without_deleting_data(self):
        await self.establish()
        await self.say("/亲密度 设置 样式 特别")
        await self.say("/亲密度 设置 特别称呼 星星")
        special = await self.say("/闺蜜 关系卡")
        self.assertIn("星星", special["text"])
        self.assertIn("特别纪念卡", special["text"])
        self.score(79.99)
        basic = await self.say("/闺蜜 关系卡")
        self.assertIn("闺蜜关系卡", basic["text"])
        self.assertNotIn("星星", basic["text"])
        self.assertNotEqual(basic["text"], special["text"])
        self.score(50)
        suspended = await self.say("/闺蜜 状态")
        self.assertIn("暂停", suspended["text"])
        self.assertTrue(self.related())
        self.score(85)
        restored = await self.say("/闺蜜 关系卡")
        self.assertIn("星星", restored["text"])
        self.assertIn("特别纪念卡", restored["text"])
        self.assertEqual(self.rows("outbox"), [])

    async def test_ordinary_profile_at_fifty_but_special_privileges_require_relationship(self):
        self.score(50)
        await self.say("/亲密度 设置 称呼 认可称呼")
        self.assertEqual(self.rows("affinity_profiles")[0]["nickname"], "认可称呼")
        await self.say("/亲密度 设置 保存 约定 一起读书")
        self.assertEqual(self.rows("affinity_preferences"), [])
        self.score(90)
        await self.say("/亲密度 设置 特别称呼 特别名字")
        self.assertEqual(self.rows("affinity_profiles")[0]["special_nickname"], "")
        self.assertFalse(self.related())
        await self.say("/亲密度 设置 保存 偏好 喜欢绿茶")
        self.assertEqual(self.rows("affinity_preferences")[0]["content"], "喜欢绿茶")

    async def test_low_score_or_disabled_can_delete_release_and_appeal_not_create(self):
        await self.establish()
        await self.say("/亲密度 设置 保存 约定 一起读书")
        await self.say("/亲密度 设置 称呼 小书虫")
        self.score(-90)
        deleted = await self.say("/亲密度 设置 删除 全部")
        self.assertEqual(self.rows("affinity_preferences"), [])
        self.assertEqual(self.rows("affinity_profiles"), [])
        self.assert_mention(deleted)
        await self.say("/申诉 请复核误判")
        self.assertEqual(len(self.rows("affinity_appeals")), 1)
        self.runtime.store.set_switch("affinity", False, "42")
        result = await self.say("/闺蜜 解除")
        self.assertFalse(self.related())
        self.assert_mention(result)
        self.score(90)
        await self.say("/闺蜜")
        await self.say("/亲密度 设置 保存 偏好 不应保存")
        self.assertEqual(self.rows("affinity_relationship_pending"), [])
        self.assertEqual(self.rows("affinity_preferences"), [])

    async def test_release_clears_pending_application_and_subscription(self):
        self.score(70)
        await self.say("/亲密度 设置 问候 早安 08:00")
        status = await self.say("/问候 状态")
        self.assertIn("08:00", status["text"])
        await self.say("/闺蜜")
        self.assertEqual(len(self.rows("affinity_relationship_pending")), 1)
        await self.say("/闺蜜 解除")
        self.assertEqual(self.rows("affinity_relationship_pending"), [])
        with self.runtime.store.connect() as db:
            rows = db.execute("SELECT enabled FROM affinity_greetings WHERE user_id='7'").fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(not row["enabled"] for row in rows))

    async def test_appeal_uniqueness_admin_auth_privacy_and_audit_without_auto_score(self):
        self.score(-90)
        first = await self.say("/申诉 私密误判说明", conversation=PRIVATE)
        self.assert_mention(first, count=0)
        await self.say("/申诉 重复说明")
        appeals = self.rows("affinity_appeals")
        self.assertEqual(len(appeals), 1)
        appeal_id = appeals[0]["id"]
        self.score(100, "8")
        unauthorized = await self.say("/申诉 列表", user="8")
        self.assertNotIn("私密误判说明", unauthorized["text"])
        group_admin = await self.say("/申诉 列表", user="42")
        self.assertNotIn("私密误判说明", group_admin["text"])
        listing = await self.say("/申诉 列表", user="42", conversation=ADMIN_PRIVATE)
        self.assertIn("私密误判说明", listing["text"])
        await self.say(f"/申诉 处理 {appeal_id} 私密复核结论", user="42", conversation=ADMIN_PRIVATE)
        self.assertEqual(self.book.score("7"), -90)
        self.assertEqual(self.rows("affinity_appeals")[0]["resolved_by"], "42")
        self.assertTrue(any(row["action"] == "appeal_resolve" and row["user_id"] == "7"
                            for row in self.rows("affinity_social_audit")))
        group_status = await self.say("/申诉 状态")
        self.assertNotIn("私密复核结论", group_status["text"])
        private_status = await self.say("/申诉 状态", conversation=PRIVATE)
        self.assertIn("私密复核结论", private_status["text"])
        await self.say("/申诉 新的复核请求", conversation=PRIVATE)
        self.assertEqual(sum(row["resolved_at"] is None for row in self.rows("affinity_appeals")), 1)

    async def test_nonqq_and_preview_cannot_mutate_even_cleanup(self):
        await self.establish()
        await self.say("/亲密度 设置 称呼 保留")
        for changes in ({"preview": True}, {"source": "web"}):
            for command in ("/闺蜜 解除", "/申诉 测试", "/亲密度 设置 删除 全部", "/亲密度 设置 称呼 替换"):
                await self.say(command, **changes)
            self.assertTrue(self.related())
            self.assertEqual(self.rows("affinity_profiles")[0]["nickname"], "保留")
            self.assertEqual(self.rows("affinity_appeals"), [])

    async def test_relationship_and_settings_survive_restart_without_optin(self):
        await self.establish()
        await self.say("/亲密度 设置 称呼 重启昵称")
        await self.runtime.close()
        self.runtime = Runtime(self.settings, client_factory=self.omp)
        result = await self.say("/闺蜜 关系卡")
        self.assertIn("重启昵称", result["text"])
        self.assertTrue(self.related())
        self.assertEqual(self.rows("outbox"), [])
        self.assertEqual(self.book.score("7"), 85)
