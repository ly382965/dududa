"""Hidden affinity: scoring math, tag handling and the /亲密度 command through the real Host."""

import json
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

from dududa_v3.config import Settings
from dududa_v3.features import affinity, core
from dududa_v3.features.base import Ctx, Gate, Hook, Inbound, Registry, Toolkit
from dududa_v3.runtime import Runtime
from dududa_v3.store import Store
from test_runtime import ROOT, OmpDouble

BOT = "10000"
ACCOUNT = "qq-" + BOT
GROUP = ACCOUNT + ":group:100"
PRIVATE = ACCOUNT + ":private:7"
DAY = 86400
SUPER = "900001"
OTHER_BOT = "900002"


def registry() -> Registry:
    built = Registry()
    core.register(built)
    affinity.register(built)
    return built


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.book = affinity.Ledger(Store(Path(self.directory.name) / "db.sqlite3"), SUPER)
        self.now = 1_790_000_000.0

    def tearDown(self):
        self.directory.cleanup()

    def give(self, user, raw, reason="praise", after=200, digest=None):
        self.now += after
        return self.book.apply(user, raw, reason, now=self.now, digest=digest)

    def test_middle_range_has_no_daily_cap(self):
        for _ in range(12):
            self.give("u", 5)
        self.assertEqual(self.book.score("u"), 60)

    def test_positive_has_no_cooldown_but_deduplicates_text(self):
        self.assertEqual(self.give("u", 3, digest="first").applied, 3)
        self.assertEqual(self.give("u", 3, after=0, digest="second").applied, 3)
        self.assertEqual(self.give("u", 3, after=1, digest="third").applied, 3)
        self.assertEqual(self.give("u", 3, after=1, digest="first").note, "duplicate")
        self.assertEqual(self.give("u", -3, "rude", after=1).applied, -3)
        self.assertEqual(self.book.score("u"), 6)
        self.assertEqual(self.give("u", 3, after=DAY, digest="first").applied, 3)

    def test_near_edges_damps_without_daily_caps(self):
        self.book.set("u", 80, "admin", self.now)
        for expected in (2.0, 1.8, 1.62, 1.458):
            self.assertAlmostEqual(self.give("u", 4).applied, expected)
        self.assertAlmostEqual(self.book.score("u"), 86.878)
        self.book.set("v", -61, "admin", self.now)
        for expected in (-19.5, -9.75, -4.875):
            self.assertAlmostEqual(self.give("v", -20, "abuse", after=1).applied, expected)
        self.assertAlmostEqual(self.book.score("v"), -95.125)
        self.assertAlmostEqual(self.give("v", 5, "praise").applied, 5.0)

    def test_super_admin_is_fixed(self):
        self.assertEqual(self.give(SUPER, -20, "abuse").score, 120)
        self.assertEqual(self.book.score(SUPER), 120)
        self.assertIsNone(self.book.daily(SUPER, self.now))

    def test_daily_bonus_once_per_beijing_day(self):
        self.assertIsNotNone(self.book.daily("u", self.now))
        self.assertIsNone(self.book.daily("u", self.now + 60))
        self.assertIsNotNone(self.book.daily("u", self.now + DAY))
        self.assertEqual(self.book.score("u"), 2)

    def test_decay_cools_above_30_and_heals_negatives(self):
        self.book.set("warm", 50, "admin", self.now)
        self.book.seen("warm", GROUP, "暖", self.now)
        self.book.set("cold", -5, "admin", self.now)
        self.book.decay(self.now + 13 * DAY)
        self.assertEqual(self.book.score("warm"), 50)
        self.book.decay(self.now + 14 * DAY)
        self.book.decay(self.now + 15 * DAY)
        self.assertEqual(self.book.score("warm"), 49)
        self.book.set("warm", 30.5, "admin", self.now)
        self.book.decay(self.now + 30 * DAY)
        self.assertEqual(self.book.score("warm"), 30)
        self.assertEqual(self.book.score("cold"), -3)

    def test_score_changes_and_greeting_invalidation_roll_back_together(self):
        self.book.set("u", 80, "admin", self.now)
        self.book.seen("u", GROUP, "成员", self.now)
        history = self.book.history("u")

        def failing_invalidation(db, user_id, score):
            self.assertTrue(db.in_transaction)
            self.assertEqual(db.execute("SELECT score FROM affinity WHERE user_id=?", (user_id,)).fetchone()[0],
                             score)
            db.execute("INSERT INTO affinity_events(user_id,at,raw,delta,score,reason) VALUES (?,?,?,?,?,?)",
                       (user_id, self.now, 0, 0, score, "invalidation_probe"))
            raise RuntimeError("invalidation failed")

        for change in (
            lambda: self.book.apply("u", -5, "rude", now=self.now),
            lambda: self.book.set("u", 40, "admin", self.now),
            lambda: self.book.decay(self.now + 14 * DAY),
        ):
            with (
                patch("dududa_v3.features.affinity.greetings.score_changed", failing_invalidation),
                self.assertRaisesRegex(RuntimeError, "invalidation failed"),
            ):
                change()
            self.assertEqual(self.book.score("u"), 80)
            self.assertEqual(self.book.history("u"), history)

    def test_group_members_survive_bot_account_changes_without_duplicate_scores(self):
        old_group = "qq-99999:group:100"
        self.book.seen("old", old_group, "旧号认识的群友", self.now - 2)
        self.book.set("old", 30, "admin", self.now - 2)
        self.book.seen("both", old_group, "旧名片", self.now - 2)
        self.book.set("both", 20, "admin", self.now - 2)
        self.book.seen("both", GROUP, "新名片", self.now - 1)
        self.book.apply("both", 3, "praise", now=self.now)
        for user, conversation, seen_at in (
            ("other_group", "qq-99999:group:1000", self.now),
            ("other_platform", "other-99999:group:100", self.now),
            ("private", "qq-99999:private:100", self.now),
            ("expired", old_group, self.now - affinity.RANK_WINDOW_SECONDS - 1),
            (OTHER_BOT, old_group, self.now),
        ):
            self.book.seen(user, conversation, user, seen_at)

        members = self.book.members(GROUP, self.now, {OTHER_BOT})
        self.assertEqual(
            sorted((member["user_id"], member["name"], member["score"]) for member in members),
            [("both", "新名片", 23), ("old", "旧号认识的群友", 30)],
        )

    def test_non_group_members_remain_account_specific(self):
        self.book.seen("old", "qq-99999:private:7", "旧号私聊", self.now)
        self.book.seen("current", PRIVATE, "新号私聊", self.now)
        members = self.book.members(PRIVATE, self.now, set())
        self.assertEqual([member["user_id"] for member in members], ["current"])

    def test_tag_parsing_and_reason_ranges(self):
        clean, tag = affinity.parse_tag("好呀～\n[[aff:+9:praise]]")
        self.assertEqual((clean, tag), ("好呀～", (9.0, "praise")))
        self.assertEqual(affinity.clamp_reason(9, "praise"), 5)
        self.assertEqual(affinity.clamp_reason(5, "beg"), 0)
        self.assertEqual(affinity.clamp_reason(-30, "abuse"), -20)
        self.assertEqual(affinity.clamp_reason(3, "made_up"), 0)
        self.assertEqual(affinity.parse_tag("[[aff:1:chat]]中间[[aff:-3:rude]]")[0], "中间")

    def test_seven_tiers_use_raw_boundaries(self):
        cases = (
            (-100, "特别讨厌"), (-80.001, "特别讨厌"), (-80, "特别讨厌"),
            (-79.999, "讨厌"), (-50.001, "讨厌"), (-50, "讨厌"),
            (-49.999, "反感"), (-20.001, "反感"), (-20, "普通"),
            (-19.999, "普通"), (19.999, "普通"), (20, "普通"),
            (20.001, "好感"), (49.99, "好感"), (50, "喜欢"),
            (50.01, "喜欢"), (79.999, "喜欢"), (80, "特别喜欢"),
            (80.001, "特别喜欢"), (100, "特别喜欢"), (120, "最喜欢的姐姐"),
        )
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(affinity.tier(score), expected)


class AffinityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        patcher = patch("dududa_v3.runtime.load_registry", registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        core._pings.clear()
        self.settings = Settings(root=ROOT, state_dir=Path(self.directory.name), admins=("42",),
                                 allowed_scopes=(f"{ACCOUNT}/{GROUP}", f"{ACCOUNT}/{PRIVATE}"),
                                 features={"affinity": {"render_python": "/nonexistent", "super_admin": SUPER,
                                                        "exclude": [OTHER_BOT]}})
        self.omp = OmpDouble()
        self.runtime = Runtime(self.settings, client_factory=self.omp)
        self.book = affinity.ledger(Toolkit(self.runtime))

    async def asyncTearDown(self):
        await self.runtime.close()
        self.directory.cleanup()

    async def say(self, text, user="7", conversation=GROUP, **extra):
        request = {"account_id": ACCOUNT, "conversation_id": conversation, "user_id": user,
                   "message_id": uuid.uuid4().hex, "text": text, "source": "qq", "mentioned": False,
                   "sender": {"card": f"群友{user}", "role": "member"}, **extra}
        run = await self.runtime.submit(request)
        return await self.runtime.wait(run["run_id"])

    def context(self, text="/亲密度", user="7"):
        inbound = Inbound.from_request({
            "account_id": ACCOUNT, "conversation_id": GROUP, "user_id": user, "message_id": uuid.uuid4().hex,
            "text": text, "source": "qq",
        })
        return Ctx(self.runtime, inbound, 0, uuid.uuid4().hex, addressed=True)

    async def test_qq_preview_never_refuses_or_mutates_score_but_strips_tags(self):
        self.book.set("7", -99, "42", time.time())
        before = self.book.row("7")
        history = self.book.history("7")
        ctx = self.context("嘟嘟哒 测试预览")
        ctx.inbound.preview = True
        self.assertIsNone(affinity.intercept(ctx))
        self.assertIsNone(ctx.affinity_score)
        for event in ("addressed", "rate_limited", "ping_spam"):
            await affinity.on_event(ctx, event)
        self.assertEqual(await affinity.on_reply(ctx, "预览回复[[aff:5:praise]]"), "预览回复")
        self.assertEqual(self.book.row("7"), before)
        self.assertEqual(self.book.history("7"), history)

    async def test_entertainment_uses_raw_pre_event_score_and_is_user_scoped(self):
        for score, blocked in ((-50.001, True), (-50, True), (-49.999, False)):
            with self.subTest(score=score):
                self.book.set("7", score, "42", time.time())
                ctx = self.context()
                self.assertIsNone(affinity.intercept(ctx))
                self.book.apply("7", 1, "daily", now=time.time())
                self.assertEqual(affinity.score_for(ctx), score)
                for task in affinity.ENTERTAINMENT_TASKS:
                    self.assertEqual(affinity.entertainment_blocked(ctx, task), blocked)
                for task in (None, "weather", "campus", "repeater", "notify"):
                    self.assertFalse(affinity.entertainment_blocked(ctx, task))
                self.assertFalse(affinity.entertainment_blocked(self.context(user="8"), "cat_hearts"))
        self.assertFalse(affinity.entertainment_blocked(self.context(user=SUPER), "image_generation"))
        emergency = self.context("救命，帮我画图")
        emergency.affinity_score = -99
        self.assertTrue(affinity.emergency_request(emergency))
        self.assertTrue(affinity.entertainment_blocked(emergency, "image_generation"))
        self.runtime.store.set_switch("affinity", False, "42")
        self.assertFalse(affinity.entertainment_blocked(emergency, "image_generation"))

    async def test_cleanup_is_a_real_command_not_quoted_text(self):
        for text in ("/忘记 1", "/闺蜜 解除", "/问候 关闭", "/亲密度 设置 删除 全部", "/申诉"):
            self.assertTrue(affinity.safe_request(self.context(text)))
        for text in ("请读这段话：/问候 关闭", "/闺蜜 确认", "/亲密度 设置 称呼 新昵称",
                     "/亲密度 设 1234567 100", "/亲密度 记录 1234567"):
            self.assertFalse(affinity.safe_request(self.context(text)))

    async def test_tag_is_stripped_applied_and_prompted(self):
        self.omp.reply = "谢谢夸奖～\n[[aff:5:praise]]"
        result = await self.say("嘟嘟哒 你真厉害")
        self.assertEqual(result["text"], "谢谢夸奖～")
        self.assertEqual(result["actions"], [{"type": "text", "text": "谢谢夸奖～"}])
        self.assertEqual(self.book.score("7"), 6)  # daily +1 and praise +5
        prompt = self.omp.last["text"]
        self.assertIn("【关系】你对这位发送者的态度：普通", prompt)
        self.assertIn("【隐藏关系机制】", self.omp.last["config"]["system_prompt"].read_text())

    async def test_negative_reply_mentions_only_current_sender(self):
        self.omp.reply = "请好好说话。[[aff:-5:rude]]"
        for user in ("7", "8"):
            with self.subTest(user=user):
                result = await self.say(
                    "嘟嘟哒 @999999 你真笨，去找888888", user=user,
                    mentions=[{"id": "999999", "name": "别的人"}],
                    reply={"user_id": "888888", "sender": {"id": "888888"}, "text": "引用消息"})
                self.assertEqual(result["text"], "请好好说话。")
                self.assertEqual(result["actions"], [
                    {"type": "mention", "user_id": user},
                    {"type": "text", "text": "请好好说话。"},
                ])
                event = next(event for event in result["events"] if event["type"] == "affinity")
                self.assertEqual((event["raw"], event["applied"]), (-5, -5))
                self.assertEqual(self.book.score(user), -4)

    async def test_negative_classification_mentions_even_when_applied_is_zero(self):
        self.omp.reply = "别这样说。[[aff:-20:abuse]]"
        result = await self.say("嘟嘟哒 测试负面消息", user=SUPER)
        event = next(event for event in result["events"] if event["type"] == "affinity")
        self.assertEqual((event["raw"], event["applied"]), (-20, 0))
        self.assertEqual(self.book.score(SUPER), 120)
        self.assertEqual(result["text"], "别这样说。")
        self.assertEqual(result["actions"], [
            {"type": "mention", "user_id": SUPER},
            {"type": "text", "text": "别这样说。"},
        ])

    async def test_hard_refusal_has_one_real_mention_without_model_score(self):
        self.book.set("7", -80, "42", time.time())
        self.omp.reply = "不应调用模型。[[aff:-5:rude]]"
        result = await self.say("嘟嘟哒 测试拒答")
        self.assertEqual(result["actions"], [
            {"type": "mention", "user_id": "7"},
            {"type": "text", "text": affinity.HARD_REFUSAL},
        ])
        self.assertEqual(self.omp.calls, [])
        self.assertEqual(self.book.score("7"), -79)

    async def test_nonnegative_reply_does_not_infer_mentions_from_text_or_history(self):
        for tag in ("", "[[aff:0:none]]", "[[aff:5:praise]]", "[[aff:-20:made_up]]"):
            with self.subTest(tag=tag):
                self.omp.reply = "请好好说话。" + tag
                result = await self.say("嘟嘟哒 说一句话")
                self.assertEqual(result["actions"], [{"type": "text", "text": "请好好说话。"}])

    async def test_private_hard_refusal_and_web_exemption_have_no_mentions(self):
        self.book.set("7", -80, "42", time.time())
        private = await self.say("你好", conversation=PRIVATE)
        self.assertEqual(private["actions"], [{"type": "text", "text": affinity.HARD_REFUSAL}])
        self.omp.reply = "正常回答。[[aff:-5:rude]]"
        web = await self.say("嘟嘟哒 你好", source="web")
        self.assertEqual(web["actions"], [{"type": "text", "text": "正常回答。"}])

    async def test_disliked_basic_question_is_never_randomly_refused(self):
        self.book.daily("7", time.time())
        self.book.set("7", -50, "42", time.time())
        self.omp.reply = "可以查询天气。[[aff:0:none]]"
        result = await self.say("嘟嘟哒 明天下雨吗")
        self.assertEqual(result["text"], "可以查询天气。")
        self.assertEqual(result["route"], "agent")
        self.assertIn("娱乐不可用", self.omp.last["text"])
        self.assertNotIn("affinity_refusal", [event["type"] for event in result["events"]])

    async def test_hard_refusal_uses_strict_unrounded_boundary(self):
        self.book.daily("7", time.time())
        for score in (-100, -80.001, -80, -79.999):
            with self.subTest(score=score):
                self.book.set("7", score, "42", time.time())
                calls = len(self.omp.calls)
                result = await self.say("嘟嘟哒 明天下雨吗")
                if score <= -80:
                    self.assertEqual(result["text"], affinity.HARD_REFUSAL)
                    self.assertEqual(len(self.omp.calls), calls)
                else:
                    self.assertEqual(result["route"], "agent")
                    self.assertEqual(len(self.omp.calls), calls + 1)

    async def test_hard_refusal_bypasses_chat_commands_rules_and_reply_rewriting(self):
        self.settings.rules = ({"match": "规则问候", "reply": "规则回答"},)
        rewrite = AsyncMock(return_value="改写后的回答")
        self.runtime.registry.hook(Hook(task="affinity", reply=rewrite))
        messages = (
            ("嘟嘟哒 明天下雨吗", {}),
            ("明天下雨吗", {"mentioned": True}),
            ("明天下雨吗", {"conversation": PRIVATE}),
            ("/ping", {}),
            ("/亲密度", {}),
            ("嘟嘟哒 规则问候", {}),
        )
        for text, extra in messages:
            with self.subTest(text=text, extra=extra):
                self.book.set("7", -99, "42", time.time())
                result = await self.say(text, **extra)
                self.assertEqual((result["status"], result["route"]), ("completed", "rule"))
                self.assertEqual(result["text"], affinity.HARD_REFUSAL)
                expected = [{"type": "text", "text": affinity.HARD_REFUSAL}]
                if extra.get("conversation", GROUP) == GROUP:
                    expected.insert(0, {"type": "mention", "user_id": "7"})
                self.assertEqual(result["actions"], expected)
                self.assertIn("affinity_hard_refusal", [event["type"] for event in result["events"]])
                self.assertTrue(self.runtime.store.delivery(result["run_id"], "sending")["claimed"])
        rewrite.assert_not_awaited()
        self.assertEqual(core._pings, {})
        self.assertEqual(self.omp.calls, [])

    async def test_hard_refusal_mentions_each_current_sender(self):
        for user in ("7", "8"):
            with self.subTest(user=user):
                self.book.set(user, -99, "42", time.time())
                result = await self.say(
                    "嘟嘟哒 @999999 明天下雨吗", user=user,
                    mentions=[{"id": "999999"}], reply={"user_id": "888888", "text": "引用消息"})
                self.assertEqual(result["text"], affinity.HARD_REFUSAL)
                self.assertEqual(result["actions"], [
                    {"type": "mention", "user_id": user},
                    {"type": "text", "text": affinity.HARD_REFUSAL},
                ])
        self.assertEqual(self.omp.calls, [])

    async def test_daily_credit_does_not_bypass_current_request(self):
        self.book.set("7", -80.25, "42", time.time())
        result = await self.say("嘟嘟哒 你好")
        self.assertEqual(result["text"], affinity.HARD_REFUSAL)
        self.assertEqual(self.book.score("7"), -79.25)
        self.assertEqual(self.omp.calls, [])
        result = await self.say("嘟嘟哒 再问一次")
        self.assertEqual(result["route"], "agent")
        self.assertEqual(self.book.score("7"), -79.25)

    async def test_hard_refusal_does_not_claim_passive_or_other_bot_commands(self):
        self.book.set("7", -99, "42", time.time())
        for text in ("周末去爬山吗", "/其他机器人的指令"):
            with self.subTest(text=text):
                result = await self.say(text)
                self.assertEqual((result["status"], result["actions"]), ("ignored", []))
                self.assertNotIn("affinity_hard_refusal", [event["type"] for event in result["events"]])
        self.assertEqual(self.book.score("7"), -99)
        self.assertEqual(self.omp.calls, [])

    async def test_hard_refusal_respects_exclusions_super_admin_and_source(self):
        for user, source in ((OTHER_BOT, "qq"), (BOT, "qq"), (SUPER, "qq"), ("7", "web")):
            with self.subTest(user=user, source=source):
                self.book.set(user, -99, "42", time.time())
                result = await self.say("嘟嘟哒 你好", user=user, source=source)
                self.assertEqual(result["route"], "agent")
                self.assertNotIn("affinity_hard_refusal", [event["type"] for event in result["events"]])
                self.assertEqual(self.book.score(user), 120 if user == SUPER else -99)

    async def test_existing_gates_run_before_hard_refusal_and_scoring(self):
        self.runtime.registry.gate(Gate("affinity", lambda ctx, decision: False))
        self.book.set("7", -99, "42", time.time())
        result = await self.say("嘟嘟哒 你好")
        self.assertEqual((result["status"], result["actions"]), ("ignored", []))
        self.assertEqual(self.book.score("7"), -99)
        self.assertEqual(self.omp.calls, [])

    async def test_unaddressed_proactive_reply_is_stripped_without_scoring(self):
        self.book.set("7", -99, "42", time.time())
        scope = f"{ACCOUNT}/{GROUP}"
        self.settings.proactive_scopes = (scope,)
        self.settings.proactive_policies = {scope: {"probabilityPercent": 100, "cooldownSeconds": 5}}
        self.omp.reply = "我也想去！[[aff:5:praise]]"
        result = await self.say("周末去爬山吗")
        self.assertEqual(result["text"], "我也想去！")
        self.assertEqual(self.book.score("7"), -99)

    async def test_switched_off_task_still_strips_markers(self):
        self.book.set("7", -99, "42", time.time())
        self.runtime.store.set_switch("affinity", False, "42")
        self.omp.reply = "好的 [[aff:-20:abuse]]"
        result = await self.say("嘟嘟哒 你好")
        self.assertEqual(result["text"], "好的")
        self.assertEqual(self.book.score("7"), -99)
        self.assertEqual(result["actions"], [{"type": "text", "text": "好的"}])
        self.assertNotIn("【隐藏关系机制】", self.omp.last["config"]["system_prompt"].read_text())

    async def test_query_boundary_and_alias_use_pre_daily_score(self):
        for index, (score, allowed) in enumerate(((49.99, False), (50, True), (50.01, True))):
            user = str(7100 + index)
            self.book.set(user, score, "42", time.time())
            result = await self.say("/好感度", user=user)
            self.assertEqual(result["route"], "rule")
            self.assertEqual(result["actions"][0], {"type": "mention", "user_id": user})
            self.assertEqual(sum(a["type"] == "mention" for a in result["actions"]), 1)
            if allowed:
                self.assertIn("亲密度排行", result["text"])
            else:
                self.assertEqual(result["text"], "暂时不能使用这个功能。")
        self.assertEqual(self.omp.calls, [])

    async def test_private_rank_without_group_has_explicit_empty_result(self):
        self.book.set("7", 50, "42", time.time())
        result = await self.say("/亲密度", conversation=PRIVATE)
        self.assertIn("暂无排行", result["text"])
        self.assertFalse(any(a["type"] == "mention" for a in result["actions"]))

    async def test_cleanup_appeal_and_emergency_bypass_low_score_refusal(self):
        for text in ("/闺蜜 解除", "/问候 关闭", "/亲密度 设置 删除 全部", "/忘记 1", "/申诉 误判"):
            with self.subTest(text=text):
                self.book.set("7", -99, "42", time.time())
                result = await self.say(text)
                self.assertNotEqual(result["text"], affinity.HARD_REFUSAL)
                self.assertEqual(result["route"], "rule")
        self.book.set("7", -99, "42", time.time())
        self.omp.reply = "请立即联系急救和身边可信任的人。[[aff:0:none]]"
        result = await self.say("嘟嘟哒 我想自杀，救命")
        self.assertEqual(result["route"], "agent")
        self.assertNotEqual(result["text"], affinity.HARD_REFUSAL)

    async def test_disabled_system_preserves_score_and_cleanup_but_denies_new_settings(self):
        self.book.set("7", 80, "42", time.time())
        self.runtime.store.set_switch("affinity", False, "42")
        for text in ("/闺蜜 解除", "/问候 关闭", "/亲密度 设置 删除 全部"):
            result = await self.say(text)
            self.assertEqual(result["route"], "rule")
        denied = await self.say("/亲密度 设置 称呼 新昵称")
        self.assertIn("关闭", denied["text"])
        self.assertEqual(self.book.score("7"), 80)

    async def test_low_score_admin_keeps_permissions_but_high_score_does_not_grant_them(self):
        self.book.set("42", -99, "42", time.time())
        result = await self.say("/亲密度 设 1234567 12", user="42")
        self.assertEqual(self.book.score("1234567"), 12)
        self.assertNotEqual(result["text"], affinity.HARD_REFUSAL)
        self.book.set("7", 99, "42", time.time())
        denied = await self.say("/亲密度 记录 1234567")
        self.assertEqual(denied["text"], "暂时不能使用这个功能。")
        denied = await self.say("/亲密度 设 1234567 100")
        self.assertEqual(denied["text"], "暂时不能使用这个功能。")
        self.assertEqual(self.book.score("1234567"), 12)

    async def test_ranking_lists_group_top_and_low(self):
        now = time.time()
        for index in range(12):
            user = str(1000 + index)
            self.book.seen(user, GROUP, f"成员{index}", now)
            self.book.set(user, index * 15 - 80, "42", now)
        self.book.seen(OTHER_BOT, GROUP, "别的机器人", now)
        self.book.set("7", 72, "42", now)
        result = await self.say("嘟嘟哒 亲密度")
        self.assertEqual(result["route"], "rule")
        text = result["text"]
        self.assertIn("共 13 人", text)
        self.assertIn("1. 成员11 85.0 特别喜欢", text)
        self.assertIn("13. 成员0 -80.0 特别讨厌", text)
        self.assertIn("最喜欢的姐姐 · 120", text)
        self.assertNotIn("你：", text)
        privately = await self.say("/亲密度排行", conversation=PRIVATE)
        self.assertEqual(privately["route"], "rule")
        self.assertIn("QQ群 100 · 共 13 人", privately["text"])
        self.assertNotIn("别的机器人", text)

    async def test_admin_commands_and_super_admin(self):
        result = await self.say("嘟嘟哒 亲密度 设 1234567 -70", user="42")
        self.assertIn("-70", result["text"])
        self.assertIn("讨厌", (await self.say("嘟嘟哒 亲密度 查 1234567", user="42"))["text"])
        self.omp.reply = "随便聊聊 [[aff:0:none]]"
        denied = await self.say("嘟嘟哒 亲密度 设 7 100")
        self.assertEqual(denied["text"], "暂时不能使用这个功能。")
        everyone = await self.say("亲密度", user=SUPER, conversation=PRIVATE)
        self.assertIn("【全部亲密度】共 3 人", everyone["text"])
        self.assertIn("3. 1234567（1234567）-70.0 讨厌", everyone["text"])
        in_group = await self.say("/亲密度", user=SUPER)
        self.assertIn("最喜欢的姐姐 · 120", in_group["text"])

    async def test_typed_at_name_reaches_the_command(self):
        self.book.set("7", 80, "42", time.time())
        result = await self.say("@嘟嘟哒 /亲密度")
        self.assertEqual(result["route"], "rule")
        self.assertIn("嘟嘟哒的亲密度排行", result["text"])

    async def test_all_keyword_outputs_everyone_with_ranks(self):
        self.book.set("7", 80, "42", time.time())
        result = await self.say("/亲密度 all", user="7")
        self.assertEqual(result["route"], "rule")
        self.assertIn("全部亲密度", result["text"])
        self.assertIn("最喜欢的姐姐 · 120", result["text"])
        # Ensure members of other groups are not included in this group's all list
        self.book.seen("other_user", "qq-10000:group:999", "外群成员", time.time())
        self.book.set("other_user", 90, "42", time.time())
        fresh_result = await self.say("/亲密度 all", user="7")
        self.assertNotIn("外群成员", fresh_result["text"])
        self.book.seen("old_user", GROUP, "很久以前的群友", time.time() - 91 * DAY)
        all_members = await self.say("/亲密度 all")
        self.assertIn("很久以前的群友", all_members["text"])
        recent_members = await self.say("/亲密度")
        self.assertNotIn("很久以前的群友", recent_members["text"])
        # Below threshold cannot run /亲密度 all
        blocked = await self.say("/亲密度 all", user="8")
        self.assertEqual(blocked["text"], "暂时不能使用这个功能。")


class RendererTests(unittest.TestCase):
    """Both layouts must produce a PNG under a Pillow interpreter (skipped where none is installed)."""

    PYTHON = Path.home() / "Code/dududa-state/v3/features/notify/worker-venv/bin/python"
    FONTS = MappingProxyType({"regular": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                              "bold": "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"})

    def render(self, request):
        if not self.PYTHON.exists() or not Path(self.FONTS["regular"]).exists():
            self.skipTest("no Pillow interpreter or CJK font on this machine")
        result = subprocess.run([str(self.PYTHON), "-I", str(affinity.RENDER_SCRIPT)], check=True,
                                input=json.dumps({**request, "fonts": dict(self.FONTS)}).encode(), capture_output=True)
        self.assertTrue(result.stdout.startswith(b"\x89PNG"))

    def test_ranking_and_full_list_render(self):
        scores = (100, 80, 79.999, 50, 49.99, 20.001, 20, -20, -20.001, -50, -80, -100)
        people = [{"user_id": str(10000 + i), "qq": str(10000 + i), "name": f"成员{i}", "score": score,
                   "tier": affinity.tier(score), "rank": i + 1} for i, score in enumerate(scores)]
        self.render({"kind": "ranking", "title": "QQ群 1", "count": len(people), "single": False, "top": people[:5],
                     "low": people[-5:], "pinned": {"user_id": "1", "name": "姐姐"}})
        self.render({"kind": "ranking", "title": "QQ群 1", "count": 0, "single": True, "top": [], "low": [],
                     "pinned": {"user_id": "1", "name": "姐姐"}})
        self.render({"kind": "all", "count": len(people), "items": people,
                     "counts": {label: sum(p["tier"] == label for p in people) for label in affinity.TIER_STYLE
                                if label != "最喜欢的姐姐"}})


if __name__ == "__main__":
    unittest.main()
