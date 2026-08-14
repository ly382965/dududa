from __future__ import annotations

from typing import Protocol, runtime_checkable

from dududa.control_plane.contracts import (
    GroupControlScope,
    GroupJoinFact,
    GroupOnboardingRecord,
    GroupServiceAssignment,
    GroupServiceProfile,
    OperatorSession,
    PreviewCommitResult,
    ProfileRef,
    ServiceCatalogSnapshot,
    StoredPreviewCommand,
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
        stored: StoredPreviewCommand,
        call: ServiceCallContext,
    ) -> PreviewCommitResult: ...


__all__ = [
    "GroupJoinSource",
    "GroupServiceCatalog",
    "GroupServiceRepository",
    "OperatorSessionResolver",
]
