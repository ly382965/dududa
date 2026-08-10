# Verification

Branch: layout-migration

## Latest Verification

- Command: Python 3.10.20 and 3.12.13 each ran `tests.test_install_plugins`,
  `tests.test_repository_contract`, `tests.test_operations_hardening`,
  `tests.test_runtime_sync` and `tests.test_rollout_rollback` with warnings as
  errors; each interpreter passed 18 tests.
- Command: the root environment ran Unified MCP worker, iCourse lifecycle and
  facade contracts after `uv sync --project services/mcp/unified-worker
  --locked`; 13 tests passed. The plugin split sample passed five tests with two
  expected AstrBot-host-only skips.
- Command: build/install/import/pip-check the `dududa-agent` wheel in a temporary
  Python 3.12 environment; compile canonical Python roots; compare root and
  canonical Compose JSON; check root/ops Shell, `uv lock --check`, canonical
  symlinks, Ruff/format for the marker fix, secrets and whitespace.
- Result: passed. The wheel is `dududa-agent==0.1.0a1`; Compose documents are
  byte-equivalent after rendering; the safety scan passed 812 files; no worker
  or Fake MCP process remained.
- Coverage gap: Web behavior was unchanged and is deferred to S19. No running
  container, real data, credential, network source, Provider or QQ send was
  used. Manifest v2 and production rollback evidence remain later gates. S18
  must automate the isolated worker `uv sync` before repository tests in clean
  CI; S17 performed that preparation explicitly.
- Recorded: 2026-08-10.
