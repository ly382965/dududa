# Task Plan

Branch: selection-contracts
Parent: model-selection
Title: S08 Selection Contracts

## Scope (owned work and boundary; not progress notes or implementation history)

- Add the shared task-complexity evidence DTO.
- Add model role/tier/reasoning/capability/privacy/endpoint/health/load/request,
  response, policy and reproducibility receipt DTOs.
- Add model Router/Provider/state/admission/codec Protocols.
- Converge the shared route-hint contract without connecting production code.
- Add invariant, digest, import-boundary and structural Protocol tests.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Public DTOs are immutable, versioned and reject invalid confidence,
  limits, identifiers, duplicate references and mutable nested values.
- [x] Role, tier and reasoning profile are orthogonal and no implicit tier
  fallback exists.
- [x] Endpoint identity, context limits, traffic freshness and reasoning mapping
  are fully expressible without Provider SDK types.
- [x] Complexity assessment cannot carry Provider/model/tier authority.
- [x] Route/Tier decisions and catalog inputs have stable canonical digests.
- [x] Protocols import and structurally conform without AstrBot installed.
- [x] Existing Runtime route hint uses the shared type and all existing tests
  remain green.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Inspect existing primitive, context, error and canonical conventions.
- [x] Implement `domain.task`, `models.contracts`, `models.policy` and exports.
- [x] Implement `ports.models` Protocols and converge `RouteHint`.
- [x] Add DTO, policy/digest, import and Protocol tests.
- [x] Run focused tests, full suite, compile and whitespace verification.
- [x] Synchronize Progress/Findings/Verification and commit branch changes.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Registry publication and last-known-good behavior.
- Candidate filtering, capacity implementation or Provider invocation.
- Fake/real Provider implementations.
- Perception, complexity algorithms, Runtime orchestration, rollout or Bandit.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. The S01-S07 core package and canonical/security primitives from baseline
   commit `c83d742`.
2. Accepted parent and root Specs; no external API or credential is required.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Existing `runtime.state.RouteHint`, primitives, Port context,
  canonical digest, errors, import tests and frozen model-routing design.
- Reuse check: No existing branch or module owns S08 model-selection contracts;
  Runtime provisional types explicitly defer them to S08+.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
