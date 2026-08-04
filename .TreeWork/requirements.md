# Requirements

## User Intent (the outcome the user is trying to achieve; not a proposed implementation)

Continue long-running development of Dududa through S08-S11. Treat task
difficulty assessment and model routing as one integrated development scope,
and do not implement or connect Bandit learning yet.

## Target User (who experiences the result and whose constraints matter)

- The sole Dududa developer/operator needs a comprehensible, extensible system
  that can be developed and rolled back one verified step at a time.
- QQ users in an explicitly authorized test group eventually experience the
  direct-chat canary, while all other users remain on the existing AstrBot
  path.

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
- [ ] An authorized real-group shadow/canary run, when credentials and group
  authorization are supplied, records zero duplicate/wrong-target/unauthorized
  or sensitive-trace incidents and captures the frozen SLO evidence.
- [x] Existing S01-S07 tests and repository safety/import boundaries remain
  green; unrelated WebUI and Sub2API work is neither modified nor committed by
  this project.

The authorized real-group criterion remains unchecked because no group IDs,
credentials, authorization or send window were supplied. Local simulation and
an AstrBot image smoke are recorded separately and are not substituted for
external evidence.

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

## Confirmed Decisions (user-owned product choices and constraints; technical responses belong in spec.md)

1. Develop S08 through S11 as the current long-running objective.
2. Difficulty assessment and model routing are one integrated development
   scope.
3. The three logical tiers are `haiku`, `sonnet`, and `opus`.
4. Bandit is explicitly deferred.
5. Existing S01-S07 foundations and legacy production behavior are preserved
   unless an S08-S11 acceptance item requires an additive change.
