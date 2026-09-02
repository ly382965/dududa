# Verification

Branch: pr10-selective-integration

## Latest Verification

- Command: `PR10 focused integration: 52 tests plus compile/Ruff/Compose/secret/stdio/build checks`
- Result: passed
- Coverage gap: Historical full-suite baseline failures remain; optional services have no live freshness or production Planner mapping
- Recorded: unix:1788367575

## Detailed Evidence

- The five CI-style service loops ran 14 unittest cases: campus-events 4,
  college-notice 4, library 2, local-recs 3, and training-plan 1.
- The repository/Registry/installer/social focused set ran 38 unittest cases;
  the combined pytest collection for this branch reports `52 passed`.
- `compileall`, production-scope Ruff, `git diff --check`, JSON registry
  parsing, `docker compose config`, `compose-contract`, `check_secrets.py`,
  and both root/Unified-worker `uv lock --check` checks passed.
- Each optional package built a source distribution and wheel. Each stdio
  smoke script completed initialize, list-tools, and its one public query using
  a temporary cache.
- The historical full repository suite was intentionally not used as a green
  signal: existing joblib/environment and stale Runtime/evaluation snapshot
  failures reproduce on the pre-integration control revision.
