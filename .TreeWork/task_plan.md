# Global Task Plan

## Project Scope (project-wide delivery boundary; not Tree topology)

- Integrated task-complexity assessment and deterministic three-tier model
  selection.
- Static endpoint routing, Provider compatibility and reliability boundaries.
- Structured perception and deterministic social/tier policy.
- Offline direct-chat runtime and side-effect-free shadow composition.
- Controlled AstrBot shadow/canary boundary, kill switch, dedup, observability
  and rollback evidence.
- Mew-source QQ client behavior over a typed server-side NapCat capability API.
- Concurrent multi-account chat, directory, notification, group-resource and
  settings workflows with account-scoped real-data persistence.
- A final authorized real-group scenario gate after all module, Web testing and
  local integration work is complete.

## Project Acceptance (project-level completion criteria; not branch-local steps)

- [ ] Every success criterion in `requirements.md` has direct implementation
  and verification evidence.
- [x] Fixed snapshots make model selection reproducible and no user input can
  bypass privacy, capability, budget or tier policy.
- [x] The offline runtime completes and acknowledges a direct reply without
  tools or memory and handles cancellation/failure safely.
- [x] Shadow is proven side-effect-free and canary ownership is proven
  single-path under concurrency and restart simulation.
- [x] The legacy path and unrelated workspace changes remain intact.
- [x] Real NapCat accounts provide all production QQ data and unsupported
  capabilities are explicit rather than simulated.
- [x] Mew-equivalent chat, directory, notification, group-resource and settings
  workflows pass adapted Unit and E2E contracts on desktop and mobile.
- [x] Concurrent accounts remain isolated through gateway actions, events,
  browser caches, drafts and uploads, with the OneBot token server-only.
- [ ] After every earlier acceptance item and local audit passes, the authorized
  real-group shadow/canary records the frozen safety and SLO evidence.

All local S08-S11 and Web criteria and their completion audits are satisfied.
The remaining project checkbox is the final real-group gate; it requires a
separate authorized external run.

## Roadmap (ordered global milestones or integration outcomes; not every branch task)

1. Establish the accepted S01-S07 baseline and model-selection contracts.
2. Implement the static Router, registry, capacity control and Provider
   conformance.
3. Implement perception, complexity assessment, TierPolicy and evaluation.
4. Integrate the offline direct-chat runtime and no-side-effect shadow.
5. Integrate controlled rollout configuration, bridge, persistent idempotency,
   metrics and rollback rehearsal.
6. Run cross-stage verification and completion audit.
7. Establish the selective Web baseline and account-scoped NapCat capability,
   rich-message, cursor-history and persistence contracts.
8. Port Mew's chat window, composer, renderers, search, drafts and message
   actions to the NapCat contracts.
9. Port contacts, notifications, group members/management/resources and
   settings with explicit capability degradation.
10. Audit real NapCat multi-account behavior, desktop/mobile UX, security and
    the complete repository regression suite.
11. After every accepted module and local audit is complete, freeze the SLO and
    rollback bundle, then run authorized single-group shadow, single-group
    canary and only afterward any layered group expansion/debugging.

If a later Tree revision adds another module or audit branch, that work is
inserted before step 11. The terminal real-group branch must depend on every
accepted local audit and cannot be entered merely because credentials arrive.

## Out Of Scope (project-wide exclusions; not branch ownership detail)

- Bandit or any live exploration.
- Tool and Memory integration, proactive chat, image generation, broad rollout,
  Agent Console runtime integration and Sub2API.

## External Dependencies (user decisions, systems, or inputs outside tree.yaml)

1. S01-S07 are integrated in `c83d742`; S08-S11 local implementation branches
   are integrated through `716e227`.
2. AstrBot runtime tests passed in the derived `s11-audit` image; ordinary host
   Python still records the two expected host-only skips.
3. The final real-group run requires explicit authorization, group identifiers,
   credentials and a user-approved external send window; these inputs are not
   requested until all preceding development and local audit work is complete.
4. Mew source behavior is pinned to commit `97df34b`; later upstream changes are
   not imported silently.
5. Full Web verification requires at least one real logged-in NapCat account;
   destructive QQ mutations and public-network exposure require separate user
   authority.
