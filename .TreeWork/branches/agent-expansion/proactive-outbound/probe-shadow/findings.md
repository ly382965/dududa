# Findings

Branch: probe-shadow

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Detector input is a versioned sanitized group projection, not raw messages. Explicit hard blockers
  are facts supplied by the future projection Adapter; the Detector cannot infer private context.
- The baseline is deterministic eligibility only. Longer silence cannot overcome an expired topic or
  blocker, and no model score can grant eligibility.
- Shadow state uses `shadow:<policy snapshot>` and an atomic per-Scope claim. A no-response outcome
  requires an attribution digest and a completed attribution window before applying long cooldown.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `dududa.proactive` exports Probe window/policy/detection/state/outcome/metadata contracts, Detector,
  in-memory Store, Composer/Builder and no-send Runtime. Existing Opportunity/Trigger v1 is unchanged.
- `dududa.ports` adds Detector, State Store, Composer, metadata-sink and Runner Ports. Metadata stores
  canonical evidence only; it has no topic summary, candidate body, group ID or user ID field.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The in-memory Store proves atomic claim/cooldown semantics but not restart-safe persistence; durable
  production storage and migration evidence belong to S16/S18 before any S23 canary.
- Synthetic projections prove boundary behavior, not real topic relevance, disturbance, group-level
  generalization, projection provenance or human acceptance. No real feedback Adapter exists.
- As recorded in S15D, shared awaited dependencies rely on cooperative cancellation; S16 should
  centralize bounded preemption rather than adding a Probe-specific cancellation control plane.
