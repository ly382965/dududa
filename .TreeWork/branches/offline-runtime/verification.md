# Verification

Branch: offline-runtime

## Latest Verification

- Command: `CPython 3.10/3.12 full unittest; -W error Runtime suites; Ruff
  0.12.7 check/format on all 42 changed Python files; compileall; import/export
  order matrix; secret scan; git diff --check`
- Result: passed; each Python version reports `325 tests, 2 skipped`; each
  warnings-as-errors Runtime suite reports `81 tests`; secret scan reports 351
  files.
- Coverage gap: two AstrBot-host-only tests remain skipped; real Provider/QQ
  delivery and group-canary evidence are deferred to S11/external runtime.
- Recorded: unix:1785812479
