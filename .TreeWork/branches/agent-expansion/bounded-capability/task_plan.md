# Task Plan

Branch: bounded-capability
Parent: agent-expansion
Title: S13 Bounded Capability Runtime

## Scope (owned work and boundary; not progress notes or implementation history)

- Strengthen the existing Capability Definition and add immutable Schema,
  Catalog, Mapping, health, query, plan, execution, Observation and validation
  contracts.
- Implement strict atomic Catalog loading, exact Provider resolution,
  deterministic eligibility/Top-K and bounded planning/binding/execution.
- Implement single-flight/idempotency, per-step authorization, limiter, budget,
  audit and fail-closed Observation validation using existing security Ports.
- Map the four approved iCourse cache-read Capabilities through the generic MCP
  Provider and prove a configuration-only Fake extension.
- Add a default-off local `USE_TOOLS` path to the existing Offline Runtime while
  retaining S10/S11 production behavior.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] Existing Core types are reused and strengthened; public S13 DTOs are
  immutable, versioned, bounded and canonical-digest bound without MCP SDK,
  AstrBot or iCourse imports.
- [ ] Catalog atomically binds Definitions, Schema documents, Provider
  descriptors and formal MCP Mappings and retains last-known-good after every
  invalid reload/publication case.
- [ ] Retrieval exposes only enabled, fresh-healthy, context/scope/privacy/risk/
  side-effect/permission/budget eligible Top-K candidates in stable order;
  denied definitions and rejection detail never leak to Planner.
- [ ] Planner output is limited to candidate ID+digest, a valid DAG, approved
  JSON Pointers and four attempts by default/eight hard; invalid or cyclic
  plans produce zero Provider calls.
- [ ] Binder reads only Validator-accepted successful Observations, validates
  the complete input Schema and cannot override fixed Mapping arguments.
- [ ] Executor re-resolves exact Catalog/Provider/Mapping/Schema and reauthorizes
  every permission at each attempt before limiter, budget, audit and dispatch.
- [ ] Stable logical-operation idempotency plus a bounded single-flight ledger
  prevents concurrent/replayed duplicate Provider calls and detects conflicts.
- [ ] Observations and errors are bounded, sanitized, Schema-checked and remain
  untrusted; stale/unknown/permission/Prompt-Injection/control-plane attempts
  fail closed and cannot become accepted facts.
- [ ] `icourse.stats.read.v1`, `icourse.courses.search.v1`,
  `icourse.course.get.v1(refresh=false)` and `icourse.reviews.get.v1` pass the
  same Provider Contract as a Fake; management/network/write Tools are absent.
- [ ] A second Fake becomes retrievable/executable through Server config,
  Definition, Mapping and permission fixture only, with no Domain, Runtime,
  generic MCP Client or generic Provider edit.
- [ ] Explicit `tools=true` plus injected Runtime traverses the three tool
  phases and produces a validated tool-assisted local response; default false,
  missing runtime, denied/budget/stale/failure cases never send or fall back.
- [ ] Synthetic course Eval reports fixed denominators for Recall@K,
  ineligible exposure, Plan/argument validity, completion and attempts without
  claiming real Chinese, Endpoint or live-service quality.
- [ ] Dual-Python, focused fault/negative tests, root regression, build/import,
  Web, secret, lock, Ruff, Compose/Shell and whitespace gates pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Freeze S13 Spec, canonical iCourse IDs, Schema document authority,
  permissions, health policy, ranking ceilings and terminal result contracts.
- [ ] Implement Capability contracts/digests/Ports and strengthen the existing
  `CapabilityDefinition` validation.
- [ ] Implement strict Config Catalog, immutable snapshots, Provider Registry,
  Health snapshots, atomic reload and last-known-good behavior.
- [ ] Implement deterministic authorization-aware Retrieval and synthetic
  ranking Eval.
- [ ] Implement deterministic Planner, Plan Validator and safe Argument Binder.
- [ ] Implement Executor, budget/limiter/audit integration, invocation ledger,
  Observation Validator and bounded loop.
- [ ] Implement generic MCP Provider, formal iCourse configuration and
  Fake/iCourse conformance plus config-only extension tests.
- [ ] Replace provisional Runtime aliases and add the default-off additive
  `USE_TOOLS` path with full state/budget/binding tests.
- [ ] Update current-status and developer documentation without changing
  historical Spike conclusions.
- [ ] Run full verification, synchronize TreeWork records and commit locally.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Real `TOOL_PLANNING` model Endpoint, training, Bandit or language-quality
  claims.
- Crawl, refresh, online search, robots, export, bulk operations, file/external
  writes, irreversible Tools or any new real MCP Server.
- S14 Memory, S15 ResponseProfile/Persona, S15C sources, Scheduler, proactive
  outbound or S23 real-group validation.
- Enabling S11 production tools, sending QQ, accessing live network/credentials,
  modifying a running container or deleting Legacy iCourse.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified S12 Unified MCP Client/Registry, iCourse facade and worker
   isolation.
2. Existing S03 security Ports/implementations and S09 Perception/Social
   contracts.
3. Existing S10 state phases, model response path and default-off rollout
   boundary.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: existing Capability Definition, security Ports, S12 MCP contracts,
  provisional mappings, Perception `need_tools`, S10 state phases and rollout
  tool prohibition.
- Reuse check: retain Actor/Scope, Authorization, Budget/Limiter/Audit,
  canonical JSON, Runtime Store, Model Router and Unified MCP ownership; do not
  create a second control plane or move Capability authority into MCP.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
