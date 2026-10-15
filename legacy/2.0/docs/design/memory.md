# Memory Design

Status: S14 offline reference implementation is complete and disabled by
default. Scope-authorized lifecycle, M0/M1/M2 retrieval and a fixed synthetic
Eval exist; Runtime consumption, a real Iris SDK backend, authorized-data
quality evidence and production cutover remain pending.

## Goals

- Prevent cross-platform, cross-Bot, cross-conversation, cross-group,
  cross-user, private-to-group, and cross-Persona disclosure.
- Make Scope a validated domain value, not optional metadata interpreted by a
  model.
- Filter by exact authorized Scope before semantic retrieval.
- Separate memory candidates, write policy, persistence, and model summaries.
- Keep Iris usable behind an adapter without coupling Agent Runtime to Iris.
- Give users inspect, export, and delete behavior that cannot reveal a broader
  scope than the requesting context permits.
- Keep runtime checkpoints, recent conversation context, and durable semantic
  memory in separate stores even though the product UI may group them under
  one "Memory System" label.

## Non-Goals

- Replacing Iris storage in the first Memory phase.
- Training a memory-specific model.
- Migrating production memories automatically without a dry run and backup.
- Treating all recent context or every message as long-term memory.

## Domain Types

### Memory Scope

```text
MemoryScope
  schema_version: int
  platform: str
  bot_id: str
  conversation_type: PRIVATE | GROUP | CHANNEL
  conversation_id: str
  group_id: str | None
  user_id: str | None
  persona_id: str
  memory_type: MemoryType
```

Validation rules are deterministic:

- Every Scope requires non-empty platform, Bot, conversation, Persona, and
  memory type values.
- Group Scope requires a non-empty `group_id` equal to the adapter-resolved
  group identity.
- Private Scope forbids a group ID and requires the private conversation ID.
- User-owned memory requires a user ID.
- Missing or malformed fields are errors, never wildcard matches.
- Platform-local IDs are opaque strings; no numeric assumptions belong in core.

### Memory Type

```text
USER_PROFILE
GROUP_MEMORY
EPISODIC
EXPLICIT_USER_MEMORY
```

`SESSION_STATE` is owned by `RuntimeStateStore`; recent messages and reply chains
are owned by `ConversationContextStore`. They are not `MemoryRecord` types and
cannot be queried through semantic long-term retrieval. This removes two sources
of truth while preserving the architecture diagram's conceptual short-term,
long-term, and user/group memory layers.

### Memory Record

```text
MemoryRecord
  schema_version: int
  memory_id: str
  scope: MemoryScope
  content: str
  source: MemorySource
  created_at: datetime
  updated_at: datetime
  confidence: float
  expires_at: datetime | None
  sensitivity: Sensitivity
  visibility: Visibility
  evidence: tuple[EvidenceReference, ...]
  content_hash: str
  version: int
```

`MemorySource` identifies explicit user request, observed user statement,
conversation summary, tool result, administrator migration, or legacy import.
It also identifies the source user where applicable. Tool or model text alone
is not proof that a fact belongs to a user.

`Sensitivity` is `PUBLIC`, `PERSONAL`, `SENSITIVE`, or `RESTRICTED`.
`Visibility` is a code-owned policy value, not model prose. The default is the
narrowest conversation Scope.

### Retrieval Result

```text
MemoryMatch
  record: MemoryRecord
  rank: int
  semantic_score: float | None
  recency_score: float
  policy_reason: str
  ranker_revision: ComponentRevision | None
```

Scores do not override Scope or privacy policy.

```python
@dataclass(frozen=True, slots=True)
class MemoryQuery:
    schema_version: int
    text: str
    locale: str
    reference_time: datetime

@dataclass(frozen=True, slots=True)
class PageRequest:
    schema_version: int
    cursor: str | None
    limit: int

@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    schema_version: int
    items: tuple[T, ...]
    next_cursor: str | None
    snapshot_revision: str
```

Cursor 是与 selector、排序、snapshot revision 绑定的 opaque 值；调用方不能修改它来扩大
Scope。`reference_time` 由 Runtime 的受信时钟提供，语义后端不能自行把过期记录拉回结果。

## Scope Matrix

