# S09 Perception/Tiering Eval Report

- Technical pass: `true`
- Release ready: `false`
- Synthetic cases: 320
- Unique texts: 300
- Material execution profiles: 320
- Independent template-family clusters: 32
- Label basis: `policy_gold`
- Empirical minimum-tier claim: `false`
- Order reproducible: `true`
- Hard-policy violation events: 0
- Policy under-selection: 0
- Policy-unexpected Opus: 0
- Fixture fallback cases: 30

Hard-gate statistics use applicable template-family clusters, not correlated
case variants:

  - `identical_prediction_fingerprints_across_orders`: 0 violations / 32 applicable clusters; zero-event 95% upper bound=0.089368198986
  - `no_cross_scope_reference`: 0 violations / 1 applicable clusters; zero-event 95% upper bound=0.950000000000
  - `no_out_of_scope_social_action`: 0 violations / 32 applicable clusters; zero-event 95% upper bound=0.089368198986
  - `no_private_boundary_reply`: 0 violations / 1 applicable clusters; zero-event 95% upper bound=0.950000000000
  - `no_prompt_routing_authority`: 0 violations / 1 applicable clusters; zero-event 95% upper bound=0.950000000000
  - `no_unauthorized_tool_action`: 0 violations / 3 applicable clusters; zero-event 95% upper bound=0.631596850136
  - `no_unsolicited_group_reply`: 0 violations / 1 applicable clusters; zero-event 95% upper bound=0.950000000000
  - `no_wrong_target`: 0 violations / 32 applicable clusters; zero-event 95% upper bound=0.089368198986

Latency, cost and real-model quality are not measured by this fixed-fixture
Eval. Human review is incomplete, so technical pass does not imply release
readiness. See `quality-rubric.json` and `DATA_CARD.md` for the claim boundary.
