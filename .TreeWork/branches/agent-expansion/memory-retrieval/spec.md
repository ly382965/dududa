# Branch Spec

Branch: memory-retrieval
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Purpose And Boundary

S14 completes the existing Memory safety skeleton without replacing
`MemoryScope`, signed `ScopeSelector`, `MemoryRepository` or
`ExplicitMemoryWriteGate`. It delivers a durable lifecycle and a bounded local
retrieval experiment:

```text
trusted Scope policy -> exact eligible records -> local deterministic ranker
                     -> bounded MemoryRetrievalResult

authorized mutation -> optimistic CAS -> durable record or tombstone
                    -> state generation change -> old snapshots fail closed
```

The branch uses only fixed synthetic records and local code. It does not enable
Memory in the S10/S11 production rollout, rewrite AstrBot commands, read real
Memory files or QQ data, add an embedding dependency, integrate production
Iris, or implement automatic extraction, Graph Memory or model-owned writes.
The formal retrieval DTO may replace the provisional Runtime type alias, but
the existing no-Memory Runtime path remains authoritative and unchanged.

### Existing Authority And Compatibility

Core continues to own exact platform, Bot, conversation, group, user, Persona,
Memory type, visibility, TTL and sensitivity. A natural-language query, model,
ranker, backend or archive cannot create or broaden a selector. Repository
reads verify the signed selector and request digest before examining records.
Rankers receive only minimal projections from the already-authorized candidate
set and may return only known IDs and scores.

Existing JSON schema v1 files containing scoped records remain readable. The
first successful S14 mutation upgrades them atomically to schema v2. Legacy
pre-scope user JSON remains quarantined and read-only. In-memory, JSON and Iris
adapters retain the same `MemoryRepository` Port; Iris lifecycle operations
that its backend cannot prove must fail closed rather than mutate only a local
shadow. No external Memory framework obtains Scope, authorization, retention,
telemetry or write authority.

### Snapshot And Time Semantics

`MemoryRepositorySnapshot` binds the static repository revision and a monotonic
state revision. `MemoryQuery.reference_time` must equal both the retrieval
request `as_of` and the snapshot `as_of`; callers cannot move the clock backward
to reveal expired records. A write, delete or restore increments state revision
and invalidates all earlier snapshots and cursors. Pagination is stable while
the generation is unchanged and fails closed after a concurrent mutation;
there is no best-effort widening or global fallback.

Eligibility always precedes ranking. Repository filtering applies exact Scope,
visibility, `created_at <= snapshot.as_of`, TTL and tombstone state at
`snapshot.as_of`, then enforces the candidate cap. Missing metadata, an invalid
selector, a mixed request digest, future `as_of`, stale generation, invalid
cursor or ranker output containing an unknown/duplicate or digest-mismatched ID
rejects the operation.

### Lifecycle Contracts And Transaction Rules

S14 adds immutable, versioned and digest-bound lifecycle DTOs for delete,
tombstone, scoped export, repository archive and restore. A tombstone retains
only the identity, previous Scope/content/version evidence and mutation
bindings needed to prevent resurrection; it never retains Memory content.

Delete requires all of the following in one locked transaction:

- an exact current record and expected-version match;
- current `memory.delete` authorization bound to Actor and conversation Scope;
- a consumed, current confirmation grant bound to the exact record payload,
  command/execution ID, authorization digest and idempotency key;
- injected authorization and confirmation verifiers; and
- an unused confirmation plus a non-conflicting idempotency key.

On success the canonical record is physically removed from the live set, its
tombstone and receipt are written, state revision advances, old snapshots are
invalidated, and the JSON replacement is fsynced atomically. Persistence
failure restores the complete pre-transaction in-memory state. Replaying the
same key and command digest returns the same receipt; changing payload under a
key, reusing one write decision or delete confirmation, deleting an already
tombstoned ID under a new key, or losing an optimistic version race is a typed
conflict.

JSON schema v2 persists live records, tombstones, write/delete/restore
idempotency evidence, consumed write decisions and consumed delete
confirmations. This is required for crash replay, not only same-process tests.
Writes to a tombstoned `memory_id` fail; an intentional new fact must receive a
new ID through the existing WriteGate. A create requires no expected version
and record version 1. An update requires exact version N, produces N+1, and
cannot change Memory ID, Scope or `created_at`; skipped versions and silent
evidence replacement fail closed.