| Memory type | Minimum exact boundary | Default visibility |
| --- | --- | --- |
| User Profile | platform + Bot + user + Persona | Same user; group use requires safe-profile policy |
| Group Memory | platform + Bot + group conversation + Persona | Same group only |
| Episodic | platform + Bot + conversation + Persona, plus owner when personal | Same conversation unless explicitly promoted |
| Explicit User Memory | platform + Bot + user + Persona and recorded origin | Same origin conversation by default |

Private-to-group reuse is denied by default. A user profile field may be used in
a group only when deterministic policy marks it safe for that user's public
context. Sensitive and restricted records are never promoted by a model.

Cross-group retrieval is always denied. A concept such as “global group
knowledge” must be represented as a separate curated capability or knowledge
base, not as a missing group filter.

### Authorized Scope Selector

```python
class SelectorMode(StrEnum):
    CURRENT_CONVERSATION = "current_conversation"
    CURRENT_GROUP = "current_group"
    SAFE_USER_PROFILE = "safe_user_profile"

@dataclass(frozen=True, slots=True)
class ScopeSelector:
    schema_version: int
    selector_id: str
    request_digest: DigestString
    mode: SelectorMode
    policy_revision: str
    purpose: str
    actor_ref: str
    current_scope_digest: DigestString
    platform: str
    bot_id: str
    persona_id: str
    conversation_id: str | None
    group_id: str | None
    user_id: str | None
    memory_types: frozenset[MemoryType]
    issued_at: datetime
    expires_at: datetime
    integrity_proof: str
```

`ScopeSelector` is an integrity-protected authorization grant, not a caller-supplied filter.
Only `MemoryRetrievalPolicy` and the administration policy can issue it. Directly
constructing the dataclass does not create a valid proof. Every
mode has a closed validation table: for example, `CURRENT_GROUP` requires the
current exact group ID and forbids another conversation; `SAFE_USER_PROFILE`
requires the current actor's user ID and can select only explicitly public-safe
profile fields. Optional fields are mode-dependent values, never wildcards.
Repositories verify the proof with an injected `ScopeSelectorVerifier` and reject expired
selectors, unsupported policy revisions, request-digest mismatches, or any selector whose
bound actor/current-scope digest does not match the signed grant. The same verification is
mandatory in-process and remotely; the proof format is an infrastructure concern and never
model-visible.

## Owned Interfaces

Agent Core owns Protocols similar to:

```python
@dataclass(frozen=True, slots=True)
class MemoryRepositorySnapshot:
    schema_version: int
    snapshot_id: str
    repository_revision: str
    selector_digests: tuple[DigestString, ...]
    request_digest: DigestString
    as_of: datetime
    expires_at: datetime
    integrity_digest: DigestString

class MemoryRepository(Protocol):
    async def open_snapshot(
        self,
        selectors: tuple[ScopeSelector, ...],
        *,
        request_digest: DigestString,
        as_of: datetime,
        call: PortCallContext,
    ) -> MemoryRepositorySnapshot: ...

    async def get(
        self,
        snapshot: MemoryRepositorySnapshot,
        memory_id: str,
        selector: ScopeSelector,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> MemoryRecord | None: ...

    async def retrieve(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        query: MemoryQuery,
        *,
        candidate_limit: int,
        cursor: str | None,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> Page[MemoryRecord]: ...

    async def commit_write(
        self,
        command: "MemoryWriteCommand",
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> "MemorySubmissionReceipt": ...

    async def commit_delete(
        self,
        command: "MemoryDeleteCommand",
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> "MemoryDeleteReceipt": ...

    async def list(
        self,
        snapshot: MemoryRepositorySnapshot,
        selector: ScopeSelector,
        page: PageRequest,
        *,
        request_digest: DigestString,
        call: PortCallContext,
    ) -> Page[MemoryRecord]: ...

class ScopeSelectorVerifier(Protocol):
    def verify(
        self,
        selector: ScopeSelector,
        *,
        expected_request_digest: DigestString,
    ) -> bool: ...

@dataclass(frozen=True, slots=True)
class IndexableMemoryProjection:
    schema_version: int
    memory_id: str
    text: str
    content_digest: DigestString
    sensitivity: Sensitivity
    visibility: Visibility
    scope_digest: DigestString

@dataclass(frozen=True, slots=True)
class MemoryRankScore:
    memory_id: str
    rank: int
    semantic_score: float | None
    ranker_revision: ComponentRevision

@dataclass(frozen=True, slots=True)
class RankerDataPolicy:
    allowed_sensitivities: frozenset[Sensitivity]
    allow_external_processing: bool
    allowed_residencies: frozenset[str]
    policy_revision: str

@dataclass(frozen=True, slots=True)
class MemoryRankRequest:
    schema_version: int
    projections: tuple[IndexableMemoryProjection, ...]
    query: str
    limit: int
    data_policy: RankerDataPolicy

class SemanticMemoryIndex(Protocol):
    async def rank(
        self,
        request: MemoryRankRequest,
        *,
        call: PortCallContext,
    ) -> tuple[MemoryRankScore, ...]: ...

@dataclass(frozen=True, slots=True)
class MemoryRetrievalRequest:
    schema_version: int
    query_id: str
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    query: MemoryQuery
    memory_types: frozenset[MemoryType]
    limit: int
    candidate_limit_per_type: int
    candidate_limit_total: int
    as_of: datetime

@dataclass(frozen=True, slots=True)
class MemoryConflictGroup:
    schema_version: int
    conflict_id: str
    matches: tuple[MemoryMatch, ...]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class MemoryRetrievalResult:
    schema_version: int
    matches: tuple[MemoryMatch, ...]
    conflicts: tuple[MemoryConflictGroup, ...]
    repository_snapshot_id: str
    repository_revision: str
    policy_revision: str
    ranker_revision: ComponentRevision | None
    retriever_revision: ComponentRevision
    degraded: bool
    reason_codes: tuple[str, ...]

class MemoryRetrievalPolicy(Protocol):
    async def selectors_for(
        self,
        request: MemoryRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> tuple[ScopeSelector, ...]: ...

class ScopedMemoryRetriever(Protocol):
    async def retrieve(
        self,
        request: MemoryRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> MemoryRetrievalResult: ...
```

