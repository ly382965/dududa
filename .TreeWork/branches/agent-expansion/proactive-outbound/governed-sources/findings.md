# Findings

Branch: governed-sources

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Cursor and item-ledger ownership stay logically separate, but a fetch commits both through one
  `SourceStateStore` Unit of Work. Per-source or per-item mutation could advance a cursor before
  dedup classification and lose content after cancellation or conflict.
- `SourceItem.content_digest` is observation evidence and includes observation time. A separate
  semantic revision-content digest excludes volatile receive time so polling the same content later
  remains `DUPLICATE` rather than a false revision.
- `SourceFetchRequest` binds a typed origin digest instead of a mandatory Trigger digest so S15D can
  implement Preview without forging Scheduler state.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `dududa.proactive` exports additive source DTOs, digest helpers, `GovernedSourceProvider`,
  `InMemorySourcePolicyRegistry` and `InMemorySourceStateStore`; existing Source v1 DTOs are unchanged.
- `dududa.ports` exports `SourcePolicyRegistry`, `SourceCapabilityReader`, `SourceStateStore` and
  `SourceProvider`. Future MCP sources implement only the Capability reader through S13 mappings.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The state store is an in-memory transactional reference, not a production persistence migration.
- Fixture receive-time freshness, normalization and citation evidence do not establish real-source
  availability, license, clock quality or content usefulness.
