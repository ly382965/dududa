# Requirements

## User Intent (the outcome the user is trying to achieve; not a proposed implementation)

Continue long-running development of Dududa beyond the completed local S08-S11
runtime and Mew/NapCat Web client. Complete every S12-S22 engineering outcome
that can be proven with local Fakes, fixtures, injected clocks and derived test
images, including deterministic answer planning and controlled proactive
outbound foundations, while retaining the existing security, rollback and
terminal real-group gates. Missing credentials, live sources and human data do
not block this offline development scope and must not be fabricated.

The confirmed long-horizon product direction is a governed group-context
adaptive Runtime with a first-class Web Bot Control Plane. When a Bot joins a
group, an authorized Bot administrator selects the initial group service
profile. Models and learned group context may adapt only inside that profile;
they never activate services, grant capabilities, or widen side effects.

## Target User (who experiences the result and whose constraints matter)

- The sole Dududa developer/operator needs a comprehensible, extensible system
  that can be developed and rolled back one verified step at a time.
- QQ users in an explicitly authorized test group eventually experience the
  direct-chat canary, while all other users remain on the existing AstrBot
  path.
- An operator explicitly enables each proactive target and subscription. Group
  members experience bounded, attributable messages with quiet hours,
  frequency limits, source citations, pause/unsubscribe controls, and no hidden
  individual targeting.
- The Dududa operator uses one browser workspace to read and operate multiple
  real QQ accounts connected by NapCat, with Mew-equivalent chat, directory,
  notification, group-management, resource and settings workflows.
- An authorized Bot administrator uses the same Web control backend to onboard
  a newly joined group, preview the eligible service bundle, choose its initial
  service profile, and later pause, revise or roll it back with an audit trail.

## Desired Experience (observable behavior and qualities the user expects)

- Dududa first understands a message with a cheap, bounded perception path,
  then deterministically selects a lightweight (`haiku`), medium (`sonnet`), or
  professional (`opus`) tier for the downstream model role.
- Each physical model endpoint declares its Provider-native model ID,
  reasoning support, context limits, privacy boundary, health, and traffic
  capacity without Core guessing from a marketing name.
- Low-confidence or conflicting difficulty evidence uses a conservative
  deterministic default; user prompt text cannot force an expensive tier or
  bypass safety and privacy filters.
- Dududa selects a versioned `short`, `medium`, or `long` answer profile for
  each visible response. Answer profile, model tier, and reasoning depth remain
  independent: a deep task may require a short answer, and a simple task may
  legitimately request a long enumerated result.
- In an explicitly enabled allowlisted group, Dududa may initiate one bounded
  topic-relevant probe after deterministic eligibility, quiet-hour, cooldown,
  target, and delivery checks. A probe does not target an individual, read
  personal Memory, or automatically follow up when nobody responds.
- Explicit subscriptions may schedule campus public information, allowlisted
  industry updates, and recent arXiv items in an IANA time zone. MCP-backed
  capabilities retrieve normalized public source items; Scheduler, policy,
  composition, authorization, delivery, and unsubscribe remain Dududa-owned.
- iCourse is the only currently implemented real MCP Server. Dududa exposes one
  framework-neutral MCP Client and Server Registry so later Servers require
  configuration and explicit Capability mapping rather than Core changes or a
  copied Client. Fixed Fake Servers prove this extension boundary without
  pretending that other production MCPs already exist.
- The first complete runtime handles explicit mentions, direct chat only, with
  tools and memory disabled. Shadow execution has no user-visible or persistent
  side effects.
- Canary delivery is restricted to an allowlisted group and explicit mention,
  supports a kill switch, prevents duplicate replies, and preserves the legacy
  route as the rollback authority.
- The existing QQ workspace opens directly into a Mew-style client when NapCat
  accounts are online and otherwise shows an honest connection state. Its
  current loopback data path has no browser login or locally invented account,
  conversation, message or Agent result. Future Control Plane routes separately
  require an authenticated operator identity.
- Multiple NapCat accounts remain connected concurrently. Every conversation,
  request, message, draft, cache entry, unread state and capability is isolated
  by `accountId`, while the operator may use either an account filter or a
  combined inbox.
- The chat experience includes the Mew source baseline's virtualized history,
  rich message segments, reply/mention/face/media/file composition, message
  actions, search, drafts and stable desktop/mobile navigation where the
  connected NapCat exposes the required capability.
- Contacts, notifications, group members, group management, announcements,
  essence messages, group files and storage/settings surfaces behave like Mew
  where NapCat has an equivalent action. Unsupported actions are disabled with
  an explicit reason rather than simulated.
