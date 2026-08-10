# Findings

Branch: local-integration-audit

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- S19 should aggregate existing authoritative evidence rather than wrap every
  command in another generic runner. Fixed gates and strict result manifests are
  enough to bind one release candidate.
- The lack of real Provider/QQ metrics does not block offline audit: pilot
  defaults are preregistered but unmeasured, while safety counters remain exact
  zero floors. This distinction must survive into the final receipt.
- Previous-release recoverability and S22 consumer inventory are release
  evidence, not cleanup work. S19 creates them but removes no compatibility
  surface.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Planned additions are operator-only CLI/config artifacts under `ops/cli` and
  `configs/release`; no Domain, Runtime, Router, MCP or Web API changes are
  required.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Docker build may need registry/package access when local cache is absent.
  Runtime smoke remains `--network none` and must not reuse production names,
  networks or volumes.
- A source archive proves code recoverability but not a historical production
  image observation. The final package must state exactly which evidence was
  rebuilt locally and which remains an S23/production gate.
