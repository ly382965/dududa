# Findings

Branch: mew-parity-foundation

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- History cursors are HMAC-signed with the server-held OneBot token and bind
  account, scene, peer and sequence, so accidental or forged cross-account reuse
  fails before a NapCat action.
- Capabilities describe the currently implemented safe Web gateway, not merely
  every action NapCat could theoretically execute.
- The legacy `content`, `attachments` and `sequence` fields remain temporary
  projections so the existing workspace stays usable during the Mew port.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `GET .../messages` now returns `HistoryPage` and accepts `before`/`after`;
  legacy consumers still read its `messages` field.
- `POST .../messages` accepts either legacy `content` or a validated ordered
  text/reply/mention/face segment array.
- `GET /api/accounts/:accountId/capabilities` and
  `capabilities.changed` expose implementation and action state.
- IndexedDB schema v1 partitions messages, conversations, ranges, events and
  drafts by account and conversation.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Cached cursor signatures become invalid if the OneBot token rotates;
  downstream history code must discard a rejected range and refresh latest.
- NapCat may vary on whether history includes the anchor message; the gateway
  requests one extra item, removes the anchor and deduplicates stable IDs.
- Node 20 reports non-blocking engine warnings for transitive Babel 8 packages;
  typecheck, tests and production build still pass and the dependency audit is
  clean.