The repository must enforce the selector in its database or backend query. It
must not fetch global candidates and then ask Python or a model to discard
other groups. Runtime and tools are not given a raw `put(record)` escape hatch:
every durable mutation requires an unexpired, matching Gate or administration
command and an idempotency key.

`MemoryRetrievalRequest.request_digest` hashes the canonical request excluding the digest
field itself. Policy copies it into every issued selector; Retriever passes the same digest
to Repository, which verifies both equality and integrity proof before querying.

一次检索先对完整 selector 集合取得 `MemoryRepositorySnapshot`，后续 get/retrieve/list 都显式
携带该 handle；Repository 拒绝 revision、selector、request digest 或 expiry 不匹配的混合
读取。`retrieve()` 必须在后端查询中应用 Scope/TTL/visibility 和 `candidate_limit`，返回绑定
snapshot 的 cursor page；每 Memory Type 与总候选数都有配置硬上限，不能先物化整个 Scope
再送给 Ranker。

`SemanticMemoryIndex` never receives a full `MemoryRecord`, evidence object, Actor, or raw
Scope. Retriever constructs a minimal projection only after authorization. `RESTRICTED`
records are never indexable; Sensitive projections require a policy that permits the concrete
local/external ranker and residency. Authorization to read a record does not automatically
authorize sending its text to an embedding Provider. Ranker returns IDs/scores only; Retriever
joins them back to the already-authorized records and rejects unknown/duplicate IDs.

`ScopeSelector` is produced by trusted policy code. It is not a bag of optional
fields from a tool plan. Any allowed broader selector, such as a safe user
profile across that user's conversations, is a named constructor with explicit
policy and tests.

## Retrieval Pipeline

```text
MessageEnvelope + Actor
  -> validate ConversationScope and identity consistency
  -> MemoryRetrievalPolicy builds named ScopeSelectors
  -> repository exact filter, TTL filter, and visibility filter
  -> optional semantic rank within authorized records
  -> sensitivity and conflict policy
  -> bounded MemoryMatch list
  -> Context Builder
```

Required properties:

1. Expired records are removed before ranking.
2. Restricted records require an explicit authorized use case.
3. Duplicate content is collapsed by content hash and version.
4. Conflicting records are returned as conflicts, not silently merged.
5. Limits apply per memory type and to the combined context budget.
6. Trace records IDs, counts, type, and reason codes, not raw content.
7. Backend errors yield no memory and a typed degraded-state trace; they never
   trigger a global fallback query.

