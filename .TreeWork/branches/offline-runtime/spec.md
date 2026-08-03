# S10 Offline Runtime Spec

## Scope And Outcome

Build the first complete, deterministic direct-chat Runtime over the integrated
S08/S09 model-selection pipeline. The branch proves the offline sequence from a
validated `RuntimeStartRequest` through a caller-owned delivery receipt and
also exposes a Shadow composition that cannot send, write Memory, execute a
Tool or stop an AstrBot event.

S10 accepts bounded pure-text private messages and group messages that
explicitly mention the current Bot. It does not accept attachments, reply-only
group messages, Memory, tools, proactive group participation or production
event ownership. `DIRECT_CHAT` names the downstream model role; it does not
make an untrusted reply reference sufficient evidence that a Bot was addressed.

## Dependency And Module Ownership

```text
ConnectorResult
  -> dududa.runtime.context
  -> S09 Perception/Complexity/Social/TierPolicy
  -> dududa.runtime.direct_chat -> S08 ModelRouter
  -> dududa.runtime.composition
  -> dududa.runtime.delivery
  -> DeliveryRequest (caller-owned send boundary)

dududa.runtime.store <-> dududa.runtime.orchestrator
dududa.runtime.shadow -> AgentRuntime only
```

- `runtime/contracts.py` owns cross-stage S10 DTOs and receipts.
- `runtime/context.py` owns current-message de-identification and identity
  binding.
- `runtime/budget.py` owns conservative two-call reservation arithmetic.
- `runtime/direct_chat.py` owns the bounded `DIRECT_CHAT` request/projection.
- `runtime/composition.py` owns the minimal Composer, deterministic Persona
  renderer and fact/digest validator.
- `runtime/store.py` owns in-memory checkpoint CAS, dedup, tombstones and
  revision waiting; it does not decide legal phase transitions.
- `runtime/delivery.py` owns DeliveryRequest construction and receipt
  acknowledgement/reconciliation reducers.
- `runtime/orchestrator.py` is the only workflow coordinator. It never holds an
  `OutputAdapter`.
- `runtime/shadow.py` exposes only a sanitized, non-deliverable receipt.
- `ports/runtime.py` owns Runtime, State Store and composition Protocols.

Core Runtime must not import AstrBot, Provider SDKs, platform events, WebUI,
Sub2API, Memory implementations or MCP implementations.

## Admission And Context

The Orchestrator validates the start digest, `call.run_id`, root trace,
deadline, cancellation and Actor/Envelope/Scope binding before the first
checkpoint. Cancellation or expiry before that commit creates no run.

The admitted S10 input is:

- one non-empty bounded text message;
- no attachments;
- private conversation, or group conversation with a trusted Connector mention
  whose platform/user ID equals the current Bot;
- a non-self Actor and a supported data classification below `RESTRICTED`.

Other group traffic returns a normal no-reply result without a model call.
Attachments and unsupported privacy return a typed deferred result. A
reply-only group message is not treated as explicit interaction because a bare
`MessageReference` contains no trusted author evidence.

`CurrentMessageContextBuilder` creates:

1. a bounded `PerceptionContext` containing opaque canonical identity/message
   references, one current message, no raw platform IDs and no reply target;
2. immutable `RuntimeIdentityBinding` values that map only known opaque
   identities back to `ResolvedIdentityRef` inside the current Scope;
3. a conservative UTF-8/token upper bound and builder revision.

The model serializer sees only item 1. Composer target resolution uses item 2
and fails closed on unknown or cross-Scope targets.

## Authorization And Social Signals

Before Perception, Runtime requests `message.respond` authorization over the
current conversation resource. `DecisionSignals` are derived as follows:

| Signal | Authority |
| --- | --- |
| `can_respond` | current `message.respond` AuthorizationDecision is `ALLOW` |
| `can_use_tools` | always false in S10 |
| `duplicate_or_self_message` | Store dedup ownership and Connector Actor/Bot equality |
| `explicit_interaction` | private conversation or trusted explicit Bot mention |
| `private_conversation` | Envelope conversation type |
| `group_mode` | immutable S10 Runtime config |
| `rate_limited` | false in offline S10; S11 owns live admission |
| `private_data_boundary` | restricted data, or sensitive/personal data crossing into a group |
| `tools_enabled` | always false |
| `known_target` | every rule-authoritative target resolves through the Runtime identity binding |

