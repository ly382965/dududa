# S08 Selection Contracts Spec

## Scope

Define the immutable, versioned contract surface required by both difficulty
assessment and static routing before execution code is written.

## Intended Files

- `dududa/domain/task.py`: task-complexity evidence shared through Runtime.
- `dududa/models/contracts.py`: roles, tiers, reasoning, capabilities, privacy,
  endpoints, traffic, requests, responses and receipts.
- `dududa/models/policy.py`: tier-selection context/decision and static policy
  definitions, without Provider execution.
- `dududa/ports/models.py`: Router, Provider, load/admission and output-codec
  Protocols.
- matching Unit, canonical/digest, import and structural conformance tests.

## Contract Decisions

- `ModelTier` values are exactly `haiku`, `sonnet`, `opus`; fallback edges are
  explicit and do not use enum ordering.
- Endpoint identity is `provider_id + endpoint_id`; `model_id` is the native
  Provider model identifier and may repeat across deployments.
- Structured-output support distinguishes no native support, JSON-object mode,
  and strict JSON-schema mode.
- Reasoning uses named abstract profiles plus an Adapter-declared mapping
  capability. Required profiles must be validated at catalog publication.
- Context declares total, optional independent input, and output limits.
- Mutable health/load never contributes to descriptor digest.
- Traffic rates include window and minimum-sample semantics; unknown/stale state
  has an explicit policy and is never silently treated as healthy.
- `TaskComplexityAssessment` contains evidence, not a Tier or Provider choice.
- `TierDecision` and `RouteDecision` are digestible reproducibility receipts.

## Acceptance

- DTO invariants reject empty/duplicate IDs, non-finite values, invalid limits,
  invalid confidence and mutable nested values.
- Cross-tier fallback cycles, missing references, unsupported profiles and
  privacy-incompatible endpoints are rejected before publication.
- Public imports work in Python 3.10+ without AstrBot or a Provider SDK.
- Existing provisional Runtime types can be replaced without an import cycle.
