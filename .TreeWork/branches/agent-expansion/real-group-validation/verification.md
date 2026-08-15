# Verification

Branch: real-group-validation

## Latest Verification

- Command: `uv run python -m unittest tests.contracts.test_production_composition tests.unit.runtime.test_perception tests.contracts.test_astrbot_rollout`
- Result: partial
- Evidence: 27 unique focused tests passed in 1.005 seconds. An earlier six-test
  smoke passed in 0.196 seconds. The tests use a Fake AstrBot Provider and prove
  zero `text_chat()` calls during construction; `off` keeps legacy ownership
  with zero Provider calls and zero sends; `shadow` performs exactly one Fake
  Provider call while legacy keeps ownership and no send occurs; disabled or
  unresolved Providers fall back to unavailable/legacy; AnswerProfile flag
  projection and rule-only Perception are wired without a second model call.
- Historical-corpus evidence remains valid: 1,402 files / 155,567 unique group
  messages / 137,026 windows; 592 Teacher drafts + 8 request-stage reviews;
  464 compiled Silver rows; 23/6 train/test conversation groups; 137,026
  Student predictions; Demo HTTP 200 at `127.0.0.1:8766` with all private,
  no-send and non-production notices.
- Coverage gap: no human Gold, live Dududa traffic, real Endpoint Conformance or
  health, container deployment and Release binding, live campus/arXiv/industry
  Source, production Projection/Output composition, QQ send, online Bandit or
  single-group ladder Receipt. S23 therefore remains `paused/partial`.
- Recorded: 2026-08-15