`IGNORE` completes as `NO_REPLY`. `DEFER` completes without visible output.
`ASK_CLARIFICATION` uses one configured deterministic message and skips the
downstream TierPolicy/Router. `DIRECT_REPLY` enters model selection. `REACT` and
`USE_TOOLS` are rejected as out of S10 scope if an alternate Social Policy emits
them.

## Perception Execution And Total Budget

S09's result contract remains unchanged. Runtime adds an execution receipt
around Router-backed Perception with:

- whether a model call started;
- deterministic ModelRequest fingerprint;
- sanitized `RouteDecision`, when one exists;
- Provider-reported `ModelUsage`, when complete;
- stable model status/failure kind and the merged `PerceptionResult`.

It contains no prompt, raw model output or Provider error body. Existing
`PerceptionEngine.perceive()` remains compatible; S10 requires the additive
execution-capable Protocol.

`RuntimeModelBudgetPlan` contains explicit Perception and Direct Chat maximum
reservations. Each contains exactly one logical model call, zero tool steps and
bounded retry/input/generated-token/cost units. The initial Runtime budget must
cover their sum. A child Router call sees only its reservation. Once any model
attempt starts, Runtime charges the full reservation unless all attempted usage
is proven within a smaller amount; v1 uses the full reservation
conservatively. A failed/invalid Perception attempt therefore cannot leave the
full original budget available to Direct Chat.

Complexity remains independent from context pressure. Runtime persists the
validated `TaskComplexityAssessment`, projects the remaining Direct Chat
reservation into `TierSelectionContext`, validates the resulting
`TierDecision`, and only then invokes S08.

## Direct Chat And Composition

`DirectChatModelCall` builds one de-identified, revisioned text request with
`ModelRole.DIRECT_CHAT`, the role-configured reasoning profile, privacy policy,
content/token bounds, optional trusted `RouteHint`, temperature zero and an
idempotency key derived from the complete request plan. User text cannot create
a Tier or Provider authority.

The successful ModelResponse must bind the request/role/route and contain one
non-empty bounded string. Runtime projects it to immutable
`DirectChatContent`; no Provider payload or raw response object crosses into
Composer. `DirectChatExecutionReceipt` stores the request fingerprint, model
response digest, route decision, reported usage, conservative charge and
content projection.

The minimal Composer creates a `DraftResponse` with rule-authoritative targets
and the Social Decision constraints. The deterministic single-Persona renderer
is a pass-through transformation to `FinalResponse`; it cannot add/remove
targets, facts, citations, refusal, warnings, attachments or constraints.
`DeterministicRenderValidator` recomputes both draft and rendered digests and
compares every protected field. Final content safety recomputes the actual
rendered digest before `ValidatedFinalResponse` can be constructed.

## State, CAS And Single-Flight

`RuntimeState` keeps the existing phase enum and adds typed current context,
response authorization, Perception execution, complexity assessment, Tier
decision, direct-chat execution/route, charged usage and Completion receipt.
No phase is added for Tier selection.

State validation enforces:

- immutable run/message/Actor/Scope/start/policy roots;
- phase-required payloads;
- budget never increases;
- Perception, assessment, Tier and route digests/roles/tiers bind one another;
- composed/rendered/delivery payloads preserve targets and constraints;
- a receipt cannot exist before `READY_TO_EMIT`;
- terminal states contain a matching Completion receipt and Runtime result.

The in-memory Store atomically creates `(run_id, MessageDedupKey, start_digest)`
and uses integer revision CAS thereafter. Same-key/same-digest concurrent calls
wait for revision changes and reuse exactly one result. Same-key/different
digest and same-run/different-key calls fail with typed conflicts. Checkpoint
and tombstone TTL/capacity are configured; expired entries may be collected,
but an unexpired checkpoint or tombstone is never evicted to admit another
message. Capacity exhaustion fails closed.

