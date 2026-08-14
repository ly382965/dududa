from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.control_plane.authorization import ControlPlaneAuthorizer
from dududa.control_plane.contracts import (
    CommandOutcome,
    GroupControlScope,
    GroupJoinFact,
    GroupServiceProfile,
    OperatorSession,
    PendingInboxQuery,
    ProfileMemoryMode,
    ProfilePreviewCommand,
    ProfileRef,
    ServiceCatalogSnapshot,
    ServiceDefinition,
    ServiceEligibilityFact,
)
from dududa.control_plane.digests import preview_command_payload_digest
from dududa.control_plane.gateway import ControlPlaneGateway, GroupJoinService
from dududa.control_plane.projector import ControlPlaneProjector
from dududa.control_plane.repository import InMemoryGroupServiceRepository
from dududa.domain.identity import Actor
from dududa.domain.primitives import (
    ActionId,
    DigestString,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.ports.context import (
    NeverCancelled,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.security.audit import InMemoryAuditSink
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.testing.control_plane import (
    FakeGroupJoinSource,
    MappingOperatorSessionResolver,
    StaticFakeServiceCatalog,
)

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


class SequentialIds:
    def __init__(self) -> None:
        self._value = 0

    def __call__(self) -> str:
        self._value += 1
        return f"control-plane-id-{self._value}"


class ControlPlaneFoundationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.call = ServiceCallContext(
            "operation-1",
            ServicePrincipal("control-plane-test", "instance-1", frozenset({"test"})),
            "control-plane-test",
            TraceContext("trace-1"),
            NOW + timedelta(hours=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "policy-v1",
        )
        self.scope = GroupControlScope(1, "qq", "bot-1", "group-1")
        self.profile = self._profile()
        self.repository = InMemoryGroupServiceRepository(clock=lambda: NOW)
        self.projector = ControlPlaneProjector(
            self.repository,
            clock=lambda: NOW,
        )
        self.audit = InMemoryAuditSink(clock=lambda: NOW)
        self.allowed_actor = Actor(
            "qq",
            "bot-1",
            "operator-raw-identity",
            frozenset({RoleId("bot-admin")}),
        )
        self.denied_actor = replace(
            self.allowed_actor,
            roles=frozenset({RoleId("viewer")}),
        )
        self.other_bot_actor = replace(self.allowed_actor, bot_id="bot-2")
        self.sessions = MappingOperatorSessionResolver(
            {
                "session-secret-value": self._session(
                    "session-secret-value",
                    self.allowed_actor,
                ),
                "session-denied": self._session(
                    "session-denied",
                    self.denied_actor,
                ),
                "session-other-bot": self._session(
                    "session-other-bot",
                    self.other_bot_actor,
                ),
                "session-expired": self._session(
                    "session-expired",
                    self.allowed_actor,
                    issued_at=NOW - timedelta(hours=2),
                    expires_at=NOW - timedelta(hours=1),
                ),
            },
            clock=lambda: NOW,
        )
        self.catalog = StaticFakeServiceCatalog(
            (self.profile,),
            self._catalog_snapshot(),
            clock=lambda: NOW,
        )
        policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "control-plane-policy-v1",
                {
                    "bot-admin": frozenset(
                        {
                            "group_service.query",
                            "group_service.preview",
                        }
                    )
                },
                {
                    "bot-admin": {
                        "group_service.query": AuthorizationConstraint(
                            frozenset({"bot-control-scope"}),
                            frozenset({"bot-1"}),
                            maximum_risk=RiskLevel.MEDIUM,
                        ),
                        "group_service.preview": AuthorizationConstraint(
                            frozenset({"group-service-scope"}),
                            frozenset({"group-1"}),
                            maximum_risk=RiskLevel.MEDIUM,
                        ),
                    }
                },
            ),
            clock=lambda: NOW,
            id_factory=SequentialIds(),
        )
        self.gateway = ControlPlaneGateway(
            sessions=self.sessions,
            authorizer=ControlPlaneAuthorizer(
                policy,
                policy,
                clock=lambda: NOW,
            ),
            repository=self.repository,
            catalog=self.catalog,
            projector=self.projector,
            audit_sink=self.audit,
            clock=lambda: NOW,
            id_factory=SequentialIds(),
        )

    def test_profile_is_frozen_and_cannot_enable_proactive_delivery(self) -> None:
        requested = ["service-ready", "service-limited"]
        profile = GroupServiceProfile(
            1,
            "profile-test",
            1,
            "Test Profile",
            requested,
            "persona-dududa",
            "trigger-default",
            "response-default",
            "budget-default",
            ProfileMemoryMode.OFF,
            False,
            False,
        )
        requested.append("service-added-later")

        self.assertEqual(
            profile.requested_service_ids,
            ("service-ready", "service-limited"),
        )
        with self.assertRaises(FrozenInstanceError):
            profile.display_name = "Changed"
        with self.assertRaises(DududaError) as raised:
            replace(profile, proactive_default_enabled=True)
        self.assertEqual(
            raised.exception.info.code,
            "profile_cannot_enable_proactive_delivery",
        )
        with self.assertRaises(DududaError) as raised:
            GroupControlScope(1, 123, "bot-1", "group-1")  # type: ignore[arg-type]
        self.assertEqual(
            raised.exception.info.code,
            "invalid_group_control_scope_field",
        )

    async def test_join_deduplicates_and_isolates_bot_and_group_scopes(self) -> None:
        other_group = GroupControlScope(1, "qq", "bot-1", "group-2")
        other_bot = GroupControlScope(1, "qq", "bot-2", "group-1")
        source = FakeGroupJoinSource(
            (
                self._join("join-1", self.scope),
                self._join("join-duplicate", self.scope),
                self._join("join-2", other_group),
                self._join("join-3", other_bot),
            ),
            clock=lambda: NOW,
        )

        records = await GroupJoinService(source, self.repository).ingest(call=self.call)
        bot_one = await self.repository.list_unassigned(
            "qq",
            "bot-1",
            call=self.call,
        )
        bot_two = await self.repository.list_unassigned(
            "qq",
            "bot-2",
            call=self.call,
        )

        self.assertEqual(records[0], records[1])
        self.assertEqual(
            tuple(record.scope.group_id for record in bot_one),
            ("group-1", "group-2"),
        )
        self.assertEqual(
            tuple(record.scope.group_id for record in bot_two),
            ("group-1",),
        )
        for scope in (self.scope, other_group, other_bot):
            self.assertIsNone(
                await self.projector.runtime_assignment(scope, call=self.call)
            )

    async def test_pending_query_applies_rbac_and_session_expiry(self) -> None:
        await self._ingest(self.scope)
        await self._ingest(GroupControlScope(1, "qq", "bot-2", "group-9"))

        allowed = await self.gateway.pending_inbox(
            self._query("session-secret-value", bot_id="bot-1"),
            call=self.call,
        )
        self.assertEqual(
            tuple(item.scope.group_id for item in allowed.items),
            ("group-1",),
        )

        attempts = (
            ("session-missing", "bot-1", "operator_session_not_found"),
            ("session-denied", "bot-1", "control_plane_authorization_denied"),
            ("session-other-bot", "bot-1", "control_plane_authorization_denied"),
            ("session-expired", "bot-1", "operator_session_expired"),
        )
        for session_ref, bot_id, expected_code in attempts:
            with self.subTest(session_ref=session_ref):
                with self.assertRaises(DududaError) as raised:
                    await self.gateway.pending_inbox(
                        self._query(session_ref, bot_id=bot_id),
                        call=self.call,
                    )
                self.assertEqual(raised.exception.info.code, expected_code)

        self.assertEqual(self.repository.audit_records, ())
        self.assertEqual(self.audit.events, [])

    async def test_preview_resolves_services_replays_and_stays_pending(self) -> None:
        await self._ingest(self.scope)
        command = self._preview_command()

        first = await self.gateway.preview_profile(command, call=self.call)
        replay = await self.gateway.preview_profile(command, call=self.call)

        self.assertEqual(first.receipt.outcome, CommandOutcome.SUCCEEDED)
        self.assertEqual(
            first.preview.desired_service_ids, self.profile.requested_service_ids
        )
        self.assertEqual(first.preview.effective_service_ids, ("service-ready",))
        self.assertEqual(
            tuple(item.reason_codes for item in first.preview.resolutions),
            (
                (),
                ("service_unhealthy", "service_not_granted"),
                ("service_definition_missing", "service_fact_missing"),
            ),
        )
        self.assertEqual(replay.receipt, first.receipt)
        self.assertEqual(replay.preview, first.preview)
        self.assertFalse(replay.audit_mirror_persisted)
        self.assertEqual(len(self.repository.audit_records), 1)
        self.assertEqual(len(self.audit.events), 1)
        self.assertIsNone(
            await self.projector.runtime_assignment(self.scope, call=self.call)
        )

        persisted = repr(
            (
                first.receipt,
                self.repository.audit_records,
                tuple(self.audit.events),
            )
        )
        self.assertNotIn("session-secret-value", persisted)
        self.assertNotIn("operator-raw-identity", persisted)

        conflicting = replace(command, command_id="command-conflict")
        with self.assertRaises(DududaError) as raised:
            await self.gateway.preview_profile(conflicting, call=self.call)
        self.assertEqual(
            raised.exception.info.code,
            "control_plane_idempotency_conflict",
        )

        stale = replace(
            command,
            command_id="command-stale",
            idempotency_key="preview-key-stale",
        )
        with self.assertRaises(DududaError) as raised:
            await self.gateway.preview_profile(stale, call=self.call)
        self.assertEqual(
            raised.exception.info.code,
            "group_onboarding_revision_conflict",
        )
        self.assertEqual(len(self.repository.audit_records), 1)
        self.assertEqual(len(self.audit.events), 1)

    async def test_preview_rejects_catalog_from_another_scope(self) -> None:
        await self._ingest(self.scope)
        self.catalog._snapshot = replace(
            self.catalog._snapshot,
            scope=GroupControlScope(1, "qq", "bot-1", "group-other"),
        )

        with self.assertRaises(DududaError) as raised:
            await self.gateway.preview_profile(self._preview_command(), call=self.call)

        self.assertEqual(raised.exception.info.code, "service_catalog_scope_mismatch")
        self.assertEqual(self.repository.audit_records, ())
        self.assertEqual(self.audit.events, [])
        onboarding = await self.repository.get_onboarding(self.scope, call=self.call)
        self.assertEqual(onboarding.revision, 1)
        self.assertIsNone(
            await self.projector.runtime_assignment(self.scope, call=self.call)
        )

        self.catalog._snapshot = replace(
            self.catalog._snapshot,
            scope=self.scope,
        )
        profile_key = (self.profile.profile_id, self.profile.revision)
        self.catalog._profiles[profile_key] = replace(
            self.profile,
            profile_id="profile-other",
        )
        with self.assertRaises(DududaError) as raised:
            await self.gateway.preview_profile(self._preview_command(), call=self.call)
        self.assertEqual(
            raised.exception.info.code,
            "group_service_profile_ref_mismatch",
        )
        self.assertEqual(self.repository.audit_records, ())

    async def _ingest(self, scope: GroupControlScope) -> None:
        source = FakeGroupJoinSource(
            (self._join(f"join-{scope.bot_id}-{scope.group_id}", scope),),
            clock=lambda: NOW,
        )
        await GroupJoinService(source, self.repository).ingest(call=self.call)

    def _join(self, event_id: str, scope: GroupControlScope) -> GroupJoinFact:
        return GroupJoinFact(1, event_id, scope, "fake-join-v1", NOW)

    def _query(self, session_ref: str, *, bot_id: str) -> PendingInboxQuery:
        return PendingInboxQuery(
            1,
            f"query-{session_ref}",
            session_ref,
            "qq",
            bot_id,
            NOW,
        )

    def _preview_command(self) -> ProfilePreviewCommand:
        candidate = ProfilePreviewCommand(
            1,
            "command-1",
            "preview-key-1",
            "session-secret-value",
            self.scope,
            ActionId("group_service.preview"),
            1,
            ProfileRef(self.profile.profile_id, self.profile.revision),
            DigestString("pending"),
            NOW,
        )
        return replace(
            candidate,
            payload_digest=preview_command_payload_digest(candidate),
        )

    def _session(
        self,
        session_ref: str,
        actor: Actor,
        *,
        issued_at: datetime = NOW - timedelta(minutes=5),
        expires_at: datetime = NOW + timedelta(hours=1),
    ) -> OperatorSession:
        return OperatorSession(
            1,
            session_ref,
            actor,
            "fake-session-v1",
            issued_at,
            expires_at,
        )

    def _profile(self) -> GroupServiceProfile:
        return GroupServiceProfile(
            1,
            "profile-default",
            1,
            "Default",
            ("service-ready", "service-limited", "service-missing"),
            "persona-dududa",
            "trigger-default",
            "response-default",
            "budget-default",
            ProfileMemoryMode.OFF,
            False,
            False,
        )

    def _catalog_snapshot(self) -> ServiceCatalogSnapshot:
        return ServiceCatalogSnapshot(
            1,
            self.scope,
            "fake-catalog-v1",
            (
                ServiceDefinition(
                    1,
                    "service-ready",
                    "Ready Service",
                    (),
                    RiskLevel.LOW,
                    "ready-v1",
                ),
                ServiceDefinition(
                    1,
                    "service-limited",
                    "Limited Service",
                    (),
                    RiskLevel.LOW,
                    "limited-v1",
                ),
            ),
            (
                ServiceEligibilityFact(
                    1,
                    "service-ready",
                    True,
                    True,
                    True,
                    True,
                    "ready-fact-v1",
                ),
                ServiceEligibilityFact(
                    1,
                    "service-limited",
                    True,
                    False,
                    False,
                    True,
                    "limited-fact-v1",
                ),
            ),
            NOW,
        )


if __name__ == "__main__":
    unittest.main()
