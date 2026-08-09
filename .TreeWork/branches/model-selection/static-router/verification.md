# Verification

Branch: static-router

## Latest Verification

- Command: Python 3.12 and Python 3.10 S08 focused `unittest` matrix covering
  contracts, policy, registries, estimation, admission, Router, Codec,
  Recording Fake and AstrBot Adapter.
- Result: passed on both interpreters, 96 tests each.
- Coverage gap: none for the S08-owned Python surface.
- Recorded: 2026-08-03 Asia/Shanghai.

- Command: `python -m unittest discover -s tests -q` with repository
  `PYTHONPATH`, repeated in Python 3.12 and the clean Python 3.10.20 venv.
- Result: passed on both interpreters, 198 tests each, with the same two
  AstrBot-host-only tests skipped locally.
- Coverage gap: local interpreters do not install AstrBot; the derived-image
  run below resolves those skips.
- Recorded: 2026-08-03 Asia/Shanghai.

- Command: Router/Adapter suites with `PYTHONASYNCIODEBUG=1` and
  `PYTHONWARNINGS=error` plus adversarial double-cancel, stubborn Provider,
  malformed response/error/getter/watcher and deadline-race fixtures.
- Result: passed; no pending-task or unawaited-coroutine warning, no leaked
  waiter/lease, and unknown outcomes produced exactly one ceiling settlement.
- Coverage gap: none for in-process cancellation and cleanup semantics.
- Recorded: 2026-08-03 Asia/Shanghai.

- Command: branch-owned Ruff check and format check over 29 files.
- Result: passed, 29 files formatted. Full-repository Ruff still reports five
  pre-existing findings in four files proven unchanged from `HEAD`:
  `adapters/message.py` F401, `commands/course.py` F821, `main.py` two F401s,
  and `services/icourse-mcp/run_icourse_mcp.py` E402.
- Coverage gap: unrelated baseline findings are not S08 regressions.
- Recorded: 2026-08-03 Asia/Shanghai.

- Command: `compileall`; repository secret scanner; Compose parse; Bash/POSIX
  shell syntax; memory migration `--help`; `git diff --check`.
- Result: all passed. Secret scanner covered 290 tracked and untracked files;
  Compose resolved `astrbot` and `napcat`.
- Coverage gap: local `gitleaks` is unavailable; the configured GitHub
  `secrets` job remains required after push.
- Recorded: 2026-08-03 Asia/Shanghai.

- Command: build `docker/astrbot/Dockerfile`, then run
  `tests.test_dududa_core_plugin_split` inside the derived image with the plugin
  mounted on `PYTHONPATH`.
- Result: image `dududa/astrbot:s08-static-router` built with digest
  `sha256:8b22114ca48a7486b9230084ac83e173bc5f319f93b07149e23c3a6ec64aebcb`;
  all 6 AstrBot-host tests passed.
- Coverage gap: pinned real OpenAI/Anthropic Provider bindings deliberately
  remain disabled because they cannot prove output-limit, single-request,
  downstream deadline/cancellation and logging guarantees.
- Recorded: 2026-08-03 Asia/Shanghai.
