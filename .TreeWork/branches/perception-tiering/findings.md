# Findings

Branch: perception-tiering

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Difficulty evidence and endpoint routing remain separate authorities:
  Perception/Assessor emits evidence, TierPolicy emits a tier, and S08 alone
  resolves that tier to a Provider endpoint.
- Model Perception always bootstraps through fixed Haiku. User text, Model output
  and `RouteHint` cannot grant Tier, Provider, authorization or Scope authority.
- Reply targets are rule-authoritative. A model adding another known group
  identity is a conflict and cannot expand delivery targets.
- Context pressure, semantic complexity and reasoning depth remain orthogonal.
  Long input alone cannot trigger Opus.
- Eval variants are correlated within template families. Risk diagnostics use
  applicable family clusters and explicitly state their synthetic assumptions.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- New `dududa.perception` DTOs, validators, digests, Schema, rules, merger,
  assessor and social policy are public lazy exports. `PerceptionLimits` includes
  an explicit degraded-component limit and immutable v1 hard ceilings.
- New Perception and bootstrap/tier policy Protocols live in `dududa.ports`;
  cross-package orchestration lives in `dududa.runtime` to preserve dependency
  direction.
- `runtime.state` now uses real `PerceptionResult` and `SocialDecision` values.
- Model Perception idempotency derives from the complete deterministic
  `ModelRequest` plan fingerprint rather than context identity alone.
- The Eval report binds dataset/split/plan/rubric/prediction-set digests and
  component revisions; `policy_selected_tier_agreement` is not an empirical
  minimum-tier claim.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Fixed structured fixtures prove deterministic policy behavior, not whether a
  real Haiku/Sonnet/Opus endpoint is sufficient for a task.
- Several safety gates have only one independent synthetic template family;
  their nominal zero-event 95% upper bound is 95%, so the result must not be
  generalized to production traffic.
- Human template review, real Provider evidence and real group traffic remain
  external release evidence.
