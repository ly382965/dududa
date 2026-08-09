# Verification

Branch: selection-contracts

## Latest Verification

- Command: `full unittest + CPython 3.10 focused + Ruff + format + compileall + diff check + forbidden dependency scan`
- Result: passed
- Coverage gap: Execution implementations are intentionally owned by static-router; two AstrBot-host-only tests skipped.
- Recorded: unix:1785760129

## Supporting Evidence

- Full repository: `PYTHONPATH=packages/dududa-agent/src:services/icourse-mcp/src python3 -m unittest discover -s tests` -> 124 passed, two AstrBot-host-only skips.
- Python 3.10.20: focused Domain/Model/Port/import suite -> 27 passed.
- Changed Python files: Ruff check passed and all 18 files were formatted.
- `compileall` passed for Core and changed tests; `git diff --check` passed.
- Forbidden dependency scan found no Bandit/LinUCB/Thompson/propensity or
  OpenAI/Anthropic SDK references in the new Core/model surface.
