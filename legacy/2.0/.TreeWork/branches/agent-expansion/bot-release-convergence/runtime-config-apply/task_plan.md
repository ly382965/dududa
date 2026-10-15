# Task Plan

Branch: runtime-config-apply
Parent: bot-release-convergence
Title: One-Click External Model Configuration Apply

## Scope

- Authenticated Web action and narrow host-side provider reconfiguration with true applied state.

## Acceptance

- [x] Saved DeepSeek pools can be explicitly applied from the page; auth, stale revisions, concurrent/active calls, rollback and secret redaction are tested with isolated doubles.
- [x] Lead integration and scoped release verification are recorded separately from isolated worker verification.

## Local Steps

- [x] Inspect existing CLI, Provider lifecycle and current retained runtime references.
- [x] Implement the smallest safe host apply boundary, status, and UI; coordinate shared lifecycle edits.
- [x] Run focused host/server/UI tests; record evidence and commit.

## Out Of Scope

- Group context, Arc, deployment, Docker socket, generic host command APIs.

## Dependencies

- Existing Bot-only release baseline and this branch's technical Spec.
- Workers coordinate additive shared lifecycle interfaces before editing overlapping code.

## Branch Intake Gate

- Inspect: Parent release maintenance records and current source demonstrate independently repairable failures.
- Reuse check: Reuse convergence parent for integration and delivery; do not reopen completed historical branches.
- New branch rationale: Independent bounded ownership enables parallel delivery for the user's explicit all-remaining-fixes request without altering the older offline engineering WIP sequence.
