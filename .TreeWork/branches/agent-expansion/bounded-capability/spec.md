# Branch Spec

Branch: bounded-capability
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Purpose And Delivery Boundary

Implement S13 as the governed business-capability layer above the completed
S12 transport boundary. The branch delivers an offline, bounded loop:

```text
query -> eligible Top-K -> plan -> bind -> authorize -> execute
      -> untrusted observation -> validate -> finish/continue/retry/stop
```

The first real-compatible Provider maps four public, cache-read iCourse
Capabilities through `UnifiedMcpClient`. A generic Fake Provider and the S12
second Fake Server prove extension without a new control plane. No real model
Endpoint, live network, credential, crawl, write or QQ delivery is enabled.

S13 also replaces the S10 provisional tool-state aliases with concrete S13
contracts and adds a default-off `USE_TOOLS` path to the existing Offline
Runtime. The original S10 no-tool path, S11 rollout admission, Static Router,
TierPolicy, Connector, delivery and Memory boundaries remain unchanged. A
local tool-assisted Runtime test is required; production rollout continues to
reject `tools_enabled` until a later authorized gate.

### Existing Authority And Contract Reuse

S13 reuses and strengthens the existing `CapabilityDefinition`, `ProviderRef`,
`SchemaRef`, `Actor`, `ConversationScope`, `RiskLevel`, `PrivacyLevel`,
`SideEffect`, `RuntimeBudget` and `ResourceUsage`. It does not create parallel
identity, authorization, budget, audit, idempotency or MCP systems.

All permission decisions use the existing `AuthorizationPolicy`; execution
budget uses `BudgetLedger`; call frequency uses `InteractionLimiter`; audit
uses `AuditSink`; and MCP-backed Providers use only the S12
`UnifiedMcpClient` Port. Core Capability modules import no MCP SDK, AstrBot or
iCourse package. Public DTOs are frozen, slotted, versioned, bounded and bound
by canonical digests.

`CapabilityDefinition` continues to reference `SchemaRef` rather than inline
mutable Schema. S13 adds immutable `CapabilitySchemaDocument` objects and
publishes Definition, Schema, Provider descriptor and Mapping in one atomic
Catalog snapshot. Definition digest validation is strengthened in place;
breaking Definition changes require a new versioned Capability ID.

### Catalog, Configuration And Canonical IDs

Strict JSON under `config/capabilities/definitions/` and
`config/capabilities/mappings/` is the S13 configuration authority. The
`configs/` rename remains owned by S17. Publication validates the complete
candidate snapshot and retains last-known-good on malformed JSON, duplicate
IDs, missing Schema, unknown Provider, invalid risk/side effects or Mapping
incompatibility.

The canonical iCourse IDs are frozen to the already verified S12 provisional
fixtures:

- `icourse.stats.read.v1` -> `icourse_stats`;
- `icourse.courses.search.v1` -> `search_courses`;
- `icourse.course.get.v1` -> `get_course` with non-overridable
  `refresh=false`; and
- `icourse.reviews.get.v1` -> `get_reviews`.

No alias IDs are introduced. `search_site_courses`, crawl/refresh, robots,
export and management Tools are absent from the Catalog. The formal
`McpCapabilityMapping` binds Capability definition digest, Server/Tool,
expected Tool input/output Schema digests, operation semantics, fixed
arguments, argument/result mapping revisions and enabled state. Discovery may
refresh transport facts but never creates or widens a Mapping.

### Eligibility And Deterministic Retrieval

One retrieval uses exactly one immutable Catalog snapshot and one bounded
Health snapshot. The first release admits only `HEALTHY`, unexpired Providers
whose exact revision and Capability definition digest match the Catalog;
`DEGRADED`, stale, missing and unavailable are ineligible.

Eligibility filters in fixed fail-closed order: enabled/config binding,
health/freshness, conversation type, every required permission, exact Scope
and privacy, maximum risk and excluded side effects, required inputs, deadline,
latency and budget. Each required permission produces its own
`AuthorizationRequest`; every decision must be `ALLOW`, current and bound to
`ResourceRef("capability", capability_id, exact_scope_digest)`. Retrieval
decisions are eligibility evidence only and are never reused for execution.

Only eligible definitions enter lexical scoring. The reference ranker uses
normalized intent/tag/entity/schema terms, stable health/latency/cost/risk
weights and deterministic `capability_id` tie-breaking. Default K is 8, the
hard limit is 20, and per-Provider and per-category caps are 4. Bandit is off.
Rejected definitions, raw goal text, commands, paths, Server configuration and
permission details do not enter Planner summaries or audit labels.

### Planner, Plan Validation And Argument Binding

There is no real `TOOL_PLANNING` Endpoint in this Goal. S13 therefore provides
the framework-neutral `ToolPlanner` Port, a deterministic reference Planner
for explicit argument hints, and scripted Fakes. This proves bounded control
flow but makes no claim about real Chinese planning quality.

Planner output is a proposal. A deterministic validator requires candidate
membership and exact Definition digest, unique step and logical-operation IDs,
a directed acyclic dependency graph, supported literal JSON, approved JSON
Pointers, input-Schema compatibility and budget feasibility. The default
maximum is four executed attempts and the hard ceiling is eight; retries count
as attempts. A step may depend only on earlier reachable steps.

