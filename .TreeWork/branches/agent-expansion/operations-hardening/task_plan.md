# Task Plan

Branch: operations-hardening
Parent: agent-expansion
Title: S16 Operations Hardening

## Scope (owned work and boundary; not progress notes or implementation history)

- Implement the versioned release store, health/backup/restore contracts and
  upgrade/rollback state machine behind a standard-library Python CLI.
- Preserve root command/data-path compatibility and validate the existing
  Compose mount/network boundary without operating real containers.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Release manifests, mutable state and stage receipts are versioned,
  digest-bound, atomic and contain no secret values.
- [x] Health is read-only; backup verifies ordinary files and SQLite snapshots;
  restore requires a verified plan and an explicit empty destination.
- [x] Upgrade promotes only after health and failed health rolls back to a
  verified previous release while preserving evidence.
- [x] Root operations expose the new commands without changing existing
  `up`, `down`, `logs`, `ps`, `restart`, `seed` or data-root semantics.
- [x] One disposable lifecycle and representative failure samples pass without
  Docker, real `.env`, credentials or runtime data.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Freeze the minimal release/state/receipt and stage-driver contracts.
- [x] Implement operations core, CLI and root compatibility forwarding.
- [x] Add the disposable lifecycle fixture and at most four focused test
  groups, including Compose mount/network sampling.
- [x] Synchronize Chinese status documentation and TreeWork evidence, commit,
  complete and integrate S16.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Repository layout migration, third-party Manifest v2 authority cutover and
  compatibility deletion (S17/S22).
- Real Docker/HTTP/MCP/QQ/Provider probes, production restore or container
  changes (S19/S23 or an authorized operator run).
- WebUI changes or a full-repository regression run.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. S15E is complete and supplies the final proactive no-send prerequisite.
2. Existing deployment, rollback and repository-layout documents are accepted
   design inputs; this branch does not reopen them.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: existing `manage.sh`, Compose, rollout rollback script, memory
  backup patterns and operations documents were inspected.
- Reuse check: S11 rollback artifacts cover behavior rollback only and cannot
  own release-wide backup/upgrade state; the existing operations branch is the
  correct owner.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
