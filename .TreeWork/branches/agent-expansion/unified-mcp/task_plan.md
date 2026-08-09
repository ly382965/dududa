# Task Plan

Branch: unified-mcp
Parent: agent-expansion
Title: S12 Unified MCP

## Scope (owned work and boundary; not progress notes or implementation history)

- Add framework-neutral MCP contracts, digests and Ports to Core.
- Add a strict configuration-backed multi-Server Registry and atomic reload.
- Implement a governed per-Server Client with Schema, retry, circuit and
  lifecycle ownership.
- Isolate MCP v2 in a locked transport-only worker while retaining iCourse v1.
- Migrate `ICourseClient` through the unified Port with an explicit legacy
  rollback implementation.
- Prove Fake/iCourse conformance, config-only extension and derived-image shape.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Core imports no MCP SDK, AstrBot or iCourse type and exposes versioned immutable MCP DTOs plus one `UnifiedMcpClient` Port.
- [x] Registry snapshots strictly bind every endpoint, SecretRef, allowlist, timeout, retry, circuit, concurrency and Schema-freshness fact and retain last-known-good on invalid reload.
- [x] The root/AstrBot/iCourse environment remains on MCP v1.29 while a separately locked worker uses MCP v2.0.0 without forming a second governance plane.
- [x] Each Server has one long-lived session/generation, isolated concurrency, health and circuit state; config change or disconnect closes the old generation.
- [x] Discovery is canonical, bypasses SDK cache authority, publishes compatible facts atomically and grants zero Capability.
- [x] Stale, expired, missing or incompatible allowlisted Tool Schema fails closed while last-known-good evidence remains bound.
- [x] Deadlines and cancellation cover connect/discover/semaphore/call/backoff/close without task, pipe or child leaks.
- [x] Retry is bounded by semantics, caller budget and deadline; unknown outcomes and unkeyed non-idempotent work are never retried.
- [x] Results and errors are bounded, immutable, Schema-checked and sanitized; raw transport details and secret values never reach consumers.
- [x] Native v2 Fake and local empty-DB iCourse v1 pass the same worker/session Contract with no live network or real cache access.
- [x] Adding a second Fake uses only Registry configuration and a Capability mapping fixture, with no Domain, Runtime or generic Client edit.
- [x] `ICourseClient` forwards through Unified MCP, explicit legacy rollback remains selectable, and plugin termination closes the complete lifecycle.
- [x] iCourse management Tools are absent from model Capability fixtures; the first mapping surface contains approved public read-only queries only.
- [x] The AstrBot-native iCourse template is disabled as a business path; course commands preserve blocked/role gates and the iCourse limiter survives across Tool calls.
- [x] Dual-Python, focused fault injection, root regression, build/import, derived-image, Web, secret, lock, Ruff and whitespace gates pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Implement MCP contracts, validation, digests and Core Port exports.
- [x] Implement strict JSON Registry, snapshots, reload and Fake resolvers.
- [x] Implement managed lifecycle, Schema publication, result normalization,
  deadline/cancel, retry and circuit state machine against Fake sessions.
- [x] Implement the locked MCP v2 worker and parent subprocess session Adapter.
- [x] Add iCourse and Fake configuration/mapping fixtures plus shared Contract.
- [x] Migrate the iCourse facade/composition/lifecycle and preserve explicit
  legacy rollback.
- [x] Disable the raw AstrBot MCP template and add course permission, cooldown
  and server-limiter regression coverage.
- [x] Update derived image and operator/development documentation.
- [x] Run focused and full verification, synchronize TreeWork records and
  commit the branch coherently.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- S13 Capability Registry, Retrieval, Planner, Executor, Observation/Validator.
- Any real Server other than iCourse or any live campus/arXiv/industry source.
- Real credentials, HTTP endpoint traffic, crawl/export, Provider calls or QQ.
- Deleting the legacy iCourse Client, changing its SQLite schema/path or
  modifying a running AstrBot/NapCat container.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Verified S12A ADOPT evidence and ADR 0006.
2. ADR 0004, root S12/S13 Spec and current iCourse/AstrBot compatibility paths.
3. Locked MCP v1 root environment and independently locked MCP v2 worker.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: current iCourse Server/Client/config, plugin composition/lifecycle,
  Core Port/Registry/error patterns, S12A worker lifecycle evidence and image.
- Reuse check: retain the iCourse Server, DB path, command surface, Core call
  contexts/errors/canonical JSON and S12A v2 dependency evidence; do not copy
  a Client per Server or move Capability authority into MCP.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
