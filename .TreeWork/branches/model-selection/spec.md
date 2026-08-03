# Model Selection Epic Spec

## Purpose

Treat difficulty assessment and model routing as one coherent selection
pipeline while preserving separate semantic, policy, and infrastructure
boundaries.

## Shared Direction

The bootstrap perception call is always `ModelRole.PERCEPTION` with an allowed
`ModelTier.HAIKU` route. Perception produces validated task evidence. Runtime
projects that evidence into a model-owned `TierSelectionContext`; a
deterministic policy produces `TierDecision`; the static Router selects and
invokes a physical endpoint for the downstream role.

No child branch may introduce a reverse import between perception and model
modules, accept a user-supplied tier as authority, infer capability from model
names, or add Bandit/random selection.

## Shared Ownership

- Shared task evidence belongs in framework-neutral domain contracts.
- Model roles, tiers, endpoint descriptors, Provider requests/responses,
  routing policies and receipts belong in `dududa.models`.
- Perception results, rule/model merger and social decisions belong in
  `dududa.perception`.
- Cross-module projection and orchestration belong in `dududa.runtime`.
- AstrBot or Provider-native payload mapping belongs only in plugin/infrastructure
  adapters.

## Shared Acceptance

- Fixed request and snapshots produce byte-for-byte equivalent decision
  receipts.
- Every model call is bounded by privacy, deadline, budget and atomic capacity.
- Provider-specific reasoning settings cannot be silently ignored.
- Invalid structured semantic output is rejected as a whole.
- The complete selection path records stable revisions and reason codes without
  raw messages, prompts or hidden reasoning.
