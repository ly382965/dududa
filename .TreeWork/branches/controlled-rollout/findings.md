# Findings

Branch: controlled-rollout

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Persist the minimum ownership/delivery evidence rather than `RuntimeState`:
  the latter contains raw messages and nested DTOs without a trusted inverse
  codec. The minimal ledger is sufficient to prevent duplicate sends.
- A durable message claim is the point of no return. Any duplicate, conflict or
  uncertain claim outcome suppresses the legacy path; availability never
  overrides single-owner delivery safety.
- The delivery reservation is committed immediately before `event.send()`.
  Restart during that boundary canonicalizes to UNKNOWN instead of guessing.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- New public `dududa.rollout` exports own typed controls, admission, ledger and
  metric Ports, SQLite implementation, Shadow/Canary coordination and rollback
  contracts without AstrBot imports.
- AstrBot Core adds a priority-100 group handler, live disk control Provider,
  persistent rollout ledger and an additive `send_guard` on Output.
- `install_rollout_runtime()` is the explicit composition boundary; plugin
  configuration alone cannot activate a real Runtime.
- Rollback manifests require digest-pinned image, plugin tree, config tree and
  an off control revision. The executable script validates before replacement.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- AstrBot host handler ordering is based on the upstream priority contract and
  local registry assertions, but the host-only test remains skipped outside the
  derived image.
- Real Provider quality/latency/cost and actual QQ delivery semantics remain
  external evidence; local simulations make no empirical sufficiency claim.
- The SQLite ledger intentionally retains terminal tombstones for a bounded
  period and must remain on durable local storage during image rollback.
