# Task Plan

Branch: mew-parity-audit
Parent: mew-parity
Title: Mew Parity Audit

## Scope (owned work and boundary; not progress notes or implementation history)

- Integrated functional, security, multi-account, responsive and repository
  regression audit for the complete Mew/NapCat parity epic.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Every Mew baseline behavior has passed evidence or a documented confirmed
  NapCat capability gap with an explicit disabled state.
- [x] Two-account transport tests and available real-account read-only checks
  show no identity, message, cache, draft, capability or upload cross-talk.
- [x] Desktop/mobile screenshots and interaction tests have no blank canvas,
  incoherent overlap, inaccessible controls or unstable history anchoring.
- [x] Production artifacts contain no demo data or protected credentials and
  the full repository regression suite passes.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Freeze the feature/capability evidence matrix.
- [x] Run focused Web, security and two-account verification.
- [x] Run authorized real NapCat read-only verification and record external
  mutation gaps honestly.
- [x] Run full repository, Compose, secret and dependency checks.
- [x] Capture desktop/mobile visual evidence and close all audit findings.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- New product features, Agent Runtime implementation and unauthorized external
  QQ mutations.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. `mew-chat-parity` and `mew-directory-parity` must be complete and integrated.
2. Real NapCat availability determines manual integration coverage; lack of
   mutation authority remains an explicit external gap, not a simulated pass.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Branch-local tests cannot prove cross-slice or real-account behavior.
- Reuse check: The existing S08-S11 completion audit owns a different runtime
  surface and cannot coherently absorb Web parity evidence.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