`ArgumentBinder` can read only JSON Pointers declared by the accepted Plan from
Validator-accepted successful Observations. It cannot read errors, future
steps, hidden Provider objects, arbitrary JSONPath or control metadata. Fixed
Mapping arguments are merged last and any attempted override fails closed.

### Execution, Authorization, Budget And Idempotency

Before every Provider call, Executor resolves the exact Catalog snapshot,
Definition, Mapping and Provider revision again; validates current health,
deadline, cancellation, Scope, arguments and Schema; obtains fresh decisions
for every required permission; reserves limiter and budget leases; and writes
an audit-start event. Any failed prerequisite produces zero Provider calls.

The stable business key binds `run_id`, logical-operation ID, Capability ID,
Definition digest and canonical normalized arguments. Replan and retry of the
same logical operation retain the key; deliberately repeated operations use a
new logical-operation ID. A bounded `ToolInvocationLedger` owns single-flight,
terminal receipts and conflict detection so concurrent duplicates neither
double-call the Provider nor rely on Provider-private caches.

One attempt reserves one tool step, conservative retry usage and the
Capability cost hint through the existing `BudgetLedger`. Success settles the
actual bounded usage; pre-dispatch failure releases the lease; unknown outcome
is conservatively charged. Audit-start failure blocks dispatch. Audit-finish
failure prevents the result from becoming an accepted factual Observation.

### Observation And Validator Boundary

Provider results are normalized into immutable, size-limited
`ToolObservation` values carrying all Catalog/Provider/policy/idempotency
bindings, status, Schema-bound data, source references, sensitivity and usage.
Raw SDK exceptions, stderr, commands, paths, credentials and full payloads are
never exposed. `UNKNOWN` is not success; non-idempotent work never retries, and
this branch defaults unknown outcomes to stop even for read-only work unless a
future policy can prove a same-key safe retry.

External strings remain untrusted data and have no control authority. Prompt
Injection is tested structurally: external content cannot add a Capability,
Tool, step, permission, binding or side effect; only accepted pointers may
flow to a later step. The Validator checks Capability output Schema, binding,
empty/business errors, size/sensitivity/source requirements and completion
state. It cannot grant permission or widen the Plan. Only accepted successful
Observations can enter the answer-model data projection, which quotes them as
untrusted data; Server text and errors never become instructions or direct
user-visible output.

### MCP Provider And Extension Rule

`McpCapabilityProvider` is a generic infrastructure Adapter. It discovers a
fresh S12 Schema snapshot, verifies formal Mapping and per-Tool Schema digests,
constructs the exact `McpCallContext`, invokes `UnifiedMcpClient`, and converts
the result into a bounded `CapabilityResult`. It does not authorize, schedule,
render, send, own retries outside declared semantics or fall back to Legacy.

The iCourse Provider is configuration plus the generic Adapter; no `if
server_id == "icourse"` branch exists in Domain, Runtime or the generic
Client. Adding the second Fake requires only its S12 Server JSON, an S13
Definition JSON, Mapping JSON and authorization fixture. It must be invisible
with discovery alone or without permission, executable after all facts are
present, and fail closed after Mapping removal.

Existing `/course` commands retain their current compatibility facade and
output contract in S13. Their admin refresh/online-search path is not relabeled
as a model Capability. S22 still owns Legacy deletion after all consumer and
previous-Release evidence exists.

### Offline Runtime Integration

The additive path is enabled only when an explicit invocation feature flag
`tools=true`, a `BoundedCapabilityRuntime` is injected, and a separate
`capability.plan` authorization is allowed. Exact Capability authorization is
still repeated inside Executor. With the flag absent or false, the prior S10
forbidden-tool invariants and `DEFER` behavior remain byte-for-byte testable.

For `USE_TOOLS`, the Runtime records concrete retrieval, plan, execution and
validation artifacts through `TOOLS_PLANNED`, `TOOLS_EXECUTED` and `VALIDATED`.
Tool usage is charged independently of the existing model-only budget plan.
Only a successful accepted result may be included in the existing Direct Chat
model request as bounded untrusted JSON, after which the existing Composer,
Persona, final Validator, delivery authorization and Output path remain the
sole expression and side-effect owners. Failure, cancellation, stale evidence,
empty acceptance or budget exhaustion ends with a stable deferred/failed
result and no delivery.

S11 production rollout continues to require tools disabled. This branch proves
the local additive graph only and does not install, restart or mutate a running
AstrBot/NapCat container.

### Verification Boundary

Unit and Contract tests cover DTO/digest/Schema bounds, atomic Catalog and
last-known-good, authorization and Top-K filtering, Plan DAG/membership/step
limits, Pointer binding, per-step reauthorization, revision drift, budget and
single-flight, unknown outcomes, audit failure and structural Prompt Injection.

The generic Fake Provider and local empty-database iCourse Provider pass the
same conformance suite. The second Fake extension proves configuration-only
growth. A synthetic fixed course set reports Recall@K, ineligible exposure,
Plan/argument validity, completion and average attempts; it is contract
evidence, not real-language or service-quality evidence. Dual Python, import,
build, secret, lock, Ruff, whitespace and necessary Web regressions remain
required.
