"""Hidden affinity: scoring math, tag handling and the /亲密度 command through the real Host."""

import json
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from dududa_v3.config import Settings
from dududa_v3.features import affinity, core
from dududa_v3.features.base import Registry, Toolkit
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

    def test_middle_range_is_unthrottled_beyond_cooldown(self):
        for _ in range(12):
            self.give("u", 5)
        self.assertEqual(self.book.score("u"), 60)

    def test_positive_cooldown_and_duplicate_praise(self):
        self.give("u", 3)
        self.assertEqual(self.give("u", 3, after=30).note, "cooldown")
        self.assertEqual(self.give("u", 3, digest="same").applied, 3)
        self.assertEqual(self.give("u", 3, digest="same").note, "duplicate")
        self.assertEqual(self.give("u", -3, "rude", after=1).applied, -3)
        self.assertEqual(self.book.score("u"), 3)

    def test_near_edges_damps_and_caps_per_day(self):
        self.book.set("u", 80, "admin", self.now)
        outcome = self.give("u", 4)
        self.assertAlmostEqual(outcome.applied, 2.0)
        self.give("u", 4)
        self.give("u", 4)
        self.assertAlmostEqual(self.book.score("u"), 84.0)
        self.now += DAY
        self.assertGreater(self.give("u", 4).applied, 0)
        self.book.set("v", -90, "admin", self.now)
        self.assertAlmostEqual(self.give("v", -20, "abuse", after=1).applied, -5.0)
        self.assertAlmostEqual(self.give("v", -20, "abuse", after=1).applied, -2.5)
        self.give("v", -20, "abuse", after=1)
        self.give("v", -20, "abuse", after=1)
        self.assertGreaterEqual(self.book.score("v"), -100)
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

    def test_tag_parsing_and_reason_ranges(self):
        clean, tag = affinity.parse_tag("好呀～\n[[aff:+9:praise]]")
        self.assertEqual((clean, tag), ("好呀～", (9.0, "praise")))
        self.assertEqual(affinity.clamp_reason(9, "praise"), 5)
        self.assertEqual(affinity.clamp_reason(5, "beg"), 0)
        self.assertEqual(affinity.clamp_reason(-30, "abuse"), -20)
        self.assertEqual(affinity.clamp_reason(3, "made_up"), 0)
        self.assertEqual(affinity.parse_tag("[[aff:1:chat]]中间[[aff:-3:rude]]")[0], "中间")
        self.assertEqual([affinity.tier(v) for v in (-51, -50, -11, -10, 30, 31, 60, 61, 120)],
                         ["讨厌", "不反感", "不反感", "普通", "普通", "喜欢", "喜欢", "非常喜欢", "最喜欢的姐姐"])


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

    async def test_tag_is_stripped_applied_and_prompted(self):
        self.omp.reply = "谢谢夸奖～\n[[aff:5:praise]]"
        result = await self.say("嘟嘟哒 你真厉害")
        self.assertEqual(result["text"], "谢谢夸奖～")
        self.assertEqual(self.book.score("7"), 6)  # daily +1 and praise +5
        prompt = self.omp.last["text"]
        self.assertIn("【关系】你对这位发送者的态度：普通", prompt)
        self.assertIn("【隐藏关系机制】", self.omp.last["config"]["system_prompt"].read_text())

    async def test_disliked_tier_refuses_with_rising_chance(self):
        toolkit = Toolkit(self.runtime)
        self.assertEqual(affinity.refusal_chance(toolkit, -50), 0.0)
        self.assertAlmostEqual(affinity.refusal_chance(toolkit, -51), 0.3)
        self.assertAlmostEqual(affinity.refusal_chance(toolkit, -100), 0.8)
        self.book.set("7", -80, "42", time.time())
        self.omp.reply = "哦。[[aff:0:none]]"
        with patch("dududa_v3.features.affinity.random.random", return_value=0.0):
            refused = await self.say("嘟嘟哒 明天下雨吗")
        self.assertIn("本轮你不想回答", self.omp.last["text"])
        self.assertIn("affinity_refusal", [event["type"] for event in refused["events"]])
        with patch("dududa_v3.features.affinity.random.random", return_value=0.99):
            await self.say("嘟嘟哒 明天下雨吗")
        self.assertNotIn("本轮你不想回答", self.omp.last["text"])
        self.assertIn("态度很差", self.omp.last["text"])

    async def test_unaddressed_proactive_reply_is_stripped_without_scoring(self):
        scope = f"{ACCOUNT}/{GROUP}"
        self.settings.proactive_scopes = (scope,)
        self.settings.proactive_policies = {scope: {"probabilityPercent": 100, "cooldownSeconds": 5}}
        self.omp.reply = "我也想去！[[aff:5:praise]]"
        result = await self.say("周末去爬山吗")
        self.assertEqual(result["text"], "我也想去！")
        self.assertEqual(self.book.score("7"), 0)

    async def test_switched_off_task_still_strips_markers(self):
        self.runtime.store.set_switch("affinity", False, "42")
        self.omp.reply = "好的 [[aff:-20:abuse]]"
        result = await self.say("嘟嘟哒 你好")
        self.assertEqual(result["text"], "好的")
        self.assertEqual(self.book.score("7"), 0)
        self.assertNotIn("【隐藏关系机制】", self.omp.last["config"]["system_prompt"].read_text())

    async def test_query_is_hidden_below_threshold(self):
        probe = await self.say("/亲密度")
        self.assertEqual((probe["status"], probe["actions"]), ("ignored", []))
        self.assertEqual(self.omp.calls, [])
        self.omp.reply = "什么亲密度呀？[[aff:0:none]]"
        result = await self.say("嘟嘟哒 亲密度")
        self.assertEqual((result["route"], result["text"]), ("agent", "什么亲密度呀？"))
        private = await self.say("/亲密度", conversation=PRIVATE)
        self.assertEqual(private["route"], "agent")
        help_text = (await self.say("嘟嘟哒 help"))["text"]
        self.assertNotIn("亲密度", help_text)

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
        self.assertIn("1. 成员11 85 非常喜欢", text)
        self.assertIn("13. 成员0 -80 讨厌", text)
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
        self.assertEqual(denied["route"], "agent")
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
        self.assertIn("【全部亲密度】", result["text"])
        self.assertIn("最喜欢的姐姐 · 120", result["text"])
        # Below threshold cannot run /亲密度 all
        blocked = await self.say("/亲密度 all", user="8")
        self.assertEqual((blocked["status"], blocked["actions"]), ("ignored", []))


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
        people = [{"user_id": str(10000 + i), "qq": str(10000 + i), "name": f"成员{i}", "score": 40 - i * 7.5,
                   "tier": affinity.tier(40 - i * 7.5), "rank": i + 1} for i in range(11)]
        self.render({"kind": "ranking", "title": "QQ群 1", "count": 11, "single": False, "top": people[:5],
                     "low": people[-5:], "pinned": {"user_id": "1", "name": "姐姐"}})
        self.render({"kind": "ranking", "title": "QQ群 1", "count": 0, "single": True, "top": [], "low": [],
                     "pinned": {"user_id": "1", "name": "姐姐"}})
        self.render({"kind": "all", "count": 11, "items": people,
                     "counts": {"讨厌": 2, "不反感": 3, "普通": 5, "喜欢": 1, "非常喜欢": 0}})


if __name__ == "__main__":
    unittest.main()
