from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import threading

from dududa.domain.delivery import DeliveryReceipt, DeliveryStatus
from dududa.domain.primitives import ComponentRevision, DigestString, require_aware
from dududa.errors import ErrorCategory, error, validation_error

from .contracts import (
    RolloutClaimDisposition,
    RolloutClaimResult,
    RolloutOwnershipRecord,
    RolloutOwnershipState,
)


@dataclass(frozen=True, slots=True)
class SQLiteRolloutLedgerConfig:
    schema_version: int
    path: Path
    busy_timeout: timedelta
    terminal_ttl: timedelta
    maximum_records: int
    component_revision: ComponentRevision

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        path = Path(self.path)
        if not str(path).strip() or str(path) == ":memory:":
            raise validation_error("invalid_rollout_ledger_path")
        for field_name in ("busy_timeout", "terminal_ttl"):
            value = getattr(self, field_name)
            if not isinstance(value, timedelta) or value <= timedelta(0):
                raise validation_error("invalid_rollout_ledger_duration", field_name)
        if type(self.maximum_records) is not int or self.maximum_records < 1:
            raise validation_error("invalid_rollout_ledger_capacity")
        if not isinstance(self.component_revision, ComponentRevision):
            raise validation_error("invalid_rollout_ledger_revision")
        object.__setattr__(self, "path", path)


