# Verification

Branch: real-group-validation

## Latest Verification

- Command: `uv run python -m unittest -q tests.contracts.test_production_composition.ProductionCompositionContractTests.test_builder_accepts_private_provider_evidence_file tests.contracts.test_production_composition.ProductionCompositionContractTests.test_builder_rejects_mismatched_private_provider_evidence tests.contracts.test_production_composition.ProductionCompositionContractTests.test_shadow_uses_endpoint_fixed_reasoning_after_healthy_evidence tests.contracts.test_production_composition.ProductionCompositionContractTests.test_shadow_stops_calling_provider_after_health_ttl`
- Result: partial; 4 focused tests passed in 0.245 seconds.
- Evidence: repository-external Evidence matching assembles the Builder;
  Provider/model mismatch is rejected; valid descriptor-bound health changes
  `UNKNOWN -> HEALTHY` and permits one Fake Shadow Provider call; advancing the
  fake clock beyond the health TTL changes it back to `UNKNOWN` and prevents a
  further Provider call.
- Evidence boundary: these are Fake Provider and fixed private-file fixture
  tests. They do not prove real AstrBot Provider Conformance, a continuous
  health collector, candidate deployment, live single-group Shadow or QQ send.
- Verification remains `partial`; S23 remains `paused`.
- Recorded: 2026-08-15

- Command: `uv run python -m unittest tests.contracts.test_astrbot_model_provider tests.contracts.test_production_composition`
- Result: partial; 34 focused tests passed in 0.719 seconds.
- Evidence: Adapter passes request-level `max_tokens`; fixed Endpoint reasoning
  maps OFF/LIGHT/BALANCED/DEEP/MAXIMUM to omitted/low/medium/high/xhigh; Builder
  requires resolved Provider binding evidence; initial health is `UNKNOWN`.
- Candidate-image sample: fixed AstrBot 4.26.2 patch applied to the pinned base;
  an isolated `--network none` payload sample retained `max_tokens=321` and
  `reasoning_effort=high` while dropping an unapproved plugin kwarg. The running
  container was not replaced.

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
- Command: private minimal Responses API and Chat Completions probes; the
  credential-bearing invocation, API key and private Base URL are intentionally
  not recorded.
- Result: partial. Responses returned HTTP 200 for Luna/Terra/Sol in
  2.212/2.816/2.698 seconds with exact model IDs, text and usage. Chat
  Completions returned HTTP 200 for both ordinary and `reasoning_effort=low`
  requests on all three models, with exact model IDs and usage at roughly
  2.2--2.3 seconds.
- Evidence boundary: the probes prove one-shot protocol reachability only. The
  candidate path now carries output/reasoning parameters, but the models are not
  registered in the running AstrBot and no refreshable health or real AstrBot
  Provider Conformance evidence exists. Only `low` was remotely sampled.
- Coverage gap: no human Gold, live Dududa traffic, real Endpoint Conformance or
  health, container deployment and Release binding, live campus/arXiv/industry
  Source, production Projection/Output composition, QQ send, online Bandit or
  single-group ladder Receipt. S23 therefore remains `paused/partial`.
- Recorded: 2026-08-15
