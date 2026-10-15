from __future__ import annotations

from dududa.ports.context import ServiceCallContext
from dududa.ports.control_plane import GroupServiceRepository

from .contracts import AssignmentStatus, GroupControlScope, GroupServiceAssignment


class RepositoryGroupServiceSnapshotProvider:
    def __init__(self, repository: GroupServiceRepository) -> None:
        self._repository = repository

    async def current(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None:
        assignment = await self._repository.get_assignment(scope, call=call)
        if assignment is None or assignment.status not in {
            AssignmentStatus.ACTIVE,
            AssignmentStatus.ROLLED_BACK,
        }:
            return None
        return assignment


__all__ = ["RepositoryGroupServiceSnapshotProvider"]
