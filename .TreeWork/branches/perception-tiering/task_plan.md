# Task Plan

Branch: perception-tiering
Parent: model-selection
Title: S09 Perception And Tiering

## Scope (owned work and boundary; not progress notes or implementation history)

- Add de-identified Perception DTOs, canonical digests, strict model Schema and
  Protocols without changing S08 Router contracts.
- Implement deterministic Rule Perception, whole-result model validation,
  merger, complexity assessment, tier selection and initial social policy.
- Add Runtime-owned Router-backed Model Perception and assessment-to-tier
  projection while preserving one-way imports.
- Commit an offline, versioned 200-500-case synthetic Eval bundle, runner and
  report with reproducibility and hard-policy checks.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Public S09 DTOs are immutable, versioned, strictly validated,
  canonical-digestible and free of raw platform identities.
- [x] `dududa.perception` and `dududa.models` have no reverse dependency;
  cross-module orchestration is confined to `dududa.runtime`.
- [x] Rule Perception, strict model projection validation and deterministic
  merge satisfy positive, fallback, conflict, injection and cross-Scope tests.
- [x] Complexity assessment distinguishes semantic difficulty from context
  pressure and emits only evidence, never routing authority.
- [x] TierPolicy implements clear-low Haiku, conservative Sonnet, guarded Opus,
  explicit budget caps and typed no-affordable-tier failure.
- [x] Bootstrap Model Perception proves `PERCEPTION/HAIKU`, strict Schema, no
  route hint, bounded privacy/deadline/cancellation and sanitized fallback.
- [x] Initial Social Decision emits only the accepted S10-safe actions and has
  zero hard-policy violations in negative fixtures.
- [x] Synthetic Eval contains 200-500 valid cases, cluster-safe splits,
  complete policy labels/provenance and a reproducible generated report.
- [x] Focused and full verification passes on Python 3.10 and 3.12, with every
  remaining external or untouched-baseline gap recorded accurately.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Freeze branch Spec, exact DTO/Protocol ownership, reason-code vocabulary,
  failure semantics and Eval label basis.
- [x] Implement Perception context/candidate/result/social contracts, Schema,
  canonical digests and public lazy exports.
- [x] Implement and unit-test deterministic Rule Perception, projection
  validator and merger.
- [x] Implement and unit-test ComplexityAssessor, Runtime projection and
  DeterministicModelTierPolicy including budget matrices.
- [x] Implement and contract-test Router-backed Model Perception plus hybrid
  fallback/cancellation behavior using Recording Fake Provider.
- [x] Implement and unit-test the initial deterministic Social Decision chain.
- [x] Build the versioned synthetic Eval generator/artifacts, deterministic
  runner, leakage checks, metrics and baseline report.
- [x] Run focused/full verification, adversarial review, secret scan and Python
  version matrix; update Progress, Findings and Verification.
- [x] Commit the branch-owned implementation and verification documents. The
  TreeWork verification/completion transactions and Lead integration follow
  this Git handoff.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Bandit, random or learned routing; empirical claims about real model quality
  without blinded per-tier judging.
- Connector construction, Context history persistence, tools/MCP, Memory,
  response generation, Persona rendering, delivery, WebUI and Sub2API.
- Real QQ traffic, production shadow/canary enablement and Provider credential
  management.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Integrated and verified S08 contracts, Router, Recording Fake, Codec and
   compatible Adapter at base commit `9715854`.
2. Existing S01-S07 identity, message, security, budget and canonical codec
   contracts remain authoritative and backward compatible.
3. The S09 release dataset is synthetic until a separately reviewed PII
   de-identification process exists.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Recovered the accepted Tree, parent/root Specs, current S08 public
  contracts, package boundaries, tests and the clean managed worktree.
- Reuse check: `perception-tiering` already owns all requested S09 work; no new
  branch or Tree revision is needed.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml` after
  verified `static-router`; work remains isolated from concurrent WebUI and
  Sub2API changes.
