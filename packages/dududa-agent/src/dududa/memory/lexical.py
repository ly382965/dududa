from __future__ import annotations

import math
import unicodedata
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal

from dududa.contracts.canonical import canonical_digest
from dududa.domain.primitives import ComponentRevision, DigestString
from dududa.errors import ErrorCategory, error
from dududa.ports.context import PortCallContext

from .digests import memory_rank_request_digest
from .models import MemoryRankRequest, MemoryRankScore

_K1 = 1.2
_B = 0.75
_SCORE_QUANTUM = Decimal("0.000000000001")
_HAN_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0x20000, 0x2EBEF),
    (0x30000, 0x323AF),
)


class CjkBm25MemoryRanker:
    """Deterministic Okapi BM25 over an already-authorized bounded projection."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        config_digest = canonical_digest(
            {
                "algorithm": "okapi-bm25",
                "projection": "cjk-bigram-nfc-casefold-v1",
                "han_ranges": _HAN_RANGES,
                "k1": Decimal("1.2"),
                "b": Decimal("0.75"),
                "idf": "ln(1+(N-df+0.5)/(df+0.5))",
                "query_terms": "deduplicated",
                "score_quantum": str(_SCORE_QUANTUM),
                "tie_break": "memory_id_ascending",
            },
            domain="memory:cjk-bm25-config:v1",
        )
        self._revision = ComponentRevision(
            "memory.cjk-bm25-ranker",
            "1",
            str(config_digest),
            DigestString("stdlib-pure-python"),
        )

    @property
    def ranker_revision(self) -> ComponentRevision:
        return self._revision

    async def rank(
        self,
        request: MemoryRankRequest,
        *,
        call: PortCallContext,
    ) -> tuple[MemoryRankScore, ...]:
        _validate_call(call, self._clock())
        if memory_rank_request_digest(request) != request.request_digest:
            raise _lexical_error("memory_rank_request_digest_mismatch")
        query_terms = tuple(sorted(set(cjk_bm25_terms(request.query))))
        if not query_terms:
            raise _lexical_error("memory_lexical_query_too_short")

        documents = tuple(
            (projection, cjk_bm25_terms(projection.text))
            for projection in request.projections
        )
        document_count = len(documents)
        average_length = sum(len(terms) for _, terms in documents) / document_count
        if average_length == 0:
            return ()
        document_frequency = {
            term: sum(term in terms for _, terms in documents) for term in query_terms
        }
        scores: list[MemoryRankScore] = []
        for projection, terms in documents:
            counts = Counter(terms)
            raw_score = 0.0
            for term in query_terms:
                frequency = counts[term]
                df = document_frequency[term]
                if frequency == 0 or df == 0:
                    continue
                inverse_document_frequency = math.log(
                    1 + (document_count - df + 0.5) / (df + 0.5)
                )
                denominator = frequency + _K1 * (
                    1 - _B + _B * len(terms) / average_length
                )
                raw_score += inverse_document_frequency * (
                    frequency * (_K1 + 1) / denominator
                )
            score = Decimal(str(raw_score)).quantize(
                _SCORE_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            )
            if score > 0:
                scores.append(
                    MemoryRankScore(
                        1,
                        projection.memory_id,
                        projection.content_digest,
                        projection.scope_digest,
                        score,
                        self._revision,
                    )
                )
        scores.sort(key=lambda item: (-item.score, item.memory_id))
        _validate_call(call, self._clock())
        return tuple(scores[: request.limit])


def cjk_bm25_terms(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFC", value).casefold()
    terms: list[str] = []
    ascii_run: list[str] = []
    han_run: list[str] = []

    def flush_ascii() -> None:
        if ascii_run:
            terms.append("a:" + "".join(ascii_run))
            ascii_run.clear()

    def flush_han() -> None:
        if len(han_run) >= 2:
            terms.extend(
                "h:" + han_run[index] + han_run[index + 1]
                for index in range(len(han_run) - 1)
            )
        han_run.clear()

    for character in normalized:
        codepoint = ord(character)
        if 0x30 <= codepoint <= 0x39 or 0x61 <= codepoint <= 0x7A:
            flush_han()
            ascii_run.append(character)
        elif _is_han(codepoint):
            flush_ascii()
            han_run.append(character)
        else:
            flush_ascii()
            flush_han()
    flush_ascii()
    flush_han()
    return tuple(terms)


def _is_han(codepoint: int) -> bool:
    return any(start <= codepoint <= end for start, end in _HAN_RANGES)


def _validate_call(call: PortCallContext, now: datetime) -> None:
    if call.cancellation.is_cancelled:
        raise _lexical_error(
            "memory_rank_cancelled",
            ErrorCategory.CANCELLED,
        )
    if call.deadline <= now:
        raise _lexical_error(
            "memory_rank_deadline_exceeded",
            ErrorCategory.TIMEOUT,
        )


def _lexical_error(
    code: str,
    category: ErrorCategory = ErrorCategory.VALIDATION,
):
    return error(code, category, "memory.ranking_unavailable")


__all__ = ["CjkBm25MemoryRanker", "cjk_bm25_terms"]
