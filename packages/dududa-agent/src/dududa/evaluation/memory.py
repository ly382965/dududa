from __future__ import annotations

import asyncio
import json
import math
import random
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from dududa.contracts.canonical import canonical_digest
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
    memory_record_digest,
    memory_retrieval_request_digest,
    memory_retrieval_result_digest,
    memory_tombstone_digest,
)
from dududa.memory.json_repository import JsonMemoryRepository
from dududa.memory.lexical import CjkBm25MemoryRanker, cjk_bm25_terms
from dududa.memory.models import (
    EvidenceReference,
    MemoryQuery,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemoryRetrievalStrategy,
    MemoryScope,
    MemorySource,
    MemoryTombstone,
    MemoryType,
    Visibility,
)
from dududa.memory.retrieval import (
    DeterministicMemoryRetrievalPolicy,
    DeterministicScopedMemoryRetriever,
)
from dududa.memory.selectors import HmacScopeSelectorAuthority
from dududa.memory.serialization import (
    record_from_dict,
    record_to_dict,
    tombstone_from_dict,
    tombstone_to_dict,
)
from dududa.ports.context import NeverCancelled, PortCallContext

BUNDLE_VERSION = "memory-retrieval-synthetic-v1"
FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
POLICY_REVISION = "memory-eval-policy-v1"
K = 2
CANDIDATE_LIMIT_PER_TYPE = 32
CANDIDATE_LIMIT_TOTAL = 64
_SELECTOR_KEY = b"0123456789abcdef0123456789abcdef"
_METRIC_QUANTUM = Decimal("0.000000000001")
_SAFETY_CATEGORIES = (
    "cross_scope",
    "future_created",
    "expired",
    "tombstoned",
    "restricted",
)
_REQUIRED_TAGS = frozenset(
    {
        "alternate_platform",
        "chinese",
        "emoji",
        "group",
        "group_memory",
        "mixed_latin",
        "private",
        "safe_user_profile",
        "short_cjk",
        "typo",
    }
)
_DOMAINS = {
    "case": "eval:memory-retrieval-case:v1",
    "gold": "eval:memory-retrieval-gold:v1",
    "records": "eval:memory-retrieval-record-state:v1",
    "cases": "eval:memory-retrieval-case-set:v1",
    "gold_set": "eval:memory-retrieval-gold-set:v1",
    "record_set": "eval:memory-retrieval-record-set:v1",
    "tombstone_set": "eval:memory-retrieval-tombstone-set:v1",
    "fixture": "eval:memory-retrieval-fixture:v1",
    "dataset": "eval:memory-retrieval-dataset:v1",
    "ranking": "eval:memory-retrieval-ranking:v1",
    "report": "eval:memory-retrieval-report:v1",
}

__all__ = [
    "check_memory_retrieval_bundle",
    "generate_memory_retrieval_bundle",
    "run_memory_retrieval_eval",
]


@dataclass(frozen=True, slots=True)
class _CaseTemplate:
    case_id: str
    tags: tuple[str, ...]
    platform: str
    bot_id: str
    user_id: str
    conversation_type: ConversationType
    conversation_id: str
    group_id: str | None
    persona_id: str
    memory_type: MemoryType
    query: str
    target: str
    distractors: tuple[str, str]
    lexical_subset: bool


@dataclass(frozen=True, slots=True)
class _EvalCase:
    case_id: str
    tags: tuple[str, ...]
    actor: Actor
    scope: ConversationScope
    query: str
    locale: str
    memory_types: frozenset[MemoryType]
    relevant_ids: frozenset[str]
    forbidden_ids: Mapping[str, frozenset[str]]
    lexical_subset: bool


@dataclass(frozen=True, slots=True)
class _LoadedBundle:
    manifest: Mapping[str, object]
    cases: tuple[_EvalCase, ...]


@dataclass(frozen=True, slots=True)
class _Prediction:
    case_id: str
    strategy: MemoryRetrievalStrategy
    selected_ids: tuple[str, ...]
    relevant_ids: frozenset[str]
    forbidden_ids: Mapping[str, frozenset[str]]
    degraded: bool
    reason_codes: tuple[str, ...]
    state_revision: int | None
    ranking_fingerprint: str


@dataclass(frozen=True, slots=True)
class _EvaluationRun:
    predictions: tuple[_Prediction, ...]
    call_counts: Mapping[str, Mapping[str, int]]


class _SequentialIds:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._value = 0

    def __call__(self) -> str:
        self._value += 1
        return f"{self._prefix}-{self._value}"


class _CountingJsonMemoryRepository(JsonMemoryRepository):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.open_calls = 0
        self.retrieve_calls = 0

    async def open_snapshot(self, *args: object, **kwargs: object):
        self.open_calls += 1
        return await super().open_snapshot(*args, **kwargs)

    async def retrieve(self, *args: object, **kwargs: object):
        self.retrieve_calls += 1
        return await super().retrieve(*args, **kwargs)


class _CountingPolicy(DeterministicMemoryRetrievalPolicy):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.selector_calls = 0

    async def selectors_for(self, *args: object, **kwargs: object):
        self.selector_calls += 1
        return await super().selectors_for(*args, **kwargs)


class _CountingRanker:
    def __init__(self, delegate: CjkBm25MemoryRanker) -> None:
        self._delegate = delegate
        self.rank_calls = 0

    @property
    def ranker_revision(self) -> ComponentRevision:
        return self._delegate.ranker_revision

    async def rank(self, *args: object, **kwargs: object):
        self.rank_calls += 1
        return await self._delegate.rank(*args, **kwargs)


def generate_memory_retrieval_bundle(output_dir: Path | str) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records, cases, gold = _fixture_documents()
    manifest = _dataset_manifest(records, cases, gold)
    _write_json(output / "records.json", records)
    _write_json(output / "cases.json", cases)
    _write_json(output / "gold.json", gold)
    _write_json(output / "manifest.json", manifest)
    (output / "DATA_CARD.md").write_text(_data_card(), encoding="utf-8")
    return run_memory_retrieval_eval(output, write_report=True)


def run_memory_retrieval_eval(
    bundle_dir: Path | str,
    *,
    write_report: bool = False,
) -> dict[str, object]:
    bundle_path = Path(bundle_dir)
    loaded = _load_bundle(bundle_path)
    normal = asyncio.run(_evaluate_cases(bundle_path, loaded.cases))
    reverse = asyncio.run(_evaluate_cases(bundle_path, tuple(reversed(loaded.cases))))
    shuffled_cases = list(loaded.cases)
    random.Random(20260101).shuffle(shuffled_cases)
    shuffled = asyncio.run(_evaluate_cases(bundle_path, tuple(shuffled_cases)))
    report = _build_report(loaded, normal, reverse, shuffled)
    if write_report:
        _write_json(bundle_path / "report.json", report)
    return report


