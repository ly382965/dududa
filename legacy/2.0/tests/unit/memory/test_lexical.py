from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dududa.domain.primitives import (
    DigestString,
    RuntimeBudget,
    Sensitivity,
    TraceContext,
)
from dududa.errors import DududaError
from dududa.memory.digests import memory_rank_request_digest
from dududa.memory.lexical import CjkBm25MemoryRanker, cjk_bm25_terms
from dududa.memory.models import (
    IndexableMemoryProjection,
    MemoryRankRequest,
    Visibility,
)
from dududa.ports.context import NeverCancelled, PortCallContext


class CjkBm25MemoryRankerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.call = PortCallContext(
            "rank-run-1",
            TraceContext("rank-trace-1"),
            self.now + timedelta(minutes=1),
            NeverCancelled(),
            RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
            "memory-policy-v1",
        )
        self.ranker = CjkBm25MemoryRanker(clock=lambda: self.now)

    def test_projection_is_nfc_casefolded_and_uses_explicit_token_classes(
        self,
    ) -> None:
        self.assertEqual(
            cjk_bm25_terms("校园通知 Python3.12 😊 “引用”"),
            (
                "h:校园",
                "h:园通",
                "h:通知",
                "a:python3",
                "a:12",
                "h:引用",
            ),
        )
        self.assertEqual(cjk_bm25_terms("Cafe\u0301"), cjk_bm25_terms("CAFÉ"))
        self.assertEqual(cjk_bm25_terms("校"), ())
        self.assertNotEqual(cjk_bm25_terms("校园"), cjk_bm25_terms("校因"))

    async def test_okapi_scores_and_tie_break_are_stable(self) -> None:
        request = self._request(
            "校园通知",
            (
                self._projection("m-newer", "校园活动 周六"),
                self._projection("m-target", "校园通知 周五发布"),
                self._projection("m-unrelated", "Python 3.12 release"),
            ),
        )
        scores = await self.ranker.rank(request, call=self.call)
        self.assertEqual([item.memory_id for item in scores], ["m-target", "m-newer"])
        self.assertEqual(
            [str(item.score) for item in scores],
            ["2.177185865299", "0.499176268302"],
        )
        self.assertTrue(
            all(item.ranker_revision == self.ranker.ranker_revision for item in scores)
        )

    async def test_short_query_tamper_and_expired_call_fail_closed(self) -> None:
        with self.assertRaises(DududaError):
            await self.ranker.rank(
                self._request("校", (self._projection("m-1", "校园"),)),
                call=self.call,
            )
        request = self._request("校园", (self._projection("m-1", "校园"),))
        with self.assertRaises(DududaError):
            await self.ranker.rank(
                replace(request, query="课程"),
                call=self.call,
            )
        with self.assertRaises(DududaError):
            await self.ranker.rank(
                request,
                call=replace(self.call, deadline=self.now),
            )

    async def test_equal_scores_use_only_ascending_memory_id(self) -> None:
        projections = (
            self._projection("m-b", "校园通知"),
            self._projection("m-a", "校园通知"),
        )
        single = await self.ranker.rank(
            self._request("校园", projections),
            call=self.call,
        )
        repeated = await self.ranker.rank(
            self._request("校园 校园", projections),
            call=self.call,
        )
        self.assertEqual([item.memory_id for item in single], ["m-a", "m-b"])
        self.assertEqual(
            [item.score for item in repeated],
            [item.score for item in single],
        )

    def _request(
        self,
        query: str,
        projections: tuple[IndexableMemoryProjection, ...],
    ) -> MemoryRankRequest:
        request = MemoryRankRequest(
            1,
            DigestString("pending"),
            query,
            projections,
            len(projections),
            1,
        )
        return replace(request, request_digest=memory_rank_request_digest(request))

    def _projection(self, memory_id: str, text: str) -> IndexableMemoryProjection:
        return IndexableMemoryProjection(
            1,
            memory_id,
            text,
            DigestString(f"content-{memory_id}"),
            DigestString(f"scope-{memory_id}"),
            Sensitivity.PERSONAL,
            Visibility.CURRENT_CONVERSATION,
            self.now,
        )


if __name__ == "__main__":
    unittest.main()
