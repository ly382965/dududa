# S11 Controlled Rollout Spec

## Scope

Add the infrastructure and AstrBot bridge required for no-send shadow and a
single authorized explicit-mention canary while retaining the legacy path as
rollback authority.

## Controls

- Strict typed `off|shadow|canary` configuration with revision, delivery enable,
  allowlisted groups and kill-switch state.
- `off` leaves the Event and legacy delivery path untouched. `shadow` takes a
  bounded immutable input snapshot and also leaves legacy ownership untouched.
  `canary` may claim only an admitted message; a durable claim is the point of
  no return and forbids later fallback to the legacy sender.
- Admission requires group allowlist, explicit mention of the current Bot,
  supported bounded text input, tools off and Memory off. Mention trust comes
  from the Connector/platform structure rather than matching display text.
- Shadow runs in a bounded background task, never stops the Event and never
  receives a side-effecting adapter.
- Canary establishes a single delivery owner before stopping the Event. It
  performs a fresh configuration read and second kill-switch/delivery-enable
  check immediately before the first platform send. Once claimed, denial,
  timeout, cancellation or an indeterminate send outcome cannot fail over to
  the legacy sender.
- Persistent CAS/dedup and delivery tombstones survive process restart and
  preserve UNKNOWN outcomes without blind resend. Claims and tombstones are
  keyed by canonical message/delivery identities and use transactional compare
  and swap; process-local locks are only an optimization.

## Runtime Boundary

- Core rollout contracts, admission, ownership, persistence and metrics do not
  import AstrBot. The bridge converts one trusted Event snapshot into those
  contracts and is the only layer allowed to stop the Event or construct an
  `AstrBotOutputAdapter`.
- Shadow receives only `AgentRuntime` plus a sanitized sink and is scheduled
  through a capacity- and deadline-bounded task supervisor. Saturation drops a
  candidate with a stable metric reason and never delays the legacy path.
- Canary uses the existing S10 Orchestrator and DeliveryRequest. The bridge
  obtains a durable Runtime ownership claim, stops further legacy processing,
  runs the Runtime, rechecks the live controls and only then invokes Output.
- A terminal ownership record distinguishes no-send, known delivery and
  `UNKNOWN`; replay returns the recorded disposition and never restarts a send
  whose outcome may already have escaped the process.

## Observability And Rollback

Record only low-cardinality sanitized mode, role/tier/endpoint revisions,
candidate/actual outcome, latency, usage and stable failure reasons. Provide a
read-only summary for the canary review. Group, sender, message, raw content,
prompt, response and Provider bodies are forbidden metric dimensions. Rollback
disables Runtime admission and restores both image and bind-mounted
plugin/config revisions; an image tag alone is insufficient. A checked manifest
records all three revisions and the expected `off` control revision.

## Acceptance

- Simulation covers whitelist/non-whitelist, explicit/non-explicit mention,
  TargetTalk overlap, concurrency, restart replay, in-flight kill-switch change
  and UNKNOWN delivery.
- Shadow action counters for send/write/tool/stop are all zero.
- Canary tests prove exactly one path owns each accepted message.
- Secrets, raw messages, QQ IDs, prompts and Provider bodies never enter Trace.
- A real external shadow/canary remains pending until the user supplies explicit
  authorization and environment inputs; local completion cannot fabricate that
  evidence.
