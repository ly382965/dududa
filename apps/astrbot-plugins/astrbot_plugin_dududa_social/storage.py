"""Small scoped SQLite repository for explicit social commands.

The repository is intentionally independent from AstrBot and from Dududa's
Core state files.  Every row carries the collision-free ``SocialScope.key``;
there is no global ``user_state.json``/``group_state.json`` namespace.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .policy import (
    SleepLog,
    SleepSummary,
    SocialPolicyError,
    SocialScope,
    UserPair,
    VoteState,
    aggregate_sleep,
    apply_vote_action,
    canonical_pair,
    parse_birthday,
    rank_interactions,
)

SCHEMA_VERSION = 1


class SocialStateStore:
    """Scoped, transactional persistence for the optional social extension."""

    def __init__(self, path: str | Path) -> None:
        if isinstance(path, Path):
            self.path = path
        elif isinstance(path, str) and path.strip() == ":memory:":
            self.path = Path(":memory:")
        elif isinstance(path, str) and path.strip():
            self.path = Path(path).expanduser()
        else:
            raise SocialPolicyError("invalid_social_state_path")

        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
        self._connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._closed = False
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if str(self.path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS social_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS birthdays (
                    scope_key TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    month_day TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_key, user_id)
                );
                CREATE TABLE IF NOT EXISTS sleep_logs (
                    scope_key TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    local_time TEXT NOT NULL,
                    PRIMARY KEY (scope_key, user_id, local_date)
                );
                CREATE TABLE IF NOT EXISTS votes (
                    scope_key TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    participants_json TEXT NOT NULL,
                    started_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cp_interactions (
                    scope_key TEXT NOT NULL,
                    first_user TEXT NOT NULL,
                    second_user TEXT NOT NULL,
                    count INTEGER NOT NULL CHECK (count >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_key, first_user, second_user)
                );
                """
            )
            row = self._connection.execute(
                "SELECT value FROM social_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO social_meta(key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif row["value"] != str(SCHEMA_VERSION):
                raise SocialPolicyError("unsupported_social_state_schema")

    def _check_scope(self, scope: SocialScope) -> str:
        if not isinstance(scope, SocialScope):
            raise SocialPolicyError("invalid_social_scope")
        return scope.key

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._closed:
                raise SocialPolicyError("social_state_store_closed")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def set_birthday(
        self,
        scope: SocialScope,
        user_id: str,
        value: str,
        *,
        at: datetime | None = None,
    ) -> str:
        scope_key = self._check_scope(scope)
        canonical = parse_birthday(value)
        if canonical is None:
            raise SocialPolicyError("invalid_birthday")
        now = _aware_datetime(at or datetime.now(timezone.utc))
        user = _user_id(user_id)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO birthdays(scope_key, user_id, month_day, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope_key, user_id) DO UPDATE SET
                    month_day = excluded.month_day,
                    updated_at = excluded.updated_at
                """,
                (scope_key, user, canonical, now.isoformat()),
            )
        return canonical

    def delete_birthday(self, scope: SocialScope, user_id: str) -> bool:
        scope_key = self._check_scope(scope)
        with self._transaction() as connection:
            result = connection.execute(
                "DELETE FROM birthdays WHERE scope_key = ? AND user_id = ?",
                (scope_key, _user_id(user_id)),
            )
        return result.rowcount > 0

    def list_birthdays(self, scope: SocialScope) -> dict[str, str]:
        scope_key = self._check_scope(scope)
        with self._lock:
            if self._closed:
                raise SocialPolicyError("social_state_store_closed")
            rows = self._connection.execute(
                "SELECT user_id, month_day FROM birthdays WHERE scope_key = ? ORDER BY month_day, user_id",
                (scope_key,),
            ).fetchall()
        return {str(row["user_id"]): str(row["month_day"]) for row in rows}

    def append_sleep(
        self,
        scope: SocialScope,
        entry: SleepLog,
        *,
        retention_days: int = 366,
    ) -> bool:
        scope_key = self._check_scope(scope)
        if not isinstance(entry, SleepLog):
            raise SocialPolicyError("invalid_sleep_log")
        if type(retention_days) is not int or not 1 <= retention_days <= 3_650:
            raise SocialPolicyError("invalid_sleep_retention")
        cutoff = entry.local_date - timedelta(days=retention_days)
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM sleep_logs WHERE scope_key = ? AND local_date < ?",
                (scope_key, cutoff.isoformat()),
            )
            result = connection.execute(
                """
                INSERT OR IGNORE INTO sleep_logs(scope_key, user_id, local_date, local_time)
                VALUES (?, ?, ?, ?)
                """,
                (
                    scope_key,
                    entry.user_id,
                    entry.local_date.isoformat(),
                    entry.local_time.isoformat(timespec="minutes"),
                ),
            )
        return result.rowcount > 0

    def sleep_summaries(self, scope: SocialScope) -> tuple[SleepSummary, ...]:
        scope_key = self._check_scope(scope)
        with self._lock:
            if self._closed:
                raise SocialPolicyError("social_state_store_closed")
            rows = self._connection.execute(
                "SELECT user_id, local_date, local_time FROM sleep_logs WHERE scope_key = ? ORDER BY local_date, local_time",
                (scope_key,),
            ).fetchall()
        logs = tuple(
            SleepLog(
                str(row["user_id"]),
                date.fromisoformat(str(row["local_date"])),
                time_from_iso(str(row["local_time"])),
            )
            for row in rows
        )
        return aggregate_sleep(logs)

    def get_vote(self, scope: SocialScope) -> VoteState | None:
        scope_key = self._check_scope(scope)
        with self._lock:
            if self._closed:
                raise SocialPolicyError("social_state_store_closed")
            row = self._connection.execute(
                "SELECT topic, creator_id, participants_json, started_at FROM votes WHERE scope_key = ?",
                (scope_key,),
            ).fetchone()
        return _vote_from_row(row)

    def apply_vote(
        self,
        scope: SocialScope,
        action: str,
        actor_id: str,
        *,
        topic: str | None = None,
        is_admin: bool = False,
        now: datetime | None = None,
    ):
        scope_key = self._check_scope(scope)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT topic, creator_id, participants_json, started_at FROM votes WHERE scope_key = ?",
                (scope_key,),
            ).fetchone()
            current = _vote_from_row(row)
            transition = apply_vote_action(
                current,
                action,
                actor_id,
                topic=topic,
                is_admin=is_admin,
                now=now,
            )
            if transition.state is None:
                connection.execute("DELETE FROM votes WHERE scope_key = ?", (scope_key,))
            elif transition.changed:
                state = transition.state
                connection.execute(
                    """
                    INSERT INTO votes(scope_key, topic, creator_id, participants_json, started_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(scope_key) DO UPDATE SET
                        topic = excluded.topic,
                        creator_id = excluded.creator_id,
                        participants_json = excluded.participants_json,
                        started_at = excluded.started_at
                    """,
                    (
                        scope_key,
                        state.topic,
                        state.creator_id,
                        json.dumps(sorted(state.participants), ensure_ascii=False),
                        state.started_at.isoformat(),
                    ),
                )
        return transition

    def record_interaction(
        self,
        scope: SocialScope,
        first_user: str,
        second_user: str,
        *,
        at: datetime | None = None,
    ) -> tuple[UserPair, int]:
        scope_key = self._check_scope(scope)
        pair = canonical_pair(first_user, second_user)
        now = _aware_datetime(at or datetime.now(timezone.utc))
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT count FROM cp_interactions WHERE scope_key = ? AND first_user = ? AND second_user = ?",
                (scope_key, pair.first, pair.second),
            ).fetchone()
            count = int(row["count"]) + 1 if row is not None else 1
            if row is None:
                connection.execute(
                    "INSERT INTO cp_interactions(scope_key, first_user, second_user, count, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (scope_key, pair.first, pair.second, count, now.isoformat()),
                )
            else:
                connection.execute(
                    "UPDATE cp_interactions SET count = ?, updated_at = ? WHERE scope_key = ? AND first_user = ? AND second_user = ?",
                    (count, now.isoformat(), scope_key, pair.first, pair.second),
                )
        return pair, count

    def rank_interactions(
        self,
        scope: SocialScope,
        *,
        limit: int = 10,
    ) -> tuple[tuple[UserPair, int], ...]:
        scope_key = self._check_scope(scope)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise SocialPolicyError("invalid_pair_limit")
        with self._lock:
            if self._closed:
                raise SocialPolicyError("social_state_store_closed")
            rows = self._connection.execute(
                "SELECT first_user, second_user, count FROM cp_interactions WHERE scope_key = ?",
                (scope_key,),
            ).fetchall()
        values = {
            UserPair(str(row["first_user"]), str(row["second_user"])): int(row["count"])
            for row in rows
        }
        return rank_interactions(values, limit)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _vote_from_row(row: sqlite3.Row | None) -> VoteState | None:
    if row is None:
        return None
    try:
        participants = json.loads(str(row["participants_json"]))
        if not isinstance(participants, list):
            raise TypeError("participants must be a list")
        started = datetime.fromisoformat(str(row["started_at"]))
        return VoteState(
            str(row["topic"]),
            str(row["creator_id"]),
            frozenset(str(item) for item in participants),
            started,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SocialPolicyError("invalid_vote_state") from exc


def _user_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise SocialPolicyError("invalid_user_id")
    return value.strip()


def _aware_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SocialPolicyError("invalid_aware_timestamp")
    return value


def time_from_iso(value: str):
    from datetime import time

    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise SocialPolicyError("invalid_sleep_time") from exc
    return parsed.replace(tzinfo=None)


__all__ = ["SCHEMA_VERSION", "SocialStateStore"]