def check_memory_retrieval_bundle(bundle_dir: Path | str) -> dict[str, object]:
    expected = Path(bundle_dir)
    actual_report = run_memory_retrieval_eval(expected)
    committed_report = _mapping(_read_json(expected / "report.json"), "report")
    if actual_report != committed_report:
        raise RuntimeError("Memory Eval committed report is stale")
    with tempfile.TemporaryDirectory(prefix="dududa-memory-eval-") as temporary:
        generated = Path(temporary)
        generate_memory_retrieval_bundle(generated)
        expected_files = {
            path.relative_to(expected) for path in expected.rglob("*") if path.is_file()
        }
        generated_files = {
            path.relative_to(generated)
            for path in generated.rglob("*")
            if path.is_file()
        }
        if expected_files != generated_files:
            raise RuntimeError("Memory Eval artifact inventory drift")
        for relative in sorted(expected_files):
            if (expected / relative).read_bytes() != (
                generated / relative
            ).read_bytes():
                raise RuntimeError(f"Memory Eval artifact drift: {relative}")
    return actual_report


def _templates() -> tuple[_CaseTemplate, ...]:
    return (
        _CaseTemplate(
            "campus-notice",
            ("chinese", "group"),
            "qq-test",
            "bot-alpha",
            "user-alpha",
            ConversationType.GROUP,
            "group-alpha",
            "group-alpha",
            "dududa",
            MemoryType.EXPLICIT_USER_MEMORY,
            "校园通知",
            "校园通知周五发布",
            ("今晚聚餐安排", "羽毛球报名"),
            True,
        ),
        _CaseTemplate(
            "python-version",
            ("mixed_latin", "private"),
            "qq-test",
            "bot-alpha",
            "user-alpha",
            ConversationType.PRIVATE,
            "dm-alpha",
            None,
            "dududa",
            MemoryType.EPISODIC,
            "Python 3.12",
            "项目运行环境固定为 Python 3.12",
            ("周末电影清单", "早餐采购计划"),
            True,
        ),
        _CaseTemplate(
            "paper-number",
            ("alternate_platform", "group", "mixed_latin"),
            "matrix-test",
            "bot-beta",
            "user-beta",
            ConversationType.GROUP,
            "research-beta",
            "research-beta",
            "research-persona",
            MemoryType.EXPLICIT_USER_MEMORY,
            "arXiv 2401",
            "待读论文编号 arXiv 2401",
            ("版本发布检查", "团队排班说明"),
            True,
        ),
        _CaseTemplate(
            "answer-preference",
            ("chinese", "group", "safe_user_profile"),
            "qq-test",
            "bot-alpha",
            "user-alpha",
            ConversationType.GROUP,
            "group-alpha",
            "group-alpha",
            "dududa",
            MemoryType.USER_PROFILE,
            "简洁回答",
            "回答偏好是简洁回答",
            ("偏好使用深色主题", "常用语言为中文"),
            True,
        ),
        _CaseTemplate(
            "group-meeting",
            ("chinese", "group", "group_memory"),
            "qq-test",
            "bot-alpha",
            "user-gamma",
            ConversationType.GROUP,
            "group-gamma",
            "group-gamma",
            "dududa",
            MemoryType.GROUP_MEMORY,
            "周会地点",
            "周会地点在东教室",
            ("本周运动安排", "社团招新时间"),
            True,
        ),
        _CaseTemplate(
            "single-han",
            ("chinese", "group", "short_cjk"),
            "qq-test",
            "bot-alpha",
            "user-alpha",
            ConversationType.GROUP,
            "group-short",
            "group-short",
            "dududa",
            MemoryType.EXPLICIT_USER_MEMORY,
            "校",
            "校",
            ("社团值班安排", "图书馆闭馆提醒"),
            False,
        ),
        _CaseTemplate(
            "synthetic-typo",
            ("chinese", "group", "typo"),
            "qq-test",
            "bot-delta",
            "user-delta",
            ConversationType.GROUP,
            "group-delta",
            "group-delta",
            "alternate-persona",
            MemoryType.EPISODIC,
            "校圆通知",
            "保留合成错别字：校圆通知",
            ("食堂菜谱更新", "实验室开放安排"),
            True,
        ),
        _CaseTemplate(
            "emoji-separator",
            ("chinese", "emoji", "private"),
            "qq-test",
            "bot-epsilon",
            "user-epsilon",
            ConversationType.PRIVATE,
            "dm-epsilon",
            None,
            "dududa",
            MemoryType.EXPLICIT_USER_MEMORY,
            "咖啡☕时间",
            "咖啡☕时间安排在下午",
            ("午餐预约规则", "会议纪要归档"),
            True,
        ),
    )


