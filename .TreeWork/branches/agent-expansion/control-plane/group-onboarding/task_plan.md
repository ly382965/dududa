# Task Plan

Branch: group-onboarding
Parent: control-plane
Title: S21B Group Onboarding

## Scope (owned work and boundary; not progress notes or implementation history)

- Implement Profile Catalog, Effective resolver and lifecycle command handlers.
- Add durable SQLite assignment/receipt/LKG storage and Runtime snapshots.
- Add the typed Control API, Node adapter and group onboarding Web workflow.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Pending inbox and Catalog expose only authoritative facts and stable
  availability reasons.
- [x] Preview/activate/update/pause/resume/rollback obey auth, Scope, expiry,
  expected revision, idempotency, Audit and Receipt contracts.
- [x] New groups remain zero-service until activation; failures preserve
  pending or LKG and Runtime reads immutable snapshots only.
- [x] Restart, two-admin CAS and multi-account/group isolation pass against
  temporary SQLite.
- [x] Web renders Desired/Effective and command receipts without local authority.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Implement Catalog/resolver and preview contracts.
- [x] Implement lifecycle handlers and SQLite repository.
- [x] Implement Runtime snapshot provider and typed API adapter.
- [x] Implement focused onboarding UI and tests; synchronize branch evidence.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Global Run/Model/MCP/Plugin/Memory/Proactive operations pages.
- Production operator identity, real group activation or Agent Output.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. `control-plane-foundation` is complete and its contracts are authoritative.
2. Existing Web QQ operations remain separate from Agent operations.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: foundation contracts, SQLite store patterns, Web server routing and
  Agent Console unavailable-state behavior.
- Reuse check: extend the foundation repository/gateway and current Web shell;
  do not duplicate resolution or authorization in TypeScript.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
