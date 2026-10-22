"""Durable explicit consent, transactional revocation, and guarded outbox behavior."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dududa_v3.config import Settings
from dududa_v3.features.affinity import Ledger, greetings
from dududa_v3.features.base import Ctx, Inbound, JobCtx, Registry, Sender, Task
from dududa_v3.store import Store

ACCOUNT = "qq-100001"
USER = "300001"
GROUP = ACCOUNT + ":group:200001"
OTHER = ACCOUNT + ":group:200002"
PRIVATE = ACCOUNT + ":private:" + USER
SECOND_ACCOUNT = "qq-100002"
SECOND_GROUP = SECOND_ACCOUNT + ":group:200001"
SCOPES = tuple(f"{account}/{conversation}" for account, conversation in (
    (ACCOUNT, GROUP), (ACCOUNT, OTHER), (ACCOUNT, PRIVATE), (SECOND_ACCOUNT, SECOND_GROUP)))


class GreetingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = datetime(2026, 10, 20, 7, 50, tzinfo=greetings.ZONE).timestamp()
        clock = patch("dududa_v3.features.affinity.greetings.time.time", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.store = Store(Path(self.directory.name) / "state.sqlite3")
        registry = Registry()
        registry.task(Task("affinity", "亲密度", ""))
        self.settings = Settings(root=Path(__file__).resolve().parents[2], state_dir=Path(self.directory.name),
                                 allowed_scopes=SCOPES, proactive_scopes=tuple(s for s in SCOPES if ":group:" in s),
                                 admins=("900001",), features={"affinity": {"super_admin": "900002"}})
        self.runtime = SimpleNamespace(store=self.store, settings=self.settings, registry=registry)
        self.runtime.task_enabled = lambda task: self.store.switches().get(task, True)
        self.book = Ledger(self.store, "900002")
        self.book.set(USER, 70, "900001", self.now)
        self.job = JobCtx(self.runtime)

    def at(self, hour=8, minute=0, second=0, day=20):
        self.now = datetime(2026, 10, day, hour, minute, second, tzinfo=greetings.ZONE).timestamp()
        return self.now

    async def command(self, args, conversation=GROUP, account=ACCOUNT, pre=None, user=USER, role="member"):
        inbound = Inbound(account, conversation, "greeting-command", "/问候 " + args,
                          Sender(user, role=role), mentioned=True)
        ctx = Ctx(self.runtime, inbound, self.store.session(inbound.scope)["id"], "run", args=args,
                  affinity_score=self.book.score(user) if pre is None else pre)
        return await greetings.greeting_command(ctx)

    def subscription(self, kind="morning", user=USER):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM affinity_greetings WHERE user_id=? AND kind=?", (user, kind)).fetchone()
        return dict(row) if row else None

    def outbox(self):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM outbox ORDER BY id")]

    def relationship(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO affinity_relationships(user_id,established_at) VALUES (?,?)", (USER, self.now))

    async def queued(self):
        await self.command("早安 08:00")
        self.at()
        self.assertEqual(greetings.queue_due(self.job), 1)
        return self.store.outbox_claim()[0]

    async def test_default_off_and_pre_event_fractional_threshold(self):
        greetings.reconcile(self.runtime)
        self.assertEqual(greetings.queue_due(self.job), 0)
        self.book.set(USER, 50.99, "900001", self.now)
        await self.command("早安 08:00", pre=49.99)
        self.assertIsNone(self.subscription())
        self.book.set(USER, 50, "900001", self.now)
        reply = await self.command("早安 08:00")
        self.assertTrue(self.subscription()["enabled"])
        self.assertEqual([a for a in reply.actions if a["type"] == "mention"], [{"type": "mention", "user_id": USER}])

    async def test_paused_relationship_cannot_subscribe_at_exactly_fifty(self):
        self.relationship()
        self.book.set(USER, 50, "900001", self.now)
        await self.command("早安 08:00")
        self.assertIsNone(self.subscription())
        self.book.set(USER, 50.01, "900001", self.now)
        await self.command("早安 08:00")
        self.assertTrue(self.subscription()["enabled"])

    async def test_special_requires_relationship_eighty_and_individual_dates(self):
        self.book.set(USER, 80, "900001", self.now)
        await self.command("生日 10-20 08:00")
        self.assertIsNone(self.subscription("birthday"))
        self.relationship()
        await self.command("生日 10-20 08:00", pre=79.99)
        self.assertIsNone(self.subscription("birthday"))
        await self.command("生日 10-20 08:00", PRIVATE)
        self.assertTrue(self.subscription("birthday")["enabled"])
        self.assertIsNone(self.subscription("anniversary"))
        await self.command("纪念日 2026-10-21 08:00", GROUP)
        self.at()
        self.assertEqual(greetings.queue_due(self.job), 1)
        item = self.store.outbox_claim()[0]
        self.assertEqual(item["conversation_id"], PRIVATE)
        self.assertFalse(any(a["type"] == "mention" for a in item["actions"]))
        self.at(day=21)
        self.assertEqual(greetings.queue_due(self.job), 1)
        self.assertEqual(self.store.outbox_claim()[0]["guard"]["kind"], "anniversary")

    async def test_invalid_time_and_dates_never_create_consent(self):
        self.relationship()
        self.book.set(USER, 80, "900001", self.now)
        for args in ("早安", "早安 24:00", "晚安 08:60", "生日 02-30 08:00", "纪念日 2026-02-29 08:00"):
            await self.command(args)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM affinity_greetings").fetchone()[0], 0)
        await self.command("生日 02-29 08:00")
        self.assertEqual(self.subscription("birthday")["annual_date"], "02-29")

    async def test_claim_does_not_authorize_and_authorization_is_one_shot(self):
        item = await self.queued()
        self.assertEqual(self.outbox()[0]["state"], "claimed")
        self.assertFalse(self.store.outbox_result(item["id"], "sent"))
        result = greetings.authorize(self.runtime, item["id"], True)
        self.assertTrue(result["authorized"])
        self.assertEqual([a for a in result["actions"] if a["type"] == "mention"], [{"type": "mention", "user_id": USER}])
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.assertTrue(self.store.outbox_result(item["id"], "sent", "qq-result"))
        self.assertEqual(self.store.outbox_claim(), [])

    async def test_daily_dedupe_survives_replacement_accounts_and_restart(self):
        item = await self.queued()
        self.assertTrue(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.store.outbox_result(item["id"], "sent")
        await self.command("早安 08:10", SECOND_GROUP, SECOND_ACCOUNT)
        await self.command("确认 早安", SECOND_GROUP, SECOND_ACCOUNT)
        self.at(minute=10)
        self.assertEqual(greetings.queue_due(self.job), 0)
        self.runtime.store = self.store = Store(self.store.path)
        greetings.reconcile(self.runtime)
        self.assertEqual(greetings.queue_due(self.job), 0)
        self.at(minute=10, day=21)
        self.assertEqual(greetings.queue_due(self.job), 1)
        self.assertEqual(self.store.outbox_claim()[0]["account_id"], SECOND_ACCOUNT)

    async def test_dispatch_date_dedupe_also_covers_midnight_delay(self):
        self.at(hour=23, minute=58)
        await self.command("晚安 23:59")
        self.at(hour=23, minute=59)
        self.assertEqual(greetings.queue_due(self.job), 1)
        item = self.store.outbox_claim()[0]
        self.at(hour=0, minute=3, day=21)
        self.assertTrue(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.store.outbox_result(item["id"], "unknown")
        self.at(hour=23, minute=59, day=21)
        self.assertEqual(greetings.queue_due(self.job), 1)
        second = self.store.outbox_claim()[0]
        self.assertFalse(greetings.authorize(self.runtime, second["id"], True)["authorized"])
        self.assertEqual(self.outbox()[-1]["state"], "cancelled")

    async def test_expiry_checked_before_claim_and_again_before_dispatch(self):
        item = await self.queued()
        self.at(minute=15, second=1)
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.assertEqual(self.outbox()[0]["state"], "cancelled")
        self.at(day=21)
        self.assertEqual(greetings.queue_due(self.job), 1)
        self.at(minute=15, second=1, day=21)
        self.assertEqual(self.store.outbox_claim(), [])
        self.at(hour=9, day=22)
        self.assertEqual(greetings.queue_due(self.job), 0)
        self.assertTrue(self.subscription()["enabled"])

    async def test_no_backfill_before_explicit_opt_in(self):
        self.at(minute=5)
        await self.command("早安 08:00")
        self.assertEqual(greetings.queue_due(self.job), 0)
        self.at(day=21)
        self.assertEqual(greetings.queue_due(self.job), 1)

    async def test_score_drop_then_recovery_permanently_revokes_claim(self):
        item = await self.queued()
        self.book.set(USER, 49.99, "900001", self.now)
        self.book.set(USER, 80, "900001", self.now)
        self.assertFalse(self.subscription()["enabled"])
        self.assertEqual(self.outbox()[0]["state"], "cancelled")
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.at(day=21)
        self.assertEqual(greetings.queue_due(self.job), 0)

    async def test_drop_to_fifty_pauses_existing_relationship_and_special_drops_at_eighty(self):
        self.relationship()
        self.book.set(USER, 80, "900001", self.now)
        await self.command("早安 08:00")
        await self.command("生日 10-20 08:00")
        self.book.set(USER, 79.99, "900001", self.now)
        self.assertTrue(self.subscription()["enabled"])
        self.assertFalse(self.subscription("birthday")["enabled"])
        self.book.set(USER, 50, "900001", self.now)
        self.assertFalse(self.subscription()["enabled"])

    async def test_score_and_cancellation_roll_back_together(self):
        item = await self.queued()
        with (
            patch.object(greetings, "_audit", side_effect=RuntimeError("audit unavailable")),
            self.assertRaises(RuntimeError),
        ):
            self.book.set(USER, 49, "900001", self.now)
        self.assertEqual(self.book.score(USER), 70)
        self.assertTrue(self.subscription()["enabled"])
        self.assertTrue(greetings.authorize(self.runtime, item["id"], True)["authorized"])

    async def test_low_score_opt_out_cancels_and_relationship_exit_revokes(self):
        item = await self.queued()
        await self.command("关闭早安", pre=-100)
        self.assertFalse(self.subscription()["enabled"])
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        await self.command("晚安 23:00")
        with self.store.connect() as db:
            greetings.disable_user(db, USER)
        self.assertFalse(self.subscription("evening")["enabled"])

    async def test_pending_replacement_cancels_old_claim_and_is_same_scope_expiring(self):
        item = await self.queued()
        await self.command("早安 08:10", PRIVATE)
        self.assertFalse(self.subscription()["enabled"])
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        await self.command("确认 早安", OTHER)
        self.assertEqual(self.subscription()["conversation_id"], GROUP)
        self.at(minute=11)
        await self.command("确认 早安", PRIVATE)
        self.assertEqual(self.subscription()["conversation_id"], GROUP)
        await self.command("早安 08:20", PRIVATE)
        await self.command("确认 早安", PRIVATE, pre=49.99)
        self.assertFalse(self.subscription()["enabled"])
        await self.command("确认 早安", PRIVATE)
        self.assertTrue(self.subscription()["enabled"])
        self.assertEqual(self.subscription()["conversation_id"], PRIVATE)

    async def test_same_target_schedule_change_revokes_claim(self):
        item = await self.queued()
        await self.command("早安 09:00")
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.at(hour=9)
        self.assertEqual(greetings.queue_due(self.job), 0)

    async def test_target_membership_failure_is_unknown_and_permanently_disables(self):
        item = await self.queued()
        self.assertFalse(greetings.authorize(self.runtime, item["id"], False)["authorized"])
        self.assertEqual(self.outbox()[0]["state"], "unknown")
        self.assertFalse(self.subscription()["enabled"])
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.at(day=21)
        self.assertEqual(greetings.queue_due(self.job), 0)

    async def test_global_disable_is_atomic_and_reset_does_not_resume(self):
        item = await self.queued()
        self.store.outbox_push(ACCOUNT, GROUP, [{"type": "text", "text": "important homework"}], "homework")
        self.store.set_switch("affinity", False, "900001")
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.assertFalse(self.subscription()["enabled"])
        ordinary = self.store.outbox_claim()
        self.assertEqual(len(ordinary), 1)
        self.assertNotIn("guard", ordinary[0])
        self.assertTrue(self.store.outbox_result(ordinary[0]["id"], "sent"))
        await self.command("早安 08:10")
        self.assertFalse(self.subscription()["enabled"])
        self.store.set_switch("affinity", None, "900001")
        self.at(day=21)
        self.assertEqual(greetings.queue_due(self.job), 0)
        await self.command("早安 08:10")
        self.assertTrue(self.subscription()["enabled"])

    async def test_group_admin_disable_is_scoped_and_reenable_is_not_opt_in(self):
        item = await self.queued()
        await self.command("群关闭")
        self.assertTrue(self.subscription()["enabled"])
        await self.command("群关闭", user="400001", role="admin")
        self.assertFalse(self.subscription()["enabled"])
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        await self.command("早安 08:10")
        self.assertFalse(self.subscription()["enabled"])
        await self.command("群开启", user="400001", role="admin")
        self.assertFalse(self.subscription()["enabled"])
        await self.command("晚安 23:00", OTHER)
        self.assertTrue(self.subscription("evening")["enabled"])

    async def test_scope_revocation_and_disabled_startup_do_not_resume(self):
        item = await self.queued()
        self.settings.proactive_scopes = ()
        self.assertFalse(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        self.assertFalse(self.subscription()["enabled"])
        await self.command("群开启", role="owner")
        await self.command("早安 08:10")
        self.assertFalse(self.subscription()["enabled"])
        await self.command("晚安 23:00", PRIVATE)
        self.assertTrue(self.subscription("evening")["enabled"])
        self.settings.allowed_scopes = ()
        greetings.reconcile(self.runtime)
        self.assertFalse(self.subscription("evening")["enabled"])
        self.settings.allowed_scopes = SCOPES
        greetings.reconcile(self.runtime)
        self.assertFalse(self.subscription("evening")["enabled"])

    async def test_restart_persists_pending_but_never_retries_claimed_or_unknown(self):
        await self.command("早安 08:00")
        self.at()
        greetings.queue_due(self.job)
        restarted = Store(self.store.path)
        restarted.recover()
        self.assertEqual(len(restarted.outbox_claim()), 1)
        restarted.recover()
        self.assertEqual(restarted.outbox_claim(), [])
        self.assertEqual(self.outbox()[0]["state"], "unknown")
        self.assertEqual(greetings.queue_due(self.job), 0)

    async def test_already_dispatched_boundary_is_not_falsely_cancelled(self):
        item = await self.queued()
        self.assertTrue(greetings.authorize(self.runtime, item["id"], True)["authorized"])
        await self.command("关闭")
        self.assertEqual(self.outbox()[0]["state"], "sending")
        self.assertTrue(self.store.outbox_result(item["id"], "unknown"))
        self.assertEqual(self.store.outbox_claim(), [])

    async def test_private_date_is_not_disclosed_in_group_status_or_replacement(self):
        self.relationship()
        self.book.set(USER, 80, "900001", self.now)
        await self.command("生日 05-20 08:00", PRIVATE)
        status = await self.command("状态", GROUP)
        replacement = await self.command("生日 11-11 09:00", GROUP)
        self.assertNotIn("05-20", status.plain_text + replacement.plain_text)
        self.assertNotIn(PRIVATE, status.plain_text + replacement.plain_text)
        await self.command("确认 生日", GROUP)
        self.assertEqual(self.subscription("birthday")["annual_date"], "11-11")
