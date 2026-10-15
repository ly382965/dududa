# Global Task Plan

## Project Scope (project-wide delivery boundary; not Tree topology)

- Integrated task-complexity assessment and deterministic three-tier model
  selection.
- Static endpoint routing, Provider compatibility and reliability boundaries.
- Structured perception and deterministic social/tier policy.
- A production-reachable but default-off composition and additive semantic
  contract proven without real Provider traffic or human data.
- One generic multi-Server MCP boundary with four real read-only query Servers,
  plus bounded Capability planning and execution. Shuttle uses the same
  Capability Runtime through a local Builtin plugin rather than an MCP Server.
- Memory lifecycle, administration and lexical retrieval baselines.
- Offline direct-chat runtime and side-effect-free shadow composition.
- Controlled AstrBot shadow/canary boundary, kill switch, dedup, observability
  and rollback evidence.
- Deterministic short/medium/long Response Plans that remain independent of
  model tier and reasoning depth.
- Default-off proactive conversation probes and explicit scheduled digest
  subscriptions over governed public information sources.
- Durable time-zone-aware scheduling, source/item deduplication, proactive-send
  authorization, quiet hours, Outbox/claim semantics, delivery reconciliation,
  unsubscribe, shadow and rollback.
- Mew-source QQ client behavior over a typed server-side NapCat capability API.
- Concurrent multi-account chat, directory, notification, group-resource and
  settings workflows with account-scoped real-data persistence.
- A final authorized real-group scenario gate after all module, Web testing and
  local integration work is complete.
- An isolated S20 offline logging/support/OPE foundation that never controls
  safety, proactive behavior or the S23 prerequisite chain.
- A Web Bot Control Plane that onboards each new Bot/group binding through an
  administrator-selected, versioned initial service profile and routes every
  mutation through authoritative Core commands.

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
- [x] Production shape, additive semantic contracts, Unified MCP/iCourse
  migration, bounded Capability and Memory lifecycle/retrieval pass their local
  negative and compatibility contracts.
- [x] Response Profile selection, dynamic output budgeting and final length/
  completeness validation pass a task-complexity by answer-profile matrix.
- [x] Proactive probes and scheduled digests pass default-off, authorization,
  target-policy/grant binding, preview-without-delivery, stable business
  idempotency across Adapter revisions, fake-clock, concurrency, MCP-source,
  citation, deduplication, quiet-hour, unsubscribe, delivery and rollback
  contracts without using real groups.
- [x] Source-provider fixtures and S20 synthetic estimator goldens are clearly
  separated from live Source Adapters and online learning claims.
- [x] A newly joined group remains pending and receives no Agent service until
  an authorized Bot administrator previews and activates a versioned service
  profile through a CAS/idempotent/audited Core command.
- [x] The Control Plane displays desired versus effective services, uses
  operator authentication and exact Bot/account/group Scope, and proves that
  Group Context, plugins, models and Bandit cannot widen the assignment.
- [ ] After every earlier acceptance item and local audit passes, the authorized
  real-group shadow/canary records the frozen safety and SLO evidence.

All S01-S22 and Web criteria in their accepted local/offline scopes are
satisfied. Revision 4 completed S21A-S21C and S21 Audit before paused/partial
S23. S23 has additionally completed its private historical Demo, Control Plane
evaluation surface and one local 2.0 natural-language iCourse success slice;
environment-specific integration and a separately authorized external run
remain outside S21.

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
11. Close the production-shape gate: derived-image SQLite, Endpoint sampling
    semantics, health snapshots and the single rollout composition root.
12. Add the compatible semantic span/decision contract and complete its
    synthetic/Schema pilot without claiming real Chinese multi-turn quality.
13. Run the MCP v2 Client/Server migration Spike, then implement Unified MCP
    with iCourse as the original real Adapter and one Fake extension proof.
    The later campus expansion adds second-class, academic and curriculum MCP
    Servers without changing the Client control plane; shuttle uses the shared
    Capability Runtime through a local Builtin plugin.
14. Implement proactive outbound contracts and durable scheduling, then prove
    source-neutral contracts with fixed campus/arXiv/industry fixtures before
    digest Shadow and probe Shadow. Live Source Adapters remain external.
15. Run fake-clock long-duration simulation, fault injection, repository-wide
    regression and a new local expansion audit.
16. Complete S21 Bot Control Plane foundations, group onboarding and governed
    operations: an authorized administrator selects an initial group service
    profile and Runtime consumes only the resulting immutable assignment.
17. After S21 and every accepted local audit are complete, mount the user's
    external long-term group corpus only in the S23 test environment. Run
    full-corpus no-send historical Shadow, then a labeled quality sample,
    authorized single-group live Shadow, inbound canary, separately authorized
    digest/probe canaries, and only afterward layered expansion/debugging.

Tree revision 4 contains the response/proactive expansion, operations, layout,
Eval/CI, local audit, cleanup, offline Bandit, completed S21 Control Plane and
terminal real-group branch. The terminal branch depends on every accepted local
audit and cannot be entered merely because credentials arrive.

## Out Of Scope (project-wide exclusions; not branch ownership detail)

- Live Bandit exploration over send/skip, targets, schedules, subscriptions,
  answer profiles or other proactive behavior.
- Unsolicited private messages, individual targeting, sensitive/private MCP
  feeds, automatic Memory writes, image generation, broad rollout, Agent
  Console runtime integration and isolated collaboration repositories.

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
6. Real Endpoint enablement needs legal Provider/model identifiers, official
   capability/price/retention/residency evidence, fixed SDK/image revisions and
   low-quota synthetic conformance credentials. Missing inputs do not block
   Fake contracts.
7. Semantic, Probe and AnswerProfile quality claims need authorized data
   governance, a second annotator/reviewer and profile examples. Until supplied,
   only synthetic/Schema pilots and deterministic limits may be claimed.
8. Source rollout needs operator-frozen campus/publisher/category allowlists,
   arXiv revision policy, IANA zone, quiet hours, misfire window and item/rate
   limits. Public fixtures remain sufficient for Adapter contract development.
9. The repository now contains four real read-only query MCP Servers: iCourse,
   second-class, academic and curriculum, plus one local shuttle plugin. New live campus-news/arXiv/industry
   Source Adapters are still absent and are not prerequisites for the generic
   S12/S13 or fixture-based S15C acceptance boundaries.
10. The current local Dududa account history is approved for private
    development replay; the legacy local account is excluded and exact account
    mapping stays local. The separate hundreds-group long-term corpus remains
    unavailable and unnecessary until S23.
