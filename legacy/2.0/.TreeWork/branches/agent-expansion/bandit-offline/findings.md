# Findings

Branch: bandit-offline

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Existing Router ordering includes route-hint precedence and differs from the
  draft standalone tie-break wording. S20 therefore binds the Router's exact
  `planned_endpoint` instead of implementing another sorter.
- Logged-action propensities alone cannot prove support for a dynamic action
  set. Each OPE sample therefore carries full behavior and evaluation
  distributions; positive evaluation probability requires nonzero, policy-
  compliant behavior support for that same action.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `dududa.bandit` is a new public framework-neutral Package. It depends only on
  standard-library/internal contracts and is included in package/import checks.
- Models, Runtime, Proactive and AstrBot retain one-way dependency direction and
  do not import or execute Bandit.
- Offline reports use 12-place `ROUND_HALF_EVEN` Decimal values and bind sorted
  sample-set and policy digests.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Deterministic production Router history has zero support for unchosen actions;
  DR cannot repair that. Future comparative OPE needs explicitly authorized
  nonzero propensities across at least two safe same-role/tier Endpoints.
- Synthetic reward and prediction values validate arithmetic only. They do not
  calibrate reward policy, model quality, cost, latency or exploration budgets.
