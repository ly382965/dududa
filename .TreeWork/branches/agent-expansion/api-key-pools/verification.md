# Verification

Branch: api-key-pools

## Passing Evidence

- `cd apps/web && npm test`: 21 frontend files / 89 tests and 12 server files /
  99 tests passed. The focused store/routes/probe subset passed 35 tests.
- `cd apps/web && npm run typecheck`: Vue and server TypeScript checks passed.
- `cd apps/web && npm run build`: production client and Node server bundles
  built; only the pre-existing large-chunk warning remains.
- `cd apps/web && npm run test:e2e`: 7 Chromium scenarios passed, including the
  default browser adapter loading all three pools.
- `uv run --locked python -m unittest tests.contracts.test_api_key_pools
  tests.test_operations_hardening -v`: 13 tests passed.
- `uv run --locked python ops/cli/check_secrets.py`: repository safety check
  passed across 1,232 files.
- Shell syntax, rendered Compose plus `compose-contract`, lock checks,
  `git diff --check`, focused Ruff and final independent frontend/server/release
  reviews passed.
- `npm audit --omit=dev --audit-level=high` exited successfully; it reported the
  repository's existing moderate TipTap advisory and no high-severity finding.

## Known Baseline / Evidence Boundary

`uv run --locked python -m dududa.evaluation.suite check evals/suite-v1.json
--profile ci-python ...` produced a failed low-sensitivity receipt before test
execution because discovery imports the optional private-corpus module while
the default environment does not install `joblib`. The same gap is already
recorded in `docs/refactor/PROGRESS.md`; it is unrelated to these API Key pool
paths. The focused Python contract and operations suites above are green.

Verification used synthetic credentials and local HTTP fixtures only. It did
not send a real Key to a Provider, restart AstrBot, mutate production Runtime
configuration, or claim that the optional controlled-reload hook is installed.
