# Findings

Branch: control-plane

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- A Group Service Profile supplies an administrator-selected initial value; it
  never grants Capability or allows learned context to widen authority.
- Web and Node are typed Control Plane adapters. Python Core owns identity,
  Scope, authorization, Desired/Effective resolution, mutation and Receipts.
- Agent draft, permission and settings controls remain honestly unavailable
  until dedicated Core commands exist; they never reuse the human QQ send path.
- The approved local Dududa corpus is a development replay input, not quality
  gold, Memory input, Bandit reward or real-send authorization.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `dududa.control_plane` now exposes Profile/Assignment, onboarding lifecycle,
  immutable Runtime snapshots, operational projections and dedicated commands.
- In-memory and SQLite repositories share command identity, CAS, Audit/Receipt,
  LKG/restart and post-lock deadline semantics.
- Node proxies authoritative Core DTOs and Vue renders them without deriving
  health, permission or Effective state locally.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Production Core HTTP/operator identity and live subsystem health are not
  wired by S21; fixture/degraded/unavailable evidence remains explicit.
- External long-term chat data, human quality, real Provider/source/output and
  online Bandit remain S23 or later work.