def _fixture_documents() -> tuple[
    dict[str, object], dict[str, object], dict[str, object]
]:
    live_records: list[MemoryRecord] = []
    tombstones: list[MemoryTombstone] = []
    cases: list[dict[str, object]] = []
    gold: list[dict[str, object]] = []
    writer_revision = ComponentRevision(
        "memory.repository",
        "2",
        "memory-json-v2",
        DigestString("builtin"),
    )

    for index, template in enumerate(_templates(), start=1):
        target_id = f"memory:{template.case_id}:target"
        distractor_ids = (
            f"memory:{template.case_id}:newer-a",
            f"memory:{template.case_id}:newer-b",
        )
        cross_scope_id = f"memory:{template.case_id}:cross-scope"
        future_id = f"memory:{template.case_id}:future"
        expired_id = f"memory:{template.case_id}:expired"
        tombstoned_id = f"memory:{template.case_id}:tombstoned"
        restricted_id = f"memory:{template.case_id}:restricted"
        primary_scope = _memory_scope(template)
        target_updated_at = (
            FIXED_NOW - timedelta(minutes=index * 4, seconds=90)
            if not template.lexical_subset
            else FIXED_NOW - timedelta(hours=6, minutes=index)
        )
        target = _record(
            target_id,
            primary_scope,
            template.target,
            updated_at=target_updated_at,
            visibility=_visibility(template),
        )
        live_records.append(target)
        for offset, (memory_id, content) in enumerate(
            zip(distractor_ids, template.distractors),
            start=1,
        ):
            live_records.append(
                _record(
                    memory_id,
                    primary_scope,
                    content,
                    updated_at=FIXED_NOW - timedelta(minutes=index * 4 + offset),
                    visibility=_visibility(template),
                )
            )
        live_records.extend(
            (
                _record(
                    cross_scope_id,
                    _cross_memory_scope(template),
                    template.target,
                    updated_at=FIXED_NOW - timedelta(minutes=2),
                    visibility=_visibility(template),
                ),
                _record(
                    future_id,
                    primary_scope,
                    template.target,
                    created_at=FIXED_NOW + timedelta(hours=1),
                    updated_at=FIXED_NOW + timedelta(hours=1),
                    visibility=_visibility(template),
                ),
                _record(
                    expired_id,
                    primary_scope,
                    template.target,
                    updated_at=FIXED_NOW - timedelta(minutes=3),
                    expires_at=FIXED_NOW - timedelta(minutes=1),
                    visibility=_visibility(template),
                ),
                _record(
                    restricted_id,
                    primary_scope,
                    template.target,
                    updated_at=FIXED_NOW - timedelta(minutes=4),
                    sensitivity=Sensitivity.RESTRICTED,
                    visibility=_visibility(template),
                ),
            )
        )
        deleted = _record(
            tombstoned_id,
            primary_scope,
            template.target,
            updated_at=FIXED_NOW - timedelta(hours=12),
            visibility=_visibility(template),
        )
        tombstone = MemoryTombstone(
            1,
            f"tombstone:{template.case_id}",
            tombstoned_id,
            primary_scope,
            memory_record_digest(deleted),
            deleted.content_hash,
            deleted.version,
            DigestString(f"synthetic-delete-command:{template.case_id}"),
            DigestString(f"synthetic-authorization:{template.case_id}"),
            DigestString(f"synthetic-confirmation:{template.case_id}"),
            POLICY_REVISION,
            writer_revision,
            FIXED_NOW - timedelta(hours=1),
            index + 1,
            DigestString("pending"),
        )
        tombstones.append(
            replace(tombstone, integrity_digest=memory_tombstone_digest(tombstone))
        )

        case = {
            "schema_version": 1,
            "case_id": template.case_id,
            "tags": sorted(template.tags),
            "actor": {
                "platform": template.platform,
                "bot_id": template.bot_id,
                "user_id": template.user_id,
                "roles": ["normal"],
            },
            "conversation_scope": {
                "platform": template.platform,
                "bot_id": template.bot_id,
                "conversation_type": template.conversation_type.value,
                "conversation_id": template.conversation_id,
                "group_id": template.group_id,
                "persona_id": template.persona_id,
            },
            "query": {"text": template.query, "locale": "zh-CN"},
            "memory_types": [template.memory_type.value],
            "k": K,
            "candidate_limit_per_type": CANDIDATE_LIMIT_PER_TYPE,
            "candidate_limit_total": CANDIDATE_LIMIT_TOTAL,
        }
        case["case_digest"] = str(canonical_digest(case, domain=_DOMAINS["case"]))
        cases.append(case)

        expected = {
            "schema_version": 1,
            "case_id": template.case_id,
            "relevant_memory_ids": [target_id],
            "forbidden_memory_ids": {
                "cross_scope": [cross_scope_id],
                "future_created": [future_id],
                "expired": [expired_id],
                "tombstoned": [tombstoned_id],
                "restricted": [restricted_id],
            },
            "lexical_subset": template.lexical_subset,
        }
        expected["gold_digest"] = str(
            canonical_digest(expected, domain=_DOMAINS["gold"])
        )
        gold.append(expected)

    live_records.sort(key=lambda item: item.memory_id)
    tombstones.sort(key=lambda item: item.memory_id)
    cases.sort(key=lambda item: str(item["case_id"]))
    gold.sort(key=lambda item: str(item["case_id"]))
    state_revision = len(tombstones) + 1
    records_document = {
        "schema_version": 2,
        "repository_revision": "memory-json-v2",
        "state_revision": state_revision,
        "records": [record_to_dict(item) for item in live_records],
        "tombstones": [tombstone_to_dict(item) for item in tombstones],
        "write_idempotency": [],
        "delete_idempotency": [],
        "restore_idempotency": [],
        "consumed_write_decisions": [],
        "consumed_delete_confirmations": [],
    }
    return (
        records_document,
        {"schema_version": 1, "cases": cases},
        {"schema_version": 1, "gold": gold},
    )


def _memory_scope(template: _CaseTemplate) -> MemoryScope:
    if template.memory_type is MemoryType.USER_PROFILE:
        return MemoryScope(
            1,
            template.platform,
            template.bot_id,
            ConversationType.PRIVATE,
            f"profile-store:{template.user_id}",
            None,
            template.user_id,
            template.persona_id,
            template.memory_type,
        )
    return MemoryScope(
        1,
        template.platform,
        template.bot_id,
        template.conversation_type,
        template.conversation_id,
        template.group_id,
        None if template.memory_type is MemoryType.GROUP_MEMORY else template.user_id,
        template.persona_id,
        template.memory_type,
    )


def _cross_memory_scope(template: _CaseTemplate) -> MemoryScope:
    if template.memory_type is MemoryType.USER_PROFILE:
        return MemoryScope(
            1,
            template.platform,
            template.bot_id,
            ConversationType.PRIVATE,
            f"profile-store:{template.user_id}:outside",
            None,
            f"{template.user_id}:outside",
            template.persona_id,
            template.memory_type,
        )
    if template.conversation_type is ConversationType.GROUP:
        conversation_id = f"{template.conversation_id}:outside"
        group_id: str | None = conversation_id
    else:
        conversation_id = f"{template.conversation_id}:outside"
        group_id = None
    return MemoryScope(
        1,
        template.platform,
        template.bot_id,
        template.conversation_type,
        conversation_id,
        group_id,
        None if template.memory_type is MemoryType.GROUP_MEMORY else template.user_id,
        template.persona_id,
        template.memory_type,
    )


def _visibility(template: _CaseTemplate) -> Visibility:
    if template.memory_type is MemoryType.USER_PROFILE:
        return Visibility.SAFE_USER_PROFILE
    if template.memory_type is MemoryType.GROUP_MEMORY:
        return Visibility.CURRENT_GROUP
    return Visibility.CURRENT_CONVERSATION


def _record(
    memory_id: str,
    scope: MemoryScope,
    content: str,
    *,
    updated_at: datetime,
    visibility: Visibility,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    sensitivity: Sensitivity = Sensitivity.PERSONAL,
) -> MemoryRecord:
    created = created_at or FIXED_NOW - timedelta(days=7)
    return MemoryRecord(
        1,
        memory_id,
        scope,
        content,
        MemorySource.EXPLICIT_USER_REQUEST,
        created,
        updated_at,
        1.0,
        expires_at,
        sensitivity,
        visibility,
        (
            EvidenceReference(
                f"evidence:{memory_id}",
                "synthetic_fixture",
                f"fixture:{memory_id}",
                scope.user_id,
            ),
        ),
        memory_content_hash(content),
        1,
    )


