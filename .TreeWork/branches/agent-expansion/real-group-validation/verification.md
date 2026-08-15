# Verification

Branch: real-group-validation

## Latest Verification

- Command: `S23A-S23E private pipeline; 600-window Terra sample; group-isolated Student; 137,026 local predictions; localhost HTTP/boundary smoke; focused Ruff/compile/unittest/diff check`
- Result: partial
- Evidence: 1,402 files / 155,567 unique group messages / 137,026 windows;
  592 Teacher drafts + 8 request-stage reviews; 464 compiled Silver rows;
  23/6 train/test conversation groups; 137,026 Student predictions; Demo HTTP
  200 at `127.0.0.1:8766` with all private/no-send/non-production notices;
  focused unit tests 10/10 passed in 0.128 seconds, with Ruff, `py_compile`
  and `git diff --check` also passing.
- Coverage gap: no human Gold, live Dududa traffic, production Router binding,
  authorization/SecretRef packet, live Source, Projection/Output composition,
  QQ send, Memory write, Tool call, online Bandit or single-group ladder Receipt.
- Recorded: 2026-08-15
