# References

## Local Authoritative Design

- `docs/refactor/implementation-plan.md`: S08-S11 scope, order and gates.
- `docs/refactor/PROGRESS.md`: S01-S07 implementation reality and residual
  boundaries.
- `docs/design/model-routing.md`: Provider, endpoint, privacy, snapshot and
  fallback contracts.
- `docs/design/perception-and-social.md`: perception, social decision and Eval
  boundaries.
- `docs/design/runtime.md`: state, orchestration, delivery and rollout
  contracts.
- `docs/design/security.md` and `docs/design/persona.md`: deterministic safety,
  budget and rendering invariants.

## External Design Evidence Reviewed 2026-08-03

- LiteLLM `de706a3`: pre-call candidate filters, cooldown, retry and bounded
  fallback; dynamic shuffle/latency/cost routing is not adopted in S08.
- Portkey Gateway `669825c`: error-triggered retry/fallback and Retry-After
  behavior; recursive policy trees are not adopted.
- TensorZero `62eb8f6`: Provider/variant separation, retry/fallback layering and
  reproducible observability.
- RouteLLM `0b64fda` and Semantic Router `ec1dec7`: learned/semantic routing
  requires representative data and remains outside S08-S11.
- Envoy AI Gateway `3fc0f4f` and AIBrix `c54565d`: gateway and self-hosted
  cluster patterns inform future infrastructure, not this single-runtime Core.
- OpenAI current model guidance confirms `gpt-5.6-luna`, `gpt-5.6-terra`, and
  `gpt-5.6-sol`, their context limits, and that reasoning mode/effort are
  independent of Dududa's logical tiers.

## Evidence (external or project sources that materially informed requirements or Spec; not an undigested link dump)

-
