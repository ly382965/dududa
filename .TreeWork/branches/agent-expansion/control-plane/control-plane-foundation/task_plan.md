# Task Plan

Branch: control-plane-foundation
Parent: control-plane
Title: S21A Control Plane Foundation

## Scope (owned work and boundary; not progress notes or implementation history)

- Add framework-neutral S21 contracts, Ports and digests.
- Add Fake operator/service/join facts plus the in-memory repository.
- Add join handling, authenticated query, Command Gateway, Projector and
  preview/Audit/Receipt for the pending zero-service slice.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Immutable Profile/Assignment/Scope/session/envelope/receipt/projection
  contracts reject invalid or authority-bearing fields.
- [ ] Duplicate Fake joins produce one pending record and pending Runtime
  lookups always expose zero services and side effects.
- [ ] A fixed Profile preview reports Desired/Effective service reasons from
  Fake Catalog facts without publishing an Assignment.
- [ ] Expired/unknown sessions, denied roles and cross-Scope requests fail
  without repository or audit-success mutation.
- [ ] Accepted/replayed commands produce stable receipts and one business
  result through existing authorization, idempotency and Audit ports.
- [ ] Focused Python tests, Ruff, package exports and import boundaries pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Implement contracts, digests and package exports.
- [ ] Implement repository/Fakes, pending join service and Profile preview.
- [ ] Implement session auth, query/command gateway and projector.
- [ ] Run focused verification and synchronize branch documents.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Profile activation/update/pause/resume/rollback and SQLite durability.
- Web UI/API transport, operational projections and any real send.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. S22 and Mew parity audit are complete and unchanged.
2. Existing `dududa.domain.identity` and `dududa.security` contracts are reused.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Core identity/security/canonical contracts, in-memory CAS stores,
  Profile registries and current Fake patterns.
- Reuse check: extend the package graph with one Control Plane domain; do not
  modify Security or create a Web-owned policy model.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
