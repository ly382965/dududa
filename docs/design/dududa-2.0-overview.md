# Dududa 2.0 Design Overview

Status: Phase 1 design; implementation has not started.

Dududa 2.0 separates a framework-neutral Agent Runtime from AstrBot adapters,
MCP servers, model Providers, memory backends, and deployment. The repository
remains one Bot Runtime Monorepo so a single review can validate adapter,
runtime, service, operation, and compatibility changes together.

## Design Index

- Runtime and state machine: `runtime.md`
- Perception and Social Decision: `perception-and-social.md`
- Memory Scope, retrieval, and Write Gate: `memory.md`
- Capability and unified MCP runtime: `capability-and-mcp.md`
- Model-role routing: `model-routing.md`
- Persona and OC rendering: `persona.md`
- Security, privacy, audit, and rate limits: `security.md`
- Target repository layout: `repository-layout.md`
- Migration summary: `migration-plan.md`
- Full current-state evidence: `../refactor/current-state.md`
- Full target architecture: `../refactor/target-architecture.md`
- Detailed old/new mapping: `../refactor/migration-map.md`
- Reviewable phase plan: `../refactor/implementation-plan.md`

## Non-Negotiable Boundaries

1. Adapters convert external types; core never reads AstrBot Events.
2. Runtime owns explicit state and bounded transitions.
3. Memory Scope is exact and fail-closed before semantic retrieval.
4. Social Decision is independent of Persona.
5. Model Router and Tool Router are separate.
6. Planner sees normalized, eligible Top-K capabilities.
7. MCP transport is hidden behind one Client and Registry.
8. Response Composer protects truth; OC Renderer only changes expression.
9. Existing plugin IDs, commands, and deployment entry points remain compatible
   until tested removal gates pass.
10. Secrets and production state never enter repository code, fixtures, traces,
    evals, or documentation.

## Delivery Strategy

The design is delivered additively. A pure package is established and tested
first. Existing plugins then become compatibility adapters one behavior at a
time. Memory and tool boundaries cut over only after isolation and contract
tests exist. Deployment paths move last, with root wrappers and rollback.

No target box in these documents should be interpreted as implemented unless
the progress document and tests identify its production entry point.
