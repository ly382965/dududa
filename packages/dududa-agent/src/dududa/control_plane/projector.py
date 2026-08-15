from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from dududa.errors import validation_error
from dududa.ports.context import ServiceCallContext
from dududa.ports.control_plane import GroupServiceRepository

from .contracts import (
    GroupControlScope,
    GroupServiceAssignment,
    ManagedGroupProjection,
    ManagedGroupsProjection,
    PendingGroupProjection,
    PendingInboxProjection,
)


class ControlPlaneProjector:
    def __init__(
        self,
        repository: GroupServiceRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def pending_inbox(
        self,
        platform: str,
        bot_id: str,
        *,
        call: ServiceCallContext,
    ) -> PendingInboxProjection:
        records = await self._repository.list_unassigned(
            platform,
            bot_id,
            call=call,
        )
        return PendingInboxProjection(
            1,
            platform,
            bot_id,
            tuple(
                PendingGroupProjection(
                    1,
                    record.scope,
                    record.status,
                    record.revision,
                    record.first_seen_at,
                    record.updated_at,
                    record.preview_id,
                )
                for record in records
            ),
            self._clock(),
        )

    async def managed_groups(
        self,
        platform: str,
        bot_id: str,
        *,
        call: ServiceCallContext,
    ) -> ManagedGroupsProjection:
        assignments = await self._repository.list_assignments(
            platform,
            bot_id,
            call=call,
        )
        items: list[ManagedGroupProjection] = []
        for assignment in assignments:
            record = await self._repository.get_onboarding(
                assignment.scope,
                call=call,
            )
            if record is None:
                raise validation_error("managed_assignment_missing_onboarding")
            items.append(
                ManagedGroupProjection(
                    1,
                    PendingGroupProjection(
                        1,
                        record.scope,
                        record.status,
                        record.revision,
                        record.first_seen_at,
                        record.updated_at,
                        record.preview_id,
                    ),
                    assignment,
                )
            )
        return ManagedGroupsProjection(
            1,
            platform,
            bot_id,
            tuple(items),
            self._clock(),
        )

    async def runtime_assignment(
        self,
        scope: GroupControlScope,
        *,
        call: ServiceCallContext,
    ) -> GroupServiceAssignment | None:
        return await self._repository.get_assignment(scope, call=call)


__all__ = ["ControlPlaneProjector"]
