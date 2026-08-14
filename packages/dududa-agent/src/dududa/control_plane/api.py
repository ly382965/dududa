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
from .operations import GovernedOperationsProjection, OperationalProjectionQuery
from .operations_service import GovernedOperationsService


class ControlPlaneApi:
    """Framework-neutral typed API consumed by HTTP or process adapters."""

    def __init__(
        self,
        *,
        gateway: ControlPlaneGateway,
        lifecycle: GroupServiceLifecycle,
        snapshots: GroupServiceSnapshotProvider,
        operations: GovernedOperationsService,
    ) -> None:
        self._gateway = gateway
        self._lifecycle = lifecycle
        self._snapshots = snapshots
        self._operations = operations

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

    async def operational_projections(
        self,
        query: OperationalProjectionQuery,
        *,
        call: ServiceCallContext,
    ) -> GovernedOperationsProjection:
        return await self._operations.query(query, call=call)


__all__ = ["ControlPlaneApi"]
