# Task Plan

Branch: governed-sources
Parent: proactive-outbound
Title: S15C Governed Source Contracts

## Scope (owned work and boundary; not progress notes or implementation history)

- S15C Source policy/provenance/cursor/identity/fetch contracts and canonical digests.
- Source/Policy/Cursor/Item-ledger/Capability-reader Ports and deterministic reference services.
- Synthetic campus/arXiv/industry fixture bundle, Fake reader and shared Contract tests.
- Focused/full verification, status documents and local commits.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Existing SourceItem/Batch/Failure v1 remains compatible; new source contracts are strict,
  immutable, versioned, digest-bound and framework-neutral.
- [ ] Policy snapshot fixes source/category/capability/host/path/size/freshness/revision rules;
  unknown source, arbitrary URL/capability and stale/mismatched policy fail closed.
- [ ] Strict observations produce only PUBLIC, cited, allowlisted, fresh, bounded SourceItems;
  Schema drift, HTML/prompt injection, truncation and malformed identity/time fail the source.
- [ ] Cursor CAS and subscription item identity/revision ledger make duplicate fetch idempotent;
  revisions are held unless the exact Definition opts in.
- [ ] Synthetic campus/arXiv/industry readers share one Contract and partial/all failure,
  timeout/cancel/circuit and NO_NEW_ITEMS behavior is deterministic.
- [ ] Adding a fourth Fake source changes only policy/binding/fixture, not Source Domain,
  Scheduler, Runtime, MCP Client or the generic governed provider.
- [ ] Python 3.10/3.12 focused/full, build/static/lock/secret/whitespace and necessary Web gates
  pass; Progress/Findings/Verification and public status are synchronized.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Reconcile approved S15C design/research/implementation constraints into this Spec/Plan.
- [ ] Add source governance DTO/digests and framework-neutral Ports.
- [ ] Implement strict normalizer, governed provider and in-memory cursor/item ledgers.
- [ ] Add manifest-bound synthetic fixtures, Fake Capability Reader and extension Contract tests.
- [ ] Run focused/full verification, synchronize docs, record TreeWork Verification, complete,
  locally merge and enter S15D.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Any live campus/arXiv/industry Adapter/MCP, network request, crawler, RSS/HTML parser, real
  credentials, real content freshness or license claim.
- Scheduler, subscription lifecycle, model/Composer/Persona, PreparedDispatch, Output or QQ send.
- Generic Planner exposure, arbitrary URL fetch, external writes, production cursor/item database
  migration, WebUI or management commands.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified and integrated S12/S13 Capability boundary, S15A source DTOs and S15B Trigger claims.
2. Approved root Goal, proactive design, source research and S15C implementation-plan row.
3. S15D consumes SourceFetchReceipt later; no later branch is needed for S15C offline proof.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Existing Source DTO/digests, Capability Ports/results, canonical patterns and local Fake
  conventions were selected for reuse.
- Reuse check: `governed-sources` exactly owns S15C; no new Tree node, MCP Server or Runtime exists.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
