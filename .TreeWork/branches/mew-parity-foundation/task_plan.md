# Task Plan

Branch: mew-parity-foundation
Parent: mew-parity
Title: NapCat Web Foundation

## Scope (owned work and boundary; not progress notes or implementation history)

- Selective baseline of the existing Web prototype.
- Account-scoped rich message, capability, cursor-history, event and browser
  persistence contracts.
- Backward-compatible gateway/frontend migration primitives for downstream
  Mew feature branches.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Existing real NapCat workspace behavior remains green after the baseline.
- [ ] Typed normalized rich messages preserve ordered known segments and safely
  degrade unknown segments without leaking raw OneBot events.
- [ ] History supports bounded opaque before/after cursors and stable
  deduplication.
- [ ] Every request/event/cache/draft/capability is isolated by account and a
  concurrent two-account contract test proves no cross-talk.
- [ ] IndexedDB stores only real normalized QQ data, coverage and drafts and can
  be cleared without server mutation.
- [ ] OneBot token, cookies, local paths and arbitrary action forwarding remain
  impossible from the browser API.
- [ ] Unit, gateway, typecheck and production build verification pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Commit only the accepted Web baseline and TreeWork metadata.
- [ ] Add shared dependencies and account-scoped domain/schema modules.
- [ ] Implement capability and cursor-history gateway endpoints/events.
- [ ] Implement Dexie cache/draft/range services and migration-safe tests.
- [ ] Adapt the current workspace adapter/composable to the new contracts while
  retaining the real text path.
- [ ] Run focused and repository regression verification, record evidence and
  commit the branch.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- User-facing Mew chat components, directory/group routes, destructive group
  actions, Agent Runtime and unrelated repository cleanup.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Existing Web files are untracked/dirty in the control workspace and require
   selective baselining before an isolated worktree can consume them.
2. NapCat availability is not required for deterministic transport tests, but
   no test fixture may enter the production bundle.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: The current gateway has the right multi-account ownership but
  flattens segments, returns only latest history and has no browser database.
- Reuse check: No existing S08-S11 branch owns Web transport or UI state.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
