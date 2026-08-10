# Task Plan

Branch: durable-scheduler
Parent: proactive-outbound
Title: S15B Durable Scheduler

## Scope (owned work and boundary; not progress notes or implementation history)

- S15B Scheduler/Subscription contracts, Ports and canonical digests.
- SQLite subscription/occurrence/claim reference store with restart and multi-connection CAS.
- Deterministic IANA/DST/misfire materialization and structured Trigger claim/ack service.
- Fake-clock lifecycle/concurrency/30-day tests, status docs, verification and local commits.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Subscription mutation, schedule claim/receipt and state contracts are strict, immutable,
  versioned, digest-bound and framework-neutral.
- [x] Create/update/pause/resume/revoke use revision CAS and idempotent mutation receipts;
  revoked tombstones cannot resume and replaced revisions invalidate pending work.
- [x] IANA local dates, weekdays, DST fold/gap and bounded misfire deterministically materialize
  at most one occurrence per subscription/local date and never materialize the future.
- [x] SQLite restart, duplicate tick and two-connection tests prove one live claim owner,
  expiry/reclaim, exact ack idempotency and no terminal-state regression.
- [x] Paused/revoked/replaced subscriptions, clock rollback and expired misfires produce zero
  claimable Trigger; 30-day fake-clock simulation has zero duplicate/late occurrence.
- [x] Scheduler objects contain no MCP, source, model, Memory, Output or Connector dependency and
  only return structured `ProactiveTrigger` ownership facts.
- [ ] Python 3.10/3.12 focused/full, build/static/lock/secret/whitespace and necessary Web gates
  pass; Progress/Findings/Verification and public status are synchronized.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Reconcile the approved root/design/implementation-plan S15B constraints into this Spec/Plan.
- [x] Add Scheduler lifecycle DTO/digests and Subscription/Schedule/Scheduler Ports.
- [x] Implement explicit subscription JSON codec and SQLite durable store/schema.
- [x] Implement IANA/DST/misfire materializer plus claim/reclaim/ack/invalidation state machine.
- [x] Add CAS, restart, dual-worker, DST and 30-day fake-clock tests and import contracts.
- [ ] Run focused/full verification, synchronize docs, record TreeWork Verification, complete,
  locally merge and enter S15C.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Any real source Provider/MCP, live network, content normalization, model/Persona execution,
  PreparedDispatch/Output delivery or QQ send.
- APScheduler production Adapter, management WebUI/commands, real Actor authorization policy,
  production database migration or container changes.
- Probe opportunity/cooldown behavior, source/item dedup, Digest Shadow and real-group testing.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified and integrated S15A proactive contracts and existing SQLite/canonical patterns.
2. Approved root Spec, proactive design and S15B row in the implementation plan.
3. S15C-S15E consume claimed Trigger facts later; none is required for S15B offline proof.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: S15A Schedule/Subscription/Trigger contracts, SQLite rollout ledger and fake-clock
  patterns were selected for reuse.
- Reuse check: `durable-scheduler` exactly owns S15B; no new Tree node or second Runtime exists.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