## Context Builder Contract

```python
@dataclass(frozen=True, slots=True)
class ContextMemoryEvidence:
    schema_version: int
    evidence_id: str
    content: str
    source_memory_ids: tuple[str, ...]
    sensitivity: Sensitivity
    visibility: Visibility
    summarized: bool
    producer: ComponentRevision
```

Context Builder receives the complete `MemoryRetrievalResult`, preserving conflicts,
degraded status, and revisions, and emits bounded `ContextMemoryEvidence` only from
authorized matches. It may select or summarize within a token
budget but cannot broaden Scope, write memory, or change sensitivity. A
model-generated summary retains all source memory IDs, the narrowest source
visibility, and the summarizer revision. Perception receives this evidence
projection, not mutable Repository records or raw selectors.

## Memory Write Gate

A response or event first creates `MemoryCandidate`; it cannot write directly.

```text
MemoryCandidate
  schema_version: int
  candidate_id: str
  producer: ComponentRevision
  proposed_content
  source
  proposed_type
  proposed_scope
  confidence
  sensitivity_hint
  evidence
  proposed_ttl: timedelta | None
  delivery_dependency: NONE | SUCCESS_REQUIRED
```

The Write Gate returns one of:

```text
REJECT
ALLOW
REQUIRE_CONFIRMATION
DEFER_FOR_CONFLICT_RESOLUTION
```

正式 Port 为：

```python
class DeliveryDependency(StrEnum):
    NONE = "none"
    SUCCESS_REQUIRED = "success_required"

@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    schema_version: int
    candidate_id: str
    producer: ComponentRevision
    proposed_content: str
    source: MemorySource
    proposed_type: MemoryType
    proposed_scope: MemoryScope
    confidence: float
    sensitivity_hint: Sensitivity
    evidence: tuple[EvidenceReference, ...]
    proposed_ttl: timedelta | None
    delivery_dependency: DeliveryDependency

class MemoryWriteAction(StrEnum):
    REJECT = "reject"
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DEFER_FOR_CONFLICT_RESOLUTION = "defer_for_conflict_resolution"

class MemorySubmissionStatus(StrEnum):
    REJECTED = "rejected"
    CONFIRMATION_REQUIRED = "confirmation_required"
    DEFERRED = "deferred"
    QUEUED = "queued"
    PERSISTED = "persisted"

@dataclass(frozen=True, slots=True)
class MemorySourceEvent:
    schema_version: int
    event_id: str
    event_type: str
    occurred_at: datetime
    source_refs: tuple[str, ...]
    payload: Mapping[str, JsonValue]
    sensitivity: Sensitivity
    producer: ComponentRevision

@dataclass(frozen=True, slots=True)
class MemoryCandidateExtractionRequest:
    schema_version: int
    message: MessageEnvelope
    actor: Actor
    conversation_scope: ConversationScope
    verified_observations: tuple[ToolObservation, ...]
    response: ValidatedFinalResponse | None
    source_events: tuple[MemorySourceEvent, ...]

class MemoryCandidateExtractor(Protocol):
    async def extract(
        self,
        request: MemoryCandidateExtractionRequest,
        *,
        call: PortCallContext,
    ) -> tuple[MemoryCandidate, ...]: ...

@dataclass(frozen=True, slots=True)
class MemoryWriteRequest:
    schema_version: int
    request_digest: DigestString
    candidate: MemoryCandidate
    actor: Actor
    conversation_scope: ConversationScope
    delivery_status: DeliveryStatus
    delivery_id: str | None
    delivery_receipt_digest: DigestString | None
    confirmation: ConfirmationGrant | None
    authorization: AuthorizationDecision
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class MemoryWriteDecision:
    schema_version: int
    decision_id: str
    request_digest: DigestString
    candidate_id: str
    candidate_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    delivery_id: str | None
    delivery_status: DeliveryStatus
    delivery_receipt_digest: DigestString | None
    confirmation_digest: DigestString | None
    authorization_digest: DigestString
    idempotency_key: str
    action: MemoryWriteAction
    reason_codes: tuple[str, ...]
    normalized_record: MemoryRecord | None
    expected_record_version: int | None
    confirmation: ConfirmationRequirement | None
    policy_revision: str
    gate_revision: ComponentRevision
    decision_expires_at: datetime

@dataclass(frozen=True, slots=True)
class MemoryWriteCommand:
    schema_version: int
    command_id: str
    request_digest: DigestString
    decision: MemoryWriteDecision
    actor: Actor
    conversation_scope: ConversationScope
    delivery_id: str | None
    delivery_status: DeliveryStatus
    delivery_receipt_digest: DigestString | None
    confirmation: ConfirmationGrant | None
    authorization: AuthorizationDecision
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class MemorySubmissionReceipt:
    schema_version: int
    command_id: str
    decision_id: str
    candidate_id: str
    idempotency_key: str
    status: MemorySubmissionStatus
    memory_id: str | None
    outbox_event_id: str | None
    policy_revision: str
    producer: ComponentRevision
    writer_revision: ComponentRevision | None
    reason_codes: tuple[str, ...]
    recorded_at: datetime

class MemoryWriteGate(Protocol):
    async def evaluate(
        self,
        request: MemoryWriteRequest,
        *,
        call: PortCallContext,
    ) -> MemoryWriteDecision: ...

@dataclass(frozen=True, slots=True)
class MemoryAdminRequest:
    schema_version: int
    actor: Actor
    conversation_scope: ConversationScope
    purpose: str
    memory_id: str | None
    page: PageRequest | None
    confirmation: ConfirmationGrant | None

@dataclass(frozen=True, slots=True)
class MemoryDeleteCommand:
    schema_version: int
    command_id: str
    actor: Actor
    conversation_scope: ConversationScope
    memory_id: str
    expected_version: int
    authorization: AuthorizationDecision
    confirmation: ConfirmationGrant
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class MemoryDeleteReceipt:
    schema_version: int
    command_id: str
    memory_id: str
    deleted: bool
    previous_version: int | None
    policy_revision: str
    writer_revision: ComponentRevision
    reason_codes: tuple[str, ...]
    completed_at: datetime

class MemoryAdministration(Protocol):
    async def inspect(
        self,
        request: MemoryAdminRequest,
        *,
        call: PortCallContext,
    ) -> MemoryRecord | None: ...

    async def export_page(
        self,
        request: MemoryAdminRequest,
        *,
        call: PortCallContext,
    ) -> Page[MemoryRecord]: ...

    async def delete(
        self,
        command: MemoryDeleteCommand,
        *,
        call: PortCallContext,
    ) -> MemoryDeleteReceipt: ...
```

