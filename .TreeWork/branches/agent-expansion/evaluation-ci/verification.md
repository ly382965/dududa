# Verification

Branch: evaluation-ci

## Latest Verification

- Command: `Python 3.10/3.12 S18 focused profiles; clean committed-bundles receipt; catalog tamper and opaque run-ID tests; package, worker, Node 22, rendered Compose, secret and static checks`
- Result: passed
- Coverage gap: Full dual-Python repository, Web/E2E, image/disposable-container, broad fault, SLO and rollback candidate audit remain S19; no real Provider/source/QQ or human-quality claim
- Recorded: unix:1786370831

## Supporting Evidence

- Clean `4cd9ddc` Python 3.12 `committed-bundles` replay passed four suites with
  `source_dirty=false`, generated `eval-<uuid>` identity and a `0600` receipt;
  digest `dududa-c14n-v1:eval:suite-receipt:v1:sha-256:e7d892f95d74ca649d76d07540a131d8fe8cb94b47737c55439d3699d18f7c68`.
- Python 3.12 `s18-focused` passed four committed bundles (350 synthetic cases)
  plus five focused Contract suites (146 cases). Python 3.10 replayed all four
  bundles and passed 30 affected receipt/Trace/Runtime/Delivery tests.
- Catalog revision, quality claim, external-gate and profile-membership
  tampering fail before execution. The CLI has no caller-supplied run-ID path;
  the final clean HEAD passed seven catalog/receipt/Trace tests.
- Root Unified MCP worker Contracts passed 11 cases; the isolated worker passed
  two no-network tests. Both uv locks, changed Ruff/format/compile, wheel clean
  install/import/pip check, Node 22 typecheck/build, rendered Compose contract,
  YAML/Shell, secret scan over 817 files and whitespace checks passed.
- All four committed quality reports retain `release_ready=false`. No remote
  GitHub Actions, real Provider/source/user data, human-quality or QQ evidence
  is claimed.
