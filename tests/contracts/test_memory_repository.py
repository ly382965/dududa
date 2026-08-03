from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ConversationType,
    DigestString,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.memory.digests import memory_content_hash
from dududa.memory.json_repository import JsonMemoryRepository
from dududa.memory.models import (
    EvidenceReference,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryType,
    ScopeSelector,
    Visibility,
)
from dududa.memory.repository import InMemoryMemoryRepository
from dududa.memory.selectors import HmacScopeSelectorAuthority
from dududa.memory.serialization import record_to_dict
from dududa.ports.context import (
    ManualCancellationToken,
    NeverCancelled,
    PortCallContext,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class MemoryRepositoryContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.clock = MutableClock(self.now)
        self.request_digest = DigestString("memory-query-request")
        self.authority = HmacScopeSelectorAuthority(
            b"0123456789abcdef0123456789abcdef",
            policy_revision="memory-policy-v1",
            clock=self.clock,
            id_factory=lambda: "selector-1",
        )
        self.actor = Actor(
            "qq", "bot-1", "u-1", frozenset({RoleId("normal")}), frozenset()
        )
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "g-1", "g-1", "dududa"
        )
        self.call = PortCallContext(
            "run-1",
            TraceContext("trace-1"),
            self.now + timedelta(hours=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal("0")),
            "policy-v1",
        )

    def record(
        self,
        memory_id: str,
        *,
        platform: str = "qq",
        bot: str = "bot-1",
        conversation_type: ConversationType = ConversationType.GROUP,
        conversation: str = "g-1",
        group: str | None = "g-1",
        user: str = "u-1",
        persona: str = "dududa",
        expires_at: datetime | None = None,
    ) -> MemoryRecord:
        content = f"needle {memory_id}"
        return MemoryRecord(
            1,
            memory_id,
            MemoryScope(
                1,
                platform,
                bot,
                conversation_type,
                conversation,
                group,
                user,
                persona,
                MemoryType.EXPLICIT_USER_MEMORY,
            ),
            content,
            MemorySource.EXPLICIT_USER_REQUEST,
            self.now - timedelta(minutes=2),
            self.now - timedelta(minutes=1),
            1.0,
            expires_at,
            Sensitivity.PERSONAL,
            Visibility.CURRENT_CONVERSATION,
            (EvidenceReference(f"e-{memory_id}", "message", "m-1", user),),
            memory_content_hash(content),
            1,
        )

    def records(self) -> list[MemoryRecord]:
        return [
            self.record("target"),
            self.record("other-platform", platform="discord"),
            self.record("other-bot", bot="bot-2"),
            self.record("other-group", conversation="g-2", group="g-2"),
            self.record("other-user", user="u-2"),
            self.record("other-persona", persona="other"),
            self.record(
                "private-origin",
                conversation_type=ConversationType.PRIVATE,
                conversation="private:u-1",
                group=None,
            ),
            self.record("expired", expires_at=self.now - timedelta(seconds=1)),
        ]

    def selector(self) -> ScopeSelector:
        return self.authority.issue_current_conversation(
            request_digest=self.request_digest,
            actor=self.actor,
            scope=self.scope,
            memory_types=frozenset({MemoryType.EXPLICIT_USER_MEMORY}),
            purpose="context",
        )

    async def repositories(self):
        memory = InMemoryMemoryRepository(
            self.authority,
            clock=self.clock,
            id_factory=lambda: "snapshot-memory",
        )
        memory.seed(self.records())
        temporary = TemporaryDirectory()
        path = Path(temporary.name) / "memory-v2.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repository_revision": "memory-json-v1",
                    "records": [record_to_dict(item) for item in self.records()],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        json_repo = JsonMemoryRepository(
            path,
            self.authority,
            clock=self.clock,
            id_factory=lambda: "snapshot-json",
        )
        return temporary, (memory, json_repo)

    async def test_complete_isolation_matrix_on_memory_and_json(self) -> None:
        temporary, repositories = await self.repositories()
        self.addCleanup(temporary.cleanup)
        selector = self.selector()
        for repository in repositories:
            with self.subTest(repository=type(repository).__name__):
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
                    candidate_limit=100,
                    cursor=None,
                    request_digest=self.request_digest,
                    call=self.call,
                )
                self.assertEqual([item.memory_id for item in page.items], ["target"])

    async def test_forged_expired_selector_and_cursor_fail_closed(self) -> None:
        repository = InMemoryMemoryRepository(
            self.authority,
            clock=self.clock,
            id_factory=lambda: "snapshot-1",
        )
        repository.seed([self.record("a"), self.record("b")])
        selector = self.selector()
        forged = replace(selector, user_id="u-2")
        with self.assertRaises(DududaError):
            await repository.open_snapshot(
                (forged,),
                request_digest=self.request_digest,
                as_of=self.now,
                call=self.call,
            )
        snapshot = await repository.open_snapshot(
            (selector,),
            request_digest=self.request_digest,
            as_of=self.now,
            call=self.call,
        )
        query = MemoryQuery(1, "needle", "zh-CN", self.now)
        first = await repository.retrieve(
            snapshot,
            selector,
            query,
            candidate_limit=1,
            cursor=None,
            request_digest=self.request_digest,
            call=self.call,
        )
        self.assertIsNotNone(first.next_cursor)
        with self.assertRaises(DududaError):
            await repository.retrieve(
                snapshot,
                selector,
                query,
                candidate_limit=1,
                cursor=str(first.next_cursor) + "tampered",
                request_digest=self.request_digest,
                call=self.call,
            )
        self.clock.value += timedelta(minutes=2)
        with self.assertRaises(DududaError):
            await repository.get(
                snapshot,
                "a",
                selector,
                request_digest=self.request_digest,
                call=self.call,
            )

    async def test_deadline_and_cancellation_bound_repository_waits(self) -> None:
        repository = InMemoryMemoryRepository(
            self.authority,
            clock=self.clock,
            id_factory=lambda: "snapshot-call",
        )
        selector = self.selector()
        expired = replace(self.call, deadline=self.now)
        with self.assertRaises(DududaError):
            await repository.open_snapshot(
                (selector,),
                request_digest=self.request_digest,
                as_of=self.now,
                call=expired,
            )

        cancellation = ManualCancellationToken()
        blocked = replace(self.call, cancellation=cancellation)
        await repository._lock.acquire()
        task = asyncio.create_task(
            repository.open_snapshot(
                (selector,),
                request_digest=self.request_digest,
                as_of=self.now,
                call=blocked,
            )
        )
        try:
            await asyncio.sleep(0)
            cancellation.cancel()
            with self.assertRaises(DududaError):
                await asyncio.wait_for(task, timeout=0.5)
        finally:
            repository._lock.release()


if __name__ == "__main__":
    unittest.main()
