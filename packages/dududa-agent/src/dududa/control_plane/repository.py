from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

from dududa.domain.primitives import DigestString, require_non_empty
from dududa.errors import ErrorCategory, error, validation_error
from dududa.ports.context import ServiceCallContext

from .contracts import (
    AssignmentCommitDisposition,
    AssignmentCommitResult,
    ControlPlaneAuditRecord,
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


class InMemoryGroupServiceRepository:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()
        self._onboarding: dict[tuple[str, str, str], GroupOnboardingRecord] = {}
        self._join_events: dict[str, tuple[str, str, str]] = {}
        self._assignments: dict[tuple[str, str, str], GroupServiceAssignment] = {}
        self._assignment_history: dict[
            tuple[tuple[str, str, str], int], GroupServiceAssignment
        ] = {}
        self._previews: dict[str, GroupServicePreview] = {}
        self._commands: dict[str, StoredPreviewCommand] = {}
        self._assignment_commands: dict[str, StoredAssignmentCommand] = {}
        self._audit_records: list[ControlPlaneAuditRecord] = []

    @property
    def audit_records(self) -> tuple[ControlPlaneAuditRecord, ...]:
        return tuple(self._audit_records)

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
        async with self._lock:
            self._validate_call(call)
            event_scope = self._join_events.get(fact.event_id)
            if event_scope is not None and event_scope != key:
                raise _conflict("join_event_scope_conflict")
            existing = self._onboarding.get(key)
            if existing is not None:
                self._join_events[fact.event_id] = key
                return existing
            record = GroupOnboardingRecord(
                1,
                fact.scope,
                OnboardingStatus.PENDING_PROFILE,
                1,
                fact.observed_at,
                fact.observed_at,
                fact.source_revision,
            )
            self._onboarding[key] = record
            self._join_events[fact.event_id] = key
            return record

    async def get_onboarding(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupOnboardingRecord | None:
        self._validate_call(call)
        async with self._lock:
            self._validate_call(call)
            return self._onboarding.get(_scope_key(scope))

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
        async with self._lock:
            self._validate_call(call)
            return tuple(
                sorted(
                    (
                        record
                        for record in self._onboarding.values()
                        if record.scope.platform == platform
                        and record.scope.bot_id == bot_id
                        and _scope_key(record.scope) not in self._assignments
                    ),
                    key=lambda item: (
                        item.first_seen_at,
                        item.scope.group_id,
                    ),
                )
            )

    async def get_assignment(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None:
        self._validate_call(call)
        async with self._lock:
            self._validate_call(call)
            return self._assignments.get(_scope_key(scope))

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
        async with self._lock:
            self._validate_call(call)
            return tuple(
                sorted(
                    (
                        assignment
                        for assignment in self._assignments.values()
                        if assignment.scope.platform == platform
                        and assignment.scope.bot_id == bot_id
                    ),
                    key=lambda item: item.scope.group_id,
                )
            )

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
        async with self._lock:
            self._validate_call(call)
            return self._assignment_history.get(
                (_scope_key(scope), assignment_revision)
            )

    async def get_preview(
        self,
        preview_id: str,
        *,
        call: ServiceCallContext,
    ) -> GroupServicePreview | None:
        require_non_empty(preview_id, "preview_id")
        self._validate_call(call)
        async with self._lock:
            self._validate_call(call)
            return self._previews.get(preview_id)

    async def lookup_preview_command(
        self,
        idempotency_key: str,
        *,
        call: ServiceCallContext,
    ) -> StoredPreviewCommand | None:
        require_non_empty(idempotency_key, "idempotency_key")
        self._validate_call(call)
        async with self._lock:
            self._validate_call(call)
            return self._commands.get(idempotency_key)

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
        if not isinstance(stored, StoredPreviewCommand):
            raise validation_error("invalid_stored_preview_command")
        if stored.request_digest != request_digest:
            raise validation_error("preview_commit_request_mismatch")
        if stored.receipt.idempotency_key != idempotency_key:
            raise validation_error("preview_commit_idempotency_mismatch")
        self._validate_call(call)
        async with self._lock:
            self._validate_call(call)
            existing = self._commands.get(idempotency_key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise _conflict("control_plane_idempotency_conflict")
                return PreviewCommitResult(
                    1,
                    PreviewCommitDisposition.DUPLICATE,
                    existing,
                )

            preview = stored.preview
            key = _scope_key(preview.scope)
            current = self._onboarding.get(key)
            if current is None:
                raise _not_found("group_onboarding_not_found")
            if current.revision != expected_onboarding_revision:
                raise _conflict("group_onboarding_revision_conflict")
            if preview.onboarding_revision != expected_onboarding_revision:
                raise validation_error("preview_onboarding_revision_mismatch")
            if preview.assignment_revision != expected_assignment_revision:
                raise validation_error("preview_assignment_revision_mismatch")
            current_assignment = self._assignments.get(key)
            current_assignment_revision = (
                current_assignment.assignment_revision
                if current_assignment is not None
                else None
            )
            if current_assignment_revision != expected_assignment_revision:
                raise _conflict("group_assignment_revision_conflict")
            if preview.preview_id in self._previews:
                raise _conflict("preview_id_conflict")

            updated = GroupOnboardingRecord(
                1,
                current.scope,
                OnboardingStatus.PREVIEW_READY,
                current.revision + 1,
                current.first_seen_at,
                preview.created_at,
                current.source_revision,
                preview.preview_id,
            )
            self._onboarding[key] = updated
            self._previews[preview.preview_id] = preview
            self._commands[idempotency_key] = stored
            self._audit_records.append(stored.audit_record)
            return PreviewCommitResult(
                1,
                PreviewCommitDisposition.CREATED,
                stored,
            )

    async def lookup_assignment_command(
        self,
        idempotency_key: str,
        *,
        call: ServiceCallContext,
    ) -> StoredAssignmentCommand | None:
        require_non_empty(idempotency_key, "idempotency_key")
        self._validate_call(call)
        async with self._lock:
            self._validate_call(call)
            return self._assignment_commands.get(idempotency_key)

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
        if not isinstance(stored, StoredAssignmentCommand):
            raise validation_error("invalid_stored_assignment_command")
        if stored.request_digest != request_digest:
            raise validation_error("assignment_commit_request_mismatch")
        if stored.receipt.idempotency_key != idempotency_key:
            raise validation_error("assignment_commit_idempotency_mismatch")
        self._validate_call(call)
        async with self._lock:
            self._validate_call(call)
            existing = self._assignment_commands.get(idempotency_key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise _conflict("control_plane_idempotency_conflict")
                return AssignmentCommitResult(
                    1,
                    AssignmentCommitDisposition.DUPLICATE,
                    existing,
                )

            assignment = stored.assignment
            key = _scope_key(assignment.scope)
            onboarding = self._onboarding.get(key)
            if onboarding is None:
                raise _not_found("group_onboarding_not_found")
            if onboarding.revision != expected_onboarding_revision:
                raise _conflict("group_onboarding_revision_conflict")
            current = self._assignments.get(key)
            current_revision = (
                current.assignment_revision if current is not None else None
            )
            if current_revision != expected_assignment_revision:
                raise _conflict("group_assignment_revision_conflict")
            next_revision = 1 if current_revision is None else current_revision + 1
            if assignment.assignment_revision != next_revision:
                raise validation_error("assignment_revision_not_next")
            if assignment.previous_revision != current_revision:
                raise validation_error("assignment_previous_revision_mismatch")
            lkg_revision = assignment.last_known_good_revision
            if (
                lkg_revision != next_revision
                and (key, lkg_revision) not in self._assignment_history
            ):
                raise validation_error("assignment_lkg_not_found")
            history_key = (key, assignment.assignment_revision)
            if history_key in self._assignment_history:
                raise _conflict("assignment_revision_conflict")

            self._assignment_history[history_key] = assignment
            self._assignments[key] = assignment
            self._assignment_commands[idempotency_key] = stored
            self._audit_records.append(stored.audit_record)
            return AssignmentCommitResult(
                1,
                AssignmentCommitDisposition.CREATED,
                stored,
            )

    def _validate_call(self, call: ServiceCallContext) -> None:
        if not isinstance(call, ServiceCallContext):
            raise validation_error("invalid_control_plane_call_context")
        now = self._clock()
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


def _scope_key(scope: GroupControlScope) -> tuple[str, str, str]:
    if not isinstance(scope, GroupControlScope):
        raise validation_error("invalid_group_control_scope")
    return (scope.platform, scope.bot_id, scope.group_id)


def _conflict(code: str):
    return error(code, ErrorCategory.CONFLICT, "control_plane.conflict")


def _not_found(code: str):
    return error(code, ErrorCategory.NOT_FOUND, "control_plane.not_found")


__all__ = ["InMemoryGroupServiceRepository"]