- NapCat remains the authoritative QQ data source. Browser persistence may
  cache only real NapCat-derived messages, coverage metadata, conversations and
  drafts; clearing it never changes QQ server data and the UI remains honest
  when a history range cannot be recovered.
- A newly discovered Bot/group binding starts in `PENDING_PROFILE`. No Agent
  service is activated until an authorized Bot administrator selects and
  confirms a versioned `GroupServiceProfile` through the control backend.
- The selected profile supplies initial values for service membership, Persona,
  trigger policy, response defaults, model-budget policy, Memory mode and
  proactive defaults. Effective services are always the intersection of the
  requested profile, installed/healthy implementations, current grants and
  rollout policy; unavailable or unauthorized services remain visibly inactive.
- Group Context and later learning are soft, time-bound evidence. They may tune
  expression within the active profile but cannot mutate the profile, enable an
  MCP/Capability, turn on Memory or proactive delivery, select a physical model
  endpoint, or grant send authority.
- Web is the product Bot Control Plane, backed by the same authoritative Core
  command handlers and projections used by other adapters. The browser does not
  become a second policy engine and never writes runtime stores or calls Agent
  side effects directly.

## Success Criteria (testable outcomes that show the need was met)

- [x] S08 provides versioned immutable model-selection contracts, a validated
  registry, deterministic tier/endpoint selection, atomic capacity admission,
  bounded retry/failover/fallback, a Fake Provider, and one real compatible
  Adapter sharing Provider contract tests.
- [x] S09 provides Rule and Model Perception, whole-result validation,
  deterministic merging and social decision, a versioned complexity
  assessment, a deterministic TierPolicy, and a reproducible synthetic or
  sanitized evaluation set and report.
- [x] The bootstrap `PERCEPTION` call always uses an allowed `haiku` endpoint;
  only the validated assessment influences the later `DIRECT_CHAT` tier.
- [x] S10 runs the offline sequence Connector -> Context -> Perception ->
  Complexity -> TierPolicy -> Router -> Direct Chat -> Composer -> one
  deterministic Persona renderer -> DeliveryRequest/receipt, with total
  deadline, cancellation, budget, state, and route receipts verified.
- [x] S10 shadow tests prove zero calls to real delivery, memory write, tool
  execution, and event stopping while the old path remains authoritative.
- [x] S11 provides typed off/shadow/canary configuration, persistent dedup and
  delivery tombstones, allowlist and explicit-mention ownership, a second
  pre-delivery kill-switch check, sanitized metrics, and an executable rollback
  procedure.
- [x] Existing S01-S07 tests and repository safety/import boundaries remain
  green; unrelated Sub2API work is neither modified nor committed by this
  project.
- [x] The production Web build contains no demo QQ or Agent data and obtains
  accounts, conversations, history, events and mutation results only from an
  authenticated server-side NapCat connection.
- [x] Two concurrent NapCat accounts can be exercised without cross-account
  request, message, cache, draft, unread, upload or capability leakage.
- [x] Mew's chat, contacts, notifications, group members/management/resources
  and settings behaviors are reproduced for every mapped NapCat capability,
  with explicit disabled states for confirmed protocol gaps.
- [x] Text, links, reply, mentions, QQ faces, custom faces, images, audio,
  video, files, forwarded messages, Markdown/light-app content and unknown
  segments have tested send/display or honest fallback behavior as applicable.
- [x] History pagination, virtual scrolling, unread positioning, local search,
  drafts, cache cleanup and recovery are verified on account-scoped real-data
  caches across desktop and mobile viewports.
- [x] The OneBot token, QQ credentials, raw local paths and unrestricted OneBot
  action access never reach the browser; destructive actions use a typed
  server allowlist and the unauthenticated Web service remains loopback-only.
- [x] The pre-S12 production shape installs one default-off Runtime composition,
  projects only proven sampling parameters, publishes bounded health snapshots
  and uses a SQLite strategy outside the known WAL-reset hazard, with partial
  startup and shutdown verified offline.
- [x] The additive S09 semantic contract preserves v1 readers and Connector
  authority while adding validated spans, entity/reference evidence and
  `ACCEPT | CLARIFY | ABSTAIN`; synthetic evidence is not called real Chinese
  quality.
- [x] S12 provides a framework-neutral Unified MCP Client, multi-Server
  Registry, per-Server lifecycle and Dududa-owned Schema snapshots. iCourse and
  a Fake Server pass the same Contract, and adding the Fake requires no Domain,
  Runtime or generic Client change.
