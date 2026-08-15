from __future__ import annotations

from typing import Protocol, runtime_checkable

from dududa.control_plane.contracts import (
    AssignmentCommitResult,
    GroupControlScope,
    GroupJoinFact,
    GroupOnboardingRecord,
    GroupServiceAssignment,
    GroupServicePreview,
    GroupServiceProfile,
    OperatorSession,
    PreviewCommitResult,
    ProfileRef,
    ServiceCatalogSnapshot,
    StoredAssignmentCommand,
    StoredPreviewCommand,
)
from dududa.control_plane.operations import (
    OperationalProjection,
    OperationalScope,
    OperationalSurface,
)
from dududa.domain.primitives import DigestString

from .context import ServiceCallContext


@runtime_checkable
class OperatorSessionResolver(Protocol):
    async def resolve(
        self,
        session_ref: str,
        *,
        call: ServiceCallContext,
    ) -> OperatorSession: ...


@runtime_checkable
class GroupJoinSource(Protocol):
    async def drain(
        self,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupJoinFact, ...]: ...


@runtime_checkable
class GroupServiceCatalog(Protocol):
    async def profiles(
        self,
        platform: str,
        bot_id: str,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupServiceProfile, ...]: ...

    async def get_profile(
        self,
        profile_ref: ProfileRef,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceProfile | None: ...

    async def snapshot(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> ServiceCatalogSnapshot: ...


@runtime_checkable
class GroupServiceRepository(Protocol):
    async def observe_join(
        self,
        fact: GroupJoinFact,
        *,
        call: ServiceCallContext,
    ) -> GroupOnboardingRecord: ...

    async def get_onboarding(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupOnboardingRecord | None: ...

    async def list_unassigned(
        self,
        platform: str,
        bot_id: str,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupOnboardingRecord, ...]: ...

    async def get_assignment(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None: ...

    async def list_assignments(
        self,
        platform: str,
        bot_id: str,
        *,
        call: ServiceCallContext,
    ) -> tuple[GroupServiceAssignment, ...]: ...

    async def get_assignment_revision(
        self,
        scope: GroupControlScope,
        assignment_revision: int,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None: ...

    async def get_preview(
        self,
        preview_id: str,
        *,
        call: ServiceCallContext,
    ) -> GroupServicePreview | None: ...

    async def lookup_preview_command(
        self,
        idempotency_key: str,
        *,
        call: ServiceCallContext,
    ) -> StoredPreviewCommand | None: ...

    async def commit_preview(
        self,
        *,
        idempotency_key: str,
        request_digest: DigestString,
        expected_onboarding_revision: int,
        expected_assignment_revision: int | None,
        stored: StoredPreviewCommand,
        call: ServiceCallContext,
    ) -> PreviewCommitResult: ...

    async def lookup_assignment_command(
        self,
        idempotency_key: str,
        *,
        call: ServiceCallContext,
    ) -> StoredAssignmentCommand | None: ...

    async def commit_assignment(
        self,
        *,
        idempotency_key: str,
        request_digest: DigestString,
        expected_onboarding_revision: int,
        expected_assignment_revision: int | None,
        stored: StoredAssignmentCommand,
        call: ServiceCallContext,
    ) -> AssignmentCommitResult: ...


@runtime_checkable
class GroupServiceSnapshotProvider(Protocol):
    async def current(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None: ...


@runtime_checkable
class OperationalProjectionProvider(Protocol):
    @property
    def surface(self) -> OperationalSurface: ...

    async def project(
        self,
        scope: OperationalScope,
        *,
        call: ServiceCallContext,
    ) -> OperationalProjection: ...


__all__ = [
    "GroupJoinSource",
    "GroupServiceCatalog",
    "GroupServiceRepository",
    "GroupServiceSnapshotProvider",
    "OperationalProjectionProvider",
    "OperatorSessionResolver",
]
