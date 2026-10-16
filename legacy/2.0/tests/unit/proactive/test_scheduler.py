from __future__ import annotations

import asyncio
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.errors import DududaError
from dududa.ports.proactive import (
    ProactiveScheduler,
    ProactiveScheduleStore,
    ProactiveSubscriptionStore,
)
from dududa.proactive.contracts import (
    ScheduleAckDisposition,
    ScheduleClaimDisposition,
    ScheduleOccurrenceState,
    ScheduleSpec,
    SubscriptionStatus,
)
from dududa.proactive.scheduler import (
    DeterministicProactiveScheduler,
    resolve_local_schedule,
)
from dududa.proactive.scheduler_codec import (
    decode_subscription,
    encode_subscription,
)
from dududa.proactive.sqlite_scheduler import (
    SchedulerJournalMode,
    SQLiteProactiveSchedulerStore,
    SQLiteSchedulerStoreConfig,
)

from ._fixtures import ProactiveFixture


class SchedulerCodecAndTimeTests(unittest.TestCase):
    def test_subscription_codec_round_trip_and_tamper_fail_closed(self) -> None:
        fixture = ProactiveFixture()
        payload = encode_subscription(fixture.subscription)
        self.assertEqual(decode_subscription(payload), fixture.subscription)

        changed = json.loads(payload)
        changed["source_policy_id"] = "forged-policy"
        with self.assertRaises(DududaError):
            decode_subscription(json.dumps(changed))

        changed = json.loads(payload)
        changed["status"] = "unknown"
        with self.assertRaises(DududaError) as captured:
            decode_subscription(json.dumps(changed))
        self.assertEqual(
            captured.exception.info.code,
            "invalid_scheduler_json_enum",
        )

    def test_dst_gap_fold_and_half_hour_transitions_are_deterministic(self) -> None:
        self.assertIsNone(
            resolve_local_schedule(
                "America/New_York",
                date(2026, 3, 8),
                time(2, 30),
            )
        )
        self.assertEqual(
            resolve_local_schedule(
                "America/New_York",
                date(2026, 11, 1),
                time(1, 30),
            ),
            datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc),
        )
        self.assertIsNone(
            resolve_local_schedule(
                "Australia/Lord_Howe",
                date(2026, 10, 4),
                time(2, 15),
            )
        )
        self.assertEqual(
            resolve_local_schedule(
                "Europe/Berlin",
                date(2026, 10, 25),
                time(2, 30),
            ),
            datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc),
        )


class DurableSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "scheduler.sqlite3"
        self.fixture = ProactiveFixture()
        self.config = SQLiteSchedulerStoreConfig(
            schema_version=1,
            path=self.path,
            busy_timeout=timedelta(seconds=2),
            maximum_subscriptions=100,
            maximum_slots=10_000,
            terminal_retention=timedelta(days=365),
        )
        self.store = SQLiteProactiveSchedulerStore(
            self.config,
            clock=self.fixture.clock,
        )
        self.scheduler = DeterministicProactiveScheduler(self.store, self.store)

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def _publish_initial(self) -> None:
        await self.store.publish(
            self.fixture.subscription,
            expected_revision=None,
            mutation_id="create-1",
            call=self.fixture.service_call("create-1"),
        )

    async def _materialize_and_claim(self, *, ttl: timedelta = timedelta(seconds=10)):
        await self.scheduler.materialize_due(
            now=self.fixture.clock.value,
            call=self.fixture.service_call("materialize"),
        )
        claims = await self.scheduler.claim_due(
            worker_id="worker-1",
            limit=10,
            ttl=ttl,
            now=self.fixture.clock.value,
            call=self.fixture.service_call("claim"),
        )
        self.assertEqual(len(claims), 1)
        return claims[0]

    async def test_store_and_service_implement_framework_neutral_ports(self) -> None:
        self.assertIsInstance(self.store, ProactiveSubscriptionStore)
        self.assertIsInstance(self.store, ProactiveScheduleStore)
        self.assertIsInstance(self.scheduler, ProactiveScheduler)
        names = set(vars(self.scheduler))
        self.assertFalse(
            names
            & {
                "_mcp",
                "_source_provider",
                "_model",
                "_memory",
                "_output",
                "_connector",
            }
        )

    async def test_subscription_cas_idempotency_pause_resume_and_revoke(self) -> None:
        fixture = self.fixture
        created = await self.store.publish(
            fixture.subscription,
            expected_revision=None,
            mutation_id="create-1",
            call=fixture.service_call("create"),
        )
        replay = await self.store.publish(
            fixture.subscription,
            expected_revision=None,
            mutation_id="create-1",
            call=fixture.service_call("create-replay"),
        )
        self.assertEqual(replay, created)

        paused = replace(
            fixture.subscription,
            revision=2,
            status=SubscriptionStatus.PAUSED,
            updated_at=fixture.now + timedelta(seconds=1),
            subscription_digest="",
        )
        receipt = await self.store.publish(
            paused,
            expected_revision=1,
            mutation_id="pause-2",
            call=fixture.service_call("pause"),
        )
        self.assertEqual(receipt.previous_revision, 1)
        self.assertEqual(await self.store.list_active(call=fixture.service_call()), ())

        resumed = replace(
            paused,
            revision=3,
            status=SubscriptionStatus.ACTIVE,
            updated_at=fixture.now + timedelta(seconds=2),
            subscription_digest="",
        )
        await self.store.publish(
            resumed,
            expected_revision=2,
            mutation_id="resume-3",
            call=fixture.service_call("resume"),
        )
        revoked = replace(
            resumed,
            revision=4,
            status=SubscriptionStatus.REVOKED,
            updated_at=fixture.now + timedelta(seconds=3),
            subscription_digest="",
        )
        await self.store.publish(
            revoked,
            expected_revision=3,
            mutation_id="revoke-4",
            call=fixture.service_call("revoke"),
        )
        with self.assertRaises(DududaError):
            await self.store.publish(
                replace(
                    revoked,
                    revision=5,
                    status=SubscriptionStatus.ACTIVE,
                    updated_at=fixture.now + timedelta(seconds=4),
                    subscription_digest="",
                ),
                expected_revision=4,
                mutation_id="forbidden-resume",
                call=fixture.service_call("forbidden-resume"),
            )

    async def test_replacement_invalidates_live_claim_and_old_ack(self) -> None:
        await self._publish_initial()
        claim = await self._materialize_and_claim(ttl=timedelta(seconds=30))
        paused = replace(
            self.fixture.subscription,
            revision=2,
            status=SubscriptionStatus.PAUSED,
            updated_at=self.fixture.now + timedelta(seconds=1),
            subscription_digest="",
        )
        await self.store.publish(
            paused,
            expected_revision=1,
            mutation_id="pause-2",
            call=self.fixture.service_call("pause"),
        )
        record = await self.store.load_schedule_record(
            self.fixture.subscription.subscription_id,
            self.fixture.now.date(),
            call=self.fixture.service_call("load-invalidated"),
        )
        assert record is not None
        self.assertIs(record.state, ScheduleOccurrenceState.INVALIDATED)
        self.assertIsNone(record.claim)
        with self.assertRaises(DududaError):
            await self.store.acknowledge(
                claim,
                at=self.fixture.now + timedelta(seconds=2),
                call=self.fixture.service_call("old-ack"),
            )

    async def test_lease_reclaim_restart_and_exact_ack_are_stable(self) -> None:
        await self._publish_initial()
        first = await self._materialize_and_claim()
        at = self.fixture.now + timedelta(seconds=11)
        second, disposition = await self.store.claim(
            first.trigger.occurrence.occurrence_digest,
            worker_id="worker-2",
            ttl=timedelta(seconds=10),
            at=at,
            call=self.fixture.service_call("reclaim"),
        )
        self.assertIs(disposition, ScheduleClaimDisposition.RECLAIMED)
        self.assertEqual(second.lease_revision, 2)
        with self.assertRaises(DududaError):
            await self.store.acknowledge(
                first,
                at=at + timedelta(seconds=1),
                call=self.fixture.service_call("old-ack"),
            )
        emitted = await self.store.acknowledge(
            second,
            at=at + timedelta(seconds=1),
            call=self.fixture.service_call("new-ack"),
        )
        self.assertIs(emitted.disposition, ScheduleAckDisposition.EMITTED)

        restarted = SQLiteProactiveSchedulerStore(
            self.config,
            clock=self.fixture.clock,
        )
        replay = await restarted.acknowledge(
            second,
            at=at + timedelta(seconds=2),
            call=self.fixture.service_call("ack-replay"),
        )
        self.assertIs(replay.disposition, ScheduleAckDisposition.EXISTING)
        self.assertEqual(replay.record_revision, emitted.record_revision)

    async def test_two_store_instances_allow_one_live_claim_owner(self) -> None:
        await self._publish_initial()
        await self.scheduler.materialize_due(
            now=self.fixture.now,
            call=self.fixture.service_call("materialize"),
        )
        second_store = SQLiteProactiveSchedulerStore(
            self.config,
            clock=self.fixture.clock,
        )
        occurrence = (
            await self.store.load_schedule_record(
                self.fixture.subscription.subscription_id,
                self.fixture.now.date(),
                call=self.fixture.service_call("load"),
            )
        ).trigger.occurrence

        def compete(item):
            store, worker = item
            try:
                return asyncio.run(
                    store.claim(
                        occurrence.occurrence_digest,
                        worker_id=worker,
                        ttl=timedelta(seconds=30),
                        at=self.fixture.now,
                        call=self.fixture.service_call(worker),
                    )
                )[1]
            except DududaError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    compete,
                    ((self.store, "worker-1"), (second_store, "worker-2")),
                )
            )
        self.assertEqual(
            sum(result is ScheduleClaimDisposition.ACQUIRED for result in results),
            1,
        )

    async def test_misfire_and_clock_rollback_never_restore_terminal_slot(self) -> None:
        await self._publish_initial()
        late = self.fixture.now + timedelta(minutes=31)
        self.fixture.clock.value = late
        receipt = (
            await self.scheduler.materialize_due(
                now=late,
                call=self.fixture.service_call("late-materialize"),
            )
        )[-1]
        self.assertIs(receipt.state, ScheduleOccurrenceState.SKIPPED_EXPIRED)
        self.assertEqual(
            await self.scheduler.claim_due(
                worker_id="worker-1",
                limit=10,
                ttl=timedelta(seconds=10),
                now=late,
                call=self.fixture.service_call("late-claim"),
            ),
            (),
        )
        replay = (
            await self.scheduler.materialize_due(
                now=self.fixture.now,
                call=self.fixture.service_call("rollback"),
            )
        )[-1]
        self.assertFalse(replay.created)
        record = await self.store.load_schedule_record(
            self.fixture.subscription.subscription_id,
            self.fixture.now.date(),
            call=self.fixture.service_call("load-terminal"),
        )
        assert record is not None
        self.assertIs(record.state, ScheduleOccurrenceState.SKIPPED_EXPIRED)

    async def test_nonexistent_wall_time_persists_one_tombstone(self) -> None:
        now = datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc)
        self.fixture.clock.value = now
        schedule = ScheduleSpec(
            1,
            "America/New_York",
            time(2, 30),
            frozenset(range(7)),
            (),
            timedelta(minutes=30),
            "new-york-gap-v1",
        )
        subscription = replace(
            self.fixture.subscription,
            schedule=schedule,
            created_at=datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc),
            subscription_digest="",
        )
        await self.store.publish(
            subscription,
            expected_revision=None,
            mutation_id="create-gap",
            call=self.fixture.service_call("create-gap"),
        )
        first = await self.scheduler.materialize_due(
            now=now,
            call=self.fixture.service_call("gap-first"),
        )
        second = await self.scheduler.materialize_due(
            now=now,
            call=self.fixture.service_call("gap-second"),
        )
        self.assertEqual(len(first), 1)
        self.assertIs(first[0].state, ScheduleOccurrenceState.SKIPPED_NONEXISTENT)
        self.assertTrue(first[0].created)
        self.assertFalse(second[0].created)

    async def test_thirty_day_fake_clock_has_no_duplicate_or_late_delivery(
        self,
    ) -> None:
        await self._publish_initial()
        created = 0
        emitted = 0
        for day in range(30):
            now = self.fixture.now + timedelta(days=day)
            self.fixture.clock.value = now
            first = await self.scheduler.materialize_due(
                now=now,
                call=self.fixture.service_call(f"materialize-{day}"),
            )
            second = await self.scheduler.materialize_due(
                now=now,
                call=self.fixture.service_call(f"duplicate-{day}"),
            )
            created += sum(receipt.created for receipt in first)
            self.assertTrue(all(not receipt.created for receipt in second))
            claims = await self.scheduler.claim_due(
                worker_id="worker-1",
                limit=10,
                ttl=timedelta(minutes=5),
                now=now,
                call=self.fixture.service_call(f"claim-{day}"),
            )
            for claim in claims:
                await self.scheduler.acknowledge(
                    claim,
                    now=now + timedelta(seconds=1),
                    call=self.fixture.service_call(f"ack-{day}"),
                )
                emitted += 1

        with sqlite3.connect(self.path) as connection:
            slot_count = connection.execute(
                "SELECT COUNT(*) FROM schedule_slots"
            ).fetchone()[0]
            emitted_count = connection.execute(
                "SELECT COUNT(*) FROM schedule_slots WHERE state = ?",
                (ScheduleOccurrenceState.EMITTED.value,),
            ).fetchone()[0]
        self.assertEqual(
            (created, emitted, slot_count, emitted_count), (30, 30, 30, 30)
        )

    async def test_default_journal_and_persisted_row_tamper_fail_closed(self) -> None:
        await self._publish_initial()
        await self.scheduler.materialize_due(
            now=self.fixture.now,
            call=self.fixture.service_call("materialize"),
        )
        with sqlite3.connect(self.path) as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            connection.execute(
                "UPDATE schedule_slots SET state = ?",
                (ScheduleOccurrenceState.EMITTED.value,),
            )
        self.assertEqual(mode.lower(), SchedulerJournalMode.DELETE.value)
        with self.assertRaises(DududaError):
            await self.store.load_schedule_record(
                self.fixture.subscription.subscription_id,
                self.fixture.now.date(),
                call=self.fixture.service_call("tampered-load"),
            )


if __name__ == "__main__":
    unittest.main()
