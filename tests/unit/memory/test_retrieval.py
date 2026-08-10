from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.domain.identity import Actor, ConversationScope
from dududa.domain.primitives import (
    ComponentRevision,
    ConversationType,
    DigestString,
    RoleId,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.memory.digests import (
    memory_content_hash,
    memory_retrieval_request_digest,
    memory_retrieval_result_digest,
)
from dududa.memory.lexical import CjkBm25MemoryRanker
from dududa.memory.models import (
    EvidenceReference,
    MemoryQuery,
    MemoryRankRequest,
    MemoryRankScore,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalStrategy,
    MemoryScope,
    MemorySource,
    MemoryType,
    Visibility,
)
from dududa.memory.repository import InMemoryMemoryRepository
from dududa.memory.retrieval import (
    DeterministicMemoryRetrievalPolicy,
    DeterministicScopedMemoryRetriever,
)
from dududa.memory.selectors import HmacScopeSelectorAuthority
from dududa.ports.context import NeverCancelled, PortCallContext
from dududa.ports.memory import ScopedMemoryRetriever


class SequentialIds:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.prefix}-{self.value}"


class RecordingRanker:
    def __init__(self, delegate: CjkBm25MemoryRanker) -> None:
        self.delegate = delegate
        self.requests: list[MemoryRankRequest] = []

    @property
    def ranker_revision(self) -> ComponentRevision:
        return self.delegate.ranker_revision

    async def rank(self, request, *, call):
        self.requests.append(request)
        return await self.delegate.rank(request, call=call)


class UnknownIdRanker:
    def __init__(self) -> None:
        self._revision = ComponentRevision(
            "memory.bad-ranker", "1", "bad", DigestString("synthetic")
        )

    @property
    def ranker_revision(self) -> ComponentRevision:
        return self._revision

    async def rank(self, request, *, call):
        del call
        return (
            MemoryRankScore(
                1,
                "unknown-memory",
                DigestString("unknown-content"),
                DigestString("unknown-scope"),
                Decimal(1),
                self._revision,
            ),
        )


class CountingRepository(InMemoryMemoryRepository):
    def __init__(self, authority: object, **kwargs: object) -> None:
        super().__init__(authority, **kwargs)
        self.open_calls = 0

    async def open_snapshot(self, *args, **kwargs):
        self.open_calls += 1
        return await super().open_snapshot(*args, **kwargs)


class CountingPolicy(DeterministicMemoryRetrievalPolicy):
    def __init__(self, authority: object, **kwargs: object) -> None:
        super().__init__(authority, **kwargs)
        self.selector_calls = 0

    async def selectors_for(self, request, *, call):
        self.selector_calls += 1
        return await super().selectors_for(request, call=call)


class ScopedMemoryRetrieverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.actor = Actor(
            "qq", "bot-1", "user-1", frozenset({RoleId("normal")}), frozenset()
        )
        self.scope = ConversationScope(
            "qq", "bot-1", ConversationType.GROUP, "group-1", "group-1", "dududa"
        )
        self.authority = HmacScopeSelectorAuthority(
            b"0123456789abcdef0123456789abcdef",
            policy_revision="memory-policy-v1",
            clock=lambda: self.now,
            id_factory=SequentialIds("selector"),
        )
        self.policy = DeterministicMemoryRetrievalPolicy(
            self.authority,
            policy_revision="memory-policy-v1",
            clock=lambda: self.now,
        )
        self.call = PortCallContext(
            "retrieval-run-1",
            TraceContext("retrieval-trace-1"),
            self.now + timedelta(minutes=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "memory-policy-v1",
        )

    async def test_m0_performs_zero_policy_repository_and_ranker_calls(self) -> None:
        repository = CountingRepository(
            self.authority,
            clock=lambda: self.now,
            id_factory=SequentialIds("snapshot"),
        )
        policy = CountingPolicy(
            self.authority,
            policy_revision="memory-policy-v1",
            clock=lambda: self.now,
        )
        ranker = RecordingRanker(CjkBm25MemoryRanker(clock=lambda: self.now))
        retriever = DeterministicScopedMemoryRetriever(
            repository,
            policy,
            ranker=ranker,
            clock=lambda: self.now,
        )
        self.assertIsInstance(retriever, ScopedMemoryRetriever)
        result = await retriever.retrieve(
            self._request(MemoryRetrievalStrategy.NO_MEMORY),
            call=self.call,
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(policy.selector_calls, 0)
        self.assertEqual(repository.open_calls, 0)
        self.assertEqual(ranker.requests, [])

    async def test_m1_and_m2_share_exact_candidates_but_rank_independently(
        self,
    ) -> None:
        repository = self._repository(
            self._record("new-unrelated", "今晚聚餐", minutes_ago=1),
            self._record("old-target", "校园通知周五发布", minutes_ago=30),
            self._record(
                "other-group",
                "校园通知周五发布",
                minutes_ago=1,
                group="group-2",
            ),
            self._record(
                "expired",
                "校园通知周五发布",
                minutes_ago=2,
                expires_at=self.now - timedelta(seconds=1),
            ),
            replace(
                self._record("future", "校园通知周五发布", minutes_ago=1),
                created_at=self.now + timedelta(minutes=1),
                updated_at=self.now + timedelta(minutes=1),
            ),
            self._record(
                "restricted",
                "校园通知周五发布",
                minutes_ago=3,
                sensitivity=Sensitivity.RESTRICTED,
            ),
        )
        recency = DeterministicScopedMemoryRetriever(
            repository,
            self.policy,
            clock=lambda: self.now,
        )
        recency_result = await recency.retrieve(
            self._request(MemoryRetrievalStrategy.RECENCY, limit=5),
            call=self.call,
        )
        self.assertEqual(
            [item.record.memory_id for item in recency_result.matches],
            ["new-unrelated", "old-target"],
        )
        self.assertIn("restricted_memory_excluded", recency_result.reason_codes)

        recording = RecordingRanker(CjkBm25MemoryRanker(clock=lambda: self.now))
        bm25 = DeterministicScopedMemoryRetriever(
            repository,
            self.policy,
            ranker=recording,
            clock=lambda: self.now,
        )
        bm25_result = await bm25.retrieve(
            self._request(MemoryRetrievalStrategy.CJK_BM25, limit=5),
            call=self.call,
        )
        self.assertEqual(
            [item.record.memory_id for item in bm25_result.matches],
            ["old-target"],
        )
        self.assertFalse(bm25_result.degraded)
        self.assertEqual(len(recording.requests), 1)
        self.assertEqual(
            {item.memory_id for item in recording.requests[0].projections},
            {"new-unrelated", "old-target"},
        )
        self.assertEqual(
            memory_retrieval_result_digest(bm25_result),
            bm25_result.result_digest,
        )

    async def test_ranker_unknown_id_degrades_only_within_same_candidates(self) -> None:
        repository = self._repository(
            self._record("newer", "聚餐", minutes_ago=1),
            self._record("older", "校园通知", minutes_ago=2),
        )
        retriever = DeterministicScopedMemoryRetriever(
            repository,
            self.policy,
            ranker=UnknownIdRanker(),
            clock=lambda: self.now,
        )
        degraded = await retriever.retrieve(
            self._request(MemoryRetrievalStrategy.CJK_BM25),
            call=self.call,
        )
        self.assertTrue(degraded.degraded)
        self.assertIn("ranker_output_invalid", degraded.reason_codes)
        self.assertEqual(
            [item.record.memory_id for item in degraded.matches],
            ["newer", "older"],
        )
        disabled = await retriever.retrieve(
            self._request(
                MemoryRetrievalStrategy.CJK_BM25,
                allow_recency_degrade=False,
            ),
            call=self.call,
        )
        self.assertTrue(disabled.degraded)
        self.assertEqual(disabled.matches, ())

    async def test_named_selectors_cover_types_without_cross_user_widening(
        self,
    ) -> None:
        repository = self._repository(
            self._record("explicit", "显式记忆", minutes_ago=1),
            self._record(
                "episodic",
                "情景记忆",
                minutes_ago=2,
                memory_type=MemoryType.EPISODIC,
            ),
            self._record(
                "group",
                "群记忆",
                minutes_ago=3,
                memory_type=MemoryType.GROUP_MEMORY,
                visibility=Visibility.CURRENT_GROUP,
                user=None,
            ),
            self._record(
                "profile",
                "安全画像",
                minutes_ago=4,
                group="group-2",
                memory_type=MemoryType.USER_PROFILE,
                visibility=Visibility.SAFE_USER_PROFILE,
            ),
            self._record(
                "other-profile",
                "其他用户画像",
                minutes_ago=1,
                group="group-2",
                memory_type=MemoryType.USER_PROFILE,
                visibility=Visibility.SAFE_USER_PROFILE,
                user="user-2",
            ),
        )
        retriever = DeterministicScopedMemoryRetriever(
            repository,
            self.policy,
            clock=lambda: self.now,
        )
        result = await retriever.retrieve(
            self._request(
                MemoryRetrievalStrategy.RECENCY,
                limit=10,
                candidate_limit_total=40,
                memory_types=frozenset(MemoryType),
            ),
            call=self.call,
        )
        self.assertEqual(
            {item.record.memory_id for item in result.matches},
            {"explicit", "episodic", "group", "profile"},
        )

    async def test_candidate_caps_apply_before_bm25_and_single_han_degrades(
        self,
    ) -> None:
        repository = self._repository(
            *(
                self._record(f"m-{index}", f"校园通知 {index}", minutes_ago=index)
                for index in range(1, 6)
            )
        )
        recording = RecordingRanker(CjkBm25MemoryRanker(clock=lambda: self.now))
        retriever = DeterministicScopedMemoryRetriever(
            repository,
            self.policy,
            ranker=recording,
            clock=lambda: self.now,
        )
        result = await retriever.retrieve(
            self._request(
                MemoryRetrievalStrategy.CJK_BM25,
                limit=2,
                candidate_limit_per_type=2,
                candidate_limit_total=2,
            ),
            call=self.call,
        )
        self.assertFalse(result.degraded)
        self.assertEqual(len(recording.requests[0].projections), 2)
        short = await retriever.retrieve(
            self._request(MemoryRetrievalStrategy.CJK_BM25, query="校"),
            call=self.call,
        )
        self.assertTrue(short.degraded)
        self.assertIn("lexical_query_too_short", short.reason_codes)
        self.assertIn("degraded_to_recency", short.reason_codes)

    def _repository(self, *records: MemoryRecord) -> InMemoryMemoryRepository:
        repository = InMemoryMemoryRepository(
            self.authority,
            clock=lambda: self.now,
            id_factory=SequentialIds("snapshot"),
        )
        repository.seed(records)
        return repository

    def _request(
        self,
        strategy: MemoryRetrievalStrategy,
        *,
        query: str = "校园通知",
        limit: int = 5,
        candidate_limit_per_type: int = 10,
        candidate_limit_total: int = 10,
        allow_recency_degrade: bool = True,
        memory_types: frozenset[MemoryType] = frozenset(
            {MemoryType.EXPLICIT_USER_MEMORY}
        ),
    ) -> MemoryRetrievalRequest:
        request = MemoryRetrievalRequest(
            1,
            f"query-{strategy.value}",
            DigestString("pending"),
            self.actor,
            self.scope,
            MemoryQuery(1, query, "zh-CN", self.now),
            memory_types,
            strategy,
            limit,
            candidate_limit_per_type,
            candidate_limit_total,
            self.now,
            allow_recency_degrade,
        )
        return replace(
            request,
            request_digest=memory_retrieval_request_digest(request),
        )

    def _record(
        self,
        memory_id: str,
        content: str,
        *,
        minutes_ago: int,
        group: str = "group-1",
        sensitivity: Sensitivity = Sensitivity.PERSONAL,
        expires_at: datetime | None = None,
        memory_type: MemoryType = MemoryType.EXPLICIT_USER_MEMORY,
        visibility: Visibility = Visibility.CURRENT_CONVERSATION,
        user: str | None = "user-1",
    ) -> MemoryRecord:
        created_at = self.now - timedelta(days=1)
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
                memory_type,
            ),
            content,
            MemorySource.EXPLICIT_USER_REQUEST,
            created_at,
            self.now - timedelta(minutes=minutes_ago),
            1.0,
            expires_at,
            sensitivity,
            visibility,
            (EvidenceReference(f"e-{memory_id}", "synthetic", "case-1"),),
            memory_content_hash(content),
            1,
        )


if __name__ == "__main__":
    unittest.main()
