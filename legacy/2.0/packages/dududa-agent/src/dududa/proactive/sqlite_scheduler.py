from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dududa._compat import StrEnum
from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import DigestString, require_aware
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext

from .contracts import (
    ProactiveSubscription,
    ProactiveTrigger,
    ProactiveTriggerKind,
    ScheduleAckDisposition,
    ScheduleClaimDisposition,
    ScheduleClaimReceipt,
    ScheduleLedgerRecord,
    ScheduleMaterializationReceipt,
    ScheduleOccurrenceState,
    ScheduleTriggerClaim,
    SubscriptionMutationDisposition,
    SubscriptionMutationReceipt,
    SubscriptionStatus,
)
from .scheduler_codec import (
    decode_claim_receipt,
    decode_materialization_receipt,
    decode_mutation_receipt,
    decode_schedule_record,
    decode_subscription,
    encode_claim_receipt,
    encode_materialization_receipt,
    encode_mutation_receipt,
    encode_schedule_record,
    encode_subscription,
)


class SchedulerJournalMode(StrEnum):
    DELETE = "delete"
    WAL = "wal"


@dataclass(frozen=True, slots=True)
class SQLiteSchedulerStoreConfig:
    schema_version: int
    path: Path
    busy_timeout: timedelta
    maximum_subscriptions: int
    maximum_slots: int
    terminal_retention: timedelta
    journal_mode: SchedulerJournalMode = SchedulerJournalMode.DELETE

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        path = Path(self.path)
        if not str(path).strip() or str(path) == ":memory:":
            raise validation_error("invalid_scheduler_store_path")
        for field_name in ("busy_timeout", "terminal_retention"):
            value = getattr(self, field_name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise validation_error("invalid_scheduler_store_duration", field_name)
        for field_name in ("maximum_subscriptions", "maximum_slots"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 1:
                raise validation_error("invalid_scheduler_store_capacity", field_name)
        if not isinstance(self.journal_mode, SchedulerJournalMode):
            raise validation_error("invalid_scheduler_journal_mode")
        object.__setattr__(self, "path", path)


class SQLiteProactiveSchedulerStore:
    """SQLite authority for subscription revisions and schedule leases."""

    def __init__(
        self,
        config: SQLiteSchedulerStoreConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(config, SQLiteSchedulerStoreConfig):
            raise TypeError("invalid SQLite scheduler store config")
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        config.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def config(self) -> SQLiteSchedulerStoreConfig:
        return self._config

    async def publish(
        self,
        subscription: ProactiveSubscription,
        *,
        expected_revision: int | None,
        mutation_id: str,
        call: ServiceCallContext,
    ) -> SubscriptionMutationReceipt:
        if not isinstance(subscription, ProactiveSubscription):
            raise validation_error("invalid_scheduler_subscription")
        _identifier(mutation_id, "subscription_mutation_id")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise validation_error("invalid_expected_subscription_revision")
        now = self._now()
        _validate_call(call, now)
        request_digest = canonical_digest(
            {
                "mutation_id": mutation_id,
                "expected_revision": expected_revision,
                "subscription_digest": subscription.subscription_digest,
            },
            domain="proactive:subscription-mutation-request:v1",
        )

        with self._transaction() as connection:
            replay = connection.execute(
                "SELECT * FROM subscription_mutations WHERE mutation_id = ?",
                (mutation_id,),
            ).fetchone()
            if replay is not None:
                if replay["request_digest"] != str(request_digest):
                    raise _conflict("subscription_mutation_id_conflict")
                return _mutation_receipt_from_row(replay)

            current_row = connection.execute(
                "SELECT * FROM proactive_subscriptions WHERE subscription_id = ?",
                (subscription.subscription_id,),
            ).fetchone()
            if current_row is None:
                if expected_revision is not None or subscription.revision != 1:
                    raise _conflict("subscription_create_revision_conflict")
                if subscription.status is SubscriptionStatus.REVOKED:
                    raise _conflict("subscription_cannot_start_revoked")
                count = connection.execute(
                    "SELECT COUNT(*) FROM proactive_subscriptions"
                ).fetchone()[0]
                if count >= self._config.maximum_subscriptions:
                    raise _conflict("scheduler_subscription_capacity_exhausted")
                previous_revision = None
                disposition = SubscriptionMutationDisposition.CREATED
            else:
                current = _subscription_from_row(current_row)
                if (
                    expected_revision != current.revision
                    or subscription.revision != current.revision + 1
                ):
                    raise _conflict("subscription_revision_cas_conflict")
                if current.status is SubscriptionStatus.REVOKED:
                    raise _conflict("revoked_subscription_is_terminal")
                if (
                    subscription.created_at != current.created_at
                    or subscription.owner_ref != current.owner_ref
                    or subscription.target_scope != current.target_scope
                    or subscription.updated_at < current.updated_at
                ):
                    raise _conflict("subscription_identity_or_time_conflict")
                previous_revision = current.revision
                disposition = SubscriptionMutationDisposition.UPDATED

            receipt = SubscriptionMutationReceipt(
                schema_version=1,
                mutation_id=mutation_id,
                subscription_id=subscription.subscription_id,
                previous_revision=previous_revision,
                applied_revision=subscription.revision,
                subscription_digest=subscription.subscription_digest,
                status=subscription.status,
                disposition=disposition,
                recorded_at=now,
            )
            payload = encode_subscription(subscription)
            connection.execute(
                """
                INSERT INTO proactive_subscriptions (
                    subscription_id, revision, status, subscription_digest,
                    payload_json, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(subscription_id) DO UPDATE SET
                    revision = excluded.revision,
                    status = excluded.status,
                    subscription_digest = excluded.subscription_digest,
                    payload_json = excluded.payload_json,
                    updated_at_us = excluded.updated_at_us
                """,
                (
                    subscription.subscription_id,
                    subscription.revision,
                    subscription.status.value,
                    str(subscription.subscription_digest),
                    payload,
                    _to_micros(now),
                ),
            )
            if previous_revision is not None:
                self._invalidate_pending(
                    connection,
                    subscription.subscription_id,
                    previous_revision,
                    now,
                )
            connection.execute(
                """
                INSERT INTO subscription_mutations (
                    mutation_id, subscription_id, request_digest, receipt_digest,
                    receipt_json, recorded_at_us
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mutation_id,
                    subscription.subscription_id,
                    str(request_digest),
                    str(receipt.receipt_digest),
                    encode_mutation_receipt(receipt),
                    _to_micros(now),
                ),
            )
            return receipt

    async def load(
        self,
        subscription_id: str,
        *,
        call: ServiceCallContext,
    ) -> ProactiveSubscription | None:
        _identifier(subscription_id, "subscription_id")
        now = self._now()
        _validate_call(call, now)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM proactive_subscriptions WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchone()
            return _subscription_from_row(row) if row is not None else None

    async def list_active(
        self,
        *,
        call: ServiceCallContext,
    ) -> tuple[ProactiveSubscription, ...]:
        now = self._now()
        _validate_call(call, now)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM proactive_subscriptions WHERE status = ? "
                "ORDER BY subscription_id",
                (SubscriptionStatus.ACTIVE.value,),
            ).fetchall()
            return tuple(_subscription_from_row(row) for row in rows)

    async def record_trigger(
        self,
        trigger: ProactiveTrigger,
        state: ScheduleOccurrenceState,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ScheduleMaterializationReceipt:
        now = _utc(at, "schedule_materialization_at")
        _validate_call(call, now)
        if (
            not isinstance(trigger, ProactiveTrigger)
            or trigger.kind is not ProactiveTriggerKind.SCHEDULED_DIGEST
            or trigger.occurrence is None
        ):
            raise validation_error("invalid_scheduler_trigger")
        if state not in {
            ScheduleOccurrenceState.READY,
            ScheduleOccurrenceState.SKIPPED_EXPIRED,
        }:
            raise validation_error("invalid_materialization_state")
        occurrence = trigger.occurrence
        expected_state = (
            ScheduleOccurrenceState.READY
            if occurrence.scheduled_for <= now <= occurrence.eligible_until
            else ScheduleOccurrenceState.SKIPPED_EXPIRED
            if now > occurrence.eligible_until
            else None
        )
        if state is not expected_state:
            raise validation_error("materialization_time_state_mismatch")

        with self._transaction() as connection:
            current = self._require_active_subscription(
                connection,
                occurrence.subscription_id,
                occurrence.subscription_revision,
            )
            if (
                trigger.target_scope != current.target_scope
                or trigger.target_policy_ref != current.target_policy_ref
            ):
                raise _conflict("schedule_trigger_subscription_mismatch")
            existing = self._select_slot(
                connection,
                occurrence.subscription_id,
                occurrence.local_date,
            )
            if existing is not None:
                return _replay_materialization(existing, now)
            self._require_slot_capacity(connection)
            record = ScheduleLedgerRecord(
                schema_version=1,
                subscription_id=occurrence.subscription_id,
                subscription_revision=occurrence.subscription_revision,
                local_date=occurrence.local_date,
                state=state,
                revision=1,
                trigger=trigger,
                claim=None,
                updated_at=now,
            )
            receipt = ScheduleMaterializationReceipt(
                schema_version=1,
                subscription_id=occurrence.subscription_id,
                subscription_revision=occurrence.subscription_revision,
                local_date=occurrence.local_date,
                state=state,
                occurrence_digest=occurrence.occurrence_digest,
                trigger_digest=trigger.trigger_digest,
                created=True,
                record_revision=1,
                recorded_at=now,
            )
            self._insert_slot(connection, record, receipt)
            return receipt

    async def record_nonexistent(
        self,
        subscription: ProactiveSubscription,
        local_date: date,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ScheduleMaterializationReceipt:
        if not isinstance(subscription, ProactiveSubscription):
            raise validation_error("invalid_scheduler_subscription")
        if not isinstance(local_date, date) or isinstance(local_date, datetime):
            raise validation_error("invalid_schedule_local_date")
        now = _utc(at, "schedule_materialization_at")
        _validate_call(call, now)
        with self._transaction() as connection:
            current = self._require_active_subscription(
                connection,
                subscription.subscription_id,
                subscription.revision,
            )
            if current.subscription_digest != subscription.subscription_digest:
                raise _conflict("subscription_snapshot_conflict")
            existing = self._select_slot(
                connection,
                subscription.subscription_id,
                local_date,
            )
            if existing is not None:
                return _replay_materialization(existing, now)
            self._require_slot_capacity(connection)
            record = ScheduleLedgerRecord(
                schema_version=1,
                subscription_id=subscription.subscription_id,
                subscription_revision=subscription.revision,
                local_date=local_date,
                state=ScheduleOccurrenceState.SKIPPED_NONEXISTENT,
                revision=1,
                trigger=None,
                claim=None,
                updated_at=now,
            )
            receipt = ScheduleMaterializationReceipt(
                schema_version=1,
                subscription_id=subscription.subscription_id,
                subscription_revision=subscription.revision,
                local_date=local_date,
                state=ScheduleOccurrenceState.SKIPPED_NONEXISTENT,
                occurrence_digest=None,
                trigger_digest=None,
                created=True,
                record_revision=1,
                recorded_at=now,
            )
            self._insert_slot(connection, record, receipt)
            return receipt

    async def list_due(
        self,
        *,
        at: datetime,
        limit: int,
        call: ServiceCallContext,
    ) -> tuple[ScheduleLedgerRecord, ...]:
        now = _utc(at, "schedule_list_due_at")
        _validate_call(call, now)
        _limit(limit)
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM schedule_slots
                WHERE state IN (?, ?) AND scheduled_for_us <= ?
                ORDER BY scheduled_for_us, subscription_id, local_date
                """,
                (
                    ScheduleOccurrenceState.READY.value,
                    ScheduleOccurrenceState.CLAIMED.value,
                    _to_micros(now),
                ),
            ).fetchall()
            due: list[ScheduleLedgerRecord] = []
            for row in rows:
                record = _schedule_record_from_row(row)
                assert record.trigger is not None
                if now > record.trigger.expires_at:
                    record = self._replace_record(
                        connection,
                        record,
                        state=ScheduleOccurrenceState.SKIPPED_EXPIRED,
                        claim=None,
                        at=now,
                    )
                    continue
                due.append(record)
                if len(due) >= limit:
                    break
            return tuple(due)

    async def claim(
        self,
        occurrence_digest: DigestString,
        *,
        worker_id: str,
        ttl: timedelta,
        at: datetime,
        call: ServiceCallContext,
    ) -> tuple[ScheduleTriggerClaim, ScheduleClaimDisposition]:
        _digest(occurrence_digest, "occurrence_digest")
        _identifier(worker_id, "schedule_worker_id")
        if not isinstance(ttl, timedelta) or not (
            timedelta(0) < ttl <= timedelta(days=1)
        ):
            raise validation_error("invalid_schedule_claim_ttl")
        now = _utc(at, "schedule_claim_at")
        _validate_call(call, now)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM schedule_slots WHERE occurrence_digest = ?",
                (str(occurrence_digest),),
            ).fetchone()
            if row is None:
                raise _conflict("schedule_occurrence_not_found")
            record = _schedule_record_from_row(row)
            if record.state not in {
                ScheduleOccurrenceState.READY,
                ScheduleOccurrenceState.CLAIMED,
            }:
                raise _conflict("schedule_occurrence_not_claimable")
            current = self._load_subscription_required(
                connection, record.subscription_id
            )
            if (
                current.status is not SubscriptionStatus.ACTIVE
                or current.revision != record.subscription_revision
            ):
                self._replace_record(
                    connection,
                    record,
                    state=ScheduleOccurrenceState.INVALIDATED,
                    claim=None,
                    at=now,
                )
                raise _conflict("schedule_subscription_not_current")
            assert record.trigger is not None
            occurrence = record.trigger.occurrence
            assert occurrence is not None
            if now < occurrence.scheduled_for:
                raise _conflict("schedule_occurrence_not_due")
            if now >= record.trigger.expires_at:
                self._replace_record(
                    connection,
                    record,
                    state=ScheduleOccurrenceState.SKIPPED_EXPIRED,
                    claim=None,
                    at=now,
                )
                raise _conflict("schedule_occurrence_expired")

            if record.state is ScheduleOccurrenceState.CLAIMED:
                assert record.claim is not None
                if now < record.claim.expires_at:
                    if record.claim.worker_id == worker_id:
                        return record.claim, ScheduleClaimDisposition.EXISTING
                    raise _conflict("schedule_claim_lease_active")
                lease_revision = record.claim.lease_revision + 1
                disposition = ScheduleClaimDisposition.RECLAIMED
            else:
                lease_revision = 1
                disposition = ScheduleClaimDisposition.ACQUIRED

            expires_at = min(now + ttl, record.trigger.expires_at)
            if expires_at <= now:
                raise _conflict("schedule_claim_window_closed")
            claim = ScheduleTriggerClaim(
                schema_version=1,
                claim_id=_stable_id(
                    "claim",
                    {
                        "occurrence_digest": occurrence_digest,
                        "worker_id": worker_id,
                        "lease_revision": lease_revision,
                    },
                    domain="proactive:schedule-claim-id:v1",
                ),
                trigger=record.trigger,
                worker_id=worker_id,
                lease_revision=lease_revision,
                claimed_at=now,
                expires_at=expires_at,
            )
            self._replace_record(
                connection,
                record,
                state=ScheduleOccurrenceState.CLAIMED,
                claim=claim,
                at=now,
            )
            return claim, disposition

    async def acknowledge(
        self,
        claim: ScheduleTriggerClaim,
        *,
        at: datetime,
        call: ServiceCallContext,
    ) -> ScheduleClaimReceipt:
        if not isinstance(claim, ScheduleTriggerClaim):
            raise validation_error("invalid_schedule_claim")
        now = _utc(at, "schedule_ack_at")
        _validate_call(call, now)
        occurrence = claim.trigger.occurrence
        assert occurrence is not None
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM schedule_slots WHERE occurrence_digest = ?",
                (str(occurrence.occurrence_digest),),
            ).fetchone()
            if row is None:
                raise _conflict("schedule_occurrence_not_found")
            record = _schedule_record_from_row(row)
            if record.state is ScheduleOccurrenceState.EMITTED:
                if record.claim != claim or row["ack_receipt_json"] is None:
                    raise _conflict("schedule_ack_claim_conflict")
                persisted = decode_claim_receipt(row["ack_receipt_json"])
                return ScheduleClaimReceipt(
                    schema_version=1,
                    claim_digest=claim.claim_digest,
                    occurrence_digest=occurrence.occurrence_digest,
                    disposition=ScheduleAckDisposition.EXISTING,
                    state=ScheduleOccurrenceState.EMITTED,
                    record_revision=record.revision,
                    completed_at=persisted.completed_at,
                )
            if record.state is not ScheduleOccurrenceState.CLAIMED:
                raise _conflict("schedule_occurrence_not_acknowledgeable")
            if record.claim != claim:
                raise _conflict("schedule_ack_claim_conflict")
            if now >= claim.expires_at:
                raise _conflict("schedule_ack_lease_expired")
            current = self._load_subscription_required(
                connection, record.subscription_id
            )
            if (
                current.status is not SubscriptionStatus.ACTIVE
                or current.revision != record.subscription_revision
            ):
                self._replace_record(
                    connection,
                    record,
                    state=ScheduleOccurrenceState.INVALIDATED,
                    claim=None,
                    at=now,
                )
                raise _conflict("schedule_subscription_not_current")
            next_revision = record.revision + 1
            receipt = ScheduleClaimReceipt(
                schema_version=1,
                claim_digest=claim.claim_digest,
                occurrence_digest=occurrence.occurrence_digest,
                disposition=ScheduleAckDisposition.EMITTED,
                state=ScheduleOccurrenceState.EMITTED,
                record_revision=next_revision,
                completed_at=now,
            )
            self._replace_record(
                connection,
                record,
                state=ScheduleOccurrenceState.EMITTED,
                claim=claim,
                at=now,
                ack_receipt=receipt,
            )
            return receipt

    async def load_schedule_record(
        self,
        subscription_id: str,
        local_date: date,
        *,
        call: ServiceCallContext,
    ) -> ScheduleLedgerRecord | None:
        _identifier(subscription_id, "subscription_id")
        if not isinstance(local_date, date) or isinstance(local_date, datetime):
            raise validation_error("invalid_schedule_local_date")
        now = self._now()
        _validate_call(call, now)
        with self._connect() as connection:
            row = self._select_slot(connection, subscription_id, local_date)
            return _schedule_record_from_row(row) if row is not None else None

    def _invalidate_pending(
        self,
        connection: sqlite3.Connection,
        subscription_id: str,
        previous_revision: int,
        now: datetime,
    ) -> None:
        rows = connection.execute(
            """
            SELECT * FROM schedule_slots
            WHERE subscription_id = ? AND subscription_revision = ?
                AND state IN (?, ?)
            """,
            (
                subscription_id,
                previous_revision,
                ScheduleOccurrenceState.READY.value,
                ScheduleOccurrenceState.CLAIMED.value,
            ),
        ).fetchall()
        for row in rows:
            self._replace_record(
                connection,
                _schedule_record_from_row(row),
                state=ScheduleOccurrenceState.INVALIDATED,
                claim=None,
                at=now,
            )

    def _require_active_subscription(
        self,
        connection: sqlite3.Connection,
        subscription_id: str,
        revision: int,
    ) -> ProactiveSubscription:
        current = self._load_subscription_required(connection, subscription_id)
        if (
            current.status is not SubscriptionStatus.ACTIVE
            or current.revision != revision
        ):
            raise _conflict("schedule_subscription_not_current")
        return current

    @staticmethod
    def _load_subscription_required(
        connection: sqlite3.Connection,
        subscription_id: str,
    ) -> ProactiveSubscription:
        row = connection.execute(
            "SELECT * FROM proactive_subscriptions WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        if row is None:
            raise _conflict("schedule_subscription_not_found")
        return _subscription_from_row(row)

    def _require_slot_capacity(self, connection: sqlite3.Connection) -> None:
        count = connection.execute("SELECT COUNT(*) FROM schedule_slots").fetchone()[0]
        if count >= self._config.maximum_slots:
            raise _conflict("scheduler_slot_capacity_exhausted")

    @staticmethod
    def _select_slot(
        connection: sqlite3.Connection,
        subscription_id: str,
        local_date: date,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM schedule_slots WHERE subscription_id = ? AND local_date = ?",
            (subscription_id, local_date.isoformat()),
        ).fetchone()

    @staticmethod
    def _insert_slot(
        connection: sqlite3.Connection,
        record: ScheduleLedgerRecord,
        receipt: ScheduleMaterializationReceipt,
    ) -> None:
        scheduled_for_us, eligible_until_us, occurrence_digest, trigger_digest = (
            _record_index_values(record)
        )
        connection.execute(
            """
            INSERT INTO schedule_slots (
                subscription_id, local_date, subscription_revision, state,
                record_revision, scheduled_for_us, eligible_until_us,
                occurrence_digest, trigger_digest, claim_digest, record_digest,
                record_json, materialization_receipt_json, ack_receipt_json,
                updated_at_us
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?)
            """,
            (
                record.subscription_id,
                record.local_date.isoformat(),
                record.subscription_revision,
                record.state.value,
                record.revision,
                scheduled_for_us,
                eligible_until_us,
                occurrence_digest,
                trigger_digest,
                str(record.record_digest),
                encode_schedule_record(record),
                encode_materialization_receipt(receipt),
                _to_micros(record.updated_at),
            ),
        )

    @staticmethod
    def _replace_record(
        connection: sqlite3.Connection,
        record: ScheduleLedgerRecord,
        *,
        state: ScheduleOccurrenceState,
        claim: ScheduleTriggerClaim | None,
        at: datetime,
        ack_receipt: ScheduleClaimReceipt | None = None,
    ) -> ScheduleLedgerRecord:
        updated = ScheduleLedgerRecord(
            schema_version=1,
            subscription_id=record.subscription_id,
            subscription_revision=record.subscription_revision,
            local_date=record.local_date,
            state=state,
            revision=record.revision + 1,
            trigger=record.trigger,
            claim=claim,
            updated_at=at,
        )
        cursor = connection.execute(
            """
            UPDATE schedule_slots SET
                state = ?, record_revision = ?, claim_digest = ?, record_digest = ?,
                record_json = ?, ack_receipt_json = COALESCE(?, ack_receipt_json),
                updated_at_us = ?
            WHERE subscription_id = ? AND local_date = ? AND record_revision = ?
            """,
            (
                updated.state.value,
                updated.revision,
                str(claim.claim_digest) if claim is not None else None,
                str(updated.record_digest),
                encode_schedule_record(updated),
                (
                    encode_claim_receipt(ack_receipt)
                    if ack_receipt is not None
                    else None
                ),
                _to_micros(at),
                record.subscription_id,
                record.local_date.isoformat(),
                record.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise _conflict("schedule_record_cas_conflict")
        return updated

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO scheduler_metadata (key, value) "
                "VALUES ('schema_version', '1')"
            )
            schema_version = connection.execute(
                "SELECT value FROM scheduler_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if schema_version is None or schema_version["value"] != "1":
                raise validation_error("unsupported_scheduler_store_schema")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS proactive_subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    status TEXT NOT NULL,
                    subscription_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at_us INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS subscription_mutations (
                    mutation_id TEXT PRIMARY KEY,
                    subscription_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    recorded_at_us INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_slots (
                    subscription_id TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    subscription_revision INTEGER NOT NULL CHECK (
                        subscription_revision >= 1
                    ),
                    state TEXT NOT NULL,
                    record_revision INTEGER NOT NULL CHECK (record_revision >= 1),
                    scheduled_for_us INTEGER,
                    eligible_until_us INTEGER,
                    occurrence_digest TEXT,
                    trigger_digest TEXT,
                    claim_digest TEXT,
                    record_digest TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    materialization_receipt_json TEXT NOT NULL,
                    ack_receipt_json TEXT,
                    updated_at_us INTEGER NOT NULL,
                    PRIMARY KEY (subscription_id, local_date),
                    CHECK ((scheduled_for_us IS NULL) = (eligible_until_us IS NULL)),
                    CHECK ((occurrence_digest IS NULL) = (trigger_digest IS NULL))
                )
                """
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS schedule_occurrence_unique "
                "ON schedule_slots(occurrence_digest) "
                "WHERE occurrence_digest IS NOT NULL"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS schedule_trigger_unique "
                "ON schedule_slots(trigger_digest) WHERE trigger_digest IS NOT NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS schedule_due_index "
                "ON schedule_slots(state, scheduled_for_us, eligible_until_us)"
            )
        try:
            os.chmod(self._config.path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        timeout = self._config.busy_timeout.total_seconds()
        connection = sqlite3.connect(
            self._config.path,
            timeout=timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute(f"PRAGMA busy_timeout = {max(1, int(timeout * 1000))}")
            if self._config.journal_mode is SchedulerJournalMode.WAL:
                runtime_version = _connection_sqlite_version(connection)
                if runtime_version < (3, 51, 3):
                    raise validation_error(
                        "unsafe_sqlite_wal_version",
                        ".".join(str(value) for value in runtime_version),
                    )
            effective_mode = str(
                connection.execute(
                    f"PRAGMA journal_mode = {self._config.journal_mode.value}"
                ).fetchone()[0]
            ).lower()
            if effective_mode != self._config.journal_mode.value:
                raise validation_error(
                    "sqlite_journal_mode_mismatch",
                    self._config.journal_mode.value,
                    effective_mode,
                )
            connection.execute("PRAGMA synchronous = FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    def _transaction(self) -> _SQLiteTransaction:
        return _SQLiteTransaction(self)

    def _now(self) -> datetime:
        return _utc(self._clock(), "scheduler_store_now")


class _SQLiteTransaction:
    def __init__(self, store: SQLiteProactiveSchedulerStore) -> None:
        self._store = store
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._store._lock.acquire()
        try:
            self._connection = self._store._connect()
            self._connection.execute("BEGIN IMMEDIATE")
            return self._connection
        except BaseException:
            self._store._lock.release()
            raise

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        assert self._connection is not None
        try:
            if exc_type is None:
                self._connection.execute("COMMIT")
            else:
                self._connection.execute("ROLLBACK")
        finally:
            self._connection.close()
            self._store._lock.release()


def _subscription_from_row(row: sqlite3.Row) -> ProactiveSubscription:
    subscription = decode_subscription(row["payload_json"])
    if (
        subscription.subscription_id != row["subscription_id"]
        or subscription.revision != row["revision"]
        or subscription.status.value != row["status"]
        or str(subscription.subscription_digest) != row["subscription_digest"]
    ):
        raise validation_error("scheduler_subscription_row_mismatch")
    return subscription


def _mutation_receipt_from_row(row: sqlite3.Row) -> SubscriptionMutationReceipt:
    receipt = decode_mutation_receipt(row["receipt_json"])
    if (
        receipt.mutation_id != row["mutation_id"]
        or receipt.subscription_id != row["subscription_id"]
        or str(receipt.receipt_digest) != row["receipt_digest"]
        or _to_micros(receipt.recorded_at) != row["recorded_at_us"]
    ):
        raise validation_error("scheduler_mutation_row_mismatch")
    return receipt


def _schedule_record_from_row(row: sqlite3.Row) -> ScheduleLedgerRecord:
    record = decode_schedule_record(row["record_json"])
    scheduled_for_us, eligible_until_us, occurrence_digest, trigger_digest = (
        _record_index_values(record)
    )
    if (
        record.subscription_id != row["subscription_id"]
        or record.local_date.isoformat() != row["local_date"]
        or record.subscription_revision != row["subscription_revision"]
        or record.state.value != row["state"]
        or record.revision != row["record_revision"]
        or scheduled_for_us != row["scheduled_for_us"]
        or eligible_until_us != row["eligible_until_us"]
        or occurrence_digest != row["occurrence_digest"]
        or trigger_digest != row["trigger_digest"]
        or str(record.record_digest) != row["record_digest"]
        or (str(record.claim.claim_digest) if record.claim else None)
        != row["claim_digest"]
    ):
        raise validation_error("scheduler_slot_row_mismatch")
    return record


def _record_index_values(
    record: ScheduleLedgerRecord,
) -> tuple[int | None, int | None, str | None, str | None]:
    if record.trigger is None:
        return None, None, None, None
    occurrence = record.trigger.occurrence
    assert occurrence is not None
    return (
        _to_micros(occurrence.scheduled_for),
        _to_micros(occurrence.eligible_until),
        str(occurrence.occurrence_digest),
        str(record.trigger.trigger_digest),
    )


def _replay_materialization(
    row: sqlite3.Row,
    now: datetime,
) -> ScheduleMaterializationReceipt:
    record = _schedule_record_from_row(row)
    original = decode_materialization_receipt(row["materialization_receipt_json"])
    if (
        original.subscription_id != record.subscription_id
        or original.subscription_revision != record.subscription_revision
        or original.local_date != record.local_date
        or (
            record.trigger is None
            and (
                original.occurrence_digest is not None
                or original.trigger_digest is not None
            )
        )
        or (
            record.trigger is not None
            and (
                original.occurrence_digest
                != record.trigger.occurrence.occurrence_digest
                or original.trigger_digest != record.trigger.trigger_digest
            )
        )
    ):
        raise validation_error("scheduler_materialization_row_mismatch")
    return replace(
        original,
        created=False,
        record_revision=record.revision,
        recorded_at=now,
        receipt_digest="",
    )


def _connection_sqlite_version(
    connection: sqlite3.Connection,
) -> tuple[int, int, int]:
    row = connection.execute("SELECT sqlite_version()").fetchone()
    raw = row[0] if row is not None and len(row) == 1 else None
    if not isinstance(raw, str):
        raise TypeError("invalid SQLite runtime version")
    parts = raw.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError("invalid SQLite runtime version")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _to_micros(value: datetime) -> int:
    value = _utc(value, "scheduler_timestamp")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value - epoch
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise validation_error("invalid_scheduler_datetime", field_name)
    require_aware(value, field_name)
    return value.astimezone(timezone.utc)


def _validate_call(call: ServiceCallContext, now: datetime) -> None:
    if not isinstance(call, ServiceCallContext):
        raise validation_error("invalid_proactive_service_call")
    if call.cancellation.is_cancelled:
        raise error(
            "proactive_call_cancelled",
            ErrorCategory.CANCELLED,
            "request.cancelled",
        )
    if call.deadline <= now:
        raise error(
            "proactive_call_deadline_exceeded",
            ErrorCategory.TIMEOUT,
            "request.timeout",
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise validation_error("invalid_scheduler_identifier", field_name)
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("invalid_scheduler_digest", field_name)
    return value


def _limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1000:
        raise validation_error("invalid_scheduler_limit")
    return value


def _stable_id(prefix: str, value: object, *, domain: str) -> str:
    digest = str(canonical_digest(value, domain=domain))
    return f"{prefix}-{digest.rsplit(':', 1)[-1]}"


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "request.conflict")


__all__ = [
    "SQLiteProactiveSchedulerStore",
    "SQLiteSchedulerStoreConfig",
    "SchedulerJournalMode",
]
