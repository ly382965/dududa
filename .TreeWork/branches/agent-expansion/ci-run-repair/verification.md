# Verification

Branch: ci-run-repair

## Latest Verification

- Commands: original ci-python profile from an installed wheel; committed-bundles
  profile on 3.10/3.12; optional MCP and isolated worker tests on both versions;
  lock checks, pip check, compileall, shell checks, Compose contract and secrets.
- Result: Python 3.10 and 3.12 each ran 983 tests OK (2 pre-existing host-only
  skips); all four committed bundles pass on both versions. Timestamp-parser
  regression assertions pass with 3/3 replay tests on both versions.
  Other focused sets passed 23, 30 and 5 tests. All operation checks passed.
- Remote run 33941400500: Web, offline-eval and secrets passed; both Python
  jobs failed release-audit checks because default checkout omitted HEAD^.
  Fresh depth-one clone reproduced both errors; depth-two clone passes all
  five unchanged audit tests on Python 3.10 and 3.12.
- Remote run 33941956099 at 93ef466: all five jobs passed (Python 3.10.20,
  Python 3.12.13, Web, offline-eval and secrets).
- Coverage gap: none for CI repair; production deployment is not in scope.
- Recorded: 2026-09-05.

## Reproduction And Verification Evidence

- Original failing run: https://github.com/ly382965/dududa/actions/runs/33897997167
- First integrated repair: 9ef9c70; follow-up run 33941400500 isolated the
  remaining shallow-checkout issue in both Python jobs.
- Checkout correction integrated at 93ef466; verification run:
  https://github.com/ly382965/dududa/actions/runs/33941956099
- Local installed-wheel command on each supported interpreter:
  `python -m dududa.evaluation.suite check evals/suite-v1.json --profile ci-python --receipt <temporary-path>`.
  Python 3.10.20: 983 tests in 536.055 seconds, OK (skipped=2).
  Python 3.12.13: 983 tests in 570.923 seconds, OK (skipped=2).
- Fresh depth-one clone: unchanged release-candidate audit module reports
  exactly two errors resolving HEAD^. After `git fetch --depth 2`, the same
  five tests pass on both Python versions.
- The two host-only skips already existed; no tests or jobs were disabled,
  no equality checks were weakened, and no continue-on-error was introduced.
