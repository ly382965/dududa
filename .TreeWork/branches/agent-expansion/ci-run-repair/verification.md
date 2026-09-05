# Verification

Branch: ci-run-repair

## Latest Verification

- Commands: original ci-python profile from an installed wheel; committed-bundles
  profile on 3.10/3.12; optional MCP and isolated worker tests on both versions;
  lock checks, pip check, compileall, shell checks, Compose contract and secrets.
- Result: Python 3.10 and 3.12 each ran 983 tests OK (2 pre-existing host-only
  skips); all four committed bundles pass on both versions. Timestamp-parser
  regression assertions pass with 3/3 replay tests on both versions.
  Other focused sets passed 23, 30 and 5 tests. All operation checks passed.
- Remote run 33941400500: Web, offline-eval and secrets passed; both Python
  jobs failed release-audit checks because default checkout omitted HEAD^.
  Fresh depth-one clone reproduced both errors; depth-two clone passes all
  five unchanged audit tests on Python 3.10 and 3.12.
- Coverage gap: GitHub workflow confirmation after checkout-depth correction.
- Recorded: 2026-09-05.