- [x] S13 maps only explicitly approved business Capabilities to MCP tools and
  fails closed for unauthorized, stale, unknown, injected or over-budget plans;
  dynamic discovery never grants permission.
- [x] S14 closes Memory write/read/delete/export/conflict/recovery behavior and
  a CJK lexical baseline without cross-Scope, expired or deleted records
  becoming visible.
- [x] A versioned Response Plan deterministically selects short/medium/long,
  binds visible character/token/part limits, respects explicit current-message
  detail requests, and is consumed by Router, Composer, Renderer, and final
  validation without equating answer length to model tier.
- [x] Proactive conversation probes are default-off and require a target-bound
  proactive-send authorization, allowlist, quiet hours, persistent occurrence
  claim, global/per-scope frequency budget, pre-send kill-switch recheck,
  delivery reconciliation, and a no-response cooldown.
- [x] Scheduled subscriptions use durable time-zone-aware occurrences,
  bounded misfire handling, source and delivery deduplication, public read-only
  Capability/MCP results with freshness and citations, and effective
  pause/unsubscribe/revision invalidation before delivery.
- [x] S15C defines a source-neutral Provider and normalized source contract and
  proves it with local campus/arXiv/industry fixtures. It does not claim live
  Adapters or create fictitious MCP Servers.
- [x] Offline/fake-clock and recommendation-only shadow evidence records zero
  wrong-target, duplicate, quiet-hour, revoked-subscription, uncited,
  prompt-injected, sensitive-trace, or unauthorized-send incidents before any
  proactive real-group canary is considered.
- [x] S16-S19 and S22 provide offline operations, migration, Eval/CI, full local
  integration and evidence-based compatibility cleanup with a recoverable
  previous release; S20 provides only replayable offline Bandit contracts and
  synthetic estimator goldens.
- [ ] Group onboarding records a Bot/account/group-scoped pending state, and an
  authorized administrator can preview and activate exactly one versioned
  `GroupServiceProfile` with expected-revision CAS, idempotency, Audit Receipt
  and last-known-good rollback.
- [ ] The control backend separately exposes desired and effective services,
  rejects unavailable or unauthorized selections, and publishes one immutable
  assignment snapshot consumed by Runtime without browser-local authority.
- [ ] Group Context, Skill candidates and Bandit cannot modify service
  assignment, Capability grants, Memory/proactive enablement, target, schedule
  or send authority; negative tests prove those boundaries.
- [ ] Agent-generated draft approval and every Control Plane mutation use typed
  governed commands and authoritative Receipts. The current direct-NapCat draft
  path and browser-local permission/config placeholders are absent from the
  connected Agent flow.
- [x] Local development may replay only the current locally authorized Dududa
  account's group records through a no-send private runner. The legacy local
  account is excluded; its exact account mapping remains a local runtime input.
  Raw message bodies and group/member/message identifiers are not committed as
  fixtures or reports.
- [ ] The user's external long-term corpus covering hundreds of groups is first
  introduced inside the S23 real-test environment. It is not an S21 dependency;
  full-corpus replay supplies compatibility/distribution evidence while quality
  claims require a separately labeled human sample.
- [ ] Only after every accepted module, Web testing task and local integration
  audit is complete, an explicitly authorized real-group shadow/canary run
  records zero duplicate, wrong-target, unauthorized-send or sensitive-trace
  incidents and captures the frozen SLO evidence.

The authorized real-group criterion is a final project-stage gate. It does not
block the completed local S08-S11 scope and must not start while any accepted
module, Web testing task or local integration audit remains incomplete. Local
simulation and AstrBot image smoke remain separate evidence and are not
substituted for the later external run.

## Non-Goals (explicit boundaries; not a backlog of unrelated future ideas)

- Using Contextual Bandit or another learner to choose proactive send/skip,
  target group/user, subscription topic, schedule, frequency, answer profile,
  or follow-up behavior. S20 may optimize only separately approved safe
  decision points such as same-tier model endpoints.
- Free-form or default-on proactive interruption, unsolicited private messages,
  automatic personal targeting, repeated unanswered probes, or broad
  production rollout.
- Private/sensitive campus records, arbitrary-URL crawling, MCP-managed
  scheduling/sending, automatic Memory writes, image roles, or multiple
  personas in the first proactive release.
- Treating a Fake, fixture, planned source or configuration placeholder as a
  second real MCP Server or a live public-source Adapter.
- Dynamic cost/latency optimization across Providers; health and load only
  determine eligibility in this scope.
- Replacing the legacy AstrBot Handler before the S11 canary gates pass.
- Sending a real QQ message without explicit test-group authorization and
  configured credentials.
