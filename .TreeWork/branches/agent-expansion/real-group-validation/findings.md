# Findings

Branch: real-group-validation

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- S23 completion is the bounded single-group ladder plus closeout. Expansion to
  3–5 groups is a later authorization decision, not an inherited grant.
- iCourse cannot satisfy digest-source readiness; it remains a course-review
  MCP and no campus/arXiv/industry live source is currently implemented.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- The planned readiness artifact contains references/digests only. Real account,
  group and test-user mappings remain in a private local binding store.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The running AstrBot/NapCat stack is not the S19 derived candidate and has not
  been authorized for replacement. S23 needs an explicit deployment window and
  a rollback owner before mutation.
