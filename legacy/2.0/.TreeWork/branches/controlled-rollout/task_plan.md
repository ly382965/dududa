# Task Plan

Branch: controlled-rollout
Parent: root
Title: S11 Controlled Rollout

## Scope (owned work and boundary; not progress notes or implementation history)

- Add strict rollout configuration and pure admission/ownership contracts.
- Add persistent transactional claim, CAS/dedup and delivery tombstone storage.
- Add bounded no-send shadow supervision and sanitized low-cardinality metrics.
- Add the thin AstrBot rollout bridge and single-owner canary delivery boundary.
- Add rollback manifest validation and local rollout simulations.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Invalid or ambiguous rollout configuration fails closed; `off`, `shadow`
      and `canary` behavior is deterministic and revisioned.
- [x] Admission simulations cover allowlist, trusted explicit mention, supported
      text, tools off, Memory off and TargetTalk overlap.
- [x] Shadow is capacity/deadline bounded and its send/write/tool/stop counters
      remain zero while the legacy path remains owner.
- [x] Canary persists exactly one ownership claim, rechecks the live kill switch
      immediately before send and never falls back after claiming.
- [x] Persistent claims, CAS/dedup and delivery tombstones survive restart;
      concurrent duplicates and `UNKNOWN` outcomes never trigger blind resend.
- [x] Metrics and read-only summaries expose only approved low-cardinality
      fields; secrets, raw content, IDs, prompts and Provider bodies are absent.
- [x] Rollback validation covers image, bind-mounted plugin/config revisions and
      an expected `off` control revision.
- [x] Python 3.10/3.12 focused and full suites, warnings-as-errors Runtime tests,
      Ruff, compile, import, secret and whitespace checks pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Define rollout contracts, config parsing, admission and sanitized metrics.
- [x] Implement SQLite transactional ownership/tombstone ledger and restart-safe
      disposition rules.
- [x] Implement bounded shadow supervisor and canary coordinator around S10.
- [x] Implement AstrBot Event snapshot/stop/output bridge and plugin lifecycle.
- [x] Add deterministic simulation fixtures for admission, overlap, concurrency,
      restart, in-flight control change and UNKNOWN delivery.
- [x] Record verification, findings, progress and rollback evidence; commit and
      complete the branch.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Bandit, learned/random routing or changes to S08/S09 selection policy.
- Tools, MCP, Memory access, attachments, proactive group chat or non-explicit
  group participation.
- External QQ sends or production rollout without explicit user authorization,
  credentials and an operator-approved allowlist.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified S10 `AgentRuntime`, `ShadowRunner`, DeliveryRequest and receipt
   acknowledgement/reconciliation contracts.
2. AstrBot host APIs are optional for core tests; bridge imports remain lazy or
   covered by host-only contract tests.
3. Real shadow/canary evidence depends on later operator authorization and live
   environment inputs.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Existing S10 Runtime, Output Adapter, core plugin lifecycle and
  TargetTalk compatibility surfaces were inspected before choosing module
  boundaries.
- Reuse check: This accepted branch already owns all S11 behavior; no new Tree
  branch is required.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
