# Task Plan

Branch: governed-operations
Parent: control-plane
Title: S21C Governed Operations

## Scope (owned work and boundary; not progress notes or implementation history)

- Add typed operational projection providers and registry.
- Map current Run/Model/MCP/Plugin/Memory/Proactive facts or honest unavailable
  states into the Core projection.
- Expose only registered dedicated Core mutations to Web.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Every operations surface is backed by a Core projection with revision,
  evidence mode and honest unavailable reasons.
- [ ] Unknown providers and cross-Scope queries fail or degrade without stale
  browser-derived authority.
- [ ] Mutation discovery exposes only dedicated authorized handlers; no generic
  settings writer exists.
- [ ] Agent draft/permission actions cannot call NapCat or claim success when
  Output/command composition is unavailable.
- [ ] Focused Python/Web tests, typecheck and build pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Implement projection contracts/registry and current Core adapters.
- [ ] Implement governed mutation bindings and HTTP endpoints.
- [ ] Connect operations/Agent Console views to projections and receipts.
- [ ] Run focused verification and synchronize branch evidence.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- New operational backends, production Output composition or real sends.
- Browser-owned health, permissions, model routing or arbitrary config writes.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. `group-onboarding` is complete and supplies the typed API/session path.
2. Existing Core registries/checkpoints remain source facts.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: current health/registry/checkpoint DTOs, Agent Console placeholders
  and server API conventions.
- Reuse check: add projection adapters around existing facts; do not move their
  ownership into Control Plane or Web.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
