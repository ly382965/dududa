# Task Plan

Branch: layout-migration
Parent: agent-expansion
Title: S17 Layout Migration

## Scope (owned work and boundary; not progress notes or implementation history)

- Move repository-owned plugins, MCP services, config, deploy, operations and
  third-party sources to their accepted canonical directories with `git mv`.
- Preserve root operation/Compose/environment compatibility and every runtime
  plugin, package, MCP, mount and data-path contract.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Canonical `apps/`, `services/mcp/`, `configs/`, `deploy/`, `ops/` and
  `third_party/` paths own the moved sources; all tracked consumers use them.
- [ ] Root `manage.sh`, `compose.yml`, `.env.example` and one-release
  `plugins.lock.json` compatibility entrypoints remain executable/readable.
- [ ] Root/canonical Compose render equivalent service/mount/network contracts;
  plugin IDs, container targets and Python distribution/import names are stable.
- [ ] Operations scripts, workspace lock, iCourse/unified worker and focused
  repository contracts pass without real containers, data or credentials.
- [ ] Chinese status and migration documents distinguish completed path moves
  from the still-unmet third-party Manifest v2 and production rollback gates.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Freeze the exact canonical/compatibility path map and consumer inventory.
- [ ] Move plugins/config/services and update their consumers; verify the batch.
- [ ] Move deploy/ops assets and add root wrappers; verify the batch.
- [ ] Move third-party v1 assets, update installer/ownership and verify the batch.
- [ ] Synchronize TreeWork/status evidence, commit, complete and integrate S17.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Agent/Runtime/MCP/plugin behavior redesign or compatibility-code deletion.
- Test-suite reorganization, Manifest v2 authority cutover, new dependency
  locks, license conclusions or external source fetching.
- Runtime data migration, real Docker start/recreate, running container changes,
  Web feature work or S23 traffic.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. S16 is complete/verified and supplies release, backup and rollback contracts.
2. Repository layout, migration map and ADR 0005 are accepted design inputs.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: every current top-level source directory, Compose/Docker/manage,
  workspace/lock, CI/Dependabot/CODEOWNERS and test path consumer was scanned.
- Reuse check: no completed branch owns physical path migration; this accepted
  S17 branch is the sole owner and no child branch is needed.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
