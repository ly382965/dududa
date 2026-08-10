# Task Plan

Branch: local-integration-audit
Parent: agent-expansion
Title: S19 Local Integration Audit

## Scope

- Add strict pilot SLO, candidate-evidence and S22 consumer-inventory contracts.
- Add bounded audit/image-smoke tooling that reuses existing CI, S16 operations
  and S18 receipts without accepting arbitrary commands.
- Run and record the complete release-required offline matrix once.
- Produce a digest-bound candidate/previous-release/rollback evidence package.

## Acceptance

- [ ] S18 and all prior release-required leaves are complete/verified and the
  S19 candidate revision is clean.
- [ ] Strict SLO policy validation freezes zero safety floors, profile token
  ceilings, labeled pilot defaults and explicit external-pending fields without
  claiming real measurements.
- [ ] Python 3.10.20 and 3.12.13 complete repository receipts pass with matching
  discovery counts and documented identical skips; both worker locks and
  worker-local suites pass.
- [ ] Four committed Eval bundles, 30-day Scheduler, day 1/2/30 Digest/Probe and
  the fixed cross-module failure sample pass without network or sends.
- [ ] Web dependency audit, Unit/Server, typecheck/build and Playwright pass once
  from the locked Node/npm environment.
- [ ] AstrBot and Web images build under unique tags; `--network none`
  disposable smoke verifies package/plugin/MCP and Web loopback health, always
  cleaning temporary containers and never touching the running stack.
- [ ] Wheel/install/import/pip, Ruff/format/compile, Shell, rendered Compose,
  secret, lock, import-boundary and whitespace gates pass.
- [ ] Candidate and previous release manifests, source artifact, backup/restore
  plan and failed-health single rollback form a verified digest-bound package.
- [ ] Every proposed S22 surface has a tracked consumer inventory and an honest
  `remove_candidate`, `retain_live` or `blocked_unknown` classification; legacy
  audit privacy is assessed separately from Runtime Trace.
- [ ] One atomic low-sensitivity S19 receipt binds every required evidence
  digest and leaves real Provider/source/QQ/human-quality gates pending.
- [ ] Progress, Findings, Verification and Chinese project status documents
  match the actual evidence; changes are locally committed without push.

## Local Steps

- [x] Inspect S16/S18 operations/evaluation assets, current CI, Dockerfiles,
  migration map and legacy consumers; freeze this Spec and Plan.
- [ ] Implement strict SLO/candidate receipt and consumer-inventory tooling with
  focused tamper/privacy/extension tests.
- [ ] Implement disposable AstrBot/Web image smoke with guaranteed cleanup and
  a static no-running-stack contract.
- [ ] Run dual-Python full discovery, worker and committed Eval gates.
- [ ] Run proactive/failure samples, Web/E2E, package/static/Compose/secret gates
  and disposable images.
- [ ] Generate and verify previous/candidate/rollback and S22 inventory package.
- [ ] Synchronize documentation, commit, record TreeWork verification and return.

## Out Of Scope

- Real Provider calls, live source fetches, production Memory/Tool enablement,
  QQ reads/sends or changes to running NapCat/AstrBot containers.
- Human Chinese/Persona quality, real cost/latency claims or S23 authorization.
- Deleting legacy code/paths (S22) or adding Bandit contracts (S20).
- New Web features, a second control plane or a generic command-execution DSL.

## Dependencies

1. S17 and S18 are complete, verified and integrated at the branch base.
2. S18 fixed suite profiles and S16 release/backup/rollback contracts remain
   authoritative and are reused rather than rewritten.
3. Docker, Node 22/npm, Playwright Chromium, uv and Python 3.10/3.12 are locally
   available; no credentials or real data are required.

## Branch Intake Gate

- Inspect: S18 suite/CI receipts, S16 operations types and CLI, Dockerfiles,
  Compose, Web scripts, migration map, symlinks and legacy audit consumers.
- Reuse check: existing runners own test execution and S16 owns release state;
  S19 adds only aggregation, policy/inventory validation and disposable smoke.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml` as the
  sole release-candidate audit before evidence-based cleanup.