def _dataset_manifest(
    records: Mapping[str, object],
    cases: Mapping[str, object],
    gold: Mapping[str, object],
) -> dict[str, object]:
    case_values = _sequence(cases["cases"], "cases")
    gold_values = _sequence(gold["gold"], "gold")
    ranker_revision = CjkBm25MemoryRanker(clock=lambda: FIXED_NOW).ranker_revision
    decoded_records = tuple(
        record_from_dict(item) for item in _sequence(records["records"], "records")
    )
    decoded_tombstones = tuple(
        tombstone_from_dict(item)
        for item in _sequence(records["tombstones"], "tombstones")
    )
    artifact_digests = {
        "repository_state": str(canonical_digest(records, domain=_DOMAINS["records"])),
        "record_set": str(
            canonical_digest(
                tuple(
                    str(memory_record_digest(item))
                    for item in sorted(
                        decoded_records,
                        key=lambda value: value.memory_id,
                    )
                ),
                domain=_DOMAINS["record_set"],
            )
        ),
        "tombstone_set": str(
            canonical_digest(
                tuple(
                    str(item.integrity_digest)
                    for item in sorted(
                        decoded_tombstones,
                        key=lambda value: value.memory_id,
                    )
                ),
                domain=_DOMAINS["tombstone_set"],
            )
        ),
        "cases": str(canonical_digest(cases, domain=_DOMAINS["cases"])),
        "gold": str(canonical_digest(gold, domain=_DOMAINS["gold_set"])),
    }
    manifest: dict[str, object] = {
        "schema_version": 1,
        "bundle_version": BUNDLE_VERSION,
        "dataset_kind": "synthetic",
        "quality_claim": "synthetic_lexical_regression_only",
        "label_basis": "generated_policy_gold",
        "generated_data_only": True,
        "human_review_complete": False,
        "real_chinese_quality_claimed": False,
        "network_allowed": False,
        "real_model_call_count": 0,
        "user_data_record_count": 0,
        "reference_time": FIXED_NOW.isoformat(),
        "generation_revision": "memory-retrieval-fixture-v1",
        "fixed_shuffle_seed": 20260101,
        "k": K,
        "candidate_limit_per_type": CANDIDATE_LIMIT_PER_TYPE,
        "candidate_limit_total": CANDIDATE_LIMIT_TOTAL,
        "repository_revision": records["repository_revision"],
        "repository_fixture_format": "memory-json-v2-test-mirror",
        "state_revision": records["state_revision"],
        "case_count": len(case_values),
        "live_record_count": len(_sequence(records["records"], "records")),
        "tombstone_count": len(_sequence(records["tombstones"], "tombstones")),
        "coverage_tags": sorted(
            {
                str(tag)
                for case in case_values
                for tag in _sequence(_mapping(case, "case")["tags"], "tags")
            }
        ),
        "lexical_subset_case_ids": sorted(
            str(_mapping(item, "gold")["case_id"])
            for item in gold_values
            if _mapping(item, "gold")["lexical_subset"] is True
        ),
        "strategies": [item.value for item in MemoryRetrievalStrategy],
        "policy_revision": POLICY_REVISION,
        "retriever_revision": "memory.scoped-retriever:1:exact-eligibility-v1",
        "ranker_revision": _component_record(ranker_revision),
        "tokenizer_revision": "cjk-bigram-nfc-casefold-v1",
        "replay_evidence_empty": True,
        "artifact_digests": artifact_digests,
    }
    manifest["fixture_digest"] = str(
        canonical_digest(
            {
                "artifact_digests": artifact_digests,
                "state_revision": records["state_revision"],
                "reference_time": FIXED_NOW,
            },
            domain=_DOMAINS["fixture"],
        )
    )
    manifest["manifest_digest"] = str(
        canonical_digest(manifest, domain=_DOMAINS["dataset"])
    )
    return manifest


def _component_record(revision: ComponentRevision) -> dict[str, object]:
    return {
        "component_id": revision.component_id,
        "implementation_version": revision.implementation_version,
        "config_revision": revision.config_revision,
        "artifact_digest": str(revision.artifact_digest),
    }


def _load_bundle(bundle_path: Path) -> _LoadedBundle:
    records = _mapping(_read_json(bundle_path / "records.json"), "records")
    cases_document = _mapping(_read_json(bundle_path / "cases.json"), "cases")
    gold_document = _mapping(_read_json(bundle_path / "gold.json"), "gold")
    manifest = _mapping(_read_json(bundle_path / "manifest.json"), "manifest")
    expected_state_keys = {
        "schema_version",
        "repository_revision",
        "state_revision",
        "records",
        "tombstones",
        "write_idempotency",
        "delete_idempotency",
        "restore_idempotency",
        "consumed_write_decisions",
        "consumed_delete_confirmations",
    }
    replay_fields = (
        "write_idempotency",
        "delete_idempotency",
        "restore_idempotency",
        "consumed_write_decisions",
        "consumed_delete_confirmations",
    )
    if set(records) != expected_state_keys or any(
        _sequence(records[name], name) for name in replay_fields
    ):
        raise RuntimeError("Memory Eval repository fixture envelope is invalid")
    frozen_records, frozen_cases, frozen_gold = _fixture_documents()
    if (
        records != frozen_records
        or cases_document != frozen_cases
        or (gold_document != frozen_gold)
    ):
        raise RuntimeError("Memory Eval input differs from frozen synthetic generator")
    expected_manifest = _dataset_manifest(records, cases_document, gold_document)
    if manifest != expected_manifest:
        raise RuntimeError("Memory Eval manifest mismatch")

    record_values = _sequence(records["records"], "records")
    tombstone_values = _sequence(records["tombstones"], "tombstones")
    live_records = tuple(record_from_dict(item) for item in record_values)
    tombstones = tuple(tombstone_from_dict(item) for item in tombstone_values)
    if (
        len({item.memory_id for item in live_records}) != len(live_records)
        or len({item.memory_id for item in tombstones}) != len(tombstones)
        or {item.memory_id for item in live_records}
        & {item.memory_id for item in tombstones}
    ):
        raise RuntimeError("Memory Eval fixture identifiers are not disjoint")

    raw_cases = _sequence(cases_document["cases"], "cases")
    raw_gold = _sequence(gold_document["gold"], "gold")
    gold_by_id: dict[str, Mapping[str, object]] = {}
    for value in raw_gold:
        item = _mapping(value, "gold")
        _verify_bound_record(item, "gold_digest", _DOMAINS["gold"])
        case_id = _string(item["case_id"], "gold.case_id")
        if case_id in gold_by_id:
            raise RuntimeError("Memory Eval duplicate gold case")
        gold_by_id[case_id] = item

    cases: list[_EvalCase] = []
    for value in raw_cases:
        item = _mapping(value, "case")
        _verify_bound_record(item, "case_digest", _DOMAINS["case"])
        case_id = _string(item["case_id"], "case.case_id")
        gold = gold_by_id.get(case_id)
        if gold is None:
            raise RuntimeError("Memory Eval case has no gold")
        cases.append(_decode_case(item, gold))
    if tuple(item.case_id for item in cases) != tuple(
        sorted(item.case_id for item in cases)
    ) or {item.case_id for item in cases} != set(gold_by_id):
        raise RuntimeError("Memory Eval case/gold inventory mismatch")
    _validate_fixture_facts(tuple(cases), live_records, tombstones, records)
    return _LoadedBundle(manifest, tuple(cases))


