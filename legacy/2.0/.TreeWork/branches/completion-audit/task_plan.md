# Task Plan

Branch: completion-audit
Parent: root
Title: S08-S11 Completion Audit

## Scope (owned work and boundary; not progress notes or implementation history)

- Audit every accepted S08-S11 success criterion against current code, tests
  and branch verification evidence.
- Re-run cross-stage Python, import, compile, security, shell, Compose and
  affected plugin/image gates.
- Synchronize project requirements and Chinese progress/audit documentation.
- Preserve the unauthorized real-group run as an explicit external gate.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] S08/S09 deterministic selection and S10/S11 Runtime/rollout requirements
      each have direct file and verification evidence.
- [x] Bandit, learned/random route selection and user-controlled Tier authority
      are absent from executable S08-S11 paths.
- [x] Full Python 3.10/3.12 suites and all repository safety/release gates pass.
- [x] S08-S11 commits contain no WebUI/Sub2API paths and the control workspace's
      unrelated dirty changes remain untouched.
- [x] Root requirements, project plan and Chinese progress documents match the
      implementation rather than the pre-S08 baseline.
- [x] Real QQ evidence is either authorized and recorded or remains explicitly
      unchecked with the exact authority/credential gap.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Build a requirement-to-code/test evidence matrix from current files.
- [x] Run cross-stage dual-version and repository verification.
- [x] Run affected AstrBot plugin/image smoke where the local environment
      supports it; record host-only gaps precisely.
- [x] Update project and operator documentation without changing Runtime logic.
- [x] Record findings/verification, commit, complete this audit branch and
      return the precise project completion status.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- New Runtime behavior, Provider tuning, Bandit, Tool/Memory integration,
  WebUI/Sub2API or unapproved external sends.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Completed and verified S08 selection contracts/static Router.
2. Completed and verified S09 Perception/Complexity/TierPolicy.
3. Completed and verified S10 Offline Runtime and S11 Controlled Rollout.
4. Real-group evidence requires explicit user authority, credentials, approved
   group IDs and a send window; none are available in this workspace.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Accepted S08-S11 Specs, branch verification, current implementation,
  repository gates and Chinese progress documents.
- Reuse check: The accepted Tree already owns the final cross-stage audit here;
  no additional branch is required.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
