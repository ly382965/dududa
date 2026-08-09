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

The pre-execution route plan and the execution receipt are separate identities.
The plan contains the semantic request/tier fingerprints, catalog and policy
identity, ordered candidate plans with estimates, stable rejection reasons and
the initially planned Endpoint. It excludes request/snapshot/lease IDs,
timestamps, latency and Provider outcomes. `RouteDecision` is the full execution
receipt: it additionally binds the acquired operational snapshot, every typed
admission result and settlement/release receipt, every Provider request and
attempt, and the terminal Endpoint. A fallback therefore changes the execution
receipt but not the original plan fingerprint.

Admission reserve returns a typed `RESERVED | REJECTED` result rather than
encoding capacity rejection as an unstructured exception. A reserved result
contains an immutable lease; every lease reaches exactly one idempotent
`SETTLED | RELEASED` receipt. Unknown Provider usage settles at the reservation
ceiling. Shared-pool accounting and validation use bounded historical catalog
and operational snapshots so an in-flight request never combines two latest
revisions.

Operational RPM/TPM/in-flight/queue counters are explicitly scoped to load
external to this admission-controller instance; locally admitted work is
accounted only by the controller's atomic state, preventing snapshot/local
double charging. Queue waiters re-run stale/load/cooldown/deadline checks after
every wake and wake at the earliest call, request or active-lease deadline.
Native task cancellation cannot leak a waiter or lease. Once Provider dispatch
starts, cancellation or any unknown exit settles at the reservation ceiling;
before dispatch it releases. Provider cancellation cleanup is bounded and any
detached task outcome is consumed without treating cancellation as success.
Provider errors are rebuilt at the Core boundary from failure kind and
outcome-known state; Provider-owned strings never enter attempts, terminal
errors or serialized route receipts.

`max_schema_repairs` is explicit policy, restricted to zero or one in S08. A
repair is a new Provider call on the same Endpoint and Tier, consumes both a
model-call and retry budget, and is globally limited for the invocation. A
second invalid result, or an invalid result when repair is disabled, stops.
Cross-tier fallback edges are traversed in their declared tuple order. A
requested Tier with no initially legal Endpoint terminates without implicit
fallback because there is no Provider failure authorizing an edge.

## Implementations

- In-memory last-known-good registry and endpoint-state registry.
- Atomic in-memory admission controller with shared quota pools.
- Strict structured-output codec boundary.
- Recording Fake Provider supporting deterministic failure scripts.
- One real compatible AstrBot Provider Adapter in plugin infrastructure. It may
  declare only capabilities the AstrBot API actually exposes.

The AstrBot Adapter is enabled only for a host/provider binding that passes the
same behavioral conformance suite as the Fake. Signature acceptance is not
capability evidence. The pinned AstrBot 4.26.2 OpenAI/Anthropic implementations
do not reliably propagate per-request output/temperature kwargs and may perform
hidden retries, so those bindings remain disabled until a pinned host patch or
upstream revision proves one downstream request, enforced deadline/output
ceiling, enforced cancellation, sanitized logging and exact model binding.
Adapter-local bounded cancellation only proves caller liveness, not termination
of the downstream network request. The Adapter may still be implemented and
tested against a conforming AstrBot-compatible harness; it must fail closed for
unverified host bindings.

Adapter enablement evidence binds the exact AstrBot Provider ID, Provider-native
model ID, verified residency set and verified retention modes declared by its
single Endpoint; boolean claims alone cannot authorize a broader descriptor.
Enablement also requires explicit deadline- and cancellation-enforcement flags.
Successful results and outcome-unknown failures are retained in a bounded TTL/
LRU idempotency ledger; an identical replay returns the result or sanitized
tombstone without a second host call, while fixed lock striping and `close()`
bound retained state.
Every primary or schema-repair Prompt is an immutable artifact resolved by the
exact `ProviderRequest.prompt_template_revision`, whose artifact digest covers
the static system and rendering instructions. Unknown revisions, a repair
artifact used for a non-repair attempt, or a repair without an output Schema
fail before the host call. Local Prompt/Schema lookup errors and structured
Provider 400/422 or safety refusals are normalized to sanitized
`ModelProviderError` values rather than crossing the Adapter boundary.

## Acceptance

- Fake and compatible Adapter share a Provider conformance suite.
- Same request plus catalog/load snapshots yields the same selected endpoint and
  reasons.
- Tests cover structured output, context boundaries, stale load, concurrency,
  RPM/TPM, cooldown, 429, timeout, auth, safety, no route, cancellation, budget,
  fallback ceilings, receipt mismatch and credential/error redaction.
- Route-plan fingerprint tests prove that correlation IDs, snapshot IDs,
  observation times, attempt latency and Provider outcome do not alter the
  plan, while semantic request, policy, candidate estimate or eligibility
  changes do; the full execution digest preserves those runtime differences.
- `PERCEPTION` defaults to Haiku; `DIRECT_CHAT` defaults to Sonnet; Opus is
  registered but receives no implicit upgrade traffic.
- No production Event is connected and the old Handler remains authoritative.
