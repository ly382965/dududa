# Findings

Branch: evaluation-ci

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- A thin catalog/adapter is sufficient. The four domain evaluators keep their
  heterogeneous metrics and reports; Unit/Contract evidence is explicitly not
  promoted into a dataset-quality claim.
- The suite manifest may select only fixed code Registry entries. Arbitrary
  callables, paths, environment values and Shell commands are not an
  extensibility mechanism.
- Binding only runner kind and dimensions was insufficient because a catalog
  could still weaken quality claims, external gates or profile membership. The
  complete canonical catalog digest is now code-bound, so any such change
  requires a reviewed code-and-catalog update.
- Receipt correlation is generated internally as `eval-<uuid>`. The CLI no
  longer accepts a caller-supplied run ID that could persist a real QQ/group ID
  or token-like value.
- Runtime Trace was previously a dormant contract: `TraceEvent` had no
  construction site and final summaries contained only one phase. S18 filled
  that existing contract instead of adding another tracing framework.
- Full image/container and repository release evidence belongs in S19. S18 CI
  prepares reproducible gates and branch-local verification remains risk based.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- New command: `python -m dududa.evaluation.suite check evals/suite-v1.json
  --profile <profile> --receipt <path>`.
- `RuntimeState.trace` is now populated for orchestrated runs. Trace v1 accepts
  only `runtime.phase.entered`, a sequence attribute, safe reason codes and
  public sensitivity; event identity is canonical-digest bound.
- `TraceSummary.phases` now contains the actual phase path. Legacy states with
  an empty trace remain readable and continue to project the requested final
  phase.
- Clean CI must synchronize and test `services/mcp/unified-worker` separately
  because it is intentionally excluded from the root uv workspace.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- `jsonschema` remains a development-only optional import used only when the
  Semantic bundle runner executes; normal package import stays standard-library
  and internal-only.
- The GitHub workflow has not itself run on a remote runner in this local-only
  branch. Its exact commands, locks, YAML, package, Compose and affected tests
  passed locally; S19 supplies the complete release-candidate execution.
- The Web Docker base tag was aligned to Node 22 and local build passed, but the
  image itself was deliberately not built until S19.
- Eval receipts are low sensitivity, not anonymous production telemetry. Their
  internal run/source correlation must still follow a future retention policy.
- A legitimate suite metadata or profile update must deliberately update the
  code-bound catalog digest and its tamper tests; editing JSON alone fails.
