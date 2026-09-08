# Findings

Branch: runtime-config-apply

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- AstrBot 4.27.5 ProviderManager.reload terminates old objects before replacements; the Core still retains them. The bounded repair uses Core-owned generations and leaves global instances alive until normal host shutdown. Host configuration caches receive only the target rows so later ordinary saves cannot restore stale credentials.
- Defense: one apply lock, whole-call counters and fixed private last-good files.
  Concrete accident: replacing a Provider during an active generation or dying between private configuration writes leaves unusable bindings.
  Why existing mechanisms fail: Git excludes credentials, and per-file atomic writes do not cover the live three-file configuration.
  Smallest sufficient control: reject active work, build a candidate, retain one private rollback copy, and exchange Core-owned references without an await.
  Stop/removal condition: controls exist only at the explicit configuration application boundary, not the model hot path beyond the entry counter.
- Probe-only metadata revisions compare equal to applied semantics; changed active credentials do not. Stale UI GET responses are excluded by a local request generation counter.
- Candidate Provider configuration, target rows copied into the host cache, and the remembered applied command are deep-copied independently. A regression exercises real candidate preparation with a fake Provider and mutates nested Key/Header lists in both the prepared command and Dashboard cache; live Provider arguments and applied-state comparison remain unchanged.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Web GET `/api/api-keys/runtime`, POST `/api/api-keys/runtime/apply` with only `{revision}`. Fixed host plugin endpoints `/runtime/configuration` and `/runtime/configuration/apply`; existing plugin-scope authentication remains authoritative.
- Application is Dududa-only immediately. Other AstrBot consumers use their existing instances until cold restart. Provider-managed retention must already be accepted; the UI does not introduce an approval bypass.
- The CLI pure candidate projection is shared with Core; cold `install --host-stopped` behavior remains protected. Existing per-role output settings are preserved rather than overwritten by migration defaults.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Applied configuration is not a perpetual upstream health guarantee. Host evidence reuse is limited to the current validated bounded OpenAI implementation and official DeepSeek policy; new protocol/provider conformance remains unsupported.
- Abrupt host death between the separate file replacements requires the operator to restore the fixed private last-good files while the host is stopped. No credentials or private backups belong in Git.
