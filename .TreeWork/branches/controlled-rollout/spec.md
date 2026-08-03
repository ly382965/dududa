# S11 Controlled Rollout Spec

## Scope

Add the infrastructure and AstrBot bridge required for no-send shadow and a
single authorized explicit-mention canary while retaining the legacy path as
rollback authority.

## Controls

- Strict typed `off|shadow|canary` configuration with revision, delivery enable,
  allowlisted groups and kill-switch state.
- Admission requires group allowlist, explicit mention of the current Bot,
  supported text input, tools off and Memory off.
- Shadow runs in a bounded background task, never stops the Event and never
  receives a side-effecting adapter.
- Canary performs a second kill-switch check before send and establishes a
  single delivery owner. Once claimed, it cannot fail over asynchronously to
  the legacy sender.
- Persistent CAS/dedup and delivery tombstones survive process restart and
  preserve UNKNOWN outcomes without blind resend.

## Observability And Rollback

Record only low-cardinality sanitized mode, role/tier/endpoint revisions,
candidate/actual outcome, latency, usage and stable failure reasons. Provide a
read-only summary for the canary review. Rollback disables Runtime admission and
restores both image and bind-mounted plugin/config revisions; an image tag alone
is insufficient.

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
