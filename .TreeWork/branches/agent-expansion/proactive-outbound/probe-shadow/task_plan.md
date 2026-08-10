# Task Plan

Branch: probe-shadow
Parent: proactive-outbound
Title: S15E Probe Shadow

## Scope (owned work and boundary; not progress notes or implementation history)

- Sanitized group-window, Probe policy/state/metadata contracts and canonical digests.
- Deterministic Opportunity Detector, atomic Shadow ledger, SHORT candidate builder and no-send Runtime.
- Minimal Ports/Fakes, six-class sampled verification and Chinese status synchronization.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Public group windows create short-TTL Opportunity/Trigger/Run bindings; expired, personal,
  sensitive or cross-Scope windows fail before composition.
- [ ] Active dialogue, directed questions, conflict/safety, recent Bot activity, pending delivery and
  unresolved probe hard blockers cannot be offset by silence or future soft scoring.
- [ ] Probe candidates are fixed SHORT, one public block, no @/target user/attachment, and preserve
  exact Persona/Plan binding without Memory, Tool, Capability or model dependencies.
- [ ] Atomic namespaced state prevents duplicate recommendations, applies ordinary cooldown and
  applies longer cooldown after explicit `NO_OBSERVED_RESPONSE` without automatic follow-up.
- [ ] COLLECT/SHADOW remain no-send; metadata stores digests only and the object graph has no Output,
  Dispatch, Scheduler, Memory, Tool, Capability or model surface.
- [ ] Six sampled scenario classes pass on Python 3.10/3.12 with affected static/build/secret gates;
  unchanged Web and full-repository tests are skipped under the approved acceleration policy.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Freeze the minimal S15E contract from approved root design/research and S15A/S15 contracts.
- [ ] Implement Probe contracts/digests, Detector, state Store and Ports.
- [ ] Implement SHORT candidate chain, no-send Runtime and recording Fake sink.
- [ ] Run focused/sampled verification, synchronize documents, complete and locally integrate.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Raw/real QQ chat, user IDs, personal Memory, model ranking, Tool/Capability calls, private probes,
  individual mentions, automatic follow-up, Output/Dispatch, production persistence or real send.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified/integrated S15A control/Target contracts, S15 Persona validation and S15D no-send pattern.
2. Current `ConversationOpportunitySnapshot` and Trigger/Run one-of binding remain unchanged.
3. S16 consumes the recorded cancellation/operations risks later; no later branch is needed for
   S15E fixture-only proof.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: existing Opportunity/Trigger/Run, Target Registry, probe control, Persona/ResponsePlan and
  recording Output Fake were selected for direct reuse.
- Reuse check: `probe-shadow` exactly owns S15E; it does not create a second send policy, Connector,
  Scheduler or Memory path.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
