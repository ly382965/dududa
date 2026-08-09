# Task Plan

Branch: production-shape
Parent: agent-expansion
Title: S12 Entry Gate Production Shape

## Scope (owned work and boundary; not progress notes or implementation history)

- Make SQLite journal mode explicit, version-gated and safe by default.
- Align Runtime sampling with proven Endpoint capability.
- Add bounded health evidence and freshness transitions.
- Install and close exactly one default-off production Runtime composition.
- Prove off/shadow behavior with Fakes and no external side effects.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Rollout persistence defaults to rollback journal and retains atomic CAS.
- [x] WAL is rejected below SQLite 3.51.3 and the effective mode is verified.
- [x] Perception and Direct Chat use `temperature=None`; Adapters never drop it silently.
- [x] Health transitions are replayable and stale/failed evidence returns to UNKNOWN.
- [x] Router continues to reject UNKNOWN and stale health with stable reasons.
- [x] One composition root installs at most one bridge and is default-off.
- [x] Partial initialization and repeated termination leak no owned resource.
- [x] Offline off records zero model calls; shadow records zero delivery and persistent writes.
- [x] Focused and affected repository tests pass without touching running containers.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Add journal policy/configuration and persistence failure tests.
- [x] Remove forced Runtime sampling and update request/Adapter contracts.
- [x] Implement the health evidence state machine and Router-facing snapshots.
- [x] Build the transactional production composition and lifecycle owner.
- [x] Add Fake-based plugin composition and no-side-effect smoke tests.
- [x] Run focused, dual-Python affected and repository safety verification.
- [x] Record Verification, Findings and the coherent local commit.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Real Endpoint enablement, model credentials or Provider quality claims.
- Running-container, Compose deployment or real QQ changes.
- Static Router redesign, semantic v2, MCP, Memory or proactive behavior.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Completed S08-S11 contracts and the completion audit.
2. Existing production-shape preflight evidence.
3. No external credentials or user data are required.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: S08-S11 completion audit, production preflight and current composition.
- Reuse check: S11 remains complete; this branch owns only its production reachability gate.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
