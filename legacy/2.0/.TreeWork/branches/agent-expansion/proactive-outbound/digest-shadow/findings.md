# Findings

Branch: digest-shadow

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Scheduled digests project a truthful `ResponsePlan` from Subscription and Source evidence instead
  of fabricating an inbound message or `SocialDecision`; the maximum profile is MEDIUM.
- Preview reuses the candidate builder with a digest-bound `preview:<id>:<subscription>` namespace,
  so it cannot consume the scheduled cursor/dedup state.
- Trigger expiry and call validity are rechecked after Actor resolution and immediately before Source
  access; elapsed dependency time cannot silently turn an expired occurrence into a source fetch.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `dududa.proactive` exports digest policy/metadata contracts, deterministic Composer/Builder,
  no-send Runtime and Preview Producer. `dududa.ports` adds Composer, Runner and metadata-sink Ports.
- Ordinary Shadow state stores only canonical digests, status and reason codes. Preview returns body
  synchronously through the existing authorized Preview boundary and does not persist it in metadata.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The existing S15C `SourceProvider` checks cancellation/deadline at cooperative boundaries but does
  not externally preempt a Reader or lock that stalls mid-await. S16 should harden that shared Port;
  S15D does not create a second cancellation control plane.
- Fixtures prove deterministic evidence preservation and dedup behavior, not live-source licensing,
  availability, freshness, usefulness, production persistence or delivery behavior.
