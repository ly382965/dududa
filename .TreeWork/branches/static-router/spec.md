# S08 Static Router Spec

## Scope

Implement catalog publication, immutable snapshots, deterministic selection,
atomic admission and bounded Provider invocation for `PERCEPTION` and
`DIRECT_CHAT`.

## Selection And Execution

The Router filters role/tier, privacy/residency/retention, capability/schema,
reasoning/context, deadline/budget, health/load/cooldown and route preference in
that order. It sorts surviving references by role-policy priority and stable
endpoint ID. It reserves capacity immediately before a call.

Retry, same-tier failover and cross-tier fallback have independent counts and
share the total call deadline/budget. Authentication, invalid request, safety
refusal and exhausted schema repair stop. Transient network, timeout, bounded
429/5xx and explicit context-overflow edges may continue only when policy and
idempotency permit.

## Implementations

- In-memory last-known-good registry and endpoint-state registry.
- Atomic in-memory admission controller with shared quota pools.
- Strict structured-output codec boundary.
- Recording Fake Provider supporting deterministic failure scripts.
- One real compatible AstrBot Provider Adapter in plugin infrastructure. It may
  declare only capabilities the AstrBot API actually exposes.

## Acceptance

- Fake and compatible Adapter share a Provider conformance suite.
- Same request plus catalog/load snapshots yields the same selected endpoint and
  reasons.
- Tests cover structured output, context boundaries, stale load, concurrency,
  RPM/TPM, cooldown, 429, timeout, auth, safety, no route, cancellation, budget,
  fallback ceilings, receipt mismatch and credential/error redaction.
- `PERCEPTION` defaults to Haiku; `DIRECT_CHAT` defaults to Sonnet; Opus is
  registered but receives no implicit upgrade traffic.
- No production Event is connected and the old Handler remains authoritative.
