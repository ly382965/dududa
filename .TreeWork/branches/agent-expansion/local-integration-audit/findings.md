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

- Operator-only artifacts now live under `ops/cli` and `configs/release`; no
  Domain, Runtime, Router, MCP or Web API changed. The candidate CLI exposes
  `policy-check`, `inventory`, `gate`, `archive` and `candidate` only.
- The complete legacy-surface catalog is code-digest-bound. Inventory stores
  relative tracked consumer paths, while the candidate receipt stores only its
  digest. Reclassifying a live surface therefore requires reviewed code and
  catalog changes.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Docker build may need registry/package access when local cache is absent.
  Runtime smoke remains `--network none` and must not reuse production names,
  networks or volumes.
- A source archive proves code recoverability but not a historical production
  image observation. The final package must state exactly which evidence was
  rebuilt locally and which remains an S23/production gate.
- The first read-only AstrBot smoke failed because upstream AstrBot derives its
  data directory from the current root and attempted to write below the
  read-only repository mount. `ASTRBOT_ROOT=/tmp/astrbot` preserves the
  read-only source boundary while giving the disposable container a writable
  data root; the rerun passed and cleanup left no S19 container running.
- One initial Playwright run produced a fully blank page before Vue mounted.
  The target case then passed eight consecutive diagnostic repetitions and the
  exact final six-case suite passed. There was no stable compact-layout or
  NapCat reconnect defect, so S19 did not modify Web behavior.
- The inventory is deliberately a handoff, not a deletion oracle: ten canonical
  path aliases are candidates, but the root wrappers, legacy Handler/Role/
  Memory/protocol/audit surfaces remain live and the dedicated iCourse Client
  remains blocked until S22 proves complete consumer migration.
