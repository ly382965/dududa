# Verification

Branch: ci-run-repair

## Latest Verification

- Commands: original ci-python profile from an installed wheel; committed-bundles
  profile on 3.10/3.12; optional MCP and isolated worker tests on both versions;
  lock checks, pip check, compileall, shell checks, Compose contract and secrets.
- Result: Python 3.12 983 tests OK (2 pre-existing host-only skips); all four
  committed bundles pass on both versions. Python 3.10 first full run had only
  one timestamp-parser failure, now fixed with 3/3 replay tests on both versions.
  Other focused sets passed 23, 30 and 5 tests. All operation checks passed.
- Coverage gap: final Python 3.10 full run and GitHub workflow confirmation.
- Recorded: 2026-09-05.
