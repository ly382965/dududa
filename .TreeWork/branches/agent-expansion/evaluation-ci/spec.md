# Branch Spec

Branch: evaluation-ci
Parent: agent-expansion

## Development Design

### Purpose And Evidence Boundary

S18 turns the repository's existing offline Evals, contracts, Runtime Trace and
CI checks into one reproducible evidence surface. It does not replace the
domain-specific evaluators, invent human-quality claims, enable a Provider,
read user data or create a second Runtime control plane. The committed S09,
Semantic v2, Memory and Response Profile bundles remain authoritative for their
own metrics; other modules remain explicitly classified as Unit/Contract
evidence until they gain a real versioned dataset and report.

Fixture inputs are limited to synthetic identifiers and synthetic or public
text. `technical_pass` means that the declared offline contract passed. It does
not rewrite `release_ready=false`, `human_review_complete=false` or an external
quality gate into a stronger claim.

### Versioned Suite Catalog

`evals/suite-v1.json` is a declarative catalog, not executable plugin code. It
records stable suite IDs, evidence kind, revision, covered dimensions, quality
claim and external gates. A fixed code Registry maps approved runner IDs to
existing checker functions or bounded `unittest` selectors. The catalog cannot
name arbitrary Python callables, shell commands, paths or environment values.

The suite covers these evidence dimensions without forcing one report schema
onto every domain:

- reply/target decisions, semantic intent/entity/reference and static routing;
- Answer Profile and deterministic Persona mechanics;
- MCP lifecycle, Capability retrieval/planning/arguments/result validation;
- Memory lifecycle, Scope isolation and M0-M2 retrieval;
- Scheduler/subscription, Source freshness/provenance/deduplication,
  Digest Shadow and Probe Shadow;
- Runtime phase Trace, Shadow privacy and import boundaries.

Committed bundles return their existing report and input digests. Contract
suites return only test counts and a digest of bounded result metadata. The
runner has focused and CI profiles, but both resolve only cataloged fixed
runners. Bandit/OPE is absent and remains owned by S20.

### Low-Sensitivity Execution Receipt

`python -m dududa.evaluation.suite check evals/suite-v1.json` validates the
whole catalog before execution, runs one selected profile and atomically writes
a versioned receipt. The receipt contains only:

- synthetic run ID, UTC timestamps, source revision/dirty bit, Python version,
  catalog/profile digests;
- suite ID/revision, evidence kind, status, case count, bounded reason code,
  input/report digest, quality claim and declared external gates;
- a final receipt digest.

It never stores fixture text, prompts, model output, QQ/user/group identifiers,
credentials, environment variables, command lines, absolute paths, hostnames
or exception text. A failed suite still produces a receipt and exits non-zero;
later suites are not presented as executed. Receipt output lives in ignored or
temporary storage and is not a new production telemetry sink.

### Runtime Trace Completion

The existing `TraceEvent` and append-only `RuntimeState.trace` contract is kept.
The orchestrator now creates one initial `RECEIVED` event and appends one event
for every committed phase transition; delivery acknowledgement transitions use
their injected timestamps. Events contain only internal run/trace correlation,
phase, bounded reason codes, sequence, timestamp and a deterministic event
digest. They contain no message body, actor/scope object, model content,
Capability payload or delivery body.

`TraceSummary.phases` projects the actual recorded path plus the pending
terminal phase instead of reporting only the final phase. Existing identity,
Scope, permission, budget, state transition and Output authority remain
unchanged. The branch proves privacy with synthetic secret-bearing inputs and
append-only transition tests; it does not add a production Trace backend.

### CI Shape

The Python 3.10/3.12 job provisions both locked environments because the root
workspace intentionally excludes `services/mcp/unified-worker`. It runs the
versioned suite profile, worker-local tests, wheel/import, compile and repository
checks. The repository job renders the real Compose model and passes it to the
existing deterministic Compose contract validator instead of validating a
handwritten projection only. Web's Docker base matches the locked Node 22
toolchain.

The existing Web Unit/Contract/build/E2E job and secret history scan remain.
Full dual-Python repository reruns, image builds, disposable-container smoke,
complete fault injection and full Web reruns are release-candidate evidence
owned by S19; S18 prepares reproducible commands and runs focused branch
samples rather than duplicating that audit locally.

### Failure And Rollback

- Unknown catalog fields, runner IDs, profiles, dimensions, duplicate IDs,
  unsafe data policy or missing coverage fail before running a suite.
- Bundle drift, non-technical pass, Contract failure, worker bootstrap failure,
  Trace mutation or receipt write failure fails closed.
- CI and the runner never delete a safety test to restore green status.
- Rollback removes the suite catalog/runner and phase-event emission, restores
  the previous CI commands and leaves every domain Eval bundle unchanged.

### Honest Deferred Claims

S18 does not establish real Chinese/Persona quality, empirical minimum model
tier, production Memory quality, live source quality, real MCP/Provider
conformance, production Trace retention, image/container health, online Bandit
learning or real QQ behavior. Those remain explicit S19/S20/S23 or external
gates.
