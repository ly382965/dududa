# Branch Spec

Branch: mcp-v2-spike
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Purpose And Decision Boundary

Decide whether Dududa may adopt MCP Python SDK v2 for the S12 production
Client/Server migration. This branch produces a pinned, repeatable transport
and lifecycle experiment plus an adopt/reject ADR. It does not implement
`UnifiedMcpClient`, `McpServerRegistry`, Capability mapping, retry/circuit
policy or an iCourse migration.

The decision is fail-closed. A nominal handshake is insufficient: adoption
requires evidence for long-lived sessions, cancellation cleanup, crash
recovery, unknown outcomes, Schema drift and legacy compatibility. A failed
hard gate records `REJECT` or `DEFER` and blocks the `unified-mcp` branch rather
than adding speculative compatibility code.

### Dependency And Fixture Isolation

The root workspace remains pinned to MCP v1.29 because the current iCourse
FastMCP Server imports APIs removed by v2. The Spike uses a PEP 723 script with
an independent lock pinned to `mcp==2.0.0`; it never changes the root lock or
the iCourse dependency declaration before the decision.

Two local stdio fixtures exercise the same transport contract:

- a native v2 Fake Server, self-spawned by the isolated Spike runtime;
- the current v1 iCourse Server, started with the caller's locked root Python,
  an empty temporary SQLite database and explicit `mode=legacy`.

The iCourse fixture calls only `list_tools`, `icourse_stats` and cached
read-only queries. It does not crawl the network, export data, read the real
cache or use AstrBot/NapCat. A child-only `sitecustomize` guard denies socket
connections and SQLite paths other than the temporary fixture database; its
audit journal supplies the zero-network and zero-off-policy-read evidence. A
stdlib process wrapper records starts and PIDs in a temporary journal;
instrumentation never enters production code.

Python 3.10 and 3.12 runs use separate uv cache roots. `uv run --script` may
otherwise resynchronize the same content-addressed PEP 723 environment while a
second interpreter is using it, which is not valid cross-version evidence.

### Session And Generation Experiment

One entered v2 `Client` owns one stdio process/session. The harness discovers
once, performs 100 sequential calls, then performs 20 concurrent calls under a
four-call semaphore. The Fake reports observed active concurrency; the process
journal proves the lifecycle starts exactly once. Reconnect is explicit: after
a terminal transport failure the old Client is closed, its generation is
retired, and a new Client performs a new handshake/discovery before use.

The Spike does not treat SDK response cache as Schema authority. Discovery is
requested with cache bypass, canonicalized by the harness and published only
into a test-owned last-known-good snapshot. Discovery changes facts but always
records zero Capability grants.

### Failure And Cancellation Semantics

The native Fake exposes deterministic modes for delayed handshake/discovery,
slow calls, crash before effect and crash after a durable effect but before a
response. Each phase has a bounded deadline. Cancellation must finish within
the recorded bound and closing the Client must leave no live child process,
Spike-owned task or unbounded file-descriptor growth.

Crash-before-effect is eligible only for an explicitly classified safe retry.
Crash-after-effect is `outcome_unknown`: the effect journal must contain one
entry and the harness must perform zero automatic retries. Recovery creates a
new generation; it never reuses the failed session or assumes the write did not
happen.

### Schema Drift And Publication

The Fake has baseline, compatible and incompatible tool-schema revisions. A
new unmapped Tool with the mapped Tool unchanged is compatible and may update
the factual Snapshot; changing the mapped Tool input type is incompatible and
is not published. A fake-clock expiry also leaves the last-known-good digest
unchanged while health moves from stale to unavailable. Discovery observations
and Capability grants are separate test-owned states, so the new Tool never
becomes an authorization.

### Evidence And Adoption Gate

The harness emits a machine-readable report containing pinned SDK/protocol
versions, fixture identities, stable counts, hard-gate booleans and sanitized
reason codes. PIDs, temporary paths, timings, raw stderr and content are not
committed. The committed report is checked against a canonical digest and an
ADR records `ADOPT`, `REJECT` or `DEFER`.

`ADOPT` requires all of the following:

- native v2 and explicit v1 legacy contracts pass;
- 100 sequential calls use one process/session and bounded concurrency does
  not duplicate initialization or discovery;
- timeout/cancel/close leave no child or task leak;
- a crashed generation is retired and a fresh generation can recover;
- an unknown write outcome is never retried automatically;
- incompatible or expired Schema is not published;
- discovery produces zero Capability grants.

The decision authorizes only the subsequent S12 implementation. It does not
claim that iCourse is already a v2 Server, that a production Unified Client
exists, or that any additional MCP Server/source is available.
