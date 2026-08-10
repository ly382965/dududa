# Verification

Branch: evaluation-ci

## Latest Verification

- Command: clean `4cd9ddc` Python 3.12 `committed-bundles` profile.
- Result: four bundles passed with `source_dirty=false`, generated opaque
  `eval-<uuid>` run identity and `0600` receipt; receipt digest
  `dududa-c14n-v1:eval:suite-receipt:v1:sha-256:e7d892f95d74ca649d76d07540a131d8fe8cb94b47737c55439d3699d18f7c68`.
- Command: `tests.unit.evaluation.test_suite` plus Runtime Trace tests, changed
  Ruff/format and `git diff --check` after catalog/receipt hardening.
- Result: seven tests passed; catalog revision, quality claim, external-gate and
  profile shrink tampering all failed before execution, and no caller-provided
  run-ID path remains.
- Command: Python 3.12 `s18-focused` suite profile.
- Result: passed four committed bundles (350 synthetic cases) and five focused
  Contract suites (146 cases); receipt digest
  `dududa-c14n-v1:eval:suite-receipt:v1:sha-256:6df0c8ca996212508fe5856305659df1b4dc7e649f95201ff11cea167debc67b`.
- Command: clean `5be566a` Python 3.12 `committed-bundles` profile.
- Result: passed with `source_dirty=false`; receipt digest
  `dududa-c14n-v1:eval:suite-receipt:v1:sha-256:0524346026425e1d3bf94dbfdb8232169fb8075e4cbcc143fa96de001d950115`;
  every suite retained `release_ready=false`.
- Command: Python 3.10 committed bundles plus affected receipt/Trace/Runtime/
  Delivery/repository contracts.
- Result: four bundles and 30 tests passed.
- Command: root Unified MCP worker Contract and isolated worker-local tests.
- Result: 11 root cases and two no-network worker cases passed.
- Command: changed-code Ruff/compile, wheel build/clean install/import/pip check,
  Node 22 typecheck/build, both uv lock checks, rendered Compose contract, YAML
  parse, shell syntax, secret scan and `git diff --check`.
- Result: passed; secret scan covered 817 files. Node reported the existing
  large-chunk/deprecated `glob@10` warnings but `npm audit` found zero
  vulnerabilities.
- Coverage gap: the complete dual-Python repository run, Web Unit/E2E, image/
  disposable-container smoke, full fault injection and release rollback/SLO
  audit are intentionally deferred to S19. No remote GitHub Actions run, real
  Provider/source/user data, human quality or QQ evidence is claimed.
- Recorded: 2026-08-10, implementation commit `5be566a`.
