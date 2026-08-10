from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from dududa.domain.primitives import ComponentRevision, DigestString, Sensitivity
from dududa.errors import DududaError, ErrorCategory, error
from dududa.ports.context import PortCallContext
from dududa.ports.memory import MemoryRanker, MemoryRepository, MemoryRetrievalPolicy

from .digests import (
    memory_rank_request_digest,
    memory_retrieval_request_digest,
    memory_retrieval_result_digest,
    memory_scope_digest,
)
from .models import (
    IndexableMemoryProjection,
    MemoryMatch,
    MemoryQuery,
    MemoryRankRequest,
    MemoryRankScore,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemoryRetrievalStrategy,
    MemoryType,
    ScopeSelector,
    SelectorMode,
    Visibility,
)


class DeterministicMemoryRetrievalPolicy:
    def __init__(
        self,
        selector_authority: object,
        *,
        policy_revision: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not policy_revision.strip():
            raise ValueError("memory retrieval policy revision is required")
        required = (
            "issue_current_conversation",
            "issue_current_group",
            "issue_safe_user_profile",
        )
        if any(
            not callable(getattr(selector_authority, name, None)) for name in required
        ):
            raise TypeError("selector authority does not implement named selectors")
        self._selector_authority = selector_authority
        self._policy_revision = policy_revision
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def policy_revision(self) -> str:
        return self._policy_revision

    async def selectors_for(
        self,
        request: MemoryRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> tuple[ScopeSelector, ...]:
        _validate_call(call, self._clock())
        _validate_request(request)
        selectors: list[ScopeSelector] = []
        purpose = f"memory-retrieval:{request.query_id}"
        for memory_type in sorted(request.memory_types, key=lambda item: item.value):
            try:
                if memory_type is MemoryType.USER_PROFILE:
                    selector = self._selector_authority.issue_safe_user_profile(
                        request_digest=request.request_digest,
                        actor=request.actor,
                        scope=request.conversation_scope,
                        purpose=purpose,
                    )
                elif memory_type is MemoryType.GROUP_MEMORY:
                    selector = self._selector_authority.issue_current_group(
                        request_digest=request.request_digest,
                        actor=request.actor,
                        scope=request.conversation_scope,
                        memory_types=frozenset({memory_type}),
                        purpose=purpose,
                    )
                else:
                    selector = self._selector_authority.issue_current_conversation(
                        request_digest=request.request_digest,
                        actor=request.actor,
                        scope=request.conversation_scope,
                        memory_types=frozenset({memory_type}),
                        purpose=purpose,
                    )
            except (TypeError, ValueError):
                raise _retrieval_error("memory_selector_policy_rejected") from None
            selectors.append(selector)
        return tuple(selectors)


class DeterministicScopedMemoryRetriever:
    def __init__(
        self,
        repository: MemoryRepository,
        policy: MemoryRetrievalPolicy,
        *,
        ranker: MemoryRanker | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(repository, MemoryRepository):
            raise TypeError("repository does not implement MemoryRepository")
        if (
            not callable(getattr(policy, "selectors_for", None))
            or not isinstance(policy.policy_revision, str)
            or not policy.policy_revision.strip()
        ):
            raise ValueError("memory retrieval policy revision is required")
        if ranker is not None and not isinstance(ranker, MemoryRanker):
            raise TypeError("ranker does not implement MemoryRanker")
        self._repository = repository
        self._policy = policy
        self._policy_revision = policy.policy_revision
        self._ranker = ranker
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._revision = ComponentRevision(
            "memory.scoped-retriever",
            "1",
            "exact-eligibility-v1",
            DigestString("builtin"),
        )

    async def retrieve(
        self,
        request: MemoryRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> MemoryRetrievalResult:
        _validate_call(call, self._clock())
        _validate_request(request)
        if request.strategy is MemoryRetrievalStrategy.NO_MEMORY:
            return self._result(
                request,
                matches=(),
                snapshot_id=None,
                repository_revision=None,
                state_revision=None,
                ranker_revision=None,
                degraded=False,
                reason_codes=("no_memory_control",),
            )

        selectors = await self._policy.selectors_for(request, call=call)
        _validate_selectors(request, selectors)
        snapshot = await self._repository.open_snapshot(
            selectors,
            request_digest=request.request_digest,
            as_of=request.as_of,
            call=call,
        )
        candidates: list[MemoryRecord] = []
        candidate_query = MemoryQuery(1, "", request.query.locale, request.as_of)
        for selector in selectors:
            page = await self._repository.retrieve(
                snapshot,
                selector,
                candidate_query,
                candidate_limit=request.candidate_limit_per_type,
                cursor=None,
                request_digest=request.request_digest,
                call=call,
            )
            if len(page.items) > request.candidate_limit_per_type or any(
                not _record_matches_selector(item, selector, request.as_of)
                for item in page.items
            ):
                raise _retrieval_error("memory_repository_scope_contract_violation")
            candidates.extend(page.items)
        if len({item.memory_id for item in candidates}) != len(candidates):
            raise _retrieval_error("memory_repository_duplicate_candidate")
        candidates.sort(
            key=lambda item: (item.updated_at, item.memory_id),
            reverse=True,
        )
        candidates = candidates[: request.candidate_limit_total]
        reason_codes: list[str] = []
        permitted = [
            item
            for item in candidates
            if item.sensitivity is not Sensitivity.RESTRICTED
        ]
        if len(permitted) != len(candidates):
            reason_codes.append("restricted_memory_excluded")
        permitted = _collapse_content_duplicates(permitted)

        if request.strategy is MemoryRetrievalStrategy.RECENCY:
            matches = _recency_matches(permitted, request.limit)
            return self._result(
                request,
                matches=matches,
                snapshot_id=snapshot.snapshot_id,
                repository_revision=snapshot.repository_revision,
                state_revision=snapshot.state_revision,
                ranker_revision=None,
                degraded=False,
                reason_codes=tuple(reason_codes),
            )

        ranker = self._ranker
        if ranker is None:
            return self._degraded_bm25_result(
                request,
                candidates=permitted,
                snapshot_id=snapshot.snapshot_id,
                repository_revision=snapshot.repository_revision,
                state_revision=snapshot.state_revision,
                reason_codes=(*reason_codes, "ranker_unavailable"),
            )
        if not permitted:
            return self._result(
                request,
                matches=(),
                snapshot_id=snapshot.snapshot_id,
                repository_revision=snapshot.repository_revision,
                state_revision=snapshot.state_revision,
                ranker_revision=ranker.ranker_revision,
                degraded=False,
                reason_codes=tuple(reason_codes),
            )
        if not request.query.text.strip():
            return self._degraded_bm25_result(
                request,
                candidates=permitted,
                snapshot_id=snapshot.snapshot_id,
                repository_revision=snapshot.repository_revision,
                state_revision=snapshot.state_revision,
                reason_codes=(*reason_codes, "lexical_query_too_short"),
            )
        try:
            projections = tuple(_projection(item) for item in permitted)
            rank_request = MemoryRankRequest(
                1,
                DigestString("pending"),
                request.query.text,
                projections,
                min(request.limit, len(projections)),
                snapshot.state_revision,
            )
            rank_request = replace(
                rank_request,
                request_digest=memory_rank_request_digest(rank_request),
            )
            scores = await ranker.rank(rank_request, call=call)
            _validate_call(call, self._clock())
            _validate_rank_scores(rank_request, scores, ranker.ranker_revision)
        except DududaError as caught:
            _validate_call(call, self._clock())
            reason = {
                "memory_lexical_query_too_short": "lexical_query_too_short",
                "invalid_memory_rank_output": "ranker_output_invalid",
            }.get(caught.info.code, "ranker_unavailable")
            return self._degraded_bm25_result(
                request,
                candidates=permitted,
                snapshot_id=snapshot.snapshot_id,
                repository_revision=snapshot.repository_revision,
                state_revision=snapshot.state_revision,
                reason_codes=(*reason_codes, reason),
            )
        except Exception:  # noqa: BLE001 - ranker failures are sanitized
            _validate_call(call, self._clock())
            return self._degraded_bm25_result(
                request,
                candidates=permitted,
                snapshot_id=snapshot.snapshot_id,
                repository_revision=snapshot.repository_revision,
                state_revision=snapshot.state_revision,
                reason_codes=(*reason_codes, "ranker_unavailable"),
            )
        by_id = {item.memory_id: item for item in permitted}
        matches = tuple(
            MemoryMatch(
                1,
                by_id[score.memory_id],
                rank,
                score.score,
                MemoryRetrievalStrategy.CJK_BM25,
                score.ranker_revision,
            )
            for rank, score in enumerate(scores, start=1)
        )
        return self._result(
            request,
            matches=matches,
            snapshot_id=snapshot.snapshot_id,
            repository_revision=snapshot.repository_revision,
            state_revision=snapshot.state_revision,
            ranker_revision=ranker.ranker_revision,
            degraded=False,
            reason_codes=tuple(reason_codes),
        )

    def _degraded_bm25_result(
        self,
        request: MemoryRetrievalRequest,
        *,
        candidates: list[MemoryRecord],
        snapshot_id: str,
        repository_revision: str,
        state_revision: int,
        reason_codes: tuple[str, ...],
    ) -> MemoryRetrievalResult:
        matches = (
            _recency_matches(candidates, request.limit)
            if request.allow_recency_degrade
            else ()
        )
        reasons = (
            (*reason_codes, "degraded_to_recency")
            if request.allow_recency_degrade
            else (*reason_codes, "degradation_disabled")
        )
        return self._result(
            request,
            matches=matches,
            snapshot_id=snapshot_id,
            repository_revision=repository_revision,
            state_revision=state_revision,
            ranker_revision=None,
            degraded=True,
            reason_codes=reasons,
        )

    def _result(
        self,
        request: MemoryRetrievalRequest,
        *,
        matches: tuple[MemoryMatch, ...],
        snapshot_id: str | None,
        repository_revision: str | None,
        state_revision: int | None,
        ranker_revision: ComponentRevision | None,
        degraded: bool,
        reason_codes: tuple[str, ...],
    ) -> MemoryRetrievalResult:
        result = MemoryRetrievalResult(
            1,
            request.request_digest,
            request.strategy,
            matches,
            (),
            snapshot_id,
            repository_revision,
            state_revision,
            self._policy_revision,
            ranker_revision,
            self._revision,
            degraded,
            tuple(dict.fromkeys(reason_codes)),
            DigestString("pending"),
        )
        return replace(
            result,
            result_digest=memory_retrieval_result_digest(result),
        )


def _validate_request(request: MemoryRetrievalRequest) -> None:
    if memory_retrieval_request_digest(request) != request.request_digest:
        raise _retrieval_error("memory_retrieval_request_digest_mismatch")


def _validate_selectors(
    request: MemoryRetrievalRequest,
    selectors: tuple[ScopeSelector, ...],
) -> None:
    if not isinstance(selectors, tuple) or len(selectors) != len(request.memory_types):
        raise _retrieval_error("invalid_memory_retrieval_selectors")
    selected_types: set[MemoryType] = set()
    for selector in selectors:
        if (
            not isinstance(selector, ScopeSelector)
            or selector.request_digest != request.request_digest
            or selector.platform != request.conversation_scope.platform
            or selector.bot_id != request.conversation_scope.bot_id
            or selector.persona_id != request.conversation_scope.persona_id
            or len(selector.memory_types) != 1
        ):
            raise _retrieval_error("invalid_memory_retrieval_selectors")
        memory_type = next(iter(selector.memory_types))
        selected_types.add(memory_type)
        if memory_type is MemoryType.USER_PROFILE:
            valid = (
                selector.mode is SelectorMode.SAFE_USER_PROFILE
                and selector.user_id == request.actor.user_id
                and selector.conversation_id is None
                and selector.group_id is None
            )
        elif memory_type is MemoryType.GROUP_MEMORY:
            valid = (
                selector.mode is SelectorMode.CURRENT_GROUP
                and selector.conversation_id
                == request.conversation_scope.conversation_id
                and selector.group_id == request.conversation_scope.group_id
            )
        else:
            valid = (
                selector.mode is SelectorMode.CURRENT_CONVERSATION
                and selector.conversation_id
                == request.conversation_scope.conversation_id
                and selector.group_id == request.conversation_scope.group_id
                and selector.user_id == request.actor.user_id
            )
        if not valid:
            raise _retrieval_error("invalid_memory_retrieval_selectors")
    if selected_types != set(request.memory_types):
        raise _retrieval_error("invalid_memory_retrieval_selectors")


def _record_matches_selector(
    record: MemoryRecord,
    selector: ScopeSelector,
    as_of: datetime,
) -> bool:
    scope = record.scope
    if (
        record.created_at > as_of
        or (record.expires_at is not None and record.expires_at <= as_of)
        or scope.platform != selector.platform
        or scope.bot_id != selector.bot_id
        or scope.persona_id != selector.persona_id
        or scope.memory_type not in selector.memory_types
    ):
        return False
    if selector.mode is SelectorMode.SAFE_USER_PROFILE:
        return (
            scope.user_id == selector.user_id
            and record.visibility is Visibility.SAFE_USER_PROFILE
        )
    if (
        scope.conversation_id != selector.conversation_id
        or scope.group_id != selector.group_id
        or (scope.user_id is not None and scope.user_id != selector.user_id)
    ):
        return False
    if record.visibility is Visibility.CURRENT_CONVERSATION:
        return selector.mode is SelectorMode.CURRENT_CONVERSATION
    return (
        record.visibility is Visibility.CURRENT_GROUP
        and scope.group_id is not None
        and selector.mode
        in {SelectorMode.CURRENT_CONVERSATION, SelectorMode.CURRENT_GROUP}
    )


def _collapse_content_duplicates(
    candidates: list[MemoryRecord],
) -> list[MemoryRecord]:
    selected: dict[DigestString, MemoryRecord] = {}
    for record in candidates:
        current = selected.get(record.content_hash)
        if current is None or (
            record.version,
            record.updated_at,
            record.memory_id,
        ) > (
            current.version,
            current.updated_at,
            current.memory_id,
        ):
            selected[record.content_hash] = record
    result = list(selected.values())
    result.sort(key=lambda item: (item.updated_at, item.memory_id), reverse=True)
    return result


def _recency_matches(
    candidates: list[MemoryRecord],
    limit: int,
) -> tuple[MemoryMatch, ...]:
    return tuple(
        MemoryMatch(
            1,
            record,
            rank,
            None,
            MemoryRetrievalStrategy.RECENCY,
            None,
        )
        for rank, record in enumerate(candidates[:limit], start=1)
    )


def _projection(record: MemoryRecord) -> IndexableMemoryProjection:
    return IndexableMemoryProjection(
        1,
        record.memory_id,
        record.content,
        record.content_hash,
        memory_scope_digest(record.scope),
        record.sensitivity,
        record.visibility,
        record.updated_at,
    )


def _validate_rank_scores(
    request: MemoryRankRequest,
    scores: tuple[MemoryRankScore, ...],
    expected_revision: ComponentRevision,
) -> None:
    if not isinstance(scores, tuple) or len(scores) > request.limit:
        raise _retrieval_error("invalid_memory_rank_output")
    projections = {item.memory_id: item for item in request.projections}
    if len({item.memory_id for item in scores}) != len(scores):
        raise _retrieval_error("invalid_memory_rank_output")
    for score in scores:
        projection = projections.get(score.memory_id)
        if (
            projection is None
            or score.content_digest != projection.content_digest
            or score.scope_digest != projection.scope_digest
            or score.ranker_revision != expected_revision
        ):
            raise _retrieval_error("invalid_memory_rank_output")
    if scores != tuple(sorted(scores, key=lambda item: (-item.score, item.memory_id))):
        raise _retrieval_error("invalid_memory_rank_output")


def _validate_call(call: PortCallContext, now: datetime) -> None:
    if call.cancellation.is_cancelled:
        raise _retrieval_error("memory_retrieval_cancelled", ErrorCategory.CANCELLED)
    if call.deadline <= now:
        raise _retrieval_error("memory_retrieval_deadline", ErrorCategory.TIMEOUT)


def _retrieval_error(
    code: str,
    category: ErrorCategory = ErrorCategory.AUTHORIZATION,
):
    return error(code, category, "memory.retrieval_unavailable")


__all__ = [
    "DeterministicMemoryRetrievalPolicy",
    "DeterministicScopedMemoryRetriever",
]
