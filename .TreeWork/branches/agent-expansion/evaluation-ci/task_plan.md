# Task Plan

Branch: evaluation-ci
Parent: agent-expansion
Title: S18 Evaluation And CI

## Scope (owned work and boundary; not progress notes or implementation history)

- Add a versioned repository Eval suite catalog and a fixed runner Registry
  that adapts the existing committed bundles and bounded Contract suites.
- Add a low-sensitivity, digest-bound execution receipt and focused/CI profiles.
- Complete the existing Runtime phase Trace path without changing Runtime
  decisions, authority or side effects.
- Make clean dual-Python CI provision and test the isolated MCP v2 worker, run
  the suite entry, validate rendered Compose and keep package/Web/secret gates
  reproducible.
- Record honest evidence boundaries and hand complete release-candidate testing
  to S19.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] `evals/suite-v1.json` is strict, versioned, covers every required S18
  dimension and can invoke only fixed registered runners.
- [ ] One CLI validates committed bundle drift and bounded Contract evidence,
  emits an atomic low-sensitivity receipt and returns non-zero on a failed gate.
- [ ] The receipt preserves technical versus external-quality status and
  contains no fixture text, command, absolute path, environment value,
  credential or real identifier field.
- [ ] Runtime checkpoints record append-only sanitized phase Trace events and
  final summaries project the recorded path; synthetic privacy and failure
  tests pass.
- [ ] Clean CI provisions root and worker locks for Python 3.10/3.12, executes
  worker-local tests, the suite profile, import/package checks, rendered Compose
  contract, repository secret scan and existing Web gates.
- [ ] Focused S18 checks pass on Python 3.10/3.12; full image/container, Web and
  repository release-candidate evidence remains accurately assigned to S19.
- [ ] Branch Progress, Findings and Verification describe actual evidence and
  external gaps without claiming real quality or production readiness.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Implement strict catalog/Registry, runner result adapters and receipt CLI.
- [ ] Add sanitized Runtime phase events and path summary projection.
- [ ] Add focused catalog, receipt, Trace and CI contract tests.
- [ ] Repair worker bootstrap/testing, rendered Compose validation and Node
  image version in CI/deployment inputs.
- [ ] Run risk-based Python 3.10/3.12 samples and static workflow checks.
- [ ] Synchronize S18 branch/project documents, commit, verify and return.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- New domain evaluator algorithms or a replacement for existing Eval reports.
- Human Chinese/Persona calibration, real Provider/source/MCP/QQ traffic or
  production Trace storage.
- Bandit decisions, propensity, OPE or estimator goldens (S20).
- Full release-candidate image/container/Web/fault audit (S19).
- Legacy compatibility deletion (S22) or any real send (S23).

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. S17 is complete, verified and integrated at the branch base.
2. Existing S09, Semantic v2, Memory and Response Profile bundles remain the
   domain authorities and must be adapted rather than rewritten.
3. The isolated worker lock is present; no external credentials or data are
   required.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: existing `dududa.evaluation` APIs, committed `evals/` bundles,
  Runtime Trace contracts, root/worker locks, CI and S16 Compose validator.
- Reuse check: no existing unified suite receipt exists; reuse all domain
  checkers, Unit/Contract suites, operations validator and CI jobs.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
