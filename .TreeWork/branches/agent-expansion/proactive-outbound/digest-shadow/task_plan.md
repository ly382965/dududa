# Task Plan

Branch: digest-shadow
Parent: proactive-outbound
Title: S15D Digest Shadow

## Scope (owned work and boundary; not progress notes or implementation history)

- Digest composition policy/metadata contracts and canonical digests.
- Deterministic Composer, Candidate Builder, no-send Shadow runner and Preview producer.
- Minimal Ports/Fakes, six-class sampled Contract verification and Chinese status synchronization.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Policy snapshot binds exact source/response/persona inputs; LONG is capped to MEDIUM without
  changing model Tier or fabricating inbound perception evidence.
- [ ] Composer and existing validators preserve every selected item Fact/Citation/source URL and
  enforce deterministic character/token/part bounds.
- [ ] COLLECT/OFF/kill-switch/config mismatch/CANARY stop before Source; SHADOW has no Output,
  Dispatch Store, Scheduler ack, Memory, model or network dependency.
- [ ] PARTIAL/NO_NEW/FAILED/CANCELLED produce deterministic metadata and never persist body text;
  duplicate fixture items do not create another candidate.
- [ ] Authorized Preview reuses composition but has an isolated source-state namespace and creates
  no occurrence, dispatch or delivery receipt.
- [ ] Six sampled scenario classes pass on Python 3.10/3.12 with affected static/build/secret gates;
  unchanged Web is skipped and status documents are synchronized.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Freeze S15D scope/contracts from the approved root design and S15C/S15A interfaces.
- [ ] Implement digest contracts, Ports and deterministic candidate composition.
- [ ] Implement Shadow runtime, Preview producer and recording Fake sink.
- [ ] Run focused/sampled verification, synchronize documents, complete and locally integrate.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Any live Source Adapter/network, model call, Memory read/write, Output/Dispatch, QQ send or
  Scheduler claim acknowledgement.
- Probe opportunities, production scheduler entrypoint, UI expansion, LONG default digest or
  modifications to inbound Response Profile selection.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified/integrated S15A contracts, S15B Scheduler, S15C SourceProvider and S15 Persona chain.
2. Existing Preview authorization remains owner; S15D Producer cannot bypass it.
3. S15E depends on this branch; no later branch is required for fixture-only no-send proof.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: S15A Preview/RunReceipt, S15C source origin/state, S15 ResponsePlan/Persona/validators and
  current proactive controls were selected for direct reuse.
- Reuse check: `digest-shadow` exactly owns S15D; no second Runtime, Source Client or send policy is
  introduced.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
