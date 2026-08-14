# Task Plan

Branch: control-plane-audit
Parent: control-plane
Title: S21 Completion Audit

## Scope (owned work and boundary; not progress notes or implementation history)

- Integrate and audit S21A-S21C against the accepted completion definition.
- Remove direct-NapCat and browser-local Agent mutation paths.
- Synchronize root status/docs and stop before S23.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Requirement-by-requirement evidence proves pending zero-service,
  authorized onboarding, Desired/Effective truth, immutable Runtime state,
  idempotency/CAS/Audit/Receipt, isolation and LKG recovery.
- [ ] Group Context/Plugin/Model/Bandit cannot widen assignment or send rights.
- [ ] Agent draft/permission/settings paths use governed commands or honest
  unavailable receipts and never direct NapCat/browser-local success.
- [ ] Focused Python/Web/server/typecheck/build and small E2E pass.
- [ ] Root documents report S21 offline complete and S23 external gates exactly.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Review integrated code and close any explicit acceptance gap.
- [ ] Replace residual browser-local/direct-NapCat Agent paths.
- [ ] Run proportional cross-stage verification and record evidence.
- [ ] Complete parent S21 verification, integrate commits and stop before S23.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Any real QQ read/send beyond existing untouched client tests.
- Real Provider/Source/Output, external corpus, human quality or online Bandit.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. S21A-S21C are complete, verified and integrated in dependency order.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: accepted S21 requirements, branch evidence, Web Agent handlers,
  import boundaries and affected tests.
- Reuse check: this branch closes cross-stage evidence and residual paths; it
  does not create another implementation owner.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
