from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from dududa.adapters.control_plane_web import (
    project_managed_groups,
    project_mutation_execution,
    project_preview_execution,
)
from dududa.control_plane.authorization import (
    ControlPlaneAuthorizer,
    group_conversation_scope,
)
from dududa.control_plane.contracts import (
    AssignmentStatus,
    GroupControlScope,
    GroupJoinFact,
    GroupServiceMutationCommand,
    GroupServiceProfile,
    ManagedGroupsQuery,
    OperatorSession,
    ProfileCatalogQuery,
    ProfileMemoryMode,
    ProfilePreviewCommand,
    ProfileRef,
    ServiceCatalogSnapshot,
    ServiceDefinition,
    ServiceEligibilityFact,
)
from dududa.control_plane.digests import (
    group_service_mutation_payload_digest,
    group_service_preview_digest,
    preview_command_payload_digest,
)
from dududa.control_plane.gateway import ControlPlaneGateway, GroupJoinService
from dududa.control_plane.lifecycle import GroupServiceLifecycle
from dududa.control_plane.projector import ControlPlaneProjector
from dududa.control_plane.snapshot import RepositoryGroupServiceSnapshotProvider
from dududa.control_plane.sqlite_repository import (
    SQLiteGroupServiceRepository,
    SQLiteGroupServiceRepositoryConfig,
)
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
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.security.audit import InMemoryAuditSink
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.confirmation import InMemoryConfirmationService
from dududa.security.digests import (
    confirmation_consume_request_digest,
    confirmation_request_digest,
)
from dududa.security.models import (
    ConfirmationConsumeRequest,
    ConfirmationRequest,
)
from dududa.testing.control_plane import (
    FakeGroupJoinSource,
    MappingOperatorSessionResolver,
    StaticFakeServiceCatalog,
)

NOW = datetime(2026, 8, 14, 13, 0, tzinfo=timezone.utc)


class SequentialIds:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._value = 0

    def __call__(self) -> str:
        self._value += 1
        return f"{self._prefix}-{self._value}"


class GroupOnboardingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.scope = GroupControlScope(1, "qq", "bot-1", "group-1")
        self.actor = Actor(
            "qq",
            "bot-1",
            "operator-private-id",
            frozenset({RoleId("bot-admin")}),
        )
        self.call = ServiceCallContext(
            "operation-1",
            ServicePrincipal("control-plane-test", "instance-1", frozenset({"test"})),
            "control-plane-test",
            TraceContext("trace-onboarding"),
            NOW + timedelta(hours=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "policy-v1",
        )
        self.port_call = PortCallContext(
            self.call.operation_id,
            self.call.trace,
            self.call.deadline,
            self.call.cancellation,
            self.call.budget,
            self.call.policy_snapshot_id,
        )
        self.profiles = (
            self._profile("profile-basic", ("service-ready",)),
            self._profile(
                "profile-expanded",
                ("service-ready", "service-limited"),
            ),
            self._profile(
                "profile-strict",
                ("service-ready", "service-limited"),
                strict=True,
            ),
        )
        self.catalog = StaticFakeServiceCatalog(
            self.profiles,
            self._catalog(),
            clock=lambda: NOW,
        )
        self.policy = self._policy()
        self.authorizer = ControlPlaneAuthorizer(
            self.policy,
            self.policy,
            clock=lambda: NOW,
        )
        self.confirmations = InMemoryConfirmationService(
            policy_revision="control-plane-policy-v1",
            authorization_verifier=self.policy,
            clock=lambda: NOW,
            id_factory=SequentialIds("confirmation"),
        )
        self.sessions = MappingOperatorSessionResolver(
            {
                "operator-session": OperatorSession(
                    1,
                    "operator-session",
                    self.actor,
                    "test-session-v1",
                    NOW - timedelta(minutes=5),
                    NOW + timedelta(hours=1),
                )
            },
            clock=lambda: NOW,
        )
        self.audit = InMemoryAuditSink(clock=lambda: NOW)
        self.gateway_ids = SequentialIds("gateway")
        self.lifecycle_ids = SequentialIds("lifecycle")
        self.repository = self._repository()
        self.gateway, self.lifecycle = self._services(self.repository)

    async def test_lifecycle_persists_restart_lkg_and_runtime_snapshot(self) -> None:
        await self._join(self.scope)
        first_preview = await self._preview(self.profiles[0], 1, None)
        projected_preview = project_preview_execution(self.last_preview_execution)
        self.assertEqual(
            projected_preview["preview"]["previewDigest"],
            str(self.last_preview_execution.receipt.result_digest),
        )
        self.assertEqual(projected_preview["onboardingRevision"], 2)
        activate = await self._mutation(
            "activate",
            onboarding_revision=2,
            assignment_revision=None,
            preview=first_preview,
        )
        first = await self.lifecycle.mutate(activate, call=self.call)
        replay = await self.lifecycle.mutate(activate, call=self.call)
        self.assertEqual(first.assignment.status, AssignmentStatus.ACTIVE)
        self.assertEqual(first.assignment.assignment_revision, 1)
        self.assertEqual(first.receipt, replay.receipt)

        update_preview = await self._preview(self.profiles[1], 2, 1)
        update = await self._mutation(
            "update",
            onboarding_revision=3,
            assignment_revision=1,
            preview=update_preview,
        )
        updated = await self.lifecycle.mutate(update, call=self.call)
        self.assertEqual(updated.assignment.assignment_revision, 2)
        self.assertEqual(updated.assignment.last_known_good_revision, 1)
        self.assertEqual(updated.assignment.effective_service_ids, ("service-ready",))

        paused = await self.lifecycle.mutate(
            await self._mutation(
                "pause",
                onboarding_revision=3,
                assignment_revision=2,
            ),
            call=self.call,
        )
        self.assertEqual(paused.assignment.status, AssignmentStatus.PAUSED)
        provider = RepositoryGroupServiceSnapshotProvider(self.repository)
        self.assertIsNone(await provider.current(self.scope, call=self.call))

        reopened = self._repository()
        reopened_gateway, reopened_lifecycle = self._services(reopened)
        persisted = await reopened.get_assignment(self.scope, call=self.call)
        self.assertEqual(persisted, paused.assignment)
        self.assertEqual(
            (
                await reopened.get_assignment_revision(self.scope, 1, call=self.call)
            ).profile_ref,
            ProfileRef("profile-basic", 1),
        )

        resumed = await reopened_lifecycle.mutate(
            await self._mutation(
                "resume",
                onboarding_revision=3,
                assignment_revision=3,
            ),
            call=self.call,
        )
        self.assertEqual(resumed.assignment.status, AssignmentStatus.ACTIVE)
        self.assertEqual(resumed.assignment.assignment_revision, 4)
        rolled_back = await reopened_lifecycle.mutate(
            await self._mutation(
                "rollback",
                onboarding_revision=3,
                assignment_revision=4,
                rollback_revision=1,
            ),
            call=self.call,
        )
        self.assertEqual(rolled_back.assignment.status, AssignmentStatus.ROLLED_BACK)
        self.assertEqual(
            rolled_back.assignment.profile_ref, ProfileRef("profile-basic", 1)
        )
        self.assertEqual(
            await RepositoryGroupServiceSnapshotProvider(reopened).current(
                self.scope,
                call=self.call,
            ),
            rolled_back.assignment,
        )
        managed = await reopened_gateway.managed_groups(
            ManagedGroupsQuery(
                1,
                "managed-query",
                "operator-session",
                "qq",
                "bot-1",
                NOW,
            ),
            call=self.call,
        )
        self.assertEqual(len(managed.items), 1)
        self.assertEqual(managed.items[0].assignment, rolled_back.assignment)
        self.assertEqual(managed.items[0].onboarding.revision, 3)
        self.assertEqual(
            project_managed_groups(managed)["items"][0]["assignment"]["status"],
            "rolled_back",
        )
        self.assertEqual(
            project_mutation_execution(rolled_back)["assignment"]["assignmentRevision"],
            5,
        )

    async def test_strict_failure_confirmation_binding_and_cas_preserve_pending(
        self,
    ) -> None:
        await self._join(self.scope)
        strict_preview = await self._preview(self.profiles[2], 1, None)
        strict_command = await self._mutation(
            "activate",
            onboarding_revision=2,
            assignment_revision=None,
            preview=strict_preview,
        )
        with self.assertRaises(DududaError) as raised:
            await self.lifecycle.mutate(strict_command, call=self.call)
        self.assertEqual(
            raised.exception.info.code,
            "strict_profile_has_ineligible_services",
        )
        self.assertIsNone(
            await self.repository.get_assignment(self.scope, call=self.call)
        )

        good_preview = await self._preview(self.profiles[0], 2, None)
        first = await self._mutation(
            "activate",
            onboarding_revision=3,
            assignment_revision=None,
            preview=good_preview,
            command_id="activate-first",
            key="activate-key-first",
        )
        tampered = replace(first, command_id="activate-tampered")
        tampered = replace(
            tampered,
            payload_digest=group_service_mutation_payload_digest(tampered),
        )
        with self.assertRaises(DududaError) as raised:
            await self.lifecycle.mutate(tampered, call=self.call)
        self.assertEqual(
            raised.exception.info.code,
            "control_plane_confirmation_binding_mismatch",
        )

        second = await self._mutation(
            "activate",
            onboarding_revision=3,
            assignment_revision=None,
            preview=good_preview,
            command_id="activate-second",
            key="activate-key-second",
        )
        await self.lifecycle.mutate(first, call=self.call)
        with self.assertRaises(DududaError) as raised:
            await self.lifecycle.mutate(second, call=self.call)
        self.assertEqual(
            raised.exception.info.code, "group_assignment_revision_conflict"
        )
        current = await self.repository.get_assignment(self.scope, call=self.call)
        self.assertEqual(current.assignment_revision, 1)

    async def test_sqlite_pending_queries_isolate_bot_and_group(self) -> None:
        scopes = (
            self.scope,
            GroupControlScope(1, "qq", "bot-1", "group-2"),
            GroupControlScope(1, "qq", "bot-2", "group-1"),
        )
        source = FakeGroupJoinSource(
            tuple(
                GroupJoinFact(1, f"join-{index}", scope, "fake-v1", NOW)
                for index, scope in enumerate(scopes)
            ),
            clock=lambda: NOW,
        )
        await GroupJoinService(source, self.repository).ingest(call=self.call)
        bot_one = await self.repository.list_unassigned("qq", "bot-1", call=self.call)
        bot_two = await self.repository.list_unassigned("qq", "bot-2", call=self.call)
        self.assertEqual(
            tuple(item.scope.group_id for item in bot_one), ("group-1", "group-2")
        )
        self.assertEqual(tuple(item.scope.group_id for item in bot_two), ("group-1",))

        catalog = await self.gateway.profile_catalog(
            ProfileCatalogQuery(
                1,
                "catalog-query",
                "operator-session",
                "qq",
                "bot-1",
                NOW,
            ),
            call=self.call,
        )
        self.assertEqual(
            tuple(profile.profile_id for profile in catalog.profiles),
            ("profile-basic", "profile-expanded", "profile-strict"),
        )

    def _repository(self) -> SQLiteGroupServiceRepository:
        return SQLiteGroupServiceRepository(
            SQLiteGroupServiceRepositoryConfig(
                1,
                Path(self.temporary.name) / "control-plane.sqlite3",
            ),
            clock=lambda: NOW,
        )

    def _services(self, repository):
        projector = ControlPlaneProjector(repository, clock=lambda: NOW)
        gateway = ControlPlaneGateway(
            sessions=self.sessions,
            authorizer=self.authorizer,
            repository=repository,
            catalog=self.catalog,
            projector=projector,
            audit_sink=self.audit,
            clock=lambda: NOW,
            id_factory=self.gateway_ids,
        )
        lifecycle = GroupServiceLifecycle(
            sessions=self.sessions,
            authorizer=self.authorizer,
            repository=repository,
            catalog=self.catalog,
            confirmation_verifier=self.confirmations,
            audit_sink=self.audit,
            clock=lambda: NOW,
            id_factory=self.lifecycle_ids,
        )
        return gateway, lifecycle

    async def _join(self, scope: GroupControlScope) -> None:
        await GroupJoinService(
            FakeGroupJoinSource(
                (GroupJoinFact(1, "join-primary", scope, "fake-v1", NOW),),
                clock=lambda: NOW,
            ),
            self.repository,
        ).ingest(call=self.call)

    async def _preview(
        self,
        profile: GroupServiceProfile,
        onboarding_revision: int,
        assignment_revision: int | None,
    ):
        candidate = ProfilePreviewCommand(
            1,
            f"preview-{profile.profile_id}-{onboarding_revision}",
            f"preview-key-{profile.profile_id}-{onboarding_revision}",
            "operator-session",
            self.scope,
            ActionId("group_service.preview"),
            onboarding_revision,
            ProfileRef(profile.profile_id, profile.revision),
            DigestString("pending"),
            NOW,
            assignment_revision,
        )
        command = replace(
            candidate,
            payload_digest=preview_command_payload_digest(candidate),
        )
        execution = await self.gateway.preview_profile(command, call=self.call)
        self.last_preview_execution = execution
        return execution.preview

    async def _mutation(
        self,
        name: str,
        *,
        onboarding_revision: int,
        assignment_revision: int | None,
        preview=None,
        rollback_revision: int | None = None,
        command_id: str | None = None,
        key: str | None = None,
    ) -> GroupServiceMutationCommand:
        action = ActionId(f"group_service.{name}")
        command_id = command_id or f"command-{name}-{assignment_revision}"
        key = key or f"key-{name}-{assignment_revision}"
        confirmation = (
            await self._confirmation(action, preview, command_id, key)
            if preview is not None
            else None
        )
        candidate = GroupServiceMutationCommand(
            1,
            command_id,
            key,
            "operator-session",
            self.scope,
            action,
            onboarding_revision,
            assignment_revision,
            preview.preview_id if preview is not None else None,
            group_service_preview_digest(preview) if preview is not None else None,
            rollback_revision,
            confirmation,
            DigestString("pending"),
            NOW,
        )
        return replace(
            candidate,
            payload_digest=group_service_mutation_payload_digest(candidate),
        )

    async def _confirmation(self, action, preview, command_id: str, key: str):
        authorization = await self.authorizer.authorize_group(
            self.actor,
            self.scope,
            action,
            risk_level=RiskLevel.MEDIUM,
            call=self.call,
        )
        candidate = ConfirmationRequest(
            1,
            DigestString("pending"),
            self.actor,
            group_conversation_scope(self.scope),
            action,
            group_service_preview_digest(preview),
            str(action),
            timedelta(minutes=5),
        )
        request = replace(
            candidate,
            request_digest=confirmation_request_digest(candidate),
        )
        requirement = await self.confirmations.issue(request, call=self.port_call)
        consume = ConfirmationConsumeRequest(
            1,
            DigestString("pending"),
            requirement.confirmation_id,
            self.actor,
            group_conversation_scope(self.scope),
            action,
            requirement.payload_digest,
            requirement.required_permission,
            command_id,
            key,
            authorization,
        )
        consume = replace(
            consume,
            request_digest=confirmation_consume_request_digest(consume),
        )
        return await self.confirmations.consume(consume, call=self.port_call)

    def _profile(
        self,
        profile_id: str,
        services: tuple[str, ...],
        *,
        strict: bool = False,
    ) -> GroupServiceProfile:
        return GroupServiceProfile(
            1,
            profile_id,
            1,
            profile_id,
            services,
            "persona-dududa",
            "trigger-explicit",
            "response-default",
            "budget-default",
            ProfileMemoryMode.OFF,
            False,
            strict,
        )

    def _catalog(self) -> ServiceCatalogSnapshot:
        return ServiceCatalogSnapshot(
            1,
            self.scope,
            "catalog-v1",
            (
                ServiceDefinition(
                    1, "service-ready", "Ready", (), RiskLevel.LOW, "ready-v1"
                ),
                ServiceDefinition(
                    1, "service-limited", "Limited", (), RiskLevel.LOW, "limited-v1"
                ),
            ),
            (
                ServiceEligibilityFact(
                    1, "service-ready", True, True, True, True, "ready-v1"
                ),
                ServiceEligibilityFact(
                    1, "service-limited", True, False, True, True, "limited-v1"
                ),
            ),
            NOW,
        )

    def _policy(self) -> RoleAuthorizationPolicy:
        actions = {
            "group_service.query",
            "group_service.preview",
            "group_service.activate",
            "group_service.update",
            "group_service.pause",
            "group_service.resume",
            "group_service.rollback",
        }
        constraints = {
            action: AuthorizationConstraint(
                frozenset({"group-service-scope"}),
                frozenset({"group-1"}),
                maximum_risk=RiskLevel.MEDIUM,
            )
            for action in actions
            if action != "group_service.query"
        }
        constraints["group_service.query"] = AuthorizationConstraint(
            frozenset({"bot-control-scope"}),
            frozenset({"bot-1"}),
            maximum_risk=RiskLevel.MEDIUM,
        )
        return RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "control-plane-policy-v1",
                {"bot-admin": frozenset(actions)},
                {"bot-admin": constraints},
            ),
            clock=lambda: NOW,
            id_factory=SequentialIds("decision"),
        )


if __name__ == "__main__":
    unittest.main()
