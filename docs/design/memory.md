# Memory Design

Status: Phase 1 design; the scoped Memory v2 interfaces are not implemented.

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

## Non-Goals

- Replacing Iris storage in the first Memory phase.
- Training a memory-specific model.
- Migrating production memories automatically without a dry run and backup.
- Treating all recent context or every message as long-term memory.

## Domain Types

### Memory Scope

```text
MemoryScope
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
SESSION_STATE
SHORT_TERM_CONVERSATION
USER_PROFILE
GROUP_MEMORY
EPISODIC
EXPLICIT_USER_MEMORY
```

### Memory Record

```text
MemoryRecord
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
  semantic_score: float | None
  recency_score: float
  policy_reason: str
```

Scores do not override Scope or privacy policy.

## Scope Matrix

| Memory type | Minimum exact boundary | Default visibility |
| --- | --- | --- |
| Session State | platform + Bot + conversation | Same execution/session only |
| Short-term Conversation | platform + Bot + conversation + Persona | Same conversation |
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

## Owned Interfaces

Agent Core owns Protocols similar to:

```python
class MemoryRepository(Protocol):
    async def retrieve(
        self, selector: ScopeSelector, query: MemoryQuery
    ) -> Sequence[MemoryRecord]: ...

    async def put(self, record: MemoryRecord, expected_version: int | None) -> MemoryRecord: ...
    async def delete(self, memory_id: str, scope: MemoryScope) -> bool: ...
    async def list(self, selector: ScopeSelector, page: PageRequest) -> Page[MemoryRecord]: ...

class SemanticMemoryIndex(Protocol):
    async def rank(
        self, authorized_records: Sequence[MemoryRecord], query: str, limit: int
    ) -> Sequence[MemoryMatch]: ...
```

The repository must enforce the selector in its database or backend query. It
must not fetch global candidates and then ask Python or a model to discard
other groups.

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

Context Builder receives already-authorized `MemoryMatch` values. It may select
or summarize within a token budget but cannot broaden Scope, write memory, or
change sensitivity. A model-generated summary retains all source memory IDs and
the narrowest source visibility.

## Memory Write Gate

A response or event first creates `MemoryCandidate`; it cannot write directly.

```text
MemoryCandidate
  proposed_content
  source
  proposed_type
  proposed_scope
  confidence
  sensitivity_hint
  evidence
```

The Write Gate returns one of:

```text
REJECT
ALLOW
REQUIRE_CONFIRMATION
DEFER_FOR_CONFLICT_RESOLUTION
```

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
- Expired memory is not returned.
- Semantic similarity cannot bypass Scope.
- Export/delete is constrained to the authorized Scope.
- Write Gate rejects credentials and inferred sensitive facts.
- Write Gate handles duplicate and conflicting records.
- Iris adapter never falls back to unscoped search.

Tests are split into pure policy unit tests, `MemoryRepository` contract tests
run against every implementation, Iris integration tests, and runtime
Context/Write Gate integration tests.

## Current Implementation And Migration

Today Core stores user and group JSON directly, does not retrieve it into model
context, and has no interface to Iris. The Iris patch filters some L2/L3 paths
but remains fail-open for missing metadata and unavailable scoped APIs.

Migration order:

1. Add domain Scope, record, candidate, decision, and Protocols with tests.
2. Wrap existing JSON state only for compatible explicit-memory behavior.
3. Add the fail-closed Iris adapter and contract tests.
4. Add scoped retrieval to Context Builder behind a disabled-by-default flag.
5. Add Write Gate in shadow mode, then selective persistence.
6. Migrate or quarantine legacy records through an offline, reversible tool.
7. Remove direct JSON/Iris access only after no production entry uses it.
