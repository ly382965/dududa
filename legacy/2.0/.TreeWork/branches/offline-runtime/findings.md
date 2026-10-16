# Findings

Branch: offline-runtime

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Difficulty evidence, Tier selection and endpoint routing remain three bound
  decisions: semantic/context evidence cannot directly name a Tier or model.
- Context pressure remains a capacity concern and cannot by itself upgrade
  semantic complexity.
- Delivery correctness cannot rely on an Orchestrator-local lock. Store CAS plus
  reload-and-reduce is the authority across Runtime instances.
- S10 composition uses `Offline*` Protocol names so its bounded synchronous
  interfaces do not freeze the future asynchronous general-purpose contracts.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `AgentRuntime` now includes delivery acknowledgement and reconciliation;
  `RuntimeResult` carries an optional sanitized selection summary.
- `dududa.runtime` exports the S10 contracts and implementations; `dududa.ports`
  exports Runtime, Store, Perception, Shadow and Offline composition Protocols.
- Delivery receipts are canonicalized to the complete part plan before storage;
  missing Adapter evidence is represented as UNKNOWN.
- AstrBot output splitting is bounded by UTF-8 bytes and exact request replay.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The S10 Store is intentionally in-memory and same-process; S11 must provide
  persistent idempotency before production canary ownership.
- Real Provider quality/latency/cost, real AstrBot event semantics and QQ
  delivery remain external evidence. No empirical model-sufficiency claim is
  made by the offline tests.
- Bandit and all learned/random routing remain absent.
