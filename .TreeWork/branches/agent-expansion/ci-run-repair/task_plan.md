# Task Plan

Branch: ci-run-repair
Parent: agent-expansion
Title: Repair GitHub CI Run 33897997167

## Scope

- Restore the Python 3.10/3.12 and offline-eval jobs using actual failed logs.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Actual GitHub failures are explained and reproduced locally.
- [x] Minimal fixes preserve every job, test, assertion and failure exit.
- [x] Relevant local CI commands pass on both supported Python versions.
- [ ] Review the diff, publish the repair, and inspect remote CI outcomes.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Diagnose missing corpus dependencies and exact S09 artifact drift.
- [x] Repair causes and run the original CI profiles.
- [ ] Finish branch records and publish verified changes.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Production deployment, notification changes and unrelated application work.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. GitHub CLI authentication and the completed evaluation-ci implementation.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Run 33897997167 logs, CI YAML and suite entrypoints.
- Reuse check: evaluation-ci is complete and TreeWork rejects reopening it;
  this follow-up owns the newly reported CI regressions.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
