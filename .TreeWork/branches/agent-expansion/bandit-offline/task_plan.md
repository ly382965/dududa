# Task Plan

Branch: bandit-offline
Parent: agent-expansion
Title: S20 Offline Bandit Foundation

## Scope

- Add framework-neutral Bandit decision, execution, feedback and OPE contracts.
- Add deterministic static baseline and strict same-role/tier/support validators.
- Add Decimal IPS/SNIPS/DR/ESS plus one committed synthetic golden bundle.
- Prove the package has no production Router/Runtime/AstrBot hook.

## Acceptance

- [ ] Versioned immutable DTOs and canonical digests bind sanitized context,
  exact eligible actions, policy artifact, propensity, Router evidence,
  execution and delayed feedback without raw chat or identifiers.
- [ ] Decisions require at least two unique same-role/tier actions; distributions
  cover the complete action set, sum exactly to one and chosen propensity
  matches the chosen action.
- [ ] Static baseline is deterministic and replayable; synthetic mode requires
  positive support for every action and neither mode can widen Router eligibility.
- [ ] Execution and feedback validators reject substituted/fallback actions,
  post-window/duplicate/censored-as-zero feedback and unexecuted decisions.
- [ ] Propensity/support validation fails closed for zero/low propensity,
  unsupported evaluation action, excessive weight, missing reward and invalid
  outcome predictions.
- [ ] Fixed synthetic golden reproduces exact IPS/SNIPS/DR/ESS in normal,
  reverse and shuffled order; tampered artifacts are rejected.
- [ ] `dududa.bandit` is standard-library/internal only and has no import from
  Router/Runtime/AstrBot/proactive production paths.
- [ ] Focused dual-Python, package/import, static, secret and whitespace checks
  pass; Progress, Findings and Verification are committed without push.

## Local Steps

- [x] Read the approved Bandit research, S08 Router contracts and S20 boundary;
  freeze this Spec/Plan before implementation.
- [ ] Implement contracts, digests, validators and deterministic baseline.
- [ ] Implement OPE evaluator and negative support/feedback tests.
- [ ] Generate and check the committed synthetic golden bundle.
- [ ] Run scoped verification, synchronize docs, verify and return.

## Out Of Scope

- Training, VW/OBP/MABWiser dependencies or a policy Worker.
- Runtime/Router/AstrBot composition, Shadow recommendation or live exploration.
- Real Provider/user/chat data, QQ sends or production credentials.
- Cross-role/tier, permissions, Memory, Tool, AnswerProfile or proactive choices.

## Dependencies

1. S22 is complete, verified and merged at control commit `715ce5d`.
2. Existing S08 Static Router DTOs and hard filters remain authoritative.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: `docs/research/contextual-bandit.md`, model contracts/digests/Router,
  canonical codec, evaluation bundle patterns and import boundaries.
- Reuse check: canonical digests, `ModelEndpointRef`, Role/Tier and existing Eval
  artifact conventions are reused; no second Router or general RL framework.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
