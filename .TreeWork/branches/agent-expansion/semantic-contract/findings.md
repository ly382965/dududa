# Findings

Branch: semantic-contract

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Taxonomy revision is bound at projection level as well as on each intent, so
  an empty-intent `ABSTAIN` remains attributable and digest-sensitive.
- Without trusted required-slot metadata, an empty slot set is not guessed to
  be invalid. The contract represents a known incomplete request with
  `CLARIFY`; only missing properties and dangling entity refs fail closed.
- JSON Schema validation remains a development dependency injected into the
  offline evaluator. The zero-dependency Core package owns only the immutable
  Schema document and validation callback boundary.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `dududa.perception` now lazily exports semantic v2 DTOs, digests, offset
  helpers, Schema/ref, versioned codec and whole-envelope validator.
- `dududa.evaluation` exposes a fixed semantic Schema pilot runner/checker. Its
  report binds five synthetic windows and the v2 Schema digest while making no
  quality or release-readiness claim.
- No existing v1 payload, public Port, Runtime phase, Router, TierPolicy or
  Connector authority changed.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The synthetic pilot proves shape, downgrade and invariants only. Intent
  taxonomy fitness, reference resolution quality, calibration and Chinese
  group-chat accuracy remain unknown until the external evidence gate.
- The v1 Runtime intentionally does not consume semantic v2 yet; any future
  consumer must preserve deterministic authorization and side-effect ownership.
