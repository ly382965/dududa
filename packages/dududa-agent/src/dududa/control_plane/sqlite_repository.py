from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dududa.domain.primitives import DigestString, require_aware, require_non_empty
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext

from .codec import (
    decode_assignment,
    decode_preview,
    decode_stored_assignment,
    decode_stored_preview,
    encode_control_plane_value,
)
from .contracts import (
    AssignmentCommitDisposition,
    AssignmentCommitResult,
    GroupControlScope,
    GroupJoinFact,
    GroupOnboardingRecord,
    GroupServiceAssignment,
    GroupServicePreview,
    OnboardingStatus,
    PreviewCommitDisposition,
    PreviewCommitResult,
    StoredAssignmentCommand,
    StoredPreviewCommand,
)


@dataclass(frozen=True, slots=True)
class SQLiteGroupServiceRepositoryConfig:
    schema_version: int
    path: Path
    busy_timeout: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise validation_error("unsupported_schema_version")
        path = Path(self.path)
        if str(path) == ":memory:" or not str(path).strip():
            raise validation_error("invalid_control_plane_database_path")
        if not isinstance(
            self.busy_timeout, timedelta
        ) or self.busy_timeout <= timedelta(0):
            raise validation_error("invalid_control_plane_busy_timeout")
        object.__setattr__(self, "path", path)


