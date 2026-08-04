# Task Plan

Branch: offline-runtime
Parent: root
Title: S10 Offline Runtime

## Scope (owned work and boundary; not progress notes or implementation history)

- Correct Runtime/Delivery drift needed by a two-stage offline execution.
- Implement bounded current-message context, complete S09/S08 selection
  orchestration and deterministic response composition.
- Implement in-memory CAS/dedup/single-flight state and delivery
  acknowledgement/reconciliation.
- Prove a non-deliverable Shadow composition with tools and Memory absent.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Runtime/Delivery public contracts are versioned, immutable,
  canonical-digestible and consistent with the S10 Spec.
- [x] Perception exposes sanitized execution evidence and total two-call budget
  accounting is conservative under success/fallback/failure.
- [x] Current-message Context is bounded/de-identified and opaque targets map
  back only through a validated current-Scope identity binding.
- [x] In-memory Store proves atomic create, revision CAS, dedup conflict,
  same-process single-flight, TTL and non-evicting tombstone capacity.
- [x] Orchestrator runs explicit private/group-mention direct chat through
  Complexity, TierPolicy, S08 Router, Composer, Renderer and validation.
- [x] Ignore, clarification, tools-disabled, invalid output, budget, deadline
  and cancellation paths produce safe typed state/results.
- [x] DeliveryRequest authorization/digests bind one intent; four real receipt
  statuses, exact replay and monotonic reconciliation are tested.
- [x] Shadow public output is non-deliverable and tests prove zero Output,
  Memory, Tool and event-stop calls.
- [x] Focused/full verification passes on Python 3.10 and 3.12 with all external
  evidence gaps recorded.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Add S10 cross-stage DTOs, execution receipts, canonical digests and public
  Protocol exports.
- [x] Correct `DeliveryConstraints`, Completion status, RuntimeResult binding,
  `reconcile_delivery()` and AstrBot exact-replay/UTF-8 splitting behavior.
- [x] Implement and test current-message Context Builder plus identity binding.
- [x] Implement and test budget reservations and execution-capable Perception.
- [x] Implement and test in-memory Runtime State Store, state invariants and
  duplicate single-flight waiting.
- [x] Implement and test Direct Chat request/projection over S08 Router.
- [x] Implement and test Composer, deterministic Persona renderer, render
  validator and content-safety binding.
- [x] Implement Orchestrator phase flow, terminal reducers and route/budget
  receipts with focused failure/cancellation tests.
- [x] Implement Delivery builder, offline delivery driver, acknowledgement and
  reconciliation with adversarial concurrent receipts.
- [x] Implement sanitized Shadow Runner and forbidden-side-effect tests.
- [x] Run adversarial review and full verification matrix; synchronize Progress,
  Findings and Verification and commit the branch handoff.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Persistent production dedup, AstrBot event ownership, canary, kill switch,
  rollback automation and real QQ traffic.
- Memory, MCP/Tool execution, attachments, trusted reply history, proactive
  group chat, reactions, multi-Persona or model-based rendering.
- Bandit or any online/learned routing behavior.
- Concurrent user WebUI, deployment and Sub2API paths.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Integrated S08 Router and Provider contracts at or after `9715854`.
2. Integrated, verified S09 Perception/Tiering at control commit `18d4958`.
3. Existing S01-S07 Connector, security, delivery and canonical contracts.
4. Real AstrBot delivery remains disabled; only recording/offline Adapter
   evidence is required here.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Reconstructed root requirements/spec, S08/S09 interfaces, Runtime
  State, Delivery/Output contracts, security policies and existing tests.
- Reuse check: `offline-runtime` owns every S10 correction and component; no
  Tree revision or sibling branch is required.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml` and
  depends on completed `perception-tiering`.