`DeliveryStatus.NOT_REQUIRED` 只用于不产生可见输出的运行；依赖送达的候选必须看到
`SUCCEEDED` 才能 `ALLOW`。`PARTIAL`、`FAILED`、`UNKNOWN` 和 `NOT_REQUIRED` 不得满足
`SUCCESS_REQUIRED`。显式 `/remember` 属于独立用户事务，候选的 dependency 为
`NONE`，但仍需通过 Scope、敏感度和确认策略。

Runtime 不直接调用裸 `put(record)`。Gate 产生的 ALLOW decision 绑定 candidate digest、
规范化 record、期望版本、Actor/Scope、投递 receipt、已消费 confirmation、幂等键、完整
request digest、当前 AuthorizationDecision digest、Policy revision 和短有效期；
`MemoryWriteCommand` 只能重复携带相同证据。
Repository 必须逐项复核后才能提交，并以 decision ID 单次消费/tombstone 阻止第二个命令
复用授权。同步成功回执为 `PERSISTED`；
异步路径先随 Runtime checkpoint 原子写入 Outbox 并返回 `QUEUED`，Worker 最终提交后另发
持久化结果事件。`CompletionReceipt` 只保存 submission receipt，不能把 `QUEUED` 写成
已经持久化。相同幂等键必须返回相同结果；过期 decision、变化的 candidate/delivery、
撤销的权限或版本冲突都 fail closed。异步 Worker 使用 `ServiceCallContext`，但 service
principal 不继承用户权限；它必须重算完整 command/request/authorization digest，并检查当前
撤销状态，不能用后台身份替代原 Actor 的授权。
`request_digest` 对除自身外的规范化完整 request 计算；`confirmation_digest` 对已经消费的
grant 计算。Repository 重算 command 证据并与 decision 比较，不能只比较调用方重复提供的
字符串。
`writer_revision` 只在 `PERSISTED` 时存在；`REJECTED/CONFIRMATION_REQUIRED/DEFERRED/
QUEUED` 由 `producer` 标识 Gate/Submission 组件，不能伪造尚未运行的 Writer revision。