def _decode_case(
    item: Mapping[str, object],
    gold: Mapping[str, object],
) -> _EvalCase:
    expected_case_keys = {
        "schema_version",
        "case_id",
        "tags",
        "actor",
        "conversation_scope",
        "query",
        "memory_types",
        "k",
        "candidate_limit_per_type",
        "candidate_limit_total",
        "case_digest",
    }
    expected_gold_keys = {
        "schema_version",
        "case_id",
        "relevant_memory_ids",
        "forbidden_memory_ids",
        "lexical_subset",
        "gold_digest",
    }
    if set(item) != expected_case_keys or set(gold) != expected_gold_keys:
        raise RuntimeError("Memory Eval case or gold schema mismatch")
    if item["schema_version"] != 1 or gold["schema_version"] != 1:
        raise RuntimeError("Memory Eval record schema mismatch")
    if item["case_id"] != gold["case_id"]:
        raise RuntimeError("Memory Eval case/gold binding mismatch")
    if (
        item["k"] != K
        or item["candidate_limit_per_type"] != CANDIDATE_LIMIT_PER_TYPE
        or item["candidate_limit_total"] != CANDIDATE_LIMIT_TOTAL
    ):
        raise RuntimeError("Memory Eval case limits differ from manifest")

    actor_value = _mapping(item["actor"], "actor")
    if set(actor_value) != {"platform", "bot_id", "user_id", "roles"}:
        raise RuntimeError("Memory Eval actor schema mismatch")
    actor = Actor(
        _string(actor_value["platform"], "actor.platform"),
        _string(actor_value["bot_id"], "actor.bot_id"),
        _string(actor_value["user_id"], "actor.user_id"),
        frozenset(
            RoleId(_string(value, "actor.role"))
            for value in _sequence(actor_value["roles"], "actor.roles")
        ),
        frozenset(),
    )
    scope_value = _mapping(item["conversation_scope"], "conversation_scope")
    if set(scope_value) != {
        "platform",
        "bot_id",
        "conversation_type",
        "conversation_id",
        "group_id",
        "persona_id",
    }:
        raise RuntimeError("Memory Eval conversation Scope schema mismatch")
    scope = ConversationScope(
        _string(scope_value["platform"], "scope.platform"),
        _string(scope_value["bot_id"], "scope.bot_id"),
        ConversationType(
            _string(scope_value["conversation_type"], "scope.conversation_type")
        ),
        _string(scope_value["conversation_id"], "scope.conversation_id"),
        _optional_string(scope_value["group_id"], "scope.group_id"),
        _string(scope_value["persona_id"], "scope.persona_id"),
    )
    query = _mapping(item["query"], "query")
    if set(query) != {"text", "locale"}:
        raise RuntimeError("Memory Eval query schema mismatch")
    memory_types = frozenset(
        MemoryType(_string(value, "memory_type"))
        for value in _sequence(item["memory_types"], "memory_types")
    )
    forbidden_value = _mapping(gold["forbidden_memory_ids"], "forbidden")
    if set(forbidden_value) != set(_SAFETY_CATEGORIES):
        raise RuntimeError("Memory Eval safety category mismatch")
    forbidden = {
        category: frozenset(
            _string(value, f"forbidden.{category}")
            for value in _sequence(forbidden_value[category], category)
        )
        for category in _SAFETY_CATEGORIES
    }
    lexical_subset = gold["lexical_subset"]
    if type(lexical_subset) is not bool:
        raise RuntimeError("Memory Eval lexical subset flag is not boolean")
    return _EvalCase(
        _string(item["case_id"], "case_id"),
        tuple(_string(value, "tag") for value in _sequence(item["tags"], "tags")),
        actor,
        scope,
        _string(query["text"], "query.text"),
        _string(query["locale"], "query.locale"),
        memory_types,
        frozenset(
            _string(value, "relevant_memory_id")
            for value in _sequence(gold["relevant_memory_ids"], "relevant_memory_ids")
        ),
        forbidden,
        lexical_subset,
    )


def _validate_fixture_facts(
    cases: tuple[_EvalCase, ...],
    records: tuple[MemoryRecord, ...],
    tombstones: tuple[MemoryTombstone, ...],
    records_document: Mapping[str, object],
) -> None:
    if not cases:
        raise RuntimeError("Memory Eval has no cases")
    by_id = {item.memory_id: item for item in records}
    tombstones_by_id = {item.memory_id: item for item in tombstones}
    covered_tags = {tag for case in cases for tag in case.tags}
    if not _REQUIRED_TAGS <= covered_tags:
        raise RuntimeError("Memory Eval required coverage tags are missing")
    if (
        len({case.actor.platform for case in cases}) < 2
        or len({case.actor.bot_id for case in cases}) < 2
        or len({case.actor.user_id for case in cases}) < 2
        or len({case.scope.persona_id for case in cases}) < 2
        or {case.scope.conversation_type for case in cases}
        != {ConversationType.GROUP, ConversationType.PRIVATE}
        or {memory_type for case in cases for memory_type in case.memory_types}
        != set(MemoryType)
    ):
        raise RuntimeError("Memory Eval identity or Memory type coverage is incomplete")
    state_revision = records_document["state_revision"]
    if (
        type(state_revision) is not int
        or state_revision < 1
        or any(item.state_revision > state_revision for item in tombstones)
    ):
        raise RuntimeError("Memory Eval repository generation is invalid")

    for case in cases:
        if not case.relevant_ids or any(
            not values for values in case.forbidden_ids.values()
        ):
            raise RuntimeError("Memory Eval metric denominator is empty")
        if case.lexical_subset != bool(cjk_bm25_terms(case.query)):
            raise RuntimeError("Memory Eval lexical subset is not fact-derived")
        forbidden_union = frozenset().union(*case.forbidden_ids.values())
        if case.relevant_ids & forbidden_union or sum(
            len(values) for values in case.forbidden_ids.values()
        ) != len(forbidden_union):
            raise RuntimeError("Memory Eval gold populations overlap")
        for memory_id in case.relevant_ids:
            record = by_id.get(memory_id)
            if record is None or not _eligible(record, case):
                raise RuntimeError("Memory Eval relevant record is not eligible")
        for memory_id in case.forbidden_ids["cross_scope"]:
            record = by_id.get(memory_id)
            if (
                record is None
                or _scope_matches(record, case)
                or record.created_at > FIXED_NOW
                or (record.expires_at is not None and record.expires_at <= FIXED_NOW)
                or record.sensitivity is Sensitivity.RESTRICTED
            ):
                raise RuntimeError("Memory Eval cross-Scope stratum is invalid")
        for memory_id in case.forbidden_ids["future_created"]:
            record = by_id.get(memory_id)
            if (
                record is None
                or not _scope_matches(record, case)
                or (record.created_at <= FIXED_NOW)
            ):
                raise RuntimeError("Memory Eval future-created stratum is invalid")
        for memory_id in case.forbidden_ids["expired"]:
            record = by_id.get(memory_id)
            if (
                record is None
                or not _scope_matches(record, case)
                or record.expires_at is None
                or record.expires_at > FIXED_NOW
            ):
                raise RuntimeError("Memory Eval expired stratum is invalid")
        for memory_id in case.forbidden_ids["restricted"]:
            record = by_id.get(memory_id)
            if (
                record is None
                or not _scope_matches(record, case)
                or record.sensitivity is not Sensitivity.RESTRICTED
            ):
                raise RuntimeError("Memory Eval Restricted stratum is invalid")
        for memory_id in case.forbidden_ids["tombstoned"]:
            tombstone = tombstones_by_id.get(memory_id)
            if tombstone is None or not _scope_identity_matches(tombstone.scope, case):
                raise RuntimeError("Memory Eval tombstone stratum is invalid")


