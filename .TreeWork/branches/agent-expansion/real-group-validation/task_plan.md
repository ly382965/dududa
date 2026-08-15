# Task Plan

Branch: real-group-validation
Parent: agent-expansion
Title: S23 Authorized Real-Group Validation

## Scope

- Complete S23A--S23E as an offline historical-corpus pipeline: deterministic
  intake, Conversation Windows, real Semantic v2 Silver labeling, local Student
  training/evaluation and a private no-send HTML Demo.
- Freeze and validate one low-sensitivity S23 readiness manifest and operator
  runbook without resolving credentials or touching live systems.
- The configuration-driven inbound Runtime production shape is now closed
  without real credentials. After explicit inputs arrive, add only real
  Endpoint Conformance/evidence resolution and the Source, Projection and
  Output environment Adapters required by the authorized stage.
- Execute the single authorized group ladder from no-send Shadow through
  inbound, manual/scheduled digest and low-frequency Probe canaries.
- Reconcile delivery, SLO, incident, rollback and deletion evidence.

## Acceptance

- [x] S23A classifies all 1,402 files and reports authoritative JSONL/ZIP/HTML,
  duplicate, supplement, conflict, excluded-private and unique-message counts.
- [x] S23B produces valid 3--12 message past-only `PerceptionContext` windows,
  including at least 50 real windows and a stratified time-boxed target chosen
  from 240/360/480/600 after measuring real Teacher throughput.
- [x] S23C obtains real Semantic v2 Silver labels for the selected target from
  Terra as the fixed Teacher, routes invalid, low-confidence or ambiguous
  results into a review queue without storing raw requests in Git, and records
  the measured throughput and reason for the selected sample size.
- [x] S23D trains and evaluates `need_tools`, `semantic_complexity` and
  `answer_profile` Students on a group-isolated split, reports Silver agreement
  and generates offline predictions for every eligible window.
- [x] S23E produces a private, reusable localhost HTML Demo that visibly states
  PRIVATE DEVELOPMENT DATA, SILVER NOT GOLD, NO SEND, NO MEMORY WRITE, NO TOOL
  CALL, NO BANDIT and NOT CURRENT DUDUDA BOT TRAFFIC.
- [x] A canonical readiness manifest binds exact release/rollback/SLO,
  Endpoint/source evidence, private SecretRefs, data policy and separate
  behavior grants; placeholder or incomplete manifests fail closed offline.
- [x] A configuration-driven inbound production Runtime parses the actually
  configured 1--3 model tiers and assembles the Static Router and DirectChat
  chain; `off` performs zero Provider calls/sends, `shadow` does not claim or
  send, and disabled or unresolved Providers fall back to legacy.
- [ ] One authorized group's no-send/no-write Shadow proves zero Output, Tool
  write, Memory read/write, wrong-target and sensitive-Trace events.
- [ ] Explicit-mention inbound Canary is limited to approved test users and
  frozen message/run budgets; all delivery outcomes are reconciled.
- [ ] Manual digest then scheduled digest use approved live sources with valid
  provenance, freshness and citations and produce no duplicate, quiet-hour,
  revoked or unsubscribed delivery.
- [ ] A separately authorized low-frequency group Probe produces no personal
  target/mention, Memory access, auto-follow-up or send after no response.
- [ ] Every safety maximum remains zero; frozen latency/cost/quality measures,
  kill-switch and exact rollback evidence are recorded without post-hoc
  threshold changes.
- [ ] All canaries end disabled, retention/deletion actions are recorded, and a
  sanitized S23 report contains no raw message, prompt, answer, real QQ/group/
  user ID, credential or Provider error body.
- [x] Progress, Findings and Verification are synchronized and all changes are
  locally committed without push.

## Local Steps

- [x] S23A: implement and run `inventory`/`extract`; write private normalized
  messages and source-conflict artifacts, then record authoritative counts.
- [x] S23B: implement and run `window`/`sample`; validate 50-window smoke and
  produce stratified 240/360/480/600 candidate samples with per-group caps.
- [x] S23C: implement the private Responses-compatible labeler; run 5, then 50,
  estimate completion from the 50-run throughput, then run the largest target
  that leaves enough of the five-hour budget for training, Demo and handoff.
- [x] Enforce a four-hour target and five-hour hard wall-clock budget: reserve
  at least 75 minutes after annotation, stop launching requests at the
  annotation deadline, reuse successful cached labels and retry a transient
  request no more than once.
- [x] S23D: train three lightweight Students, evaluate with group isolation and
  classify all eligible windows.
- [x] S23E: generate/replay/serve the private no-send Demo, synchronize S23 and
  Chinese development documents, and create no more than three local commits.
- [x] Implement the offline readiness manifest/checker, template and runbook;
  record the current fail-closed external blockers.
- [x] Implement the production Builder, automatic plugin wiring, AnswerProfile
  feature flag and rule-only Runtime Perception; sample the production
  composition, Perception and Rollout contracts.
- [ ] Receive and privately bind the authorization, Endpoint, source, SLO and
  SecretRef packet; do not commit identifiers or credential values.
- [ ] Obtain real Endpoint Conformance/health/evidence resolution and add live
  Source, Projection and Output composition only for the authorized stage.
- [ ] Execute Preflight and single-group no-send/no-write Shadow; review the
  sanitized receipt before promotion.
- [ ] Execute explicit-mention inbound Canary and reconcile every request and
  delivery before promotion.
- [ ] Execute manual digest, then scheduled digest, with separate promotion and
  receipts.
- [ ] Execute one separately authorized Probe Canary, then disable all canaries.
- [ ] Run closeout, rollback/kill-switch checks, deletion, report, verification
  and protected completion.

## Out Of Scope

- Calling the historical export current Dududa traffic, reconnecting its source
  account, real QQ sends, production routing, live probes/digests or online
  Bandit learning during S23A--S23E.
- Default-on or broad production launch, private/personal proactive targets,
  arbitrary Tool writes, automatic Memory writes or unbounded group history.
- Bandit selection of send/skip, target, schedule, frequency, AnswerProfile,
  permission, Tool or Memory; S20 is not connected in S23.
- Fabricating campus/arXiv/industry MCP Servers or treating fixtures/iCourse as
  live news sources.
- Redesigning S01–S20 contracts, expanding WebUI or changing running containers
  before an approved deployment window.
- Automatic expansion to 3–5 groups; that requires a new grant after bounded
  single-group completion.

## Dependencies

1. S17–S20, S22, S19 release audit and the Mew/NapCat Web audit are complete.
2. External: behavior-specific group authorization, test-user references,
   data governance, private SecretRefs, frozen SLO and deployment window.
3. External/engineering: at least one conformance-proven real model Endpoint;
   digest stages additionally need approved live Source Adapter evidence;
   Probe needs a real sanitized group Projection Adapter.
4. The current candidate and exact previous release must both remain
   recoverable throughout the ladder.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: S19 pilot SLO/receipt/rollback evidence, S22 exact previous release,
  S11 rollout controls, S15A-S15E proactive contracts, current production-shape
  evidence and the external-input checklist.
- Reuse check: reuse existing authorization, rollout, Scheduler, Source,
  ResponsePlan, Output and operations Ports; add only S23 readiness/evidence and
  environment Adapters proven necessary by supplied facts.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
