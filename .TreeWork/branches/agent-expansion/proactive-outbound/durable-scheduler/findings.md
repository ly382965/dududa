# Findings

Branch: durable-scheduler

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- `materialize_due()` returns digest-bound materialization receipts. A Trigger leaves the durable
  store only inside a live `ScheduleTriggerClaim`, preventing callers from treating a tick as
  ownership.
- A nonexistent wall time is represented by one permanent local-date slot tombstone; ambiguous
  times use the earliest UTC candidate after round-trip validation.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added public Subscription/Schedule/Scheduler Ports plus the SQLite reference Store and
  deterministic Scheduler implementation. Existing S15A contracts and delivery controls are
  unchanged.
- Schedule persistence is typed JSON with self-digest and indexed-column cross-checks; mutation,
  occurrence and Trigger identities survive restart and reject tampering.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- This is an offline reference authority, not production composition. Capacity and terminal
  retention must be sized conservatively because local-date tombstones cannot be deleted without
  weakening the cross-revision no-duplicate guarantee.
