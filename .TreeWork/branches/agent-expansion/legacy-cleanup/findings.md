# Findings

Branch: legacy-cleanup

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- S19 substring inventory missed paths assembled from components and dotted
  imports. S22 added canonical repository contracts rather than treating the
  immutable S19 catalog as a live post-removal scanner.
- A missing Unified installation is a startup capability state, not authority
  to replay through another transport. The plugin stays available while the
  iCourse facade rejects with one stable, non-retryable error.
- Root `manage.sh`/`compose.yml` are deliberate operator APIs; the root env
  template and directory symlinks were temporary aliases and are removed.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Current host commands use `deploy/env/.env.example` and canonical source
  paths. Test discovery uses `-t .` so `tests/__init__.py` installs the single
  canonical AstrBot plugin source root.
- AstrBot configuration no longer exposes `icourse_mcp_mode`; status reports
  `unified` or `unavailable`. Persisted unknown legacy config fields are ignored
  and cannot select a direct Client.
- Rollback changed from an in-Release transport switch to restoring the exact
  S19 Release. Worker `protocol_mode=legacy` remains the required iCourse v1
  protocol adapter.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- External scripts outside the repository that still address a deleted alias
  must move to canonical paths or restore the full S19 Release.
- The AstrBot base image still carries upstream `jieba` SyntaxWarnings and a
  deprecated `register_star` warning; S22 introduced neither warning.
- Historical baseline, review, ADR and S19 catalog text legitimately retains
  old identifiers; a whole-repository literal-zero scan would destroy evidence
  and is not the S22 absence contract.
