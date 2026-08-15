# Findings

Branch: control-plane-audit

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- `command_id` identifies one accepted command across preview and assignment;
  idempotency keys still own replay. A second key cannot reuse the command ID.
- SQLite call validation must happen both before attempting a write and after
  acquiring `BEGIN IMMEDIATE`; the latter prevents a timed-out caller from
  committing after lock contention.
- Disabled browser controls are projections, not drafts. They use `:value` or
  `:checked` without `v-model` or mutation handlers until a Core Command exists.
- Existing tests already cover the remaining S21 completion requirements, so
  the audit uses a focused cross-stage sample instead of a new broad harness.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- In-memory Group Service Repository now owns a unified command ID set.
- SQLite adds `cp_command_ids` and reserves IDs in the same transaction as the
  command result, Audit and Receipt. Exact idempotent replay remains unchanged.
- SQLite write transactions optionally receive the service call and revalidate
  it after lock acquisition; expired calls roll back before their first write.
- Agent settings/draft/permission controls no longer expose browser mutation
  events. Human QQ message composition continues to use the existing typed
  NapCat path.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- S21 was never deployed as a production Control Plane, so no production
  command ledger requires backfill. Production database migration remains an
  environment concern if a private pre-release database is retained.
- Production HTTP/operator identity, live health, Provider/Source/Projection/
  Output and real-group quality remain unproven by this offline audit.
