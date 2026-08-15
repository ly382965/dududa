from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.adapters.control_plane_web import project_governed_operations
from dududa.control_plane.contracts import OperatorSession
from dududa.control_plane.operations import (
    GovernedMutationRegistry,
    OperationalEvidenceMode,
    OperationalFact,
    OperationalProjection,
    OperationalProjectionQuery,
    OperationalProjectionRegistry,
    OperationalScope,
    OperationalStatus,
    OperationalSurface,
    group_service_mutation_descriptors,
)
from dududa.control_plane.operations_service import GovernedOperationsService
from dududa.domain.identity import Actor
from dududa.domain.primitives import RoleId, RuntimeBudget, TraceContext
from dududa.errors import DududaError
from dududa.ports.context import (
    NeverCancelled,
    ServiceCallContext,
    ServicePrincipal,
)

NOW = datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)


class _Sessions:
    def __init__(self, actor: Actor) -> None:
        self._session = OperatorSession(
            1,
            "operator-session",
            actor,
            "session-revision-1",
            NOW - timedelta(minutes=1),
            NOW + timedelta(hours=1),
        )

    async def resolve(self, session_ref: str, *, call: ServiceCallContext):
        if session_ref != self._session.session_ref:
            raise AssertionError("unexpected session")
        return self._session


class _Authorizer:
    def __init__(self) -> None:
        self.bot_calls: list[tuple[str, str]] = []
        self.group_calls: list[tuple[str, str, str]] = []

    async def authorize_bot(self, actor, platform, bot_id, action, **kwargs):
        if actor.platform != platform or actor.bot_id != bot_id:
            raise AssertionError("cross-scope bot authorization")
        self.bot_calls.append((platform, bot_id))

    async def authorize_group(self, actor, scope, action, **kwargs):
        if actor.platform != scope.platform or actor.bot_id != scope.bot_id:
            raise AssertionError("cross-scope group authorization")
        self.group_calls.append((scope.platform, scope.bot_id, scope.group_id))


class _ModelProvider:
    surface = OperationalSurface.MODEL_ROUTER

    async def project(self, scope: OperationalScope, *, call: ServiceCallContext):
        fact = OperationalFact(
            1,
            "tier-policy",
            "Static Router",
            OperationalStatus.READY,
            "router-r3",
            "haiku / sonnet / opus",
            ("static_router_active",),
            NOW,
        )
        return OperationalProjection(
            1,
            self.surface,
            scope,
            "router-r3",
            OperationalEvidenceMode.OFFLINE,
            OperationalStatus.READY,
            (fact,),
            ("static_router_active",),
            NOW,
        )


class _WrongScopeProvider(_ModelProvider):
    async def project(self, scope: OperationalScope, *, call: ServiceCallContext):
        projected = await super().project(scope, call=call)
        wrong_scope = OperationalScope(1, scope.platform, "another-bot", scope.group_id)
        return OperationalProjection(
            projected.schema_version,
            projected.surface,
            wrong_scope,
            projected.revision,
            projected.evidence_mode,
            projected.status,
            projected.facts,
            projected.reason_codes,
            projected.observed_at,
        )


class GovernedOperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.actor = Actor(
            "qq",
            "bot-1",
            "private-operator",
            frozenset({RoleId("bot-admin")}),
        )
        self.call = ServiceCallContext(
            "operations-test",
            ServicePrincipal("control-plane-test", "instance-1", frozenset({"test"})),
            "control-plane-test",
            TraceContext("trace-operations"),
            NOW + timedelta(hours=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "policy-v1",
        )

    async def test_projects_every_surface_and_only_discovers_group_service_commands(self) -> None:
        authorizer = _Authorizer()
        service = GovernedOperationsService(
            sessions=_Sessions(self.actor),
            authorizer=authorizer,
            projections=OperationalProjectionRegistry((_ModelProvider(),), clock=lambda: NOW),
            mutations=GovernedMutationRegistry(group_service_mutation_descriptors()),
            clock=lambda: NOW,
        )
        scope = OperationalScope(1, "qq", "bot-1", "group-1")
        result = await service.query(
            OperationalProjectionQuery(
                1,
                "query-1",
                "operator-session",
                scope,
                tuple(OperationalSurface),
                NOW,
            ),
            call=self.call,
        )

        self.assertEqual(authorizer.group_calls, [("qq", "bot-1", "group-1")])
        self.assertEqual(
            tuple(item.surface for item in result.projections),
            tuple(OperationalSurface),
        )
        self.assertEqual(result.projections[1].status, OperationalStatus.READY)
        self.assertTrue(
            all(
                item.status is OperationalStatus.UNAVAILABLE
                for item in result.projections
                if item.surface is not OperationalSurface.MODEL_ROUTER
            )
        )
        actions = {str(item.action) for item in result.mutations}
        self.assertEqual(
            actions,
            {
                "group_service.activate",
                "group_service.pause",
                "group_service.preview",
                "group_service.resume",
                "group_service.rollback",
                "group_service.update",
            },
        )
        self.assertNotIn("agent.draft.approve", actions)
        self.assertNotIn("agent.permission.approve", actions)
        self.assertNotIn("control_plane.settings.write", actions)

        web = project_governed_operations(result)
        self.assertEqual(web["scope"], {"platform": "qq", "botId": "bot-1", "groupId": "group-1"})
        self.assertEqual(len(web["projections"]), 6)

    async def test_rejects_provider_result_from_another_scope(self) -> None:
        registry = OperationalProjectionRegistry((_WrongScopeProvider(),), clock=lambda: NOW)
        with self.assertRaises(DududaError) as raised:
            await registry.project(
                OperationalScope(1, "qq", "bot-1"),
                (OperationalSurface.MODEL_ROUTER,),
                call=self.call,
            )
        self.assertEqual(
            raised.exception.info.code,
            "operational_provider_result_scope_mismatch",
        )


if __name__ == "__main__":
    unittest.main()
