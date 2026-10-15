# Task Plan

Branch: mcp-v2-spike
Parent: agent-expansion
Title: S12A MCP V2 Spike

## Scope (owned work and boundary; not progress notes or implementation history)

- Pin an isolated MCP v2.0.0 Spike without changing the root v1 lock.
- Build a native v2 Fake and current iCourse v1 legacy fixture over stdio.
- Measure long-session, bounded concurrency, timeout, cancellation, crash,
  generation, Schema-drift and resource-close behavior.
- Commit a sanitized machine-readable report and an adopt/reject ADR.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] The root workspace and iCourse remain on MCP v1.29 during the Spike; v2 dependencies are independently locked.
- [x] A native v2 Fake and v1 iCourse legacy fixture pass one shared discovery/call/close contract without network or real cache access.
- [x] One entered Client performs 100 sequential calls with exactly one process/session and one initial discovery.
- [x] Twenty calls under a concurrency limit of four never exceed four active Fake handlers or start another process/session.
- [x] Connect/handshake, discovery and tool-call deadlines fail in bounded time with stable classifications.
- [x] Cancel and close leave no live child process, Spike-owned task or material file-descriptor leak.
- [x] Crash-before-effect and crash-after-effect are distinguished; unknown outcomes have zero automatic retries.
- [x] A crashed generation is retired and a newly initialized generation recovers without reusing old state.
- [x] Incompatible Schema drift is observed but not published; last-known-good remains bound and discovery grants no Capability.
- [x] The committed report is sanitized, digest-bound and reproducible on Python 3.10/3.12.
- [x] An ADR records ADOPT/REJECT/DEFER and accurately limits what the result proves.
- [x] Focused Spike, root regression, import, secret, build and whitespace gates pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Add the isolated PEP 723 dependency lock and stdio fixture instrumentation.
- [x] Implement native v2 and iCourse legacy shared contract probes.
- [x] Implement sequential/concurrency, deadline/cancel and resource-leak probes.
- [x] Implement crash phase, generation recovery and unknown-outcome probes.
- [x] Implement canonical Schema snapshot/drift publication probes.
- [x] Generate/check the sanitized report and write the decision ADR.
- [x] Run Python 3.10/3.12 and repository verification.
- [x] Record Verification, Findings and the coherent local commit.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Production `UnifiedMcpClient`, Registry, Schema store, retry or circuit breaker.
- iCourse Server upgrade, plugin migration, Capability Runtime or tool exposure.
- Real cache, crawl, export, network source, credentials, AstrBot/NapCat or QQ.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Completed Production Shape and additive S09 semantic entry gates.
2. Accepted ADR 0004 and the MCP lifecycle research report.
3. Current v1 iCourse Server and locked root Python environment.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: iCourse FastMCP Server, dedicated Client, root lock, MCP config,
  ADR 0004 and existing offline handshake.
- Reuse check: retain the current Server and empty-DB handshake as the legacy
  fixture; do not turn the Spike harness into the production Client.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