A scoped export is just the canonical live records visible through one valid
snapshot and selector page; it contains no selector proof, embedding, ranker
state or unrelated Scope. A repository archive is a service-only recovery
artifact containing live records and tombstones with an integrity digest.
Repository archive export and restore require explicit service roles and
operation kinds; scoped user export remains Selector-bound. Restore uses
expected-state-revision CAS, validates the archive digest, replaces live
records from the archive, and unions archive tombstones with all tombstones
already known by the destination. Tombstones win over records regardless of
archive age. Thus clean import round-trips live records, while restoring a
pre-delete archive into a repository that has seen the deletion cannot revive
the record. Restore is itself idempotent and advances generation.

### Retrieval Contracts

S14 formalizes `MemoryRetrievalRequest`, `MemoryMatch`,
`MemoryRetrievalResult`, minimal index projections, rank requests/scores and
the framework-neutral `MemoryRetrievalPolicy`, `MemoryRanker` and
`ScopedMemoryRetriever` Ports. Public DTOs are frozen, slotted, schema-v1,
bounded and canonical-digest bound. The result carries request, snapshot,
repository, policy, retriever and optional ranker revisions plus explicit
degradation reasons. It never contains selectors or authorization proofs.

The deterministic policy issues one named selector per requested Memory type:
current-conversation for explicit/episodic records, current-group for group
memory, and the existing public-safe user-profile selector for user profile.
Unsupported combinations fail closed. Per-selector, per-type, total candidate
and final result limits are enforced before ranking.

Exact eligibility is the common authority layer, not a third relevance
algorithm. The offline strategies are independent and versioned:

- `M0 NO_MEMORY`: return no durable records and perform no repository/ranker
  call; this is the control, not a failure fallback disguised as quality.
- `M1 RECENCY`: sort the exact eligible authorized candidates by `updated_at`
  then `memory_id`, both descending, without interpreting query relevance.
- `M2 CJK_BM25`: rank the same candidate set with NFC + casefold normalization,
  contiguous Latin/number tokens and overlapping CJK bigrams. Punctuation,
  quotes and emoji are separators; a one-character CJK query is too short and
  explicitly degrades to M1 rather than introducing a noisy unigram or fuzzy
  match. The frozen Okapi BM25 parameters are `k1=1.2` and `b=0.75`; scores are
  bounded decimals and ties use only ascending Memory ID, never recency.

The existing Repository normalized-substring query remains a compatibility
surface but is not labeled M1 or M2. The M2 implementation is an in-process
deterministic bounded-projection baseline, not a persistent production search
service. It imports no tokenizer package, model SDK or network client. Ranker
cancellation, deadline or structural failure produces no widened query; an
explicitly configured recency degradation may use only the same already-
authorized candidate set and is marked in the result.

Duplicate content hashes collapse deterministically after authorization.
Semantic contradiction detection is not inferred from free text in S14;
optimistic version conflicts are closed, while richer subject/predicate and
temporal conflict groups remain deferred until a structured write contract
exists.

### Synthetic M0-M2 Evaluation

A checked-in, generated-data-only bundle supplies fixed Chinese, mixed Latin,
short CJK, emoji and typo cases across multiple platforms, Bots, groups,
private conversations, users, Personas, Memory types, expiry states and
tombstones. Its manifest binds the fixture digest, generation revision,
tokenizer/ranker revisions, reference time, `k`, candidate ceilings and the
fact that neither human review nor real-Chinese quality has been established.

M0, M1 and M2 run over the same cases and frozen judgments. Reports keep fixed
denominators for relevant records, selected records, reciprocal rank and every
forbidden population. Cross-Scope, expired and tombstoned exposure counts have
a hard target of zero and are never traded against Recall, Precision or MRR.
The golden may demonstrate that M2 retrieves lexical synthetic targets that
recency misses, but it cannot authorize production Memory or claim real QQ
quality. External LoCoMo/LongMemEval data and local embeddings remain outside
this branch and are not downloaded.

### Verification Boundary

Contract tests run the same read/delete/export/archive/restore behavior against
in-memory and JSON adapters where supported, including concurrent CAS,
idempotency conflict, cancellation/deadline, persistence rollback, restart,
v1-to-v2 upgrade, rebuild and pre-delete-archive restore. Iris proves explicit
unsupported lifecycle failure and never unscoped fallback.

Retrieval tests cover tokenizer and BM25 golden values, unknown/duplicate rank
IDs, all Scope axes, visibility, TTL, query-time binding, generation/cursor
invalidations, candidate ceilings and M0 zero calls. Evaluation tests validate
the bundle and exact report denominators. Completion also requires Python
3.10/3.12 repository suites, changed-file Ruff/format, compileall, package
build/import, secret/lock/Compose/Shell/whitespace and necessary unchanged-Web
regressions. Real Memory data, human relevance judgments, production Iris,
embedding/hybrid gain, live Runtime integration and S23 remain explicit gaps.
