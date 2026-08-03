# S10 Offline Runtime Spec

## Scope

Build the first complete direct-chat loop for explicit mentions using only
current-message context, S09 perception/tiering and S08 model routing. Tools,
Memory, proactive chat and production delivery remain disabled.

## Required Contract Corrections

- Delivery completion must preserve real `SUCCEEDED`, `PARTIAL`, `FAILED` or
  `UNKNOWN` status rather than forcing `NOT_REQUIRED`.
- The AgentRuntime Protocol includes idempotent delivery acknowledgement and
  reconciliation.
- Design and implementation converge on one `DeliveryConstraints` definition.
- Runtime State replaces provisional perception/social types and stores tier
  and route receipts without inventing a new phase.

## Components

- In-memory CAS RuntimeStateStore with message dedup and bounded tombstones.
- Minimal current-message ContextBuilder.
- Deterministic direct-mention social policy.
- Orchestrator with total deadline, cancellation and budget accounting across
  perception and direct-chat calls.
- Minimal Composer, deterministic single Persona renderer and fact-preserving
  validator.
- DeliveryRequest builder plus acknowledgement/reconciliation reducer.
- Side-effect-denying `ShadowRunner` composition with recording sinks only.

## Acceptance

- Full expected phase sequence and persisted revision history are tested.
- Duplicate/concurrent starts reuse one run and never create two deliveries.
- Invalid model output, timeout, cancellation and exhausted budget produce safe
  typed outcomes.
- Facts, targets, refusal and constraints survive composition/rendering.
- Shadow proves zero real output, memory, tool and event-stop actions.
