# Task Plan

Branch: proactive-contracts
Parent: proactive-outbound
Title: S15A Proactive Contracts

## Scope (owned work and boundary; not progress notes or implementation history)

- S15A framework-neutral proactive DTOs, digests, Port contracts and stable errors.
- Deterministic default-off initiation/pre-dispatch gates with exact Target/Grant/Scope binding.
- Strict proactive config, in-memory Registry/Dispatch/Preview stores and local Fakes.
- Preview isolation and stable PreparedDispatch idempotency/recovery contracts.
- Focused/full verification, status documentation and local Git commits.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] TargetPolicy/Grant Ref, Trigger, Subscription/Schedule, Run/Preview, Source, Policy,
  Dispatch/Claim and Receipt contracts are strict, immutable, versioned and digest-bound.
- [x] Exact Target/Grant/Scope/action/revision/expiry resolution fails closed for missing,
  revoked, replaced, stale or cross-kind evidence.
- [x] Default config is OFF with empty allowlists and active kill switches; OFF/COLLECT/SHADOW
  and every failed quiet-hour/limit/audit/authorization gate produce zero delivery.
- [x] Preview uses its own action and Port, returns only to an authorized Actor and cannot create
  occurrences, PreparedDispatch, DeliveryRequest/Receipt or Output calls.
- [x] PreparedDispatch business idempotency is stable across worker/attempt/Adapter revisions;
  exact replay reuses the stored object and changed content/target/ref conflicts.
- [x] Fake Clock/Registry/Store/Output and Contract tests use only synthetic local fixtures and
  prove there is no network, model, MCP, real source or real send dependency.
- [x] Existing inbound Runtime/Router/ResponsePlan/Output behavior and import boundaries remain
  compatible; no second control plane or forged Connector path is introduced.
- [x] Python 3.10/3.12 focused/full, build/lock/compile/secret/whitespace and necessary Web gates
  pass; Progress/Findings/Verification and public implementation status are synchronized.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Reconcile the approved root Spec, proactive design and S15A plan; freeze this branch Spec
  and Task Plan before code.
- [x] Implement proactive enums, immutable DTOs, canonical projections/digests and public exports.
- [x] Implement strict config plus Target/Grant Registry resolution and preflight validation.
- [x] Implement deterministic initiation/pre-dispatch gates, quiet-hour/limit/kill-switch inputs
  and stable reason codes using existing security Ports where applicable.
- [x] Implement Preview isolation, PreparedDispatch idempotency/recovery and local Fakes.
- [x] Add Unit/Contract/import tests for negative matrices and focused warning-as-error gates.
- [x] Synchronize status/developer docs, run full dual-Python/repository/Web verification, record
  TreeWork Verification, complete, locally merge and return to the control workspace.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Durable Scheduler, timezone occurrence materialization, persistent CAS/lease and 30-day
  simulation; these belong to S15B.
- Real/fake source collection implementation, MCP mapping, normalization and fixture digests;
  these belong to S15C.
- Digest/Probe composition, Persona execution, Shadow runtime, real Output integration or QQ send;
  these belong to S15D/S15E/S23.
- Real credentials, user/group data, live network, running container changes, Bandit exploration,
  personal Memory, private proactive messages or automatic follow-up.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified and integrated S15 Response/Profile branch plus existing S03 authorization/limits,
   S04 Delivery, S11 rollout and S12/S13 MCP/Capability contracts.
2. Approved root Spec, `docs/design/proactive-messaging.md` and S15A row in the implementation plan.
3. S15B-S15E consume these contracts later; none is required to prove the S15A offline boundary.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Existing identity/Scope, canonical codec, AuthorizationDecision, limiter/audit Ports,
  Delivery/Binding, rollout config and in-memory CAS patterns were selected for reuse.
- Reuse check: `proactive-contracts` exactly owns S15A; no new Tree node or alternate Runtime is
  needed. Existing inbound Runtime and Output Adapter remain unchanged.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
