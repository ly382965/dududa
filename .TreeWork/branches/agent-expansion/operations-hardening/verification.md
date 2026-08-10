# Verification

Branch: operations-hardening

## Latest Verification

- Command: `PYTHONPATH=packages/dududa-agent/src /tmp/dududa-py310/bin/python -W error -m unittest -v tests.test_operations_hardening tests.unit.proactive.test_sources.GovernedSourceProviderTests.test_running_reader_is_bounded_by_call_cancellation` and the identical Python 3.12 command; targeted Ruff/format/compile, `bash -n manage.sh`, actual `docker compose ... config --format json | dududa_ops.py compose-contract`, `git diff --check`.
- Result: verified; Python 3.10.20 and 3.12.13 each passed 5/5 representative samples, Python 3.12 passed the complete 9-test affected Source module, actual Compose contract passed, and all targeted static checks passed.
- Coverage gap: no real container start/change, HTTP/MCP/QQ/Provider probe, production data, in-place restore, encrypted/off-host backup, Web regression or full-repository test. These are S19/S23 gates; Web was not changed.
- Recorded: 2026-08-10 Asia/Shanghai.
