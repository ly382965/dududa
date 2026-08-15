# Task Plan

Branch: control-plane
Parent: agent-expansion
Title: S21 Bot Control Plane

## Scope (owned work and boundary; not progress notes or implementation history)

- Deliver S21A, S21B, S21C and the completion audit in dependency order.
- Keep Python Core authoritative and Web limited to typed queries/commands.
- Stop after offline S21 completion and leave S23 paused.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] S21A-S21C and the audit are complete, verified and integrated locally.
- [x] An authorized Fake operator can initialize a pending Fake group through
  one versioned Profile and Runtime consumes only its immutable Assignment.
- [x] Desired/Effective state is explainable and no model/plugin/context/
  Bandit output can widen service, capability, Memory or send authority.
- [x] Web Agent operations use authoritative queries/commands and no Agent
  draft, permission or setting mutation succeeds in browser-local state.
- [x] S23 remains paused with real adapters, human quality and sends external.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Complete and integrate `control-plane-foundation`.
- [x] Complete and integrate `group-onboarding`.
- [x] Complete and integrate `governed-operations`.
- [x] Complete the cross-stage `control-plane-audit` and parent verification.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Real Provider/Source/Output adapters, production operator identity and S23.
- Group Context learning, Plugin marketplace/lifecycle and online Bandit.
- A generic browser config writer or unrestricted OneBot action proxy.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. S22 and Mew/NapCat Web audit are complete.
2. Existing Security, Capability, Router, Memory, Proactive and Output
   contracts remain authoritative.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: root Requirements/Spec, `docs/design/bot-control-plane.md`, current
  Core security/runtime packages and the Agent Console placeholders.
- Reuse check: no accepted branch owns governed group onboarding; existing Web
  parity owns QQ client behavior only and existing Security owns authorization.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
