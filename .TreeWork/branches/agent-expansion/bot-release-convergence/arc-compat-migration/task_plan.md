# Task Plan

Branch: arc-compat-migration
Parent: bot-release-convergence
Title: Current Arc Compatibility Release

## Scope

- Canonical compatibility implementation preserving deployed legacy QQ commands and current local capability contract.

## Acceptance

- [x] Old/new command mapping is explicit; isolated positive/negative tests cover inputs, authentication and redaction; current plugin loads without production actions.
- [ ] Lead integration and scoped release verification are recorded separately from isolated worker verification.

## Local Steps

- [x] Inspect canonical and deployed plugin source only; map commands and dependencies.
- [x] Port compatibility behavior with external config and no secrets in source.
- [x] Run isolated plugin tests; document migration and commit.

## Out Of Scope

- Production credentials/data, actual upstream account binding, QQ sends, deployment, other services.

## Dependencies

- Existing Bot-only release baseline and this branch's technical Spec.
- Workers coordinate additive shared lifecycle interfaces before editing overlapping code.

## Branch Intake Gate

- Inspect: Parent release maintenance records and current source demonstrate independently repairable failures.
- Reuse check: Reuse convergence parent for integration and delivery; do not reopen completed historical branches.
- New branch rationale: Independent bounded ownership enables parallel delivery for the user's explicit all-remaining-fixes request without altering the older offline engineering WIP sequence.
