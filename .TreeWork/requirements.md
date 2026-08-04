# Requirements

## User Intent (the outcome the user is trying to achieve; not a proposed implementation)

Continue long-running development of Dududa beyond the completed local S08-S11
runtime by adding a real QQ multi-account Web client. Reproduce the observable
QQ-client functionality of USTC-XeF2/mew-ui as closely as NapCat permits while
retaining Dududa's server-side OneBot boundary and without shipping demo data.

## Target User (who experiences the result and whose constraints matter)

- The sole Dududa developer/operator needs a comprehensible, extensible system
  that can be developed and rolled back one verified step at a time.
- QQ users in an explicitly authorized test group eventually experience the
  direct-chat canary, while all other users remain on the existing AstrBot
  path.
- The Dududa operator uses one browser workspace to read and operate multiple
  real QQ accounts connected by NapCat, with Mew-equivalent chat, directory,
  notification, group-management, resource and settings workflows.

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
- The first complete runtime handles explicit mentions, direct chat only, with
  tools and memory disabled. Shadow execution has no user-visible or persistent
  side effects.
- Canary delivery is restricted to an allowlisted group and explicit mention,
  supports a kill switch, prevents duplicate replies, and preserves the legacy
  route as the rollback authority.
- The Web client opens directly into a Mew-style workspace when NapCat accounts
  are online and otherwise shows an honest connection state. It has no browser
  login, locally invented account, conversation, message or Agent result.
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

- Contextual Bandit, learned online exploration, random weighted routing, or
  counterfactual policy claims.
- Tool/MCP execution, Memory retrieval or automatic writes, free-form proactive
  group interruption, image roles, multiple personas, or broad production
  rollout.
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
- Features that Mew itself does not implement, including calls/recording,
  temporary sessions, friend add/delete, message editing, red packets,
  location, announcement publishing and per-member mute management.

## Confirmed Decisions (user-owned product choices and constraints; technical responses belong in spec.md)

1. Develop S08 through S11 as the current long-running objective.
2. Difficulty assessment and model routing are one integrated development
   scope.
3. The three logical tiers are `haiku`, `sonnet`, and `opus`.
4. Bandit is explicitly deferred.
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
10. Browser identity authentication remains removed for the local deployment.
    The OneBot Access Token remains mandatory between NapCat and the server and
    never enters the browser.
11. The Agent Console runtime is deferred until QQ/Mew parity is independently
    implemented and audited.
12. Real group-chat scenario testing runs last, after all accepted modules,
    Web testing work and local integration audits are complete. Bandit remains
    separately deferred and is not pulled into the critical path by this rule.