def _eligible(record: MemoryRecord, case: _EvalCase) -> bool:
    return (
        _scope_matches(record, case)
        and record.created_at <= FIXED_NOW
        and (record.expires_at is None or record.expires_at > FIXED_NOW)
        and record.sensitivity is not Sensitivity.RESTRICTED
    )


def _scope_matches(record: MemoryRecord, case: _EvalCase) -> bool:
    if not _scope_identity_matches(record.scope, case):
        return False
    memory_type = record.scope.memory_type
    if memory_type is MemoryType.USER_PROFILE:
        return record.visibility is Visibility.SAFE_USER_PROFILE
    if memory_type is MemoryType.GROUP_MEMORY:
        return record.visibility is Visibility.CURRENT_GROUP
    return record.visibility is Visibility.CURRENT_CONVERSATION


def _scope_identity_matches(scope: MemoryScope, case: _EvalCase) -> bool:
    if (
        scope.platform != case.scope.platform
        or scope.bot_id != case.scope.bot_id
        or scope.persona_id != case.scope.persona_id
        or scope.memory_type not in case.memory_types
    ):
        return False
    if scope.memory_type is MemoryType.USER_PROFILE:
        return scope.user_id == case.actor.user_id
    if scope.memory_type is MemoryType.GROUP_MEMORY:
        return (
            scope.conversation_id == case.scope.conversation_id
            and scope.group_id == case.scope.group_id
            and scope.user_id is None
        )
    return (
        scope.conversation_id == case.scope.conversation_id
        and scope.group_id == case.scope.group_id
        and scope.user_id == case.actor.user_id
    )


async def _evaluate_cases(
    bundle_path: Path,
    cases: Sequence[_EvalCase],
) -> _EvaluationRun:
    records_document = _mapping(_read_json(bundle_path / "records.json"), "records")
    expected_revision = _string(
        records_document["repository_revision"], "repository_revision"
    )
    expected_state_revision = _integer(
        records_document["state_revision"], "state_revision"
    )
    with tempfile.TemporaryDirectory(prefix="dududa-memory-state-") as temporary:
        state_path = Path(temporary) / "records.json"
        _write_json(state_path, records_document)
        authority = HmacScopeSelectorAuthority(
            _SELECTOR_KEY,
            policy_revision=POLICY_REVISION,
            clock=lambda: FIXED_NOW,
            id_factory=_SequentialIds("selector"),
        )
        repository = _CountingJsonMemoryRepository(
            state_path,
            authority,
            clock=lambda: FIXED_NOW,
            id_factory=_SequentialIds("snapshot"),
        )
        policy = _CountingPolicy(
            authority,
            policy_revision=POLICY_REVISION,
            clock=lambda: FIXED_NOW,
        )
        ranker = _CountingRanker(CjkBm25MemoryRanker(clock=lambda: FIXED_NOW))
        retriever = DeterministicScopedMemoryRetriever(
            repository,
            policy,
            ranker=ranker,
            clock=lambda: FIXED_NOW,
        )
        call_counts = {
            strategy.value: {
                "policy": 0,
                "repository_open": 0,
                "repository_retrieve": 0,
                "ranker": 0,
            }
            for strategy in MemoryRetrievalStrategy
        }
        predictions: list[_Prediction] = []
        for case in cases:
            for strategy in MemoryRetrievalStrategy:
                before = _call_counter_snapshot(repository, policy, ranker)
                request = _retrieval_request(case, strategy)
                result = await retriever.retrieve(
                    request,
                    call=_port_call(case.case_id, strategy),
                )
                after = _call_counter_snapshot(repository, policy, ranker)
                for name in before:
                    call_counts[strategy.value][name] += after[name] - before[name]
                _validate_eval_result(
                    request,
                    result,
                    expected_revision=expected_revision,
                    expected_state_revision=expected_state_revision,
                )
                selected_ids = tuple(match.record.memory_id for match in result.matches)
                fingerprint_payload = {
                    "case_id": case.case_id,
                    "strategy": strategy.value,
                    "request_digest": str(request.request_digest),
                    "selected": [
                        {
                            "memory_id": match.record.memory_id,
                            "rank": match.rank,
                            "score": str(match.score)
                            if match.score is not None
                            else None,
                            "match_strategy": match.strategy.value,
                            "ranker_revision": (
                                _component_record(match.ranker_revision)
                                if match.ranker_revision is not None
                                else None
                            ),
                        }
                        for match in result.matches
                    ],
                    "degraded": result.degraded,
                    "reason_codes": list(result.reason_codes),
                    "repository_revision": result.repository_revision,
                    "state_revision": result.state_revision,
                    "policy_revision": result.policy_revision,
                    "retriever_revision": _component_record(result.retriever_revision),
                }
                predictions.append(
                    _Prediction(
                        case.case_id,
                        strategy,
                        selected_ids,
                        case.relevant_ids,
                        case.forbidden_ids,
                        result.degraded,
                        result.reason_codes,
                        result.state_revision,
                        str(
                            canonical_digest(
                                fingerprint_payload,
                                domain=_DOMAINS["ranking"],
                            )
                        ),
                    )
                )
        return _EvaluationRun(tuple(predictions), call_counts)


def _retrieval_request(
    case: _EvalCase,
    strategy: MemoryRetrievalStrategy,
) -> MemoryRetrievalRequest:
    request = MemoryRetrievalRequest(
        1,
        f"memory-eval:{case.case_id}:{strategy.value}",
        DigestString("pending"),
        case.actor,
        case.scope,
        MemoryQuery(1, case.query, case.locale, FIXED_NOW),
        case.memory_types,
        strategy,
        K,
        CANDIDATE_LIMIT_PER_TYPE,
        CANDIDATE_LIMIT_TOTAL,
        FIXED_NOW,
        True,
    )
    return replace(
        request,
        request_digest=memory_retrieval_request_digest(request),
    )


def _port_call(
    case_id: str,
    strategy: MemoryRetrievalStrategy,
) -> PortCallContext:
    return PortCallContext(
        f"memory-eval:{case_id}:{strategy.value}",
        TraceContext(f"memory-eval-trace:{case_id}:{strategy.value}"),
        FIXED_NOW + timedelta(minutes=5),
        NeverCancelled(),
        RuntimeBudget(0, 0, 0, 0, 0, Decimal(0)),
        POLICY_REVISION,
    )


def _call_counter_snapshot(
    repository: _CountingJsonMemoryRepository,
    policy: _CountingPolicy,
    ranker: _CountingRanker,
) -> dict[str, int]:
    return {
        "policy": policy.selector_calls,
        "repository_open": repository.open_calls,
        "repository_retrieve": repository.retrieve_calls,
        "ranker": ranker.rank_calls,
    }


