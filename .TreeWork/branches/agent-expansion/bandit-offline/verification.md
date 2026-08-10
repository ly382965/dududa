# Verification

Branch: bandit-offline

## Latest Verification

- Command: `Python 3.10/3.12 focused S20; full import-boundary suite; Ruff/format/compile; wheel build/clean import/pip check; secret and whitespace checks`
- Result: verified. Python 3.10 and 3.12 each passed 16/16 S20 tests; the
  existing import-boundary suite passed 13/13. The committed four-sample bundle
  reproduced IPS `0.812500000000`, SNIPS `0.650000000000`, DR
  `0.787500000000` and ESS `3.846153846154` across normal/reverse/shuffle and
  rejected support, propensity, reward, prediction and artifact tampering.
  The wheel contains and cleanly imports `dududa.bandit`; `pip check`, Ruff,
  format, compile, 841-file secret scan and `git diff --check` passed.
- Coverage gap: intentionally no real Endpoint, user/chat data, policy
  training, production persistence, Router/Runtime hook, Shadow or live
  exploration. Those are later external gates, not missing S20 evidence.
- Recorded: 2026-08-11
