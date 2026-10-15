# Findings

Branch: operations-hardening

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Deployment orchestration remains outside `dududa-agent`; a standard-library
  script is the migration source for S17 `ops/cli`, while Agent runtime logic
  stays free of Compose and filesystem release policy.
- Immutable Release Manifest, mutable current/previous State and append-only
  Stage Receipts are separate authorities. Promotion occurs only after a
  healthy report.
- SQLite Backup API can preserve WAL journal mode and create sidecars while
  verifying a snapshot. Normalizing the completed snapshot to DELETE mode and
  checking it through an immutable read prevents sidecars from escaping the
  backup inventory.
- Existing Source Ports already carry cancellation/deadline facts; racing each
  awaited lock/Reader/Store call closes the recorded S15D gap without changing
  Source DTOs.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Root `manage.sh` adds `bootstrap`, `start`, `health`, `backup`, `restore` and
  `rollback`; parameterized `upgrade` uses the protected CLI while no-argument
  `upgrade` retains the legacy development behavior.
- Private state is written below `STACK_DATA_ROOT/.dududa`; verified backups are
  published below `STACK_DATA_ROOT/backups`. Restore defaults to plan-only and
  apply accepts only an empty destination in S16.
- Driver plans are explicit argv arrays and health output is a digest-bound JSON
  report. No Docker, MCP or HTTP implementation is fabricated by the core.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Concurrent independent operator processes are not yet a supported control
  plane; S19 must serialize real deployment commands before production use.
- Production backup selection, secret-at-rest encryption and Writer quiescence
  depend on the authorized runtime and cannot be proven with disposable data.
- The legacy no-argument upgrade remains non-transactional for compatibility;
  it is not an unattended production path.
