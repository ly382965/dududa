# Findings

Branch: bounded-capability

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Capability permission and transport remain separate facts: discovery and a
  healthy MCP session never create a Capability or grant model visibility.
- Runtime integration uses the existing S10 state machine and adds only a
  default-off tool path; it does not create a second orchestrator, router,
  authorization service or budget ledger.
- Missing result evidence is charged conservatively. Cancellation or a
  non-terminal executor records one `UnobservedToolAttempt`; it is never
  accepted as a factual Observation or retried as if failure were known.
- Audit time is now injectable for deterministic fixtures, while production
  sinks retain the UTC wall clock by default.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Runtime State now persists `CapabilityRunRequest/Receipt`, plan authorization,
  Retrieval, Plan, Observations, unobserved attempts, validation and an
  independent `RuntimeToolBudgetPlan` through the tool phases.
- Direct Chat accepts only a validated Capability receipt and projects accepted
  Observations into size-bounded canonical JSON marked as untrusted external
  data; privacy and input-token bounds include that projection.
- `dududa.evaluation` exposes digest-bound Retrieval and Runtime Capability Eval
  reports. The four canonical iCourse IDs and fixed `refresh=false` Mapping are
  reflected in current developer documentation.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Current Context Builder capability categories and default rules do not prove
  natural-language iCourse routing; the Runtime vertical test uses a synthetic
  Perception result and PUBLIC fixture context deliberately.
- Synthetic Eval proves metric and policy behavior only. It does not establish
  real Chinese Recall, parameter extraction quality, live MCP reliability or
  answer usefulness.
- The repository-wide Ruff baseline has historical findings outside changed
  files. S13 verifies every changed Python file; unrelated cleanup is not a
  completion claim.
