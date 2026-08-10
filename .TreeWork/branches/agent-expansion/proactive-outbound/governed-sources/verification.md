# Verification

Branch: governed-sources

## Latest Verification

- Command: Python 3.10.20 and 3.12.13 full `unittest` discovery; focused S15C `-W error`;
  Ruff on all changed Python; import-boundary Contract.
- Result: each Python ran 616 tests with zero failures/errors and two existing AstrBot-only skips;
  17-test focused selection and static/import checks passed. Locked wheel build and isolated import,
  affected compile, `uv lock --check`, whitespace and the 794-file repository safety scan passed.
- Coverage gap: Web was not run because this branch changes no Web code/contract. No live source
  Adapter, live network, production source state, real content quality or real send is claimed.
- Recorded: 2026-08-10.
