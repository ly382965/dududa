# Verification

Branch: ci-run-repair

## Latest Verification

- Command: `Local Python 3.10.20 and 3.12.13: 983 tests each; GitHub Actions run 33941956099 at 93ef466: all five jobs passed`
- Result: passed
- Coverage gap: None for scoped CI repair; production deployment excluded
- Recorded: unix:1788579498

## Evidence

- Passing workflow: https://github.com/ly382965/dududa/actions/runs/33941956099
  at 93ef466. Both Python jobs, Web, offline-eval and secrets passed.
- Installed-wheel repository command on both supported interpreters:
  `python -m dududa.evaluation.suite check evals/suite-v1.json --profile ci-python --receipt <temporary-path>`.
  Python 3.10.20: 983 tests in 536.055 seconds, OK (skipped=2).
  Python 3.12.13: 983 tests in 570.923 seconds, OK (skipped=2).
- All four committed bundles, optional MCP and isolated worker tests passed
  on both versions; package, lock, Compose, shell and secret checks passed.
- Fresh depth-one clone reproduces the two release-audit HEAD^ errors;
  fetching depth two passes all five unchanged audit tests on both versions.
- The two host-only skips already existed. No tests or jobs were disabled,
  assertions weakened, or continue-on-error introduced.
- Commits following 93ef466 contain only TreeWork completion documentation
  and state. Production deployment and legacy services were not changed.
