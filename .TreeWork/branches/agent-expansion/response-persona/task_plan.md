# Task Plan

Branch: response-persona
Parent: agent-expansion
Title: S15 Response Profile And Persona

## Scope (owned work and boundary; not progress notes or implementation history)

- S15 framework-neutral AnswerProfile/ResponsePlan contracts, deterministic policy,
  current-message evidence, preference isolation and dynamic output-budget projection.
- Additive ModelRequest, Runtime State and direct-chat binding of the immutable Plan.
- Composer, typed Persona Catalog/Registry, deterministic Renderer and final Profile
  Validator integration without a real model or production send.
- Versioned typed `dududa`/`neutral` Persona assets plus a fixed synthetic 3x3 Eval.
- Documentation, rollback notes, focused/full verification and local Git commits.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] `AnswerProfile`, evidence, preference, limits, immutable `ResponsePlan`, canonical
  digests and stable reason/error codes are validated and framework-neutral.
- [ ] Deterministic policy proves explicit-message priority, task/default behavior,
  conversation caps, exact-Scope preference isolation and the full 3x3 matrix.
- [ ] Dynamic reservation only narrows existing budget; Direct Chat and ModelRequest bind
  Plan digest, visible limit and generated-token limit without changing TierPolicy.
- [ ] Composer, Persona Renderer and final Validator consume the same Plan; Runtime State
  persists it once and rejects missing, forged or replay-mismatched evidence.
- [ ] Typed Persona assets, atomic Catalog snapshot, last-known-good, explicit neutral
  fallback and rollback all pass Contract tests; legacy seed remains intact.
- [ ] Fact, Citation, Refusal, Target, Attachment, Warning and Scope changes are zero in
  negative/property fixtures; over-limit output never reaches Delivery.
- [ ] `evals/response-profile/v1` is deterministic, digest-bound, tamper-rejecting and
  explicitly makes no real-data, human-quality or Provider-tokenizer claim.
- [ ] Python 3.10/3.12 full and focused tests, import/build/compile/secret/lock checks and
  necessary Web regressions pass; branch Progress/Findings/Verification are synchronized.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Freeze S15 branch Spec/Plan and commit the design boundary before code.
- [x] Implement `dududa.responses` contracts, digests, policy, counter, budget projection
  and Protocol exports with focused Unit/Contract tests.
- [x] Add ModelRequest/DirectChat/Runtime State Plan bindings and preserve S10-compatible
  readers; prove Tier/Profile/Reasoning orthogonality.
- [ ] Implement `dududa.persona` typed definitions, asset loader, Registry snapshot,
  last-known-good and explicit fallback; add versioned repository assets.
- [ ] Integrate Composer/Renderer/final Profile Validator and Runtime Orchestrator, then
  cover direct/tool/clarification/failure/recovery flows.
- [ ] Add and regenerate the versioned synthetic 3x3 Eval plus tamper/order tests.
- [ ] Synchronize design/status/developer documentation and run focused verification.
- [ ] Run full dual-Python/repository/Web gates, record TreeWork Verification, complete,
  locally merge and return to the control workspace.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Any real Provider Endpoint, QQ send, live MCP/source, production Memory or container change.
- Human blind review, real Chinese/group-chat calibration, final profile budgets or quality claims.
- `/style` migration, persistent preference storage, multiple product Personas, Persona/Bandit
  exploration or a model-based Persona Renderer.
- S08/S09 redesign, Static Router/TierPolicy changes, hidden-CoT output, automatic truncation,
  Output Adapter reimplementation or proactive S15A-S15E behavior.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified and integrated S14 Memory branch plus existing S08-S13 Runtime, Router,
   Perception, Capability and safety contracts.
2. Approved root Spec, implementation plan, Persona design and response research.
3. External ideal/counterexample answers, second reviewer, real Provider evidence and real QQ
   constraints are intentionally unavailable and are not required for this offline branch.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: S10 composition/direct-chat/state, S08 Router budgets, S09 complexity/social
  contracts, current Persona seed/assets and existing Eval patterns were inspected.
- Reuse check: existing `response-persona` leaf exactly owns S15; no second route or new Tree
  node is needed. Existing Composer, Renderer and validators are extended additively.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
