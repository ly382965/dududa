# Verification

Branch: pr10-selective-integration

## Latest Verification

- Command: `PYTHONPATH=<five optional service src paths> .venv/bin/python -m unittest discover -s services/mcp/<service>/tests -v` for each of the five services; focused repository unittest set; `compileall`; production Ruff; `git diff --check`; JSON/Compose/secret/lock checks; five `scripts/check_mcp.py` stdio probes; `uv build` for each optional package.
- Result: Passed. The five CI-style service loops ran 14 tests total; the repository/Registry/installer/social focused set ran 38 tests. All five MCP probes completed initialize, list-tools, and the single public query. Five source distributions and wheels built. `docker compose config` and `compose-contract` passed, `check_secrets.py` reported repository safety passed, and no new generated runtime data is tracked.
- Coverage gap: The historical full repository suite still has baseline/environment failures (including joblib and stale Runtime/evaluation snapshots) reproduced before this branch. Optional services remain disabled, cache-only, and unmapped; no live freshness, production Planner call, proactive delivery, or real-group evidence is claimed.
- Recorded: 2026-09-03 in the branch worktree; branch is ready for Lead merge/push, not yet merged or pushed.
