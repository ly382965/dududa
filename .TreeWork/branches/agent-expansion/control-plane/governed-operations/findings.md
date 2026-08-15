# Findings

Branch: governed-operations

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Operational evidence is snapshot-only. A Control Plane read never initiates
  model, MCP, Capability, NapCat or network probing.
- MCP and Capability registries do not currently expose cached health through a
  bounded read API, so enabled entries are `DEGRADED` with stable
  `*_health_not_cached` reasons rather than being called healthy.
- The absence or failure of one surface is a projection fact, not permission to
  retain an older browser result or disable Group Onboarding.
- Agent placeholders stay read-only until their dedicated Core command and
  Output composition exist. Human QQ operations remain a separate path.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added six operational surfaces, evidence/status/fact DTOs, exact-scope query,
  projection registry and governed mutation descriptors.
- Added Model Router and combined MCP/Capability snapshot adapters. Unbound
  Runs/Plugin/Memory/Proactive providers produce explicit unavailable results.
- Added `ControlPlaneApi.operational_projections()`, Python Web projection,
  Node `operations()` proxy and `/api/control-plane/accounts/:id/operations`.
- Group scope discovers only the six existing Group Service lifecycle actions;
  no draft, permission, arbitrary settings or generic config mutation is
  discoverable.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Production HTTP/operator adapters and live subsystem health sources are not
  present, so current evidence proves offline projection behavior only.
- The operations detail strings are bounded registry metadata, not quality,
  latency, cost or live-availability claims.
