# Findings

Branch: selection-contracts

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- A normal `TierDecision` cannot authorize bootstrap Perception because no
  assessment exists yet. `BootstrapTierDecision` is closed to
  `PERCEPTION + HAIKU`, and the shared validator enforces the call boundary.
- Native JSON-object/Schema support is an Endpoint capability, while mandatory
  Core Schema validation is a role-policy requirement. Conflating them would
  exclude the real AstrBot compatible Adapter.
- `TierSelectionContext` embeds the immutable assessment. Duplicating its
  fields or accepting a free signal count allowed the same digest to be paired
  with conflicting upgrade evidence.
- Stable selection fingerprints exclude correlation IDs, timestamps and
  latency; full receipt digests retain those facts. Both are required for
  replay and audit.
- `generated_tokens` already includes its optional reasoning-token subset.
  Adding reasoning again would double-charge Context, TPM and Runtime budgets.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added `dududa.domain.task`, `dududa.models`, and `dududa.ports.models` public
  surfaces plus lazy exports that remain import-order safe on Python 3.10.
- `ModelRouter.invoke()` accepts an explicit tier authority. Provider and Router
  terminal failures carry sanitized `ModelFailureKind` and route receipts.
- Endpoint identity is `provider_id + endpoint_id`; Provider-native `model_id`
  may repeat. Shared quota pools require one traffic-policy revision.
- `ModelInvocationEstimator` estimates full request Context and cost before
  atomic admission. Admission binds request, estimate, descriptor, traffic and
  operational snapshot digests.
- Runtime `RouteHint` now includes schema version and optional Endpoint ID but
  has no Tier authority.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Provider-native token/accounting fields differ; the Adapter conformance suite
  must prove normalization into `generated_tokens` and sanitized failures.
- Fingerprint fields are validated structurally here; the static Router must
  recompute them rather than trust caller-supplied digest text.
- Real AstrBot capability discovery may expose only prompt-only JSON support;
  the strict Core codec remains mandatory for Perception.
