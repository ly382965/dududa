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
- iCourse remains the only real MCP Server. S12 now owns the Unified MCP Port,
  Registry, shared lifecycle and compatibility facade; S13 maps only four
  approved public cache-read Capabilities through the generic Provider. S22
  removed the plugin-dedicated per-call Client; the isolated worker still
  retains its evidenced legacy server-protocol compatibility mode.
- The current S09 Eval and Memory retrieval are narrower than their interface
  names imply: the former is synthetic policy gold, and the latter is exact
  Scope/TTL plus substring/recency rather than semantic retrieval.
- S18 makes root and isolated Unified MCP worker lock provisioning explicit in
  CI; fresh runs no longer rely on a pre-existing local worker environment.
- S23 offline readiness proves manifest structure only. A self-declared digest,
  `live` flag or authorized status never becomes executable evidence until live
  Preflight resolves it against the exact candidate, target and prior Receipt.
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
- Plugin, Group Context, Skill and Observatory contracts are future Alignment
  inputs. The research report does not modify the accepted Tree or establish
  implementation evidence for those interfaces.

## Research Candidates For Next Alignment (not accepted project decisions)

- The report recommends keeping governance authority in a non-removable kernel.
  Model, Memory, MCP, Persona, Source and observation implementations may become
  reversible realm-scoped plugins, while Identity, Scope, Authorization,
  Budget, WriteGate, Dispatch commit and Receipt authority stay fixed.
- The report recommends separating Group Context, Memory, relationship evidence,
  Skill candidates and Bandit. Group Context would be a time-decayed weak prior,
  relationship edges auditable evidence rather than social facts, and Bandit a
  ranker only over already legal safety-equivalent candidates.
- The report recommends a read-only Agent Observatory projected from authoritative
  Receipts and checkpoints, never a second Router, permission, Memory, MCP or send
  control plane. Any future mutation would require a dedicated governed command.

## Risks And Unknowns (project-wide residual hazards; not unfinished branch work)

- S01-S20/S22 and S23 offline readiness are locally committed but not pushed;
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
