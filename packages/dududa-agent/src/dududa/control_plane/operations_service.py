from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from dududa.domain.primitives import ActionId, RiskLevel
from dududa.errors import validation_error
from dududa.ports.context import ServiceCallContext
from dududa.ports.control_plane import OperatorSessionResolver

from .authorization import ControlPlaneAuthorizer
from .contracts import GroupControlScope
from .operations import (
    GovernedMutationRegistry,
    GovernedOperationsProjection,
    OperationalProjectionQuery,
    OperationalProjectionRegistry,
)


class GovernedOperationsService:
    def __init__(
        self,
        *,
        sessions: OperatorSessionResolver,
        authorizer: ControlPlaneAuthorizer,
        projections: OperationalProjectionRegistry,
        mutations: GovernedMutationRegistry,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._authorizer = authorizer
        self._projections = projections
        self._mutations = mutations
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def query(
        self,
        query: OperationalProjectionQuery,
        *,
        call: ServiceCallContext,
    ) -> GovernedOperationsProjection:
        if not isinstance(query, OperationalProjectionQuery):
            raise validation_error("invalid_operational_projection_query")
        session = await self._sessions.resolve(query.session_ref, call=call)
        action = ActionId("control_plane.operations.query")
        if query.scope.group_id is None:
            await self._authorizer.authorize_bot(
                session.actor,
                query.scope.platform,
                query.scope.bot_id,
                action,
                risk_level=RiskLevel.LOW,
                call=call,
            )
        else:
            await self._authorizer.authorize_group(
                session.actor,
                GroupControlScope(
                    1,
                    query.scope.platform,
                    query.scope.bot_id,
                    query.scope.group_id,
                ),
                action,
                risk_level=RiskLevel.LOW,
                call=call,
            )
        projections = await self._projections.project(
            query.scope,
            query.surfaces,
            call=call,
        )
        return GovernedOperationsProjection(
            1,
            query.scope,
            projections,
            self._mutations.discover(query.scope),
            self._clock(),
        )


__all__ = ["GovernedOperationsService"]