def _validate_eval_result(
    request: MemoryRetrievalRequest,
    result: MemoryRetrievalResult,
    *,
    expected_revision: str,
    expected_state_revision: int,
) -> None:
    if (
        not isinstance(result, MemoryRetrievalResult)
        or result.request_digest != request.request_digest
        or result.strategy is not request.strategy
        or result.result_digest != memory_retrieval_result_digest(result)
    ):
        raise RuntimeError("Memory Eval retriever returned invalid evidence")
    if request.strategy is MemoryRetrievalStrategy.NO_MEMORY:
        if (
            result.repository_revision is not None
            or result.state_revision is not None
            or result.repository_snapshot_id is not None
            or result.matches
        ):
            raise RuntimeError("Memory Eval M0 touched durable Memory evidence")
    elif (
        result.repository_revision != expected_revision
        or result.state_revision != expected_state_revision
    ):
        raise RuntimeError("Memory Eval strategy observed a different generation")


def _build_report(
    loaded: _LoadedBundle,
    normal: _EvaluationRun,
    reverse: _EvaluationRun,
    shuffled: _EvaluationRun,
) -> dict[str, object]:
    normal_fingerprints = {
        (item.case_id, item.strategy.value): item.ranking_fingerprint
        for item in normal.predictions
    }
    reverse_fingerprints = {
        (item.case_id, item.strategy.value): item.ranking_fingerprint
        for item in reverse.predictions
    }
    shuffled_fingerprints = {
        (item.case_id, item.strategy.value): item.ranking_fingerprint
        for item in shuffled.predictions
    }
    order_reproducible = (
        normal_fingerprints == reverse_fingerprints == shuffled_fingerprints
    )
    by_strategy = {
        strategy: tuple(
            item for item in normal.predictions if item.strategy is strategy
        )
        for strategy in MemoryRetrievalStrategy
    }
    metrics = {
        strategy.value: _retrieval_metrics(values)
        for strategy, values in by_strategy.items()
    }
    safety = {
        strategy.value: _safety_metrics(values)
        for strategy, values in by_strategy.items()
    }
    lexical_case_ids = frozenset(
        _string(value, "lexical_subset_case_id")
        for value in _sequence(
            loaded.manifest["lexical_subset_case_ids"],
            "lexical_subset_case_ids",
        )
    )
    lexical_metrics = {
        strategy.value: _retrieval_metrics(
            tuple(
                item
                for item in by_strategy[strategy]
                if item.case_id in lexical_case_ids
            )
        )
        for strategy in (
            MemoryRetrievalStrategy.RECENCY,
            MemoryRetrievalStrategy.CJK_BM25,
        )
    }
    m1_ndcg = Decimal(
        _mapping(
            lexical_metrics[MemoryRetrievalStrategy.RECENCY.value]["binary_ndcg_at_k"],
            "m1_ndcg",
        )["value"]
    )
    m2_ndcg = Decimal(
        _mapping(
            lexical_metrics[MemoryRetrievalStrategy.CJK_BM25.value]["binary_ndcg_at_k"],
            "m2_ndcg",
        )["value"]
    )
    lexical_improved = m2_ndcg > m1_ndcg
    m0_counts = normal.call_counts[MemoryRetrievalStrategy.NO_MEMORY.value]
    m0_zero_calls = all(value == 0 for value in m0_counts.values())
    expected_state_revision = _integer(
        loaded.manifest["state_revision"], "state_revision"
    )
    same_generation = all(
        item.state_revision is None
        if item.strategy is MemoryRetrievalStrategy.NO_MEMORY
        else item.state_revision == expected_state_revision
        for item in normal.predictions
    )
    degraded = {
        strategy.value: sorted(item.case_id for item in values if item.degraded)
        for strategy, values in by_strategy.items()
    }
    expected_degradation = degraded == {
        MemoryRetrievalStrategy.NO_MEMORY.value: [],
        MemoryRetrievalStrategy.RECENCY.value: [],
        MemoryRetrievalStrategy.CJK_BM25.value: ["single-han"],
    }
    zero_safety_events = all(
        _integer(_mapping(item, "safety_item")["exposure_event_count"], "exposure") == 0
        for strategy_report in safety.values()
        for item in strategy_report.values()
    )
    technical_pass = all(
        (
            order_reproducible,
            normal.call_counts == reverse.call_counts == shuffled.call_counts,
            lexical_improved,
            m0_zero_calls,
            same_generation,
            expected_degradation,
            zero_safety_events,
        )
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "bundle_version": BUNDLE_VERSION,
        "dataset_kind": "synthetic",
        "quality_claim": "synthetic_lexical_regression_only",
        "technical_pass": technical_pass,
        "release_ready": False,
        "human_review_complete": False,
        "real_chinese_quality_claimed": False,
        "network_call_count": 0,
        "real_model_call_count": 0,
        "user_data_record_count": 0,
        "manifest_digest": loaded.manifest["manifest_digest"],
        "manifest_bound": True,
        "case_count": len(loaded.cases),
        "k": K,
        "fixture_state_revision": expected_state_revision,
        "same_fixture_generation": same_generation,
        "order_reproducible": order_reproducible,
        "call_counts": normal.call_counts,
        "m0_zero_calls": m0_zero_calls,
        "degraded_case_ids": degraded,
        "metrics": metrics,
        "safety": safety,
        "lexical_subset_comparison": {
            "primary_metric": "binary_ndcg_at_k",
            "case_ids": sorted(lexical_case_ids),
            "m1": lexical_metrics[MemoryRetrievalStrategy.RECENCY.value],
            "m2": lexical_metrics[MemoryRetrievalStrategy.CJK_BM25.value],
            "m2_strictly_better": lexical_improved,
            "evidence_boundary": "synthetic_lexical_subset_only",
        },
        "per_case": {
            strategy.value: [
                _prediction_record(item)
                for item in sorted(values, key=lambda value: value.case_id)
            ]
            for strategy, values in by_strategy.items()
        },
        "external_gates": [
            "authorized_memory_or_conversation_data",
            "independent_human_relevance_judgments",
            "held_out_real_chinese_quality_evaluation",
            "production_iris_evidence",
            "runtime_enablement_and_s23",
        ],
    }
    report["report_digest"] = str(canonical_digest(report, domain=_DOMAINS["report"]))
    return report


def _prediction_record(prediction: _Prediction) -> dict[str, object]:
    hit_ranks = [
        rank
        for rank, memory_id in enumerate(prediction.selected_ids, start=1)
        if memory_id in prediction.relevant_ids
    ]
    return {
        "case_id": prediction.case_id,
        "selected_memory_ids": list(prediction.selected_ids),
        "relevant_hit_ranks": hit_ranks,
        "degraded": prediction.degraded,
        "reason_codes": list(prediction.reason_codes),
        "ranking_fingerprint": prediction.ranking_fingerprint,
    }


