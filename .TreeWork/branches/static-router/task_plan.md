# Task Plan

Branch: static-router
Parent: model-selection
Title: S08 Static Router

## Scope (owned work and boundary; not progress notes or implementation history)

- Publish validated, immutable in-memory catalog snapshots with exact Provider,
  endpoint, route-policy, descriptor, traffic-policy and reasoning-profile
  revision binding, retaining the last known good catalog on rejected updates.
- Publish bounded operational snapshots and provide atomic shared-quota-pool
  admission for concurrency, queue, RPM, TPM, stale/minimum-sample load and
  cooldown constraints.
- Estimate complete Provider invocations, validate structured output, and route
  `PERCEPTION`/`DIRECT_CHAT` requests deterministically through bounded retry,
  same-tier failover and explicit cross-tier fallback.
- Provide a recording scripted Fake Provider and a conservative AstrBot
  Provider Adapter that pass one shared Provider conformance suite.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Invalid catalog/operational publications are rejected atomically and the
  previous snapshot remains readable; exact revision and shared quota-pool
  invariants are covered by tests.
- [x] Admission atomically enforces concurrency, queue, RPM and TPM across
  endpoints sharing a quota pool; stale load, insufficient samples, cooldown,
  cancellation, reservation ceilings and unknown usage settle fail closed.
- [x] Estimation includes prompt, Schema, Provider wrapping, Context, generated
  output/reasoning and cost without double-counting reasoning tokens; context,
  deadline and budget boundaries have negative tests.
- [x] Structured output is whole-result validated, allows a bounded single
  schema-repair attempt where configured, and never crosses tier after an
  invalid second result.
- [x] Routing applies the Spec filter order, treats hints as eligible-only
  reordering, sorts by policy priority plus endpoint ID, and produces stable
  plan fingerprints for identical semantic inputs and snapshots.
- [x] Retry, same-tier failover and tier fallback have independent ceilings,
  share deadline/budget, re-run all hard gates, and terminate on auth, invalid
  request, safety refusal, cancellation and exhausted schema repair.
- [x] Recording Fake and AstrBot Adapter pass the same Provider conformance
  suite, redact Provider errors/credentials, and declare only observed AstrBot
  API capabilities.
- [x] `PERCEPTION` is fixed to Haiku, `DIRECT_CHAT` defaults to Sonnet, Opus has
  no implicit traffic, no production Event is connected, and S01-S07 plus the
  complete repository verification matrix remain green.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Inspect frozen contracts, digests, security budget patterns, AstrBot call
  surface and existing test/fake conventions; settle branch-local file layout.
- [x] Extend the accepted contracts with plan/execution separation, typed
  admission results, per-attempt capacity evidence and one schema-repair ceiling.
- [x] Implement catalog and operational registries with last-known-good atomic
  publication and exact revision resolution.
- [x] Implement complete invocation estimator and strict structured-output
  codec.
- [x] Implement atomic in-memory quota-pool admission leases and deterministic
  clock-friendly accounting.
- [x] Implement static selection/filter receipts and bounded invocation loop.
- [x] Implement scripted recording Fake Provider and focused unit/contract
  tests, including concurrency and failure matrices.
- [x] Implement conservative AstrBot Provider Adapter and shared conformance
  suite without importing AstrBot into Core.
- [x] Run formatting, lint, compile, focused tests, full tests, import/secret and
  whitespace checks; update Progress/Findings/Verification and commit.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Rule/Model Perception, task difficulty assessment, TierPolicy implementation,
  social decision or Eval data (owned by S09).
- Runtime orchestration, production Event ownership, shadow/canary delivery,
  Memory, tools/MCP, images, proactive group chat or legacy Handler replacement.
- Bandit, randomized/learned ranking, dynamic latency/cost optimization or
  capability inference from model names.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Integrated `selection-contracts` commit `3629798` and the model-selection
   parent Spec are authoritative.
2. Core remains independent of AstrBot and Provider SDKs; the compatible
   Adapter lives under `plugins/astrbot_plugin_dududa_core/adapters`.
3. Host AstrBot may be absent; shared conformance uses a protocol-compatible
   harness and real-host registry smoke remains explicitly skippable.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Existing model contracts, ports, canonical digests, security budget
  ledger, test fakes and actual AstrBot Provider calls were reviewed before
  implementation.
- Reuse check: `static-router` is the accepted existing branch and owns all S08
  implementation in this plan; no additional branch is needed.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
