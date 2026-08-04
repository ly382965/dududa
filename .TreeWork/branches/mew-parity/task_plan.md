# Task Plan

Branch: mew-parity
Parent: root
Title: Mew And NapCat Web Parity

## Scope (owned work and boundary; not progress notes or implementation history)

- Shared Web architecture, source-baseline ownership and cross-branch contract
  boundaries for the complete Mew/NapCat parity epic.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Foundation, chat and directory branches satisfy their acceptance and the
  audit proves their integration without cross-account leakage or demo data.
- [x] Every confirmed NapCat gap has an explicit UI capability state and no
  operation reports success without a real OneBot response.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Establish and verify the shared Foundation.
- [x] Integrate Chat and Directory slices after Foundation completion.
- [x] Run the joint real-account and repository audit.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Agent Runtime, model controls, QQ login/protocol implementation, Sub2API and
  Mew-external feature expansion.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Mew commit `97df34b` remains available as the pinned source reference.
2. Real external QQ mutations require explicit authority during audit.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Existing Tree had only S08-S11 runtime branches and explicitly
  excluded WebUI.
- Reuse check: No prior branch coherently owned a QQ operator client or its
  protocol/persistence contracts.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