def _retrieval_metrics(
    predictions: tuple[_Prediction, ...],
) -> dict[str, object]:
    if not predictions:
        raise RuntimeError("Memory Eval metric input is empty")
    relevant_total = 0
    retrieved_relevant_total = 0
    selected_total = 0
    recall_sum = Decimal(0)
    recall_any = 0
    recall_all = 0
    reciprocal_rank_sum = Decimal(0)
    ndcg_sum = Decimal(0)
    for prediction in predictions:
        if not prediction.relevant_ids:
            raise RuntimeError("Memory Eval case has no relevance denominator")
        selected = prediction.selected_ids[:K]
        hit_ranks = tuple(
            rank
            for rank, memory_id in enumerate(selected, start=1)
            if memory_id in prediction.relevant_ids
        )
        hit_count = len(hit_ranks)
        relevant_count = len(prediction.relevant_ids)
        relevant_total += relevant_count
        retrieved_relevant_total += hit_count
        selected_total += len(selected)
        recall_sum += Decimal(hit_count) / Decimal(relevant_count)
        recall_any += bool(hit_ranks)
        recall_all += hit_count == relevant_count
        if hit_ranks:
            reciprocal_rank_sum += Decimal(1) / Decimal(hit_ranks[0])
        ideal_count = min(relevant_count, K)
        ideal_dcg = sum(
            (_discount(rank) for rank in range(1, ideal_count + 1)), Decimal(0)
        )
        actual_dcg = sum((_discount(rank) for rank in hit_ranks), Decimal(0))
        ndcg_sum += actual_dcg / ideal_dcg
    case_count = len(predictions)
    return {
        "case_count": case_count,
        "selected_total": selected_total,
        "retrieved_relevant_total": retrieved_relevant_total,
        "relevant_total": relevant_total,
        "precision_at_k": _integer_metric(
            retrieved_relevant_total,
            case_count * K,
        ),
        "recall_at_k": _decimal_metric(recall_sum, case_count),
        "micro_recall_at_k": _integer_metric(
            retrieved_relevant_total,
            relevant_total,
        ),
        "recall_any": _integer_metric(recall_any, case_count),
        "recall_all": _integer_metric(recall_all, case_count),
        "mrr": _decimal_metric(reciprocal_rank_sum, case_count),
        "binary_ndcg_at_k": _decimal_metric(ndcg_sum, case_count),
    }


def _safety_metrics(
    predictions: tuple[_Prediction, ...],
) -> dict[str, object]:
    if not predictions:
        raise RuntimeError("Memory Eval safety input is empty")
    result: dict[str, object] = {}
    for category in _SAFETY_CATEGORIES:
        opportunities = sum(len(item.forbidden_ids[category]) for item in predictions)
        applicable_cases = sum(
            bool(item.forbidden_ids[category]) for item in predictions
        )
        exposed_pairs = {
            (item.case_id, memory_id)
            for item in predictions
            for memory_id in item.selected_ids
            if memory_id in item.forbidden_ids[category]
        }
        if opportunities < 1 or applicable_cases < 1:
            raise RuntimeError("Memory Eval safety opportunity denominator is empty")
        exposure_events = len(exposed_pairs)
        result[category] = {
            "opportunity_count": opportunities,
            "applicable_case_count": applicable_cases,
            "exposure_event_count": exposure_events,
            "exposed_record_count": len({item[1] for item in exposed_pairs}),
            "nominal_one_sided_95_percent_upper_if_zero": (
                _zero_event_upper_bound(opportunities) if exposure_events == 0 else None
            ),
            "upper_bound_basis": "synthetic_case_record_opportunities",
        }
    return result


def _discount(rank: int) -> Decimal:
    return Decimal(1) / Decimal(str(math.log2(rank + 1)))


def _integer_metric(numerator: int, denominator: int) -> dict[str, object]:
    if denominator < 1:
        raise RuntimeError("Memory Eval metric denominator is empty")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": _format_decimal(Decimal(numerator) / Decimal(denominator)),
    }


def _decimal_metric(numerator: Decimal, denominator: int) -> dict[str, object]:
    if denominator < 1:
        raise RuntimeError("Memory Eval metric denominator is empty")
    return {
        "numerator": _format_decimal(numerator),
        "denominator": denominator,
        "value": _format_decimal(numerator / Decimal(denominator)),
    }


def _format_decimal(value: Decimal) -> str:
    return format(value.quantize(_METRIC_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _zero_event_upper_bound(opportunities: int) -> str:
    if opportunities < 1:
        raise RuntimeError("Memory Eval zero-event denominator is empty")
    value = Decimal(str(1 - math.pow(0.05, 1 / opportunities)))
    return _format_decimal(value)


def _verify_bound_record(
    item: Mapping[str, object],
    digest_key: str,
    domain: str,
) -> None:
    digest = item.get(digest_key)
    if not isinstance(digest, str) or not digest:
        raise RuntimeError("Memory Eval record digest is missing")
    payload = {key: value for key, value in item.items() if key != digest_key}
    if digest != str(canonical_digest(payload, domain=domain)):
        raise RuntimeError("Memory Eval record digest mismatch")


def _read_json(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise RuntimeError(f"Invalid Memory Eval JSON: {path.name}") from None


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RuntimeError(f"Memory Eval {name} must be an object")
    return value


def _sequence(value: object, name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"Memory Eval {name} must be an array")
    return tuple(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Memory Eval {name} must be a non-empty string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"Memory Eval {name} must be an integer")
    return value


def _data_card() -> str:
    return """# S14 Memory Retrieval 合成评测数据卡

状态：固定生成、仅合成数据、尚未完成人工评审。

- Bundle：`memory-retrieval-synthetic-v1`
- 数据来源：本地确定性生成器；不含真实 QQ、用户或 Memory 数据
- 策略：M0 no-memory、M1 recency、M2 CJK BM25
- 网络与模型调用：禁止，计数为 0
- 人工相关性评审：未完成
- 真实中文检索质量：未建立

所有策略使用同一份 JSON v2 状态、同一 UTC 参考时间和同一候选上限。
这里的 JSON v2 只是 S14 reference Adapter 的派生测试镜像，不是稳定的 Eval
Domain DTO；未来存储格式迁移必须显式重生成并重新验证 golden。
安全分母来自 fixture 中实际存在的跨 Scope、未来创建、已过期、tombstone
和 Restricted 记录，而不是来自返回结果。安全事件必须为 0；零事件的单侧
95% 上界只描述本合成覆盖，不是对真实流量的统计保证。

tombstone stratum 证明固定 v2 状态中的已删 ID 不会被检索或复活；它不替代
删除事务、崩溃恢复和 restore fence 的 lifecycle Contract Test。

预注册 lexical subset 只验证固定词法目标上 M2 相对 M1 的回归改善。它不证明
真实中文体验、长期记忆有效性、生产 Iris、Embedding/Hybrid 增益或 Runtime
启用条件；这些仍需授权数据、人工标注和后续外部门禁。
"""
