# Task Plan

Branch: memory-retrieval
Parent: agent-expansion
Title: S14 Memory Lifecycle And Retrieval

## Scope (owned work and boundary; not progress notes or implementation history)

- Add versioned lifecycle, tombstone, archive/restore, rank and retrieval DTOs,
  digests and framework-neutral Ports while retaining existing Scope/WriteGate.
- Implement generation-bound reads plus atomic delete, scoped export, recovery
  and crash-stable idempotency for in-memory and JSON repositories.
- Implement shared exact eligibility, recency and a deterministic local
  CJK-bigram BM25 ranker only over authorized bounded candidates.
- Add a formal scoped retriever and fixed synthetic M0-M2 Eval with hard
  zero-exposure metrics and explicit evidence limits.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Existing Scope, Selector and WriteGate remain authoritative; new public
  DTOs are immutable, versioned, bounded and digest-bound without framework,
  model, SQLite-extension or Iris imports.
- [ ] Query/reference time and state generation bind every read; mutation makes
  old snapshots/cursors fail closed and no expired/deleted/out-of-Scope record
  reaches a ranker or result.
- [ ] Delete verifies exact Scope, authorization, confirmation, expected
  version and idempotency; concurrent/replayed/conflicting mutations have
  deterministic receipts or typed conflicts.
- [ ] JSON v1 scoped data upgrades atomically to v2, and v2 persists records,
  tombstones and replay evidence across restart without changing legacy
  pre-scope quarantine behavior.
- [ ] Scoped export leaks no selector/index/other-Scope state; archive restore
  is CAS/idempotent, preserves destination tombstones and proves clean
  round-trip plus pre-delete-backup no-resurrection.
- [ ] Iris unsupported delete/archive/restore paths fail closed and never claim
  that deleting a local projection deleted its backend source.
- [ ] M0 no-memory performs zero repository/ranker calls; M1 recency and M2
  CJK BM25 rank the same exact authorized candidate set with stable limits,
  revisions, tie-breaking and structural rank-output validation.
- [ ] Fixed synthetic M0-M2 reports bind their manifest and retain exact
  denominators; cross-Scope, expired and tombstoned exposures are all zero,
  without claiming real Chinese/QQ relevance quality.
- [ ] Dual-Python, focused lifecycle/retrieval/fault tests, repository
  regression, build/import, Web, secret, lock, Ruff, Compose/Shell and
  whitespace gates pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Freeze S14 snapshot, lifecycle, restore, ranking and evaluation semantics
  in this Spec and record the branch-local executable Plan.
- [x] Implement lifecycle/retrieval DTOs, canonical digests, serializers and
  Port surface plus focused validation/import tests.
- [x] Implement state generation, delete/tombstone/export/archive/restore and
  crash-stable v2 JSON persistence with rollback and adapter Contract tests.
- [ ] Implement retrieval policy, scoped retriever, exact/recency strategies,
  CJK tokenizer and BM25 ranker with security/failure tests.
- [ ] Add and validate the fixed synthetic M0-M2 bundle, evaluator and golden
  reports; update current design/status documentation.
- [ ] Run full verification, synchronize Progress/Findings/Verification,
  commit locally, complete the TreeWork branch and merge it to the lead branch.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Automatic Memory extraction/writes, automatic deletion/forgetting,
  subject/predicate inference, temporal or Graph Memory.
- Embedding, hybrid/RRF, learned reranking, Mem0/Graphiti Spikes, external
  benchmark downloads or production Iris.
- Reading real QQ/Memory data, Provider credentials or production environment;
  enabling Memory in S10/S11/S23 or sending any message.
- Rewriting AstrBot `/remember`, `/forget` or export commands, changing the
  current rollout authority, or adding WebUI control-plane features.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified S13 Capability branch and the existing S01-S07 Memory Scope,
   selector, WriteGate, security context and canonical-digest foundations.
2. Approved root Spec/requirements and `docs/research/memory-evaluation.md`;
   no external data or owner policy choice is needed for this offline slice.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: existing Memory models/Port, in-memory/JSON/Iris adapters,
  selector authority, WriteGate, migration and repository Contract tests.
- Reuse check: keep existing identity, Scope, Selector, Authorization,
  Confirmation, call-context, JSON atomic-write and canonical-digest machinery;
  do not introduce another Memory database or permission plane.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