class SQLiteRolloutLedger:
    def __init__(
        self,
        config: SQLiteRolloutLedgerConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(config, SQLiteRolloutLedgerConfig):
            raise TypeError("invalid SQLite rollout ledger config")
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        config.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def config(self) -> SQLiteRolloutLedgerConfig:
        return self._config

    def claim(
        self,
        message_key_digest: DigestString,
        invocation_digest: DigestString,
        control_revision: str,
    ) -> RolloutClaimResult:
        _non_empty_digest(message_key_digest, "rollout_message_key_digest")
        _non_empty_digest(invocation_digest, "rollout_invocation_digest")
        if not isinstance(control_revision, str) or not control_revision.strip():
            raise validation_error("invalid_rollout_revision")
        now = self._now()
        with self._transaction() as connection:
            existing = self._select(connection, str(message_key_digest))
            if existing is not None:
                disposition = (
                    RolloutClaimDisposition.EXISTING
                    if existing.invocation_digest == invocation_digest
                    else RolloutClaimDisposition.CONFLICT
                )
                return RolloutClaimResult(1, disposition, existing)
            self._collect_expired(connection, now)
            count = connection.execute(
                "SELECT COUNT(*) FROM rollout_ownership"
            ).fetchone()[0]
            if count >= self._config.maximum_records:
                raise _ledger_error("rollout_ledger_capacity_exhausted")
            timestamp = _to_micros(now)
            connection.execute(
                """
                INSERT INTO rollout_ownership (
                    message_key_digest, invocation_digest, control_revision, state,
                    revision, delivery_id, delivery_request_digest, delivery_status,
                    reason_code, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, 1, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (
                    str(message_key_digest),
                    str(invocation_digest),
                    control_revision,
                    RolloutOwnershipState.CLAIMED.value,
                    timestamp,
                    timestamp,
                ),
            )
            record = self._select_required(connection, str(message_key_digest))
            return RolloutClaimResult(1, RolloutClaimDisposition.ACQUIRED, record)

    def load(self, message_key_digest: DigestString) -> RolloutOwnershipRecord | None:
        _non_empty_digest(message_key_digest, "rollout_message_key_digest")
        with self._connect() as connection:
            return self._select(connection, str(message_key_digest))

    def mark_runtime_started(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
    ) -> RolloutOwnershipRecord:
        return self._transition(
            message_key_digest,
            expected_revision,
            RolloutOwnershipState.CLAIMED,
            RolloutOwnershipState.RUNTIME_STARTED,
        )

    def mark_ready_to_send(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        delivery_id: str,
        delivery_request_digest: DigestString,
    ) -> RolloutOwnershipRecord:
        if not isinstance(delivery_id, str) or not delivery_id.strip():
            raise validation_error("invalid_rollout_delivery_id")
        _non_empty_digest(delivery_request_digest, "rollout_delivery_request_digest")
        return self._transition(
            message_key_digest,
            expected_revision,
            RolloutOwnershipState.RUNTIME_STARTED,
            RolloutOwnershipState.READY_TO_SEND,
            delivery_id=delivery_id,
            delivery_request_digest=delivery_request_digest,
        )

    def begin_delivery(
        self,
        message_key_digest: DigestString,
        delivery_id: str,
        delivery_request_digest: DigestString,
    ) -> RolloutOwnershipRecord:
        _non_empty_digest(message_key_digest, "rollout_message_key_digest")
        _non_empty_digest(delivery_request_digest, "rollout_delivery_request_digest")
        with self._transaction() as connection:
            record = self._select_required(connection, str(message_key_digest))
            if (
                record.state is not RolloutOwnershipState.READY_TO_SEND
                or record.delivery_id != delivery_id
                or record.delivery_request_digest != delivery_request_digest
            ):
                raise _ledger_error("rollout_delivery_gate_conflict")
            return self._update_state(
                connection,
                record,
                RolloutOwnershipState.SEND_STARTED,
            )

    def finish_delivery(
        self,
        message_key_digest: DigestString,
        receipt: DeliveryReceipt,
    ) -> RolloutOwnershipRecord:
        if not isinstance(receipt, DeliveryReceipt):
            raise validation_error("invalid_rollout_delivery_receipt")
        target = {
            DeliveryStatus.SUCCEEDED: RolloutOwnershipState.SUCCEEDED,
            DeliveryStatus.PARTIAL: RolloutOwnershipState.PARTIAL,
            DeliveryStatus.FAILED: RolloutOwnershipState.FAILED,
            DeliveryStatus.UNKNOWN: RolloutOwnershipState.UNKNOWN,
        }.get(receipt.status)
        if target is None:
            raise validation_error("invalid_rollout_delivery_receipt_status")
        with self._transaction() as connection:
            record = self._select_required(connection, str(message_key_digest))
            if (
                record.state is not RolloutOwnershipState.SEND_STARTED
                or record.delivery_id != receipt.delivery_id
                or record.delivery_request_digest != receipt.delivery_request_digest
            ):
                raise _ledger_error("rollout_delivery_receipt_conflict")
            return self._update_state(
                connection,
                record,
                target,
                delivery_status=receipt.status,
                reason_code=receipt.error_code,
            )

    def mark_no_delivery(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        reason_code: str,
    ) -> RolloutOwnershipRecord:
        return self._transition(
            message_key_digest,
            expected_revision,
            RolloutOwnershipState.RUNTIME_STARTED,
            RolloutOwnershipState.NO_DELIVERY,
            delivery_status=DeliveryStatus.NOT_REQUIRED,
            reason_code=reason_code,
        )

    def mark_suppressed(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        reason_code: str,
    ) -> RolloutOwnershipRecord:
        return self._transition(
            message_key_digest,
            expected_revision,
            RolloutOwnershipState.READY_TO_SEND,
            RolloutOwnershipState.SUPPRESSED,
            reason_code=reason_code,
        )

    def mark_aborted(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        expected_state: RolloutOwnershipState,
        reason_code: str,
    ) -> RolloutOwnershipRecord:
        if expected_state not in {
            RolloutOwnershipState.CLAIMED,
            RolloutOwnershipState.RUNTIME_STARTED,
            RolloutOwnershipState.READY_TO_SEND,
        }:
            raise validation_error("invalid_rollout_abort_state")
        return self._transition(
            message_key_digest,
            expected_revision,
            expected_state,
            RolloutOwnershipState.ABORTED,
            reason_code=reason_code,
        )

    def mark_send_unknown(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        reason_code: str,
    ) -> RolloutOwnershipRecord:
        return self._transition(
            message_key_digest,
            expected_revision,
            RolloutOwnershipState.SEND_STARTED,
            RolloutOwnershipState.UNKNOWN,
            delivery_status=DeliveryStatus.UNKNOWN,
            reason_code=reason_code,
        )

    def recover_incomplete(self) -> tuple[RolloutOwnershipRecord, ...]:
        now = self._now()
        recovered: list[RolloutOwnershipRecord] = []
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM rollout_ownership
                WHERE state IN (?, ?, ?, ?)
                ORDER BY created_at_us, message_key_digest
                """,
                (
                    RolloutOwnershipState.CLAIMED.value,
                    RolloutOwnershipState.RUNTIME_STARTED.value,
                    RolloutOwnershipState.READY_TO_SEND.value,
                    RolloutOwnershipState.SEND_STARTED.value,
                ),
            ).fetchall()
            for row in rows:
                record = _record(row)
                if record.state is RolloutOwnershipState.SEND_STARTED:
                    target = RolloutOwnershipState.UNKNOWN
                    status = DeliveryStatus.UNKNOWN
                    reason = "process_restarted_during_send"
                else:
                    target = RolloutOwnershipState.ABORTED
                    status = None
                    reason = "process_restarted_before_send"
                recovered.append(
                    self._update_state(
                        connection,
                        record,
                        target,
                        delivery_status=status,
                        reason_code=reason,
                        now=now,
                    )
                )
        return tuple(recovered)

    def _transition(
        self,
        message_key_digest: DigestString,
        expected_revision: int,
        expected_state: RolloutOwnershipState,
        target_state: RolloutOwnershipState,
        *,
        delivery_id: str | None = None,
        delivery_request_digest: DigestString | None = None,
        delivery_status: DeliveryStatus | None = None,
        reason_code: str | None = None,
    ) -> RolloutOwnershipRecord:
        _non_empty_digest(message_key_digest, "rollout_message_key_digest")
        if type(expected_revision) is not int or expected_revision < 1:
            raise validation_error("invalid_rollout_ownership_revision")
        with self._transaction() as connection:
            record = self._select_required(connection, str(message_key_digest))
            if (
                record.revision != expected_revision
                or record.state is not expected_state
            ):
                raise _ledger_error("rollout_ownership_cas_conflict")
            return self._update_state(
                connection,
                record,
                target_state,
                delivery_id=delivery_id,
                delivery_request_digest=delivery_request_digest,
                delivery_status=delivery_status,
                reason_code=reason_code,
            )

    def _update_state(
        self,
        connection: sqlite3.Connection,
        record: RolloutOwnershipRecord,
        target_state: RolloutOwnershipState,
        *,
        delivery_id: str | None = None,
        delivery_request_digest: DigestString | None = None,
        delivery_status: DeliveryStatus | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> RolloutOwnershipRecord:
        now = now or self._now()
        next_delivery_id = (
            delivery_id if delivery_id is not None else record.delivery_id
        )
        next_delivery_digest = (
            delivery_request_digest
            if delivery_request_digest is not None
            else record.delivery_request_digest
        )
        try:
            cursor = connection.execute(
                """
                UPDATE rollout_ownership
                SET state = ?, revision = revision + 1, delivery_id = ?,
                    delivery_request_digest = ?, delivery_status = ?, reason_code = ?,
                    updated_at_us = ?
                WHERE message_key_digest = ? AND revision = ? AND state = ?
                """,
                (
                    target_state.value,
                    next_delivery_id,
                    (
                        str(next_delivery_digest)
                        if next_delivery_digest is not None
                        else None
                    ),
                    delivery_status.value if delivery_status is not None else None,
                    reason_code,
                    _to_micros(now),
                    str(record.message_key_digest),
                    record.revision,
                    record.state.value,
                ),
            )
        except sqlite3.IntegrityError:
            raise _ledger_error("rollout_delivery_identity_conflict") from None
        if cursor.rowcount != 1:
            raise _ledger_error("rollout_ownership_cas_conflict")
        return self._select_required(connection, str(record.message_key_digest))

    def _collect_expired(self, connection: sqlite3.Connection, now: datetime) -> None:
        cutoff = _to_micros(now - self._config.terminal_ttl)
        terminals = tuple(
            state.value for state in RolloutOwnershipState if state.is_terminal
        )
        placeholders = ",".join("?" for _ in terminals)
        connection.execute(
            f"DELETE FROM rollout_ownership WHERE state IN ({placeholders}) "
            "AND updated_at_us < ?",
            (*terminals, cutoff),
        )

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rollout_ownership (
                    message_key_digest TEXT PRIMARY KEY,
                    invocation_digest TEXT NOT NULL,
                    control_revision TEXT NOT NULL,
                    state TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    delivery_id TEXT,
                    delivery_request_digest TEXT,
                    delivery_status TEXT,
                    reason_code TEXT,
                    created_at_us INTEGER NOT NULL,
                    updated_at_us INTEGER NOT NULL,
                    CHECK ((delivery_id IS NULL) = (delivery_request_digest IS NULL))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS rollout_ownership_state_updated "
                "ON rollout_ownership(state, updated_at_us)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS rollout_delivery_id_unique "
                "ON rollout_ownership(delivery_id) WHERE delivery_id IS NOT NULL"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS rollout_delivery_request_unique "
                "ON rollout_ownership(delivery_request_digest) "
                "WHERE delivery_request_digest IS NOT NULL"
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
        connection.execute(f"PRAGMA busy_timeout = {max(1, int(timeout * 1000))}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _transaction(self):
        return _SQLiteTransaction(self)

    @staticmethod
    def _select(
        connection: sqlite3.Connection,
        message_key_digest: str,
    ) -> RolloutOwnershipRecord | None:
        row = connection.execute(
            "SELECT * FROM rollout_ownership WHERE message_key_digest = ?",
            (message_key_digest,),
        ).fetchone()
        return _record(row) if row is not None else None

    def _select_required(
        self,
        connection: sqlite3.Connection,
        message_key_digest: str,
    ) -> RolloutOwnershipRecord:
        record = self._select(connection, message_key_digest)
        if record is None:
            raise _ledger_error("rollout_ownership_not_found")
        return record

    def _now(self) -> datetime:
        now = self._clock()
        require_aware(now, "rollout_ledger_now")
        return now.astimezone(timezone.utc)


class _SQLiteTransaction:
    def __init__(self, ledger: SQLiteRolloutLedger) -> None:
        self._ledger = ledger
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._ledger._lock.acquire()
        try:
            self._connection = self._ledger._connect()
            self._connection.execute("BEGIN IMMEDIATE")
            return self._connection
        except BaseException:
            self._ledger._lock.release()
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
            self._ledger._lock.release()


def _record(row: sqlite3.Row) -> RolloutOwnershipRecord:
    delivery_status = row["delivery_status"]
    return RolloutOwnershipRecord(
        schema_version=1,
        message_key_digest=DigestString(row["message_key_digest"]),
        invocation_digest=DigestString(row["invocation_digest"]),
        control_revision=row["control_revision"],
        state=RolloutOwnershipState(row["state"]),
        revision=row["revision"],
        delivery_id=row["delivery_id"],
        delivery_request_digest=(
            DigestString(row["delivery_request_digest"])
            if row["delivery_request_digest"] is not None
            else None
        ),
        delivery_status=(
            DeliveryStatus(delivery_status) if delivery_status is not None else None
        ),
        reason_code=row["reason_code"],
        created_at=_from_micros(row["created_at_us"]),
        updated_at=_from_micros(row["updated_at_us"]),
    )


def _to_micros(value: datetime) -> int:
    require_aware(value, "rollout_timestamp")
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000)


def _from_micros(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000, timezone.utc)


def _non_empty_digest(value: DigestString, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("empty_field", field_name)


def _ledger_error(code: str):
    return error(code, ErrorCategory.CONFLICT, "rollout.ownership_conflict")
