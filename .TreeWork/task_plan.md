# Global Task Plan

## Project Scope (project-wide delivery boundary; not Tree topology)

- Integrated task-complexity assessment and deterministic three-tier model
  selection.
- Static endpoint routing, Provider compatibility and reliability boundaries.
- Structured perception and deterministic social/tier policy.
- Offline direct-chat runtime and side-effect-free shadow composition.
- Controlled AstrBot shadow/canary boundary, kill switch, dedup, observability
  and rollback evidence.

## Project Acceptance (project-level completion criteria; not branch-local steps)

- [ ] Every success criterion in `requirements.md` has direct implementation
  and verification evidence.
- [ ] Fixed snapshots make model selection reproducible and no user input can
  bypass privacy, capability, budget or tier policy.
- [ ] The offline runtime completes and acknowledges a direct reply without
  tools or memory and handles cancellation/failure safely.
- [ ] Shadow is proven side-effect-free and canary ownership is proven
  single-path under concurrency and restart simulation.
- [ ] The legacy path and unrelated workspace changes remain intact.

## Roadmap (ordered global milestones or integration outcomes; not every branch task)

1. Establish the accepted S01-S07 baseline and model-selection contracts.
2. Implement the static Router, registry, capacity control and Provider
   conformance.
3. Implement perception, complexity assessment, TierPolicy and evaluation.
4. Integrate the offline direct-chat runtime and no-side-effect shadow.
5. Integrate controlled rollout configuration, bridge, persistent idempotency,
   metrics and rollback rehearsal.
6. Run cross-stage verification and completion audit.

## Out Of Scope (project-wide exclusions; not branch ownership detail)

- Bandit or any live exploration.
- Tool and Memory integration, proactive chat, image generation, broad rollout,
  WebUI and Sub2API.

## External Dependencies (user decisions, systems, or inputs outside tree.yaml)

1. Existing S01-S07 uncommitted work must be selectively baselined before
   isolated branches can import it.
2. AstrBot runtime tests require the derived image because the host environment
   does not install AstrBot.
3. A real S11 group run requires explicit authorization, group identifiers,
   credentials and a user-approved external send window.