Extractor 只从 request 中受信的 Actor 与 ConversationScope 构造 proposed Scope；它先验证
Actor 与 MessageEnvelope identity 一致，不能从自然语言、Tool output 或模型实体猜测
platform/Bot/conversation/group/user/Persona 边界。

Administration 不接受 selector 参数。服务从 request 中的当前 Actor、Scope、purpose 和
confirmation 重新授权，再由内部 Policy 构造 `ScopeSelector`；消息正文中的 user/group ID
永远不能直接成为查询或删除边界。

It evaluates:

- Is the statement worth retaining beyond current context?
- Is it a concrete fact, explicit preference, or user-requested memory?
- Did the affected user provide it, or is it hearsay/model inference?
- Does it contain credentials, health, identity, grades, location, or other
  sensitive data?
- Is there future value and a defined consumer?
- Is it duplicate, stale, or contradictory?
- Which exact Scope and memory type own it?
- Is a TTL required?
- Does policy require user confirmation?

Hard rules:

- Passwords, verification codes, API keys, Cookies, tokens, private keys, and QQ
  login state are rejected.
- Tool output is not written as a user fact without provenance and policy.
- Inferred sensitive attributes are rejected.
- Explicit memory commands can request a write but do not bypass sensitivity or
  Scope checks.
- A model may classify a candidate; deterministic code makes the final decision.

## Updates, Conflicts, And Deletion

- Writes use optimistic version checks or backend transactions.
- A new conflicting fact does not overwrite a prior record silently.
- Conflict resolution records evidence and actor authorization.
- User delete/export APIs accept a Scope derived from the current Actor and
  conversation, never an arbitrary user/group ID supplied in text.
- Group invocation cannot print private-origin records.
- Bulk deletion requires confirmation bound to actor, conversation, action,
  target Scope, expiry, and current authorization.

## Iris Adapter

`IrisMemoryRepository` implements core interfaces in an outer adapter. Agent
Runtime never imports Iris.

The adapter must:

1. Translate exact `MemoryScope` to Iris metadata/query parameters.
2. Reject or quarantine records missing any field required by their Memory Type,
   including group for group-owned records and user for user-owned records.
3. Refuse global-search fallback when a scoped API is unavailable.
4. Preserve legacy IDs and source metadata during migration.
5. Expose health and capability information without exposing raw memory.
6. Treat the existing patch as defense in depth, not proof of core isolation.

Legacy records without complete Scope require an offline migration workflow:
inventory, classify, dry-run, operator review, backup, migrate or quarantine,
verify counts, and retain rollback. Unknown records are not served until
resolved.

## Failure Behavior

| Failure | Runtime behavior |
| --- | --- |
| Invalid/missing Scope | Fail closed; no retrieval/write |
| Backend unavailable | Continue without long-term memory; trace degradation |
| Semantic index unavailable | Exact/recency retrieval only within authorized set |
| Conflict | Do not present one value as fact; clarify or defer |
| Write confirmation unavailable | Keep candidate transient; do not persist |
| Adapter returns out-of-scope record | Security error, discard batch, high-severity audit |

## Required Tests

At minimum, fixtures must prove:

- Group A cannot retrieve Group B memory for the same user and Persona.
- User A cannot retrieve User B memory in the same group.
- Private memory does not appear in a group response.
- One Bot identity cannot retrieve another Bot's memory.
- One Persona cannot retrieve another Persona's memory unless an explicit,
  tested migration policy allows it.
- Platform-local IDs do not collide across platforms.
- Missing metadata fails closed.
- Forged, expired, wrong-request, or wrong-policy selector proofs fail before a backend query.
- Snapshot handle rejects mixed repository revision/selector/request/expiry; cursors cannot widen Scope.
- Per-type/total candidate hard limits are enforced in the backend before semantic ranking.
- Expired memory is not returned.
- Semantic similarity cannot bypass Scope.
- Export/delete is constrained to the authorized Scope.
- Write Gate rejects credentials and inferred sensitive facts.
- Write Gate handles duplicate and conflicting records.
- Repository rejects raw/unbound records, expired Gate decisions, mismatched
  delivery evidence, reused confirmation, and changed candidate digests.
