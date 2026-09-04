# Task Plan

Branch: preview-context-repair
Parent: bot-release-convergence
Title: Group Context And Honest Preview Results

## Scope

- Web/Runtime history propagation, explicit terminal preview outcomes, and demonstrated hybrid perception conflict repair.

## Acceptance

- [ ] History reaches perception and generation with bounded same-scope context; empty/deferred/error results display an explanation; isolated tests prove no sends or memory writes.
- [ ] Lead integration and scoped release verification are recorded separately from isolated worker verification.

## Local Steps

- [ ] Inspect current adapters and fixtures; reproduce dropped context and empty results.
- [ ] Implement additive context/outcome handling and narrowly justified classification repair.
- [ ] Run focused TS/Python/browser tests; record evidence and commit.

## Out Of Scope

- API Key apply, Arc, host deployment, credentials.

## Dependencies

- Existing Bot-only release baseline and this branch's technical Spec.
- Workers coordinate additive shared lifecycle interfaces before editing overlapping code.

## Branch Intake Gate

- Inspect: Parent release maintenance records and current source demonstrate independently repairable failures.
- Reuse check: Reuse convergence parent for integration and delivery; do not reopen completed historical branches.
- New branch rationale: Independent bounded ownership enables parallel delivery for the user's explicit all-remaining-fixes request without altering the older offline engineering WIP sequence.
