from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ConversationType,
    DigestString,
    ResourceRef,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.memory.digests import (
    memory_content_hash,
    memory_delete_payload_digest,
    memory_delete_request_digest,
    memory_record_digest,
    memory_restore_request_digest,
)
from dududa.memory.json_repository import JsonMemoryRepository
from dududa.memory.models import (
    EvidenceReference,
    MemoryDeleteCommand,
    MemoryQuery,
    MemoryRecord,
    MemoryRestoreCommand,
    MemoryScope,
    MemorySource,
    MemoryType,
    PageRequest,
    Visibility,
)
from dududa.memory.repository import InMemoryMemoryRepository
from dududa.memory.selectors import HmacScopeSelectorAuthority
from dududa.memory.serialization import record_to_dict
from dududa.ports.context import (
    NeverCancelled,
    PortCallContext,
    ServiceCallContext,
    ServicePrincipal,
)
from dududa.ports.memory import MemoryRepository
from dududa.security.authorization import (
    AuthorizationConstraint,
    AuthorizationPolicyConfig,
    RoleAuthorizationPolicy,
)
from dududa.security.confirmation import InMemoryConfirmationService
from dududa.security.digests import (
    authorization_request_digest,
    confirmation_consume_request_digest,
    confirmation_request_digest,
    scope_digest,
)
from dududa.security.models import (
    AuthorizationEffect,
    AuthorizationRequest,
    ConfirmationConsumeRequest,
    ConfirmationRequest,
)


class SequentialIds:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.prefix}-{self.value}"


class MemoryLifecycleRepositoryContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.actor = Actor(
            "qq",
            "bot-1",
            "user-1",
            frozenset({RoleId("memory-admin")}),
            frozenset(),
        )
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "group-1", "group-1", "dududa"
        )
        self.record = self._record()
        self.request_digest = DigestString("memory-read-request")
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(hours=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "memory-policy-v1",
        )

    async def test_delete_restart_restore_and_rebuild_never_revive_record(
        self,
    ) -> None:
        for kind in ("memory", "json"):
            with self.subTest(kind=kind):
                resources = self._repository(kind)
                self.addCleanup(resources.close)
                repository = resources.repository
                self.assertIsInstance(repository, MemoryRepository)
                selector = resources.authority.issue_current_conversation(
                    request_digest=self.request_digest,
                    actor=self.actor,
                    scope=self.scope,
                    memory_types=frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
                    purpose="lifecycle-contract",
                )
                snapshot = await repository.open_snapshot(
                    (selector,),
                    request_digest=self.request_digest,
                    as_of=self.now,
                    call=self.call,
                )
                export = await repository.export_page(
                    snapshot,
                    selector,
                    PageRequest(1, None, 10),
                    request_digest=self.request_digest,
                    call=self.call,
                )
                self.assertEqual([item.memory_id for item in export.records], ["m-1"])
                archive = await repository.export_archive(
                    call=self._service_call("memory.export", "memory.backup")
                )
                command = await resources.delete_command("delete-1", "delete-key-1")
                deleted = await repository.commit_delete(command, call=self.call)
                self.assertEqual(
                    await repository.commit_delete(command, call=self.call), deleted
                )
                with self.assertRaises(DududaError):
                    await repository.get(
                        snapshot,
                        "m-1",
                        selector,
                        request_digest=self.request_digest,
                        call=self.call,
                    )

                checkpoint = await repository.export_tombstone_checkpoint(
                    call=self._service_call(
                        "memory.tombstone-checkpoint", "memory.backup"
                    )
                )
                restore = MemoryRestoreCommand(
                    1,
                    "restore-1",
                    DigestString("pending"),
                    archive,
                    checkpoint,
                    deleted.state_revision,
                    checkpoint.state_revision,
                    "restore-key-1",
                )
                restore = replace(
                    restore,
                    request_digest=memory_restore_request_digest(restore),
                )
                restored = await repository.restore(
                    restore,
                    call=self._service_call("memory.restore", "memory.restore"),
                )
                self.assertEqual(restored.restored_records, 0)
                self.assertEqual(restored.suppressed_records, 1)
                await self._assert_not_visible(repository, resources.authority)

                if resources.path is not None:
                    payload = json.loads(resources.path.read_text(encoding="utf-8"))
                    self.assertEqual(payload["schema_version"], 2)
                    self.assertEqual(payload["records"], [])
                    self.assertEqual(len(payload["tombstones"]), 1)
                    self.assertNotIn("content", payload["tombstones"][0])
                    self.assertNotIn("evidence", payload["tombstones"][0])
                    reloaded = JsonMemoryRepository(
                        resources.path,
                        resources.authority,
                        authorization_decision_verifier=resources.policy,
                        confirmation_grant_verifier=resources.confirmations,
                        clock=lambda: self.now,
                        id_factory=SequentialIds("reload"),
                    )
                    self.assertEqual(
                        await reloaded.commit_delete(command, call=self.call), deleted
                    )
                    await self._assert_not_visible(reloaded, resources.authority)

    async def test_concurrent_delete_has_one_winner_and_one_typed_conflict(
        self,
    ) -> None:
        resources = self._repository("memory")
        self.addCleanup(resources.close)
        first = await resources.delete_command("delete-a", "delete-key-a")
        second = await resources.delete_command("delete-b", "delete-key-b")
        results = await asyncio.gather(
            resources.repository.commit_delete(first, call=self.call),
            resources.repository.commit_delete(second, call=self.call),
            return_exceptions=True,
        )
        self.assertEqual(
            sum(not isinstance(item, BaseException) for item in results), 1
        )
        failures = [item for item in results if isinstance(item, DududaError)]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].info.category.value, "conflict")
        self.assertEqual(len(resources.repository._tombstones), 1)
        self.assertEqual(resources.repository._state_revision, 2)

    async def test_current_archive_clean_import_round_trips_exact_record(self) -> None:
        resources = self._repository("memory")
        self.addCleanup(resources.close)
        archive = await resources.repository.export_archive(
            call=self._service_call("memory.export", "memory.backup")
        )
        checkpoint = await resources.repository.export_tombstone_checkpoint(
            call=self._service_call("memory.tombstone-checkpoint", "memory.backup")
        )
        target = InMemoryMemoryRepository(
            resources.authority,
            clock=lambda: self.now,
            id_factory=SequentialIds("clean-import"),
        )
        command = MemoryRestoreCommand(
            1,
            "clean-import-1",
            DigestString("pending"),
            archive,
            checkpoint,
            0,
            checkpoint.state_revision,
            "clean-import-key-1",
        )
        command = replace(
            command,
            request_digest=memory_restore_request_digest(command),
        )
        receipt = await target.restore(
            command,
            call=self._service_call("memory.restore", "memory.restore"),
        )
        self.assertEqual(receipt.restored_records, 1)
        selector = resources.authority.issue_current_conversation(
            request_digest=self.request_digest,
            actor=self.actor,
            scope=self.scope,
            memory_types=frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
            purpose="clean-import-contract",
        )
        snapshot = await target.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        restored = await target.get(
            snapshot,
            "m-1",
            selector,
            request_digest=self.request_digest,
            call=self.call,
        )
        self.assertEqual(restored, self.record)

    async def test_json_persistence_failure_rolls_back_complete_transaction(
        self,
    ) -> None:
        resources = self._repository("json")
        self.addCleanup(resources.close)
        repository = resources.repository
        selector = resources.authority.issue_current_conversation(
            request_digest=self.request_digest,
            actor=self.actor,
            scope=self.scope,
            memory_types=frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
            purpose="rollback-contract",
        )
        snapshot = await repository.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        command = await resources.delete_command("delete-fail", "delete-key-fail")
        original = resources.path.read_bytes()

        def fail_persist() -> None:
            raise OSError("synthetic persistence failure")

        repository._persist = fail_persist
        with self.assertRaises(OSError):
            await repository.commit_delete(command, call=self.call)
        self.assertEqual(resources.path.read_bytes(), original)
        self.assertEqual(repository._tombstones, {})
        self.assertEqual(repository._state_revision, 1)
        self.assertIsNotNone(
            await repository.get(
                snapshot,
                "m-1",
                selector,
                request_digest=self.request_digest,
                call=self.call,
            )
        )

    async def test_json_v2_tamper_fails_closed_on_restart(self) -> None:
        resources = self._repository("json")
        self.addCleanup(resources.close)
        command = await resources.delete_command("delete-tamper", "delete-key-tamper")
        await resources.repository.commit_delete(command, call=self.call)
        payload = json.loads(resources.path.read_text(encoding="utf-8"))
        payload["tombstones"][0]["deleted_version"] = 99
        resources.path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaises(DududaError):
            JsonMemoryRepository(
                resources.path,
                resources.authority,
                authorization_decision_verifier=resources.policy,
                confirmation_grant_verifier=resources.confirmations,
                clock=lambda: self.now,
            )

    async def test_wrong_service_role_and_query_time_fail_without_state_change(
        self,
    ) -> None:
        resources = self._repository("memory")
        self.addCleanup(resources.close)
        with self.assertRaises(DududaError):
            await resources.repository.export_archive(
                call=self._service_call("memory.export", "memory.restore")
            )
        selector = resources.authority.issue_current_conversation(
            request_digest=self.request_digest,
            actor=self.actor,
            scope=self.scope,
            memory_types=frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
            purpose="time-contract",
        )
        snapshot = await resources.repository.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        with self.assertRaises(DududaError):
            await resources.repository.retrieve(
                snapshot,
                selector,
                MemoryQuery(1, "校园", "zh-CN", self.now - timedelta(days=1)),
                candidate_limit=10,
                cursor=None,
                request_digest=self.request_digest,
                call=self.call,
            )
        self.assertEqual(resources.repository._state_revision, 1)

    async def _assert_not_visible(
        self,
        repository: InMemoryMemoryRepository,
        authority: HmacScopeSelectorAuthority,
    ) -> None:
        selector = authority.issue_current_conversation(
            request_digest=self.request_digest,
            actor=self.actor,
            scope=self.scope,
            memory_types=frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
            purpose="post-lifecycle-contract",
        )
        snapshot = await repository.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        self.assertIsNone(
            await repository.get(
                snapshot,
                "m-1",
                selector,
                request_digest=self.request_digest,
                call=self.call,
            )
        )
        page = await repository.list(
            snapshot,
            selector,
            PageRequest(1, None, 10),
            request_digest=self.request_digest,
            call=self.call,
        )
        self.assertEqual(page.items, ())

    def _repository(self, kind: str) -> RepositoryResources:
        authority = HmacScopeSelectorAuthority(
            b"0123456789abcdef0123456789abcdef",
            policy_revision="memory-policy-v1",
            clock=lambda: self.now,
            id_factory=SequentialIds(f"selector-{kind}"),
        )
        policy = RoleAuthorizationPolicy(
            AuthorizationPolicyConfig(
                "memory-policy-v1",
                {"memory-admin": frozenset({"memory.delete"})},
                {
                    "memory-admin": {
                        "memory.delete": AuthorizationConstraint(
                            frozenset({"memory"}),
                            frozenset({self.record.memory_id}),
                        )
                    }
                },
                confirmation_risks=frozenset(),
            ),
            clock=lambda: self.now,
            id_factory=SequentialIds(f"authorization-{kind}"),
        )
        confirmations = InMemoryConfirmationService(
            policy_revision="memory-policy-v1",
            authorization_verifier=policy,
            clock=lambda: self.now,
            id_factory=SequentialIds(f"confirmation-{kind}"),
        )
        temporary = TemporaryDirectory() if kind == "json" else None
        path = Path(temporary.name) / "memory.json" if temporary else None
        kwargs = {
            "authorization_decision_verifier": policy,
            "confirmation_grant_verifier": confirmations,
            "clock": lambda: self.now,
            "id_factory": SequentialIds(f"repository-{kind}"),
        }
        if path is None:
            repository = InMemoryMemoryRepository(authority, **kwargs)
            repository.seed((self.record,))
        else:
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "repository_revision": "memory-json-v1",
                        "records": [record_to_dict(self.record)],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            repository = JsonMemoryRepository(path, authority, **kwargs)
        return RepositoryResources(
            repository,
            authority,
            policy,
            confirmations,
            self,
            temporary,
            path,
        )

    def _record(self) -> MemoryRecord:
        content = "校园通知在周五发布"
        return MemoryRecord(
            1,
            "m-1",
            MemoryScope(
                1,
                "qq",
                "bot-1",
                ConversationType.GROUP,
                "group-1",
                "group-1",
                "user-1",
                "dududa",
                MemoryType.EXPLICIT_USER_MEMORY,
            ),
            content,
            MemorySource.EXPLICIT_USER_REQUEST,
            self.now - timedelta(days=1),
            self.now - timedelta(hours=1),
            1.0,
            None,
            Sensitivity.PERSONAL,
            Visibility.CURRENT_CONVERSATION,
            (EvidenceReference("e-1", "synthetic", "case-1", "user-1"),),
            memory_content_hash(content),
            1,
        )

    def _service_call(self, operation_kind: str, role: str) -> ServiceCallContext:
        return ServiceCallContext(
            f"operation-{operation_kind}",
            ServicePrincipal("memory-maintenance", "instance-1", frozenset({role})),
            operation_kind,
            TraceContext(f"trace-{operation_kind}"),
            self.now + timedelta(hours=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "memory-policy-v1",
        )


class RepositoryResources:
    def __init__(
        self,
        repository: InMemoryMemoryRepository,
        authority: HmacScopeSelectorAuthority,
        policy: RoleAuthorizationPolicy,
        confirmations: InMemoryConfirmationService,
        fixture: MemoryLifecycleRepositoryContractTests,
        temporary: TemporaryDirectory[str] | None,
        path: Path | None,
    ) -> None:
        self.repository = repository
        self.authority = authority
        self.policy = policy
        self.confirmations = confirmations
        self.fixture = fixture
        self.temporary = temporary
        self.path = path

    async def delete_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> MemoryDeleteCommand:
        actor = self.fixture.actor
        scope = self.fixture.scope
        record = self.fixture.record
        authorization = AuthorizationRequest(
            1,
            DigestString("pending"),
            actor,
            scope,
            ActionId("memory.delete"),
            ResourceRef("memory", record.memory_id, scope_digest(scope)),
            None,
            RiskLevel.HIGH,
            {},
        )
        authorization = replace(
            authorization,
            request_digest=authorization_request_digest(authorization),
        )
        decision = await self.policy.decide(
            authorization,
            call=self.fixture.call,
        )
        if decision.effect is not AuthorizationEffect.ALLOW:
            raise AssertionError("delete authorization fixture must allow")
        payload = memory_delete_payload_digest(
            record.memory_id,
            record.version,
            memory_record_digest(record),
        )
        issue = ConfirmationRequest(
            1,
            DigestString("pending"),
            actor,
            scope,
            ActionId("memory.delete"),
            payload,
            "memory.delete",
            timedelta(minutes=5),
        )
        issue = replace(issue, request_digest=confirmation_request_digest(issue))
        requirement = await self.confirmations.issue(issue, call=self.fixture.call)
        consume = ConfirmationConsumeRequest(
            1,
            DigestString("pending"),
            requirement.confirmation_id,
            actor,
            scope,
            requirement.action,
            requirement.payload_digest,
            requirement.required_permission,
            command_id,
            idempotency_key,
            decision,
        )
        consume = replace(
            consume,
            request_digest=confirmation_consume_request_digest(consume),
        )
        grant = await self.confirmations.consume(consume, call=self.fixture.call)
        command = MemoryDeleteCommand(
            1,
            command_id,
            DigestString("pending"),
            actor,
            scope,
            record.memory_id,
            record.version,
            memory_record_digest(record),
            decision,
            grant,
            idempotency_key,
        )
        return replace(command, request_digest=memory_delete_request_digest(command))

    def close(self) -> None:
        if self.temporary is not None:
            self.temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
