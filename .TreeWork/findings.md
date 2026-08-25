# Global Findings

## Decisions (project-wide conclusions learned during development; planned pre-coding design belongs in spec.md)

- The initial perception model must be statically pinned to `haiku`; otherwise
  difficulty-based selection is recursively dependent on itself.
- Complexity evidence and endpoint routing are one pipeline but not one module.
- Load snapshots are advisory eligibility evidence; atomic admission is required
  to prevent concurrent overbooking.
- S11 cannot use an image-only rollback because plugin source is bind-mounted;
  the rollback artifact must cover both image and plugin/config revision.
- Real group-chat testing is a terminal validation stage. It must not interrupt
  unfinished module or Web testing work, and Bandit remains outside this
  critical path.
- Local environment readiness and production readiness are separate claims.
  The locked dual-Python/Node toolchain is green, while the running AstrBot
  remains disconnected from Dududa Core and fails four production-shape gates.
- Static routing remains the authority. Learning may later reorder only legal
  same-role/tier compatibility classes after admission-aware propensity and
  feedback contracts exist; Provider failure/fallback cannot reuse a sampled
  action's propensity.
- Response length, model tier and reasoning effort are independent decisions.
  Initial length numbers are pilot defaults and must not become enum semantics.
- MCP transports approved capabilities but owns neither Schema freshness,
  scheduling nor delivery. Scheduler occurrence/CAS remains Dududa-owned.
- iCourse was the original real MCP Server. The Registry now contains four
  read-only query Servers and 17 Capability mappings: iCourse, second-class,
  academic and shuttle. S12 still owns the single Unified MCP Port, Registry and
  shared lifecycle; S22 removed the plugin-dedicated per-call Client. Natural-
  language Agent planning currently closes only the iCourse `query` slice; the
  other mappings are Control Plane-callable facts, not automatic Planner proof.
- The current S09 Eval and Memory retrieval are narrower than their interface
  names imply: the former is synthetic policy gold, and the latter is exact
  Scope/TTL plus substring/recency rather than semantic retrieval.
- S18 makes root and isolated Unified MCP worker lock provisioning explicit in
  CI; fresh runs no longer rely on a pre-existing local worker environment.
- S23 offline readiness proves manifest structure only. A self-declared digest,
  `live` flag or authorized status never becomes executable evidence until live
  Preflight resolves it against the exact candidate, target and prior Receipt.
- The accepted long-horizon product shape is a governed group-context adaptive
  Runtime: a non-removable governance kernel composes reversible scope-bound
  capabilities, while learned outputs remain evaluated candidate assets and
  Bandit ranks only safe-equivalent legal actions.
- Web is a first-class Bot Control Plane, not an observation-only test surface.
  It forms one logical control plane with typed Core command handlers; the
  browser and Web gateway do not duplicate Authorization, Router, Memory,
  Capability, Scheduler or Output authority.
- Group onboarding supplies the hard initial condition. A newly joined group is
  pending until an authorized Bot administrator selects a versioned
  `GroupServiceProfile`; learned Group Context may adapt expression but cannot
  enable services, permissions, Memory, proactive behavior or delivery.
- The current NapCat version interprets historical direction as
  `before -> reverse_order=true` and `after -> reverse_order=false`. The deployed
  Web Gateway had this mapping reversed, causing repeated pages; source and its
  focused server contract were corrected without restarting NapCat.
- The approved local `嘟嘟哒` development replay processed 84,159 usable log
  records plus 1,464 structured Gateway records. After 83 current-Bot
  self-message admission skips, 85,540 records completed the deterministic
  policy path with no module exception. Rules-only Perception selected SONNET
  for every assessed item because its fallback confidence is 0.59; this is
  conservative defaulting, not real difficulty calibration.

## Interface Or Contract Effects (effects crossing branch or product boundaries)

- Semantic v2 is additive: existing Perception ports and v1 readers remain;
  spans, linguistic references and `ACCEPT | CLARIFY | ABSTAIN` add evidence
  without moving structural reply/mention authority out of Connector.
- Real Provider enablement becomes a per-Endpoint, digest-bound conformance
  artifact. Registry configuration alone cannot assert limits, reasoning,
  sampling, usage, cancellation, residency, retention or health.
- `ResponsePlan` is one immutable authority consumed by Router budgeting,
  Composer, Persona and final validators; no later component reselects profile.
- Memory rankers receive only already Scope/TTL/visibility-filtered candidate
  IDs. Repository, WriteGate, deletion and export remain Core authorities.
- MCP extensibility is proven by adding a Fake through Registry configuration
  and Capability mapping while reusing the same Contract. It is not proven by
  AstrBot merely preserving an unknown Server entry in its JSON file.
- S21 now implements the accepted offline Control Plane contracts and group
  onboarding through revision 4. Plugin lifecycle, Group Context and Skill
  evolution remain long-horizon design inputs without implementation evidence.

## Risks And Unknowns (project-wide residual hazards; not unfinished branch work)

- S01-S22 and S23 offline readiness are locally committed but not pushed;
  the control branch plus the paused managed S23 worktree remain the authority.
- Native DeepSeek and Anthropic model IDs/capabilities must remain Adapter
  configuration until verified; endpoint aliases cannot be treated as facts.
- The workspace does not establish authorization or credentials for a real QQ
  group canary.
- Token underestimation, stale load snapshots, duplicate delivery after restart,
  prompt-injected tier requests, and cross-tier privacy drift require explicit
  negative tests.
- The running AstrBot SQLite 3.46.1 is affected by the official WAL-reset bug;
  multi-connection WAL tests and durable rollout remain blocked until the image
  or journal strategy changes.
- Real semantic/Probe evaluation needs authorized de-identified group windows,
  independent annotation and adjudication. Silence remains censored evidence,
  not a negative reward.
- The user has an external long-term corpus spanning hundreds of groups, but it
  is intentionally withheld until the S23 test environment. The approved local
  Dududa corpus remains available for private no-send development replay.