class SQLiteGroupServiceRepository:
    def __init__(
        self,
        config: SQLiteGroupServiceRepositoryConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(config, SQLiteGroupServiceRepositoryConfig):
            raise TypeError("invalid SQLite group service repository config")
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        config.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    async def observe_join(
        self,
        fact: GroupJoinFact,
        *,
        call: ServiceCallContext,
    ) -> GroupOnboardingRecord:
        if not isinstance(fact, GroupJoinFact):
            raise validation_error("invalid_group_join_fact")
        self._validate_call(call)
        key = _scope_key(fact.scope)
        with self._transaction(call) as connection:
            event = connection.execute(
                "SELECT platform, bot_id, group_id FROM cp_join_events WHERE event_id = ?",
                (fact.event_id,),
            ).fetchone()
            if event is not None and tuple(event) != key:
                raise _conflict("join_event_scope_conflict")
            existing = self._select_onboarding(connection, fact.scope)
            if existing is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO cp_join_events VALUES (?, ?, ?, ?)",
                    (fact.event_id, *key),
                )
                return existing
            observed_at = _timestamp(fact.observed_at)
            connection.execute(
                """
                INSERT INTO cp_onboarding (
                    platform, bot_id, group_id, status, revision, first_seen_at,
                    updated_at, source_revision, preview_id
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, NULL)
                """,
                (
                    *key,
                    OnboardingStatus.PENDING_PROFILE.value,
                    observed_at,
                    observed_at,
                    fact.source_revision,
                ),
            )
            connection.execute(
                "INSERT INTO cp_join_events VALUES (?, ?, ?, ?)",
                (fact.event_id, *key),
            )
            return self._select_onboarding_required(connection, fact.scope)

    async def get_onboarding(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupOnboardingRecord | None:
        self._validate_call(call)
        with self._connect() as connection:
            return self._select_onboarding(connection, scope)

    async def list_unassigned(
        self,
        platform: str,
        bot_id: str,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupOnboardingRecord, ...]:
        require_non_empty(platform, "platform")
        require_non_empty(bot_id, "bot_id")
        self._validate_call(call)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT o.* FROM cp_onboarding AS o
                LEFT JOIN cp_current_assignments AS a
                  ON a.platform = o.platform AND a.bot_id = o.bot_id
                 AND a.group_id = o.group_id
                WHERE o.platform = ? AND o.bot_id = ? AND a.group_id IS NULL
                ORDER BY o.first_seen_at, o.group_id
                """,
                (platform, bot_id),
            ).fetchall()
            return tuple(_onboarding(row) for row in rows)

    async def get_assignment(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None:
        self._validate_call(call)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM cp_current_assignments
                WHERE platform = ? AND bot_id = ? AND group_id = ?
                """,
                _scope_key(scope),
            ).fetchone()
            return decode_assignment(row["payload"]) if row is not None else None

    async def list_assignments(
        self,
        platform: str,
        bot_id: str,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupServiceAssignment, ...]:
        require_non_empty(platform, "platform")
        require_non_empty(bot_id, "bot_id")
        self._validate_call(call)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM cp_current_assignments
                WHERE platform = ? AND bot_id = ?
                ORDER BY group_id
                """,
                (platform, bot_id),
            ).fetchall()
            return tuple(decode_assignment(row["payload"]) for row in rows)

    async def get_assignment_revision(
        self,
        scope: GroupControlScope,
        assignment_revision: int,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None:
        if type(assignment_revision) is not int or assignment_revision < 1:
            raise validation_error("invalid_assignment_revision")
        self._validate_call(call)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM cp_assignment_history
                WHERE platform = ? AND bot_id = ? AND group_id = ?
                  AND assignment_revision = ?
                """,
                (*_scope_key(scope), assignment_revision),
            ).fetchone()
            return decode_assignment(row["payload"]) if row is not None else None

    async def get_preview(
        self,
        preview_id: str,
        *,
        call: ServiceCallContext,
    ) -> GroupServicePreview | None:
        require_non_empty(preview_id, "preview_id")
        self._validate_call(call)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM cp_previews WHERE preview_id = ?",
                (preview_id,),
            ).fetchone()
            return decode_preview(row["payload"]) if row is not None else None

    async def lookup_preview_command(
        self,
        idempotency_key: str,
        *,
        call: ServiceCallContext,
    ) -> StoredPreviewCommand | None:
        require_non_empty(idempotency_key, "idempotency_key")
        self._validate_call(call)
        with self._connect() as connection:
            return self._select_preview_command(connection, idempotency_key)

    async def commit_preview(
        self,
        *,
        idempotency_key: str,
        request_digest: DigestString,
        expected_onboarding_revision: int,
        expected_assignment_revision: int | None,
        stored: StoredPreviewCommand,
        call: ServiceCallContext,
    ) -> PreviewCommitResult:
        _validate_commit_inputs(
            idempotency_key,
            request_digest,
            expected_onboarding_revision,
            expected_assignment_revision,
        )
        if not isinstance(stored, StoredPreviewCommand):
            raise validation_error("invalid_stored_preview_command")
        if stored.request_digest != request_digest:
            raise validation_error("preview_commit_request_mismatch")
        if stored.receipt.idempotency_key != idempotency_key:
            raise validation_error("preview_commit_idempotency_mismatch")
        self._validate_call(call)
        with self._transaction(call) as connection:
            existing = self._select_preview_command(connection, idempotency_key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise _conflict("control_plane_idempotency_conflict")
                return PreviewCommitResult(
                    1, PreviewCommitDisposition.DUPLICATE, existing
                )
            self._reserve_command_id(
                connection,
                stored.receipt.command_id,
                "preview",
                idempotency_key,
            )
            preview = stored.preview
            onboarding = self._select_onboarding_required(connection, preview.scope)
            if onboarding.revision != expected_onboarding_revision:
                raise _conflict("group_onboarding_revision_conflict")
            if preview.onboarding_revision != expected_onboarding_revision:
                raise validation_error("preview_onboarding_revision_mismatch")
            if preview.assignment_revision != expected_assignment_revision:
                raise validation_error("preview_assignment_revision_mismatch")
            current_revision = self._select_current_revision(connection, preview.scope)
            if current_revision != expected_assignment_revision:
                raise _conflict("group_assignment_revision_conflict")
            try:
                connection.execute(
                    "INSERT INTO cp_previews VALUES (?, ?, ?, ?, ?)",
                    (
                        preview.preview_id,
                        *_scope_key(preview.scope),
                        encode_control_plane_value(preview),
                    ),
                )
                connection.execute(
                    "INSERT INTO cp_preview_commands VALUES (?, ?, ?)",
                    (
                        idempotency_key,
                        str(request_digest),
                        encode_control_plane_value(stored),
                    ),
                )
                self._insert_audit(connection, stored)
            except sqlite3.IntegrityError:
                raise _conflict("preview_or_command_identity_conflict") from None
            cursor = connection.execute(
                """
                UPDATE cp_onboarding
                SET status = ?, revision = revision + 1, updated_at = ?, preview_id = ?
                WHERE platform = ? AND bot_id = ? AND group_id = ? AND revision = ?
                """,
                (
                    OnboardingStatus.PREVIEW_READY.value,
                    _timestamp(preview.created_at),
                    preview.preview_id,
                    *_scope_key(preview.scope),
                    expected_onboarding_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise _conflict("group_onboarding_revision_conflict")
            return PreviewCommitResult(1, PreviewCommitDisposition.CREATED, stored)

    async def lookup_assignment_command(
        self,
        idempotency_key: str,
        *,
        call: ServiceCallContext,
    ) -> StoredAssignmentCommand | None:
        require_non_empty(idempotency_key, "idempotency_key")
        self._validate_call(call)
        with self._connect() as connection:
            return self._select_assignment_command(connection, idempotency_key)

    async def commit_assignment(
        self,
        *,
        idempotency_key: str,
        request_digest: DigestString,
        expected_onboarding_revision: int,
        expected_assignment_revision: int | None,
        stored: StoredAssignmentCommand,
        call: ServiceCallContext,
    ) -> AssignmentCommitResult:
        _validate_commit_inputs(
            idempotency_key,
            request_digest,
            expected_onboarding_revision,
            expected_assignment_revision,
        )
        if not isinstance(stored, StoredAssignmentCommand):
            raise validation_error("invalid_stored_assignment_command")
        if stored.request_digest != request_digest:
            raise validation_error("assignment_commit_request_mismatch")
        if stored.receipt.idempotency_key != idempotency_key:
            raise validation_error("assignment_commit_idempotency_mismatch")
        self._validate_call(call)
        with self._transaction(call) as connection:
            existing = self._select_assignment_command(connection, idempotency_key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise _conflict("control_plane_idempotency_conflict")
                return AssignmentCommitResult(
                    1,
                    AssignmentCommitDisposition.DUPLICATE,
                    existing,
                )
            self._reserve_command_id(
                connection,
                stored.receipt.command_id,
                "assignment",
                idempotency_key,
            )
            assignment = stored.assignment
            onboarding = self._select_onboarding_required(connection, assignment.scope)
            if onboarding.revision != expected_onboarding_revision:
                raise _conflict("group_onboarding_revision_conflict")
            current_revision = self._select_current_revision(
                connection, assignment.scope
            )
            if current_revision != expected_assignment_revision:
                raise _conflict("group_assignment_revision_conflict")
            next_revision = 1 if current_revision is None else current_revision + 1
            if assignment.assignment_revision != next_revision:
                raise validation_error("assignment_revision_not_next")
            if assignment.previous_revision != current_revision:
                raise validation_error("assignment_previous_revision_mismatch")
            if assignment.last_known_good_revision != next_revision:
                lkg = connection.execute(
                    """
                    SELECT 1 FROM cp_assignment_history
                    WHERE platform = ? AND bot_id = ? AND group_id = ?
                      AND assignment_revision = ?
                    """,
                    (
                        *_scope_key(assignment.scope),
                        assignment.last_known_good_revision,
                    ),
                ).fetchone()
                if lkg is None:
                    raise validation_error("assignment_lkg_not_found")
            payload = encode_control_plane_value(assignment)
            try:
                connection.execute(
                    """
                    INSERT INTO cp_assignment_history VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        *_scope_key(assignment.scope),
                        assignment.assignment_revision,
                        payload,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO cp_assignment_commands VALUES (?, ?, ?)
                    """,
                    (
                        idempotency_key,
                        str(request_digest),
                        encode_control_plane_value(stored),
                    ),
                )
                self._insert_audit(connection, stored)
            except sqlite3.IntegrityError:
                raise _conflict("assignment_or_command_identity_conflict") from None
            if current_revision is None:
                connection.execute(
                    "INSERT INTO cp_current_assignments VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        *_scope_key(assignment.scope),
                        assignment.assignment_revision,
                        assignment.last_known_good_revision,
                        payload,
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE cp_current_assignments
                    SET assignment_revision = ?, last_known_good_revision = ?, payload = ?
                    WHERE platform = ? AND bot_id = ? AND group_id = ?
                      AND assignment_revision = ?
                    """,
                    (
                        assignment.assignment_revision,
                        assignment.last_known_good_revision,
                        payload,
                        *_scope_key(assignment.scope),
                        current_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise _conflict("group_assignment_revision_conflict")
            return AssignmentCommitResult(
                1,
                AssignmentCommitDisposition.CREATED,
                stored,
            )

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cp_onboarding (
                    platform TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    preview_id TEXT,
                    PRIMARY KEY (platform, bot_id, group_id)
                );
                CREATE TABLE IF NOT EXISTS cp_join_events (
                    event_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    group_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cp_previews (
                    preview_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cp_preview_commands (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cp_assignment_history (
                    platform TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    assignment_revision INTEGER NOT NULL CHECK (assignment_revision >= 1),
                    payload TEXT NOT NULL,
                    PRIMARY KEY (platform, bot_id, group_id, assignment_revision)
                );
                CREATE TABLE IF NOT EXISTS cp_current_assignments (
                    platform TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    assignment_revision INTEGER NOT NULL CHECK (assignment_revision >= 1),
                    last_known_good_revision INTEGER NOT NULL CHECK (last_known_good_revision >= 1),
                    payload TEXT NOT NULL,
                    PRIMARY KEY (platform, bot_id, group_id)
                );
                CREATE TABLE IF NOT EXISTS cp_assignment_commands (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cp_command_ids (
                    command_id TEXT PRIMARY KEY,
                    command_kind TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cp_audit_records (
                    audit_record_id TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
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
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _transaction(
        self,
        call: ServiceCallContext | None = None,
    ) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if call is not None:
                self._validate_call(call)
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _reserve_command_id(
        connection: sqlite3.Connection,
        command_id: str,
        command_kind: str,
        idempotency_key: str,
    ) -> None:
        try:
            connection.execute(
                "INSERT INTO cp_command_ids VALUES (?, ?, ?)",
                (command_id, command_kind, idempotency_key),
            )
        except sqlite3.IntegrityError:
            raise _conflict("control_plane_command_id_conflict") from None

    @staticmethod
    def _select_onboarding(
        connection: sqlite3.Connection,
        scope: GroupControlScope,
    ) -> GroupOnboardingRecord | None:
        row = connection.execute(
            """
            SELECT * FROM cp_onboarding
            WHERE platform = ? AND bot_id = ? AND group_id = ?
            """,
            _scope_key(scope),
        ).fetchone()
        return _onboarding(row) if row is not None else None

    def _select_onboarding_required(
        self,
        connection: sqlite3.Connection,
        scope: GroupControlScope,
    ) -> GroupOnboardingRecord:
        record = self._select_onboarding(connection, scope)
        if record is None:
            raise _not_found("group_onboarding_not_found")
        return record

    @staticmethod
    def _select_current_revision(
        connection: sqlite3.Connection,
        scope: GroupControlScope,
    ) -> int | None:
        row = connection.execute(
            """
            SELECT assignment_revision FROM cp_current_assignments
            WHERE platform = ? AND bot_id = ? AND group_id = ?
            """,
            _scope_key(scope),
        ).fetchone()
        return int(row["assignment_revision"]) if row is not None else None

    @staticmethod
    def _select_preview_command(
        connection: sqlite3.Connection,
        idempotency_key: str,
    ) -> StoredPreviewCommand | None:
        row = connection.execute(
            "SELECT payload FROM cp_preview_commands WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return decode_stored_preview(row["payload"]) if row is not None else None

    @staticmethod
    def _select_assignment_command(
        connection: sqlite3.Connection,
        idempotency_key: str,
    ) -> StoredAssignmentCommand | None:
        row = connection.execute(
            "SELECT payload FROM cp_assignment_commands WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return decode_stored_assignment(row["payload"]) if row is not None else None

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        stored: StoredPreviewCommand | StoredAssignmentCommand,
    ) -> None:
        record = stored.audit_record
        connection.execute(
            "INSERT INTO cp_audit_records VALUES (?, ?, ?)",
            (
                record.audit_record_id,
                _timestamp(record.recorded_at),
                encode_control_plane_value(record),
            ),
        )

    def _validate_call(self, call: ServiceCallContext) -> None:
        if not isinstance(call, ServiceCallContext):
            raise validation_error("invalid_control_plane_call_context")
        now = self._clock()
        require_aware(now, "control_plane_repository_clock")
        if call.cancellation.is_cancelled:
            raise error(
                "control_plane_call_cancelled",
                ErrorCategory.CANCELLED,
                "request.cancelled",
            )
        if call.deadline <= now:
            raise error(
                "control_plane_call_expired",
                ErrorCategory.TIMEOUT,
                "request.expired",
            )


def _validate_commit_inputs(
    idempotency_key: str,
    request_digest: DigestString,
    expected_onboarding_revision: int,
    expected_assignment_revision: int | None,
) -> None:
    require_non_empty(idempotency_key, "idempotency_key")
    require_non_empty(str(request_digest), "request_digest")
    if (
        type(expected_onboarding_revision) is not int
        or expected_onboarding_revision < 1
    ):
        raise validation_error("invalid_onboarding_revision")
    if expected_assignment_revision is not None and (
        type(expected_assignment_revision) is not int
        or expected_assignment_revision < 1
    ):
        raise validation_error("invalid_assignment_revision")


def _scope_key(scope: GroupControlScope) -> tuple[str, str, str]:
    if not isinstance(scope, GroupControlScope):
        raise validation_error("invalid_group_control_scope")
    return (scope.platform, scope.bot_id, scope.group_id)


def _onboarding(row: sqlite3.Row) -> GroupOnboardingRecord:
    return GroupOnboardingRecord(
        1,
        GroupControlScope(1, row["platform"], row["bot_id"], row["group_id"]),
        OnboardingStatus(row["status"]),
        int(row["revision"]),
        _parse_timestamp(row["first_seen_at"]),
        _parse_timestamp(row["updated_at"]),
        row["source_revision"],
        row["preview_id"],
    )


def _timestamp(value: datetime) -> str:
    require_aware(value, "control_plane_timestamp")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise validation_error("invalid_control_plane_database_timestamp") from None
    require_aware(parsed, "control_plane_database_timestamp")
    return parsed


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "control_plane.conflict")


def _not_found(code: str):
    return error(code, ErrorCategory.NOT_FOUND, "control_plane.not_found")


__all__ = [
    "SQLiteGroupServiceRepository",
    "SQLiteGroupServiceRepositoryConfig",
]
