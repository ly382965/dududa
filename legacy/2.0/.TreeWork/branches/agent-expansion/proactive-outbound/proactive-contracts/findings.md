# Findings

Branch: proactive-contracts

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Existing `InteractionLimiter` cannot express one atomic global-plus-Scope message window, so
  S15A adds a narrow paired quota lease instead of overloading model/tool budget counters.
- Initiated runs resolve a current `Actor` from the durable `ActorRef`; service identity never
  substitutes for operator or subscription-owner authority.
- Recovery retains the original validated response in `PreparedDispatch`, while Preview stores
  only digest-bound metadata and never persists the synchronous response body.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `dududa.proactive` now exports additive v1 contracts, config, Registry, policy, quota, Preview
  and Dispatch recovery primitives. `dududa.ports.proactive` exposes replaceable Protocols for all
  dependency boundaries, including full Dispatch recovery and metadata-only Preview recording.
- Business idempotency excludes worker, attempt, timestamps and Adapter revision. Exact replay
  returns the first prepared object; a changed target, content or policy reference conflicts.
- Existing inbound Runtime, AstrBot Adapter, MCP/Capability Runtime and Output composition are
  unchanged; there is no new production entry point.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- In-memory stores prove semantics but not durable multi-process CAS/lease behavior; S15B owns the
  persistent Scheduler/occurrence layer and later stages own real delivery reconciliation.
- No real source, Provider, group policy, QQ target or send was used. Proactive behavior remains
  default-off until later branch evidence and separately authorized S23 canaries exist.
