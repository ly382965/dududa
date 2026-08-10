from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.domain.delivery import DeliveryStatus
from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ActionId,
    ComponentRevision,
    ConversationType,
    DigestString,
    RiskLevel,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.memory.digests import memory_content_hash, memory_write_request_digest
from dududa.memory.iris import IrisExactFilter, IrisMemoryRepository, IrisSearchPage
from dududa.memory.models import (
    DeliveryDependency,
    EvidenceReference,
    MemoryCandidate,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryType,
    MemoryWriteAction,
    MemoryWriteRequest,
    Visibility,
)
from dududa.memory.selectors import HmacScopeSelectorAuthority
from dududa.memory.serialization import record_from_dict, record_to_dict
from dududa.memory.write_gate import ExplicitMemoryWriteGate
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)
from dududa.security.digests import actor_digest, scope_digest
from dududa.security.models import AuthorizationDecision, AuthorizationEffect


class FakeIrisBackend:
    def __init__(
        self, records: list[dict[str, object]], *, supported: bool = True
    ) -> None:
        self._records = records
        self._supported = supported
        self.search_calls: list[IrisExactFilter] = []
        self.upsert_calls: list[IrisExactFilter] = []
        self.return_out_of_scope = False

    @property
    def supports_exact_scope(self) -> bool:
        return self._supported

    async def search_exact(self, exact_filter, *, query, as_of, limit, offset):
        self.search_calls.append(exact_filter)
        if self.return_out_of_scope:
            selected = self._records
        else:
            selected = [
                item
                for item in self._records
                if _backend_matches(item, exact_filter, query, as_of)
            ]
            selected += [item for item in self._records if "scope" not in item]
        page = selected[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(selected) else None
        return IrisSearchPage(tuple(page), next_offset, "fake-iris-v1")

    async def get_exact(self, memory_id, exact_filter, *, as_of):
        for item in self._records:
            if item.get("memory_id") == memory_id and _backend_matches(
                item, exact_filter, "", as_of
            ):
                return item
        return None

    async def upsert_scoped(
        self, record, exact_filter, *, expected_version, idempotency_key
    ):
        self.upsert_calls.append(exact_filter)
        decoded = record_from_dict(record)
        self._records = [
            item for item in self._records if item.get("memory_id") != decoded.memory_id
        ]
        self._records.append(dict(record))


class BlockingSearchIrisBackend(FakeIrisBackend):
    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def search_exact(self, exact_filter, *, query, as_of, limit, offset):
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()


class BlockingUpsertIrisBackend(FakeIrisBackend):
    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def upsert_scoped(
        self,
        record,
        exact_filter,
        *,
        expected_version,
        idempotency_key,
    ):
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()


def _backend_matches(
    raw, exact_filter: IrisExactFilter, query: str, as_of: datetime
) -> bool:
    try:
        record = record_from_dict(raw)
    except DududaError:
        return False
    scope = record.scope
    return (
        scope.platform == exact_filter.platform
        and scope.bot_id == exact_filter.bot_id
        and scope.persona_id == exact_filter.persona_id
        and scope.conversation_id == exact_filter.conversation_id
        and scope.group_id == exact_filter.group_id
        and scope.user_id == exact_filter.user_id
        and scope.memory_type in exact_filter.memory_types
        and (record.expires_at is None or record.expires_at > as_of)
        and (not query or query.casefold() in record.content.casefold())
    )


class IrisMemoryRepositoryContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.actor = Actor(
            "qq", "bot-1", "u-1", frozenset({RoleId("normal")}), frozenset()
        )
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
        )
        self.request_digest = DigestString("query-request")
        self.authority = HmacScopeSelectorAuthority(
            b"0123456789abcdef0123456789abcdef",
            policy_revision="memory-policy-v1",
            clock=lambda: self.now,
            id_factory=lambda: "selector-1",
        )
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(minutes=5),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "policy-v1",
        )

    def record(
        self, memory_id: str, *, group: str = "g-1", user: str = "u-1"
    ) -> MemoryRecord:
        content = f"needle {memory_id}"
        return MemoryRecord(
            1,
            memory_id,
            MemoryScope(
                1,
                "qq",
                "bot-1",
                ConversationType.GROUP,
                group,
                group,
                user,
                "dududa",
                MemoryType.EXPLICIT_USER_MEMORY,
            ),
            content,
            MemorySource.EXPLICIT_USER_REQUEST,
            self.now - timedelta(minutes=1),
            self.now - timedelta(minutes=1),
            1.0,
            None,
            Sensitivity.PERSONAL,
            Visibility.CURRENT_CONVERSATION,
            (EvidenceReference("e-1", "message", "m-1", user),),
            memory_content_hash(content),
            1,
        )

    def selector(self):
        return self.authority.issue_current_conversation(
            request_digest=self.request_digest,
            actor=self.actor,
            scope=self.scope,
            memory_types=frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
            purpose="context",
        )

    async def test_unsupported_lifecycle_never_mutates_local_or_backend_state(
        self,
    ) -> None:
        backend = FakeIrisBackend([record_to_dict(self.record("target"))])
        repository = IrisMemoryRepository(
            backend, self.authority, clock=lambda: self.now
        )
        with self.assertRaises(DududaError):
            await repository.commit_delete(object(), call=self.call)  # type: ignore[arg-type]
        self.assertEqual(backend.search_calls, [])
        self.assertEqual(backend.upsert_calls, [])
        self.assertEqual(repository._records, {})
        self.assertEqual(repository._tombstones, {})

    async def write_command(self, backend):
        authorization = AuthorizationDecision(
            1,
            "auth-1",
            AuthorizationEffect.ALLOW,
            DigestString("request"),
            actor_digest(self.actor),
            scope_digest(self.scope),
            ActionId("memory.write"),
            DigestString("resource"),
            None,
            RiskLevel.MEDIUM,
            DigestString("metadata"),
            "policy-v1",
            (),
            self.now,
            self.now + timedelta(minutes=5),
        )
        candidate = MemoryCandidate(
            1,
            "candidate-1",
            ComponentRevision("legacy.remember", "1", "cfg", DigestString("artifact")),
            "我喜欢简洁回答",
            MemorySource.EXPLICIT_USER_REQUEST,
            MemoryType.EXPLICIT_USER_MEMORY,
            MemoryScope(
                1,
                "qq",
                "bot-1",
                ConversationType.GROUP,
                "g-1",
                "g-1",
                "u-1",
                "dududa",
                MemoryType.EXPLICIT_USER_MEMORY,
            ),
            1.0,
            Sensitivity.PERSONAL,
            (EvidenceReference("e-1", "message", "m-1", "u-1"),),
            None,
            DeliveryDependency.NONE,
        )
        request = MemoryWriteRequest(
            1,
            DigestString("pending"),
            candidate,
            self.actor,
            self.scope,
            DeliveryStatus.NOT_REQUIRED,
            None,
            None,
            None,
            authorization,
            "write-key-1",
        )
        request = replace(request, request_digest=memory_write_request_digest(request))
        ids = iter(("memory-1", "decision-1"))
        gate = ExplicitMemoryWriteGate(
            clock=lambda: self.now, id_factory=lambda: next(ids)
        )
        repository = IrisMemoryRepository(
            backend,
            self.authority,
            write_decision_verifier=gate,
            clock=lambda: self.now,
        )
        decision = await gate.evaluate(request, call=self.call)
        command = gate.command(request, decision, command_id="command-1")
        return repository, decision, command

    async def test_exact_query_quarantines_missing_metadata_without_global_fallback(
        self,
    ) -> None:
        backend = FakeIrisBackend(
            [
                record_to_dict(self.record("target")),
                record_to_dict(self.record("other-group", group="g-2")),
                record_to_dict(self.record("other-user", user="u-2")),
                {"schema_version": 1, "memory_id": "missing-scope"},
            ]
        )
        repository = IrisMemoryRepository(
            backend, self.authority, clock=lambda: self.now
        )
        selector = self.selector()
        snapshot = await repository.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        page = await repository.retrieve(
            snapshot,
            selector,
            MemoryQuery(1, "needle", "zh-CN", self.now),
            candidate_limit=10,
            cursor=None,
            request_digest=self.request_digest,
            call=self.call,
        )
        self.assertEqual([item.memory_id for item in page.items], ["target"])
        self.assertEqual(len(repository.quarantine.records), 1)
        self.assertEqual(len(backend.search_calls), 1)
        self.assertEqual(backend.search_calls[0].group_id, "g-1")
        self.assertEqual(backend.search_calls[0].user_id, "u-1")

    async def test_missing_capability_and_out_of_scope_backend_result_fail_closed(
        self,
    ) -> None:
        unsupported = IrisMemoryRepository(
            FakeIrisBackend([], supported=False), self.authority, clock=lambda: self.now
        )
        with self.assertRaises(DududaError):
            await unsupported.open_snapshot(
                (self.selector(),),
                request_digest=self.request_digest,
                as_of=self.now,
                call=self.call,
            )
        backend = FakeIrisBackend([record_to_dict(self.record("other", group="g-2"))])
        backend.return_out_of_scope = True
        repository = IrisMemoryRepository(
            backend, self.authority, clock=lambda: self.now
        )
        selector = self.selector()
        snapshot = await repository.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        with self.assertRaises(DududaError):
            await repository.retrieve(
                snapshot,
                selector,
                MemoryQuery(1, "", "zh-CN", self.now),
                candidate_limit=10,
                cursor=None,
                request_digest=self.request_digest,
                call=self.call,
            )

    async def test_explicit_write_uses_scoped_upsert(self) -> None:
        backend = FakeIrisBackend([])
        repository, decision, command = await self.write_command(backend)
        self.assertEqual(decision.action, MemoryWriteAction.ALLOW)
        await repository.commit_write(command, call=self.call)
        self.assertEqual(len(backend.upsert_calls), 1)
        self.assertEqual(backend.upsert_calls[0].conversation_id, "g-1")
        self.assertEqual(backend.upsert_calls[0].user_id, "u-1")

    async def test_backend_wait_honors_deadline_and_cancellation(self) -> None:
        backend = BlockingSearchIrisBackend()
        repository = IrisMemoryRepository(
            backend, self.authority, clock=lambda: self.now
        )
        selector = self.selector()
        snapshot = await repository.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        expired = replace(self.call, deadline=self.now)
        with self.assertRaises(DududaError):
            await repository.retrieve(
                snapshot,
                selector,
                MemoryQuery(1, "", "zh-CN", self.now),
                candidate_limit=10,
                cursor=None,
                request_digest=self.request_digest,
                call=expired,
            )
        self.assertFalse(backend.started.is_set())

        cancellation = ManualCancellationToken()
        call = replace(self.call, cancellation=cancellation)
        task = asyncio.create_task(
            repository.retrieve(
                snapshot,
                selector,
                MemoryQuery(1, "", "zh-CN", self.now),
                candidate_limit=10,
                cursor=None,
                request_digest=self.request_digest,
                call=call,
            )
        )
        await backend.started.wait()
        cancellation.cancel()
        with self.assertRaises(DududaError):
            await asyncio.wait_for(task, timeout=0.5)
        self.assertTrue(backend.cancelled.is_set())

    async def test_cancelled_backend_write_rolls_back_local_state(self) -> None:
        backend = BlockingUpsertIrisBackend()
        repository, _, command = await self.write_command(backend)
        task = asyncio.create_task(repository.commit_write(command, call=self.call))
        await backend.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(backend.cancelled.is_set())
        self.assertEqual(repository._records, {})
        self.assertEqual(repository._idempotency, {})
        self.assertEqual(repository._consumed_decisions, set())


if __name__ == "__main__":
    unittest.main()