Expected visible phase sequence:

```text
RECEIVED -> PREPROCESSED -> CONTEXT_READY -> PERCEIVED -> DECIDED
         -> COMPOSED -> RENDERED -> READY_TO_EMIT
```

No-output sequence:

```text
PREPROCESSED -> MEMORY_EVALUATED -> COMPLETED(NOT_REQUIRED)  # admission ignore
DECIDED      -> MEMORY_EVALUATED -> COMPLETED(NOT_REQUIRED)  # social ignore
```

## Delivery, Acknowledgement And Reconciliation

The authoritative `DeliveryConstraints` is versioned and contains maximum
parts, maximum UTF-8 bytes per part, forward-bundle permission, allowed
attachment schemes and a positive reconciliation window. AstrBot splitting
must not cut a Unicode code point or exceed the byte bound.

Runtime creates the immutable Delivery intent, obtains a separately bound
`message.send` AuthorizationDecision, then computes the final request digest.
`run()` stops at `READY_TO_EMIT`. `OfflineDeliveryDriver` is the only S10 helper
that holds an `OutputAdapter`; it performs `run -> deliver -> acknowledge` for
offline tests and never retries `UNKNOWN`.

Acknowledgement validates run, delivery ID, request digest, idempotency key,
attempt, Adapter revision, part IDs/digests and platform Scope. Any real status
(`SUCCEEDED`, `PARTIAL`, `FAILED`, `UNKNOWN`) advances through
`DELIVERY_ACKNOWLEDGED -> MEMORY_EVALUATED -> COMPLETED` and is preserved in
`CompletionReceipt`; S10 creates no Memory candidates.

An exact duplicate acknowledgement returns the original Completion receipt.
A later different receipt uses `reconcile_delivery()` within the configured
window. Part status may improve from `UNKNOWN` to `FAILED` or `SUCCEEDED`, and
from `FAILED` to `SUCCEEDED`; `SUCCEEDED` never regresses. Different content
digest, successful platform reference, delivery binding or immutable request
identity is `CONFLICT`. Reconciliation only updates the `COMPLETED` checkpoint
revision; it never performs a backward phase transition.

## Shadow Boundary

`ShadowRunner` depends only on `AgentRuntime` and a sanitized recording sink.
It has no OutputAdapter, Memory writer, Tool executor or event-stop function.
Its result contains run/outcome, selected Tier and route/candidate digests,
reason codes and timestamp. It contains no response body, DeliveryRequest,
AuthorizationDecision, platform ID or callable send handle. A Shadow candidate
cannot be handed to `OutputAdapter.deliver()` by type.

## Acceptance

- The direct Haiku/Sonnet/Opus selection path uses S09 assessment/TierPolicy and
  S08 Router without Bandit or user-controlled Tier authority.
- Current-message context is bounded/de-identified and target bindings cannot
  cross Scope.
- Total two-call budget, deadline and cancellation behavior are conservative
  under success, invalid output, retry and failure.
- State/CAS/dedup/single-flight tests prove one model chain and one immutable
  DeliveryRequest under concurrent duplicate starts.
- Full direct reply, deterministic clarification, ignore, tool-defer and failure
  paths satisfy typed phase/result invariants.
- Composer/renderer/validator preserve facts, citations, refusal, targets and
  constraints and reject forged digests or changed anchors.
- Delivery handles four real statuses, idempotent acknowledgement and monotonic
  reconciliation without blind retry.
- Shadow tests prove zero Output, Memory, Tool and event-stop calls and a
  non-deliverable public receipt.
- Python 3.10/3.12 full and focused suites, warnings-as-errors async tests,
  import boundaries, Ruff/format, compile, secret and whitespace scans pass.

## Out Of Scope

- Bandit, random/learned routing, empirical real-model sufficiency claims.
- Tools/MCP, Memory read/write, attachment preprocessing, trusted reply history,
  proactive chat, reactions and multiple/persona-model rendering.
- AstrBot production bridge ownership, persistent cross-restart store, canary,
  kill switch, live metrics and real QQ sends; S11 owns these.
