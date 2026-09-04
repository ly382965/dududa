# Findings

Branch: plugin-group-controls

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

PR12 needed three demonstrated fixes: deny redirects before a second request,
bound gzip output while decompressing, and move large metadata parse/cache work
off the event loop. Preserve exact PR ancestry; do not squash away the requested
head. Per-group behavior uses existing Scope Policy, not global plugin unloads.

Fake events exposed Sub2API output after mid-request revoke, malformed master
switch acceptance, and Arc queued-image output after group disable. Fixed with
a signature-preserving async-generator guard, strict boolean enable and a final
Arc send check that retains queue cleanup. Reread counters now include bot ID.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

Catalog adds emoji.kitchen and arc.compat, defaults off. Group switches edit
drafts and persist through existing PUT /api/agent/config. Private conversations
cannot enable the new group-only modes. Installing third-party plugins remains
separate from explicit participation in the governed catalog.

Managed missing/malformed scopes fail closed; standalone installs without a
Dududa policy path retain their original global configuration behavior. Existing
Sub2API sensitive allowlists and Arc hard limits are not widened. Legacy empty
Reread whitelist no longer bypasses explicit Web group policy.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

MCP healthy checks validate protocol/discovery, not every business result. Live
message quality and B50 upstream behavior were not exercised. Public-domain 522
is distinct from the healthy local Web and origin Auth entry and remains an
external-network concern; this release does not change shared infrastructure.
