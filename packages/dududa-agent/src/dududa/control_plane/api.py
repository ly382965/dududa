from __future__ import annotations

from dududa.ports.context import ServiceCallContext
from dududa.ports.control_plane import GroupServiceSnapshotProvider

from .contracts import (
    GroupControlScope,
    GroupServiceAssignment,
    GroupServiceMutationCommand,
    GroupServiceMutationExecution,
    ManagedGroupsProjection,
    ManagedGroupsQuery,
    PendingInboxProjection,
    PendingInboxQuery,
    ProfileCatalogProjection,
    ProfileCatalogQuery,
    ProfilePreviewCommand,
    ProfilePreviewExecution,
)
from .gateway import ControlPlaneGateway
from .lifecycle import GroupServiceLifecycle


class ControlPlaneApi:
    """Framework-neutral typed API consumed by HTTP or process adapters."""

    def __init__(
        self,
        *,
        gateway: ControlPlaneGateway,
        lifecycle: GroupServiceLifecycle,
        snapshots: GroupServiceSnapshotProvider,
    ) -> None:
        self._gateway = gateway
        self._lifecycle = lifecycle
        self._snapshots = snapshots

    async def pending_inbox(
        self,
        query: PendingInboxQuery,
        *,
        call: ServiceCallContext,
    ) -> PendingInboxProjection:
        return await self._gateway.pending_inbox(query, call=call)

    async def profile_catalog(
        self,
        query: ProfileCatalogQuery,
        *,
        call: ServiceCallContext,
    ) -> ProfileCatalogProjection:
        return await self._gateway.profile_catalog(query, call=call)

    async def managed_groups(
        self,
        query: ManagedGroupsQuery,
        *,
        call: ServiceCallContext,
    ) -> ManagedGroupsProjection:
        return await self._gateway.managed_groups(query, call=call)

    async def preview_profile(
        self,
        command: ProfilePreviewCommand,
        *,
        call: ServiceCallContext,
    ) -> ProfilePreviewExecution:
        return await self._gateway.preview_profile(command, call=call)

    async def mutate_group_service(
        self,
        command: GroupServiceMutationCommand,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceMutationExecution:
        return await self._lifecycle.mutate(command, call=call)

    async def runtime_assignment(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None:
        return await self._snapshots.current(scope, call=call)


__all__ = ["ControlPlaneApi"]
