# Verification

Branch: layout-migration

## Latest Verification

- Command: `S17 dual-Python focused tests, isolated MCP worker contracts,
  wheel/build/import, canonical Compose equivalence, shell, lock, secret and
  path contracts`.
- Detailed evidence: Python 3.10.20 and 3.12.13 each passed 18 representative
  layout/operations/rollback tests with warnings as errors. The isolated MCP
  worker, iCourse lifecycle and facade set passed 13 tests after an explicit
  locked worker sync. Plugin split passed five tests with two expected
  AstrBot-host-only skips.
- Detailed evidence: `dududa-agent==0.1.0a1` built as sdist/wheel and passed a
  clean wheel install/import/`py.typed`/pip check. Canonical compileall,
  root/canonical Compose JSON equality, uv locks, Shell syntax, Ruff/format,
  symlink/index contracts, 812-file secret scan and whitespace passed. No
  worker or Fake MCP process remained.
- Result: passed.
- Coverage gap: Web and real-container behavior were unchanged and remain S19
  gates. Manifest v2, production rollback, real data, credentials, network
  sources, Providers and QQ sends were not exercised. S18 must automate the
  isolated worker sync in clean CI.
- Recorded: unix:1786365897.
