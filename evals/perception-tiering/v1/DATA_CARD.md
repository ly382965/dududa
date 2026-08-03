# S09 Synthetic Eval Data Card

Status: generated, synthetic-only, agent-reviewed pending human confirmation.

- Bundle: `s09-perception-tiering-eval-v1`
- Templates / independent clusters: 32
- Cases: 320
- Unique texts: 300
- Material execution profiles: 320
- Development: 80
- Held-out test: 240
- Label basis: `policy_gold`
- Real chat data: none
- Network calls: forbidden

These labels verify deterministic policy behavior. They do not establish that a
real Haiku, Sonnet or Opus endpoint meets a minimum task-quality threshold.
`empirical_frozen_quality` requires a separate blinded, same-task per-tier
evaluation against a frozen rubric.

Template lineage is the split unit. Variants from one template never cross the
development/test boundary. The 10 variants are correlated samples and never
inflate the binomial denominator: risk bounds use applicable template-family
clusters. Those bounds are nominal diagnostics under an independent Bernoulli
cluster assumption; designed synthetic templates are not a random real-traffic
sample. The current general redactor is not accepted as proof that real QQ chat
is de-identified, so no sanitized-real provenance is claimed here.