- One Gate decision cannot authorize two different commands or be consumed twice.
- Repeated write/delete idempotency keys return the same receipt; concurrent
  expected-version conflicts never overwrite newer evidence.
- `QUEUED` and `PERSISTED` remain distinguishable through crash/replay tests.
- Service Worker cannot use its principal to replace a revoked/mismatched user AuthorizationDecision.
- Iris adapter never falls back to unscoped search.
- Runtime checkpoints and recent Conversation Context are not retrievable as
  durable `MemoryRecord` values.
- External rankers never receive Restricted data or a projection disallowed by ranker privacy/
  residency policy; unknown/duplicate ranked IDs are rejected.

Tests are split into pure policy unit tests, `MemoryRepository` contract tests
run against every implementation, Iris integration tests, and runtime
Context/Write Gate integration tests.

Retrieval quality is evaluated only after the isolation suite passes. S14 now
ships a fixed generated-data-only bundle at `evals/memory-retrieval/v1` that
runs M0 no-memory, M1 deterministic recency and M2 bounded CJK BM25 over the
same JSON v2 state revision. It reports Precision@K, Recall@K, recall-any/all,
MRR, binary nDCG@K and a ranking fingerprint for every case. Cross-Scope,
future-created, expired, tombstoned and Restricted opportunities come from
actual non-empty fixture strata; their exposure counts are hard zero gates and
each zero count retains a nominal one-sided 95% upper bound.

This bundle is a deterministic security and lexical regression, not a held-out
real-language benchmark. It explicitly records `human_review_complete=false`,
`real_chinese_quality_claimed=false` and `network_allowed=false`. Its JSON v2
state is a reference-Adapter test mirror, not a stable Eval Domain storage
format. The tombstone stratum proves that already-tombstoned IDs in that fixed
state are not returned; lifecycle Contract Tests separately prove delete,
restart, restore fences and fault rollback.

M2 is a pure-Python Okapi BM25 reranker over the bounded authorized projection.
This deliberately narrows the research option of a persistent SQLite FTS5
index: a second derived store and platform tokenizer/runtime variance add no
measured value at S14 scale. The lexical tokenizer and formula revisions are
manifest-bound. M2 only claims improvement over M1 on the pre-registered
synthetic lexical subset. Embedding, hybrid/RRF, reranking, P50/P95 and
token/cost comparisons require an authorized held-out set and may enter shadow
only after a predeclared stable gain with no safety regression.

That future held-out set must be split by user/group and time, include
high-similarity out-of-scope distractors and stale/conflicting facts, and freeze
relevance judgments before comparison. Independent cases use paired bootstrap;
group/conversation-correlated cases use cluster or hierarchical bootstrap with
a 95% interval. No zero-event synthetic bound is described as proof that real
leakage probability is literally zero.

## Current Implementation And Migration

The production Core still stores user and group JSON directly and does not read
Memory v2 into model context. The framework-neutral package now provides
generation-bound snapshots/cursors, durable delete/tombstone and replay
evidence, scoped export, service archive/checkpoint restore, formal retrieval
DTO/Ports, recency and CJK BM25. The in-memory and JSON reference adapters prove
the supported lifecycle; Iris explicitly rejects delete/archive/restore that
its current backend cannot prove. No real Iris SDK backend is present.

All of this remains disabled from production. The legacy `/remember`, fuzzy
`/forget` and direct export paths are not relabeled as governed operations and
are not S14 consumers. The existing Iris patch remains defense in depth for the
old path rather than proof of the new boundary.

Migration order:

1. Completed: domain Scope, record, candidate, decisions and Ports with tests.
2. Completed: JSON v1 reader/v2 atomic state, tombstones and crash-stable replay
   evidence without overwriting pre-Scope legacy JSON.
3. Completed: fail-closed Iris Protocol adapter and explicit unsupported
   lifecycle tests.
4. Pending: add scoped retrieval to Context Builder behind a disabled-by-default
   flag using a separate consumer-migration branch.
5. Pending: route user commands through governed Administration/Write Gate;
   automatic writes remain out of scope.
6. Available but not executed on production: reversible offline migration and
   quarantine tooling.
7. S22 only: remove direct JSON/Iris access after every consumer has migration
   evidence and the previous release remains recoverable.