- Implementing QQ login or the QQ protocol itself; NapCat remains responsible
  for interactive login and QQ connectivity.
- Claiming exact parity for capabilities absent from the connected NapCat,
  currently including QQ-synchronized peer pinning, group-folder rename and
  complete historical friend-request retrieval.
- Connecting or simulating the Agent Console runtime in the Mew parity epic.
  Agent sessions, model controls and reply approval remain a separate project
  branch and the UI must show an honest unavailable state until then.
- Letting the browser, a model, Group Context or a plugin grant service access,
  edit Core policy stores directly, or bypass governed commands merely because
  Web is the product Control Plane.
- Features that Mew itself does not implement, including calls/recording,
  temporary sessions, friend add/delete, message editing, red packets,
  location, announcement publishing and per-member mute management.

## Confirmed Decisions (user-owned product choices and constraints; technical responses belong in spec.md)

1. Develop S08 through S11 as the current long-running objective.
2. Difficulty assessment and model routing are one integrated development
   scope.
3. The three logical tiers are `haiku`, `sonnet`, and `opus`.
4. Bandit is a later S20 scope and remains prohibited for proactive send/skip,
   target, schedule, frequency, subscription, and answer-profile decisions.
5. Existing S01-S07 foundations and legacy production behavior are preserved
   unless an S08-S11 acceptance item requires an additive change.
6. USTC-XeF2/mew-ui commit `97df34b3c8ca1747b92003fa3bb6566a58668a3f`
   is the accepted QQ-client source and observable behavior baseline.
7. NapCat/OneBot, not Milky and not browser-local fixtures, is the production QQ
   backend.
8. Dududa's concurrent multi-account runtime is preserved even though Mew has a
   single active client.
9. Browser persistence is allowed only for real NapCat data, drafts and derived
   UI metadata; it is never an alternate QQ source.
10. Browser identity authentication remains absent from the existing local QQ
    workspace. S21 Control Plane queries and mutations require a separate
    authenticated operator session; loopback origin, QQ role and the OneBot
    Access Token are not administrator identity. The OneBot token remains
    server-only.
11. The Agent Console runtime was deferred until QQ/Mew parity was independently
    implemented and audited. That prerequisite is now complete; its next role
    is the Web Bot Control Plane, not a browser-local Agent simulator.
12. Real group-chat scenario testing runs last, after all accepted modules,
    Web testing work and local integration audits are complete. Static inbound
    canary runs before separately authorized digest and probe canaries.
13. Visible answers have three profiles: `short`, `medium`, and `long`.
    Response profile, model tier, and reasoning depth are separate authorities;
    Router consumes the resulting budget but does not infer the profile.
14. Conversation probes and scheduled digests are default-off initiated runs,
    not forged Connector messages. They require a dedicated proactive-send
    permission, exact target Scope, durable claim, and pre-send revalidation.
15. MCP is an optional infrastructure path for public source retrieval only.
    It never owns schedules, subscriptions, target selection, policy, message
    composition, or delivery.
16. iCourse is the only real MCP Server in the current repository. S12 builds
    the reusable Client/Registry/Capability boundary and uses a Fake as the
    second conformance implementation; it does not invent other real Servers.
17. S15C completes source contracts and fixed fixtures only. Real campus,
    arXiv and industry Adapters remain external work until their sources and
    operator policies are supplied.
18. The current Goal may complete S20's offline decision/log/support and
    estimator foundations, but may not train, run a production worker, or
    perform Shadow/live exploration.
19. The current local `嘟嘟哒` corpus may be read by the private no-send
    development replay explicitly approved on 2026-08-14. No external corpus,
    S23 live behavior, real Provider call, live source fetch or running-container
    mutation is authorized by the next S21 Goal.
20. Dududa's long-horizon architecture is a governed group-context adaptive
    Runtime: a non-removable governance kernel composes reversible, observable,
    scope-bound capability plugins, while self-improvement remains evaluated,
    reversible candidate assets and Bandit ranks only safe-equivalent actions.
21. Web is a first-class Bot Control Plane. It may expose governed mutations,
    but the UI/API cannot duplicate Router, Authorization, Memory, Capability,
    Scheduler or Output authority; it calls the same typed Core commands.
22. When the Bot joins a group, an authorized Bot administrator chooses a
    versioned initial `GroupServiceProfile`. No model or learned context may
    enable services or permissions, and missing selection fails closed.
23. External long-term records from hundreds of groups remain outside the
    development workspace until S23. Historical replay precedes any real send;
    raw history alone is not Memory truth, semantic gold or Bandit feedback.
