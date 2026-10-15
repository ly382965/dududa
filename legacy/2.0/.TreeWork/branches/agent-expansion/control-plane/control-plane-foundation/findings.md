# Findings

Branch: control-plane-foundation

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Existing Core `bot_id` is sufficient for account isolation. A Web
  `accountId` stays an Adapter mapping and does not create a second Core key.
- Pending onboarding remains separate from Assignment, so a joined group has
  structurally zero Runtime services before activation.
- The repository audit record is committed with the preview result. The generic
  `AuditSink` is a best-effort mirror and its failure does not falsify the
  repository transaction.
- Only committed/replayed mutations own Receipts. Stable `DududaError` remains
  the Core failure contract, preventing the Web Adapter from inventing a second
  failure or authorization model.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added public `dududa.control_plane` contracts/services and four
  `dududa.ports` Protocols: session resolver, join source, service Catalog and
  repository.
- Profile preview exposes Desired/Effective service IDs and stable reason codes
  without publishing an Assignment. Catalog snapshots carry their exact Scope,
  and returned Profiles must match the requested Profile revision.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The S21A repository is deliberately process-local. Restart recovery,
  immutable Assignment history and LKG behavior require S21B durability.
- Fake service facts prove contract behavior, not production service health or
  real administrator identity mapping.
