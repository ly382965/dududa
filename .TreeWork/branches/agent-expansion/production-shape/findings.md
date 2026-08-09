# Findings

Branch: production-shape

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Rollback journal is the portable baseline. WAL remains opt-in and is rejected
  unless `sqlite_version()` on the actual opened connection is at least 3.51.3;
  a caller-supplied version claim is not an authority.
- Health TTL must not be added silently to the frozen v1 operational DTO because
  doing so changes canonical receipts. A bounded Registry view owns TTL and
  Catalog binding and projects ordinary v1 UNKNOWN snapshots instead.
- A synchronous plugin installer cannot await Provider cleanup. Rejected
  Assemblies therefore have a distinct pending-cleanup owner consumed by the
  async lifecycle; successful and failed resources are tracked separately for
  retry without double-close.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `SQLiteRolloutLedgerConfig.journal_mode` defaults to `delete`; `wal` has an
  explicit SQLite version gate and effective-mode check.
- Perception and Direct Chat now request `temperature=None`. Non-null sampling
  remains contingent on Endpoint conformance.
- Core exports `ModelOperationalSnapshotPublisher`, `ModelHealthEvidence` and
  `BoundedModelHealthPublisher`; `ModelOperationalSnapshotResolver` keeps
  Router and Admission on one exact projected fact, and the existing v1
  operational digest is covered by a golden compatibility test.
- Plugin initialization installs one bridge even without Endpoint evidence, but
  marks its Runtime unavailable. Off/global-disabled/unavailable paths never
  read or claim an Event. Assemblies are one-shot, repeated initialization is
  rejected, and failed composition leaves legacy ownership intact.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Fakes prove lifecycle and transition semantics, not any real Provider's
  availability, quality, price, privacy policy or cancellation behavior.
- No deployment or running-container evidence is claimed by this branch. The
  production bridge remains unavailable until later external conformance and
  release gates explicitly replace the placeholder Assembly.
