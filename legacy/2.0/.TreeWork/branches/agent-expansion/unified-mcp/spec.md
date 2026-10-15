# Branch Spec

Branch: unified-mcp
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Purpose And Delivery Boundary

Implement the S12 transport and lifecycle boundary approved by ADR 0004 and
ADR 0006. Core gains immutable MCP contracts, one `UnifiedMcpClient` Port and a
configuration-backed multi-Server Registry. The production implementation
owns one governed generation per Server and migrates iCourse through a
compatibility facade while retaining the old direct Client as an explicit
rollback selection.

This branch does not implement Capability Retrieval, a model Planner or
Executor. Discovery records transport facts only. No Tool becomes model-visible
until the separate S13 Capability Registry explicitly maps it, so S12 tests may
call management Tools only through deterministic compatibility/admin fixtures.

### Contract And Dependency Ownership

Framework-neutral contracts live under `dududa.mcp`; Protocols live under
`dududa.ports.mcp`. They may depend only on existing Core primitives, call
contexts and stable `DududaError` categories. They never import `mcp`, AstrBot,
iCourse, an SDK content type or a mutable configuration object.

The public boundary includes:

- strict server, endpoint, timeout, retry, circuit and concurrency definitions;
- `SecretRef` without a secret value;
- bounded Tool descriptors, canonical Schema snapshots and health projections;
- call context bound to a caller context, expected Schema snapshot, request
  digest and read-only/idempotent/non-idempotent semantics;
- normalized text/image/resource/structured results with size ceilings;
- stable transport, timeout, cancellation, Schema, result, circuit and unknown
  outcome error classifications;
- `UnifiedMcpClient.discover`, `call_tool`, `health` and idempotent `close`;
- `McpServerRegistry` immutable snapshot lookup and atomic reload; and
- private infrastructure session/factory and Secret/Environment resolver Ports.

All DTO collections are frozen, identifiers and strings are bounded, JSON is
recursively copied, booleans are not accepted as integers and non-finite values
are rejected. Canonical digests bind every field that can change eligibility,
connection behavior, Schema publication or retry safety.

### Registry And Configuration Authority

`ConfigMcpServerRegistry` reads strict versioned JSON files from
`config/mcp/servers/`; JSON keeps the parser in the standard-library-only Core.
One atomic `McpRegistrySnapshot` is the only connection authority. Invalid,
duplicate or partially changed configuration is rejected while the previous
snapshot remains current.

Each definition binds server ID, enabled state, stdio command/args/cwd or HTTPS
URL, protocol mode, environment allowlist, `SecretRef`s, Tool allowlist,
connect/discovery/call/max-call deadlines, retry ceiling/backoff, circuit
threshold/window/open duration, concurrency, Schema TTL and configuration
revision/digest. Commands, URLs, environment keys, SecretRefs and policy
ceilings can never come from a model, message or Tool argument.

HTTP definitions require HTTPS, no URL userinfo/fragment and an explicit host
allowlist. Stdio executables and cwd must be absolute in production definitions;
test definitions may use explicitly marked local fixture paths. Secret values
are resolved only by an injected infrastructure resolver immediately before
session creation and never enter Registry snapshots, results, health or logs.

Adding a test Fake Server requires one new definition plus a future Capability
mapping fixture; it cannot require a conditional in Domain, Runtime or the
generic Client. Production configuration contains only iCourse in this branch.

### MCP v2 Dependency Isolation

The AstrBot interpreter and current iCourse FastMCP Server must remain on
`mcp==1.29.0`; MCP v2 cannot coexist in that interpreter. A separately locked
`services/unified-mcp-worker/` environment therefore contains `mcp==2.0.0`.
The derived image installs it into a dedicated virtualenv without changing the
AstrBot/iCourse environment.

The parent `SubprocessMcpV2SessionFactory` launches one worker per Server
generation over a bounded line-delimited local protocol. The worker opens the
exact stdio or Streamable HTTP endpoint supplied from the accepted Registry and
implements initialize/discover/call/cancel/close only. It returns sanitized
transport observations and never owns Registry reload, Schema freshness,
Capability mapping, retries, circuit state, scheduling, targets or delivery.
Thus the process is an SDK Adapter for the private session Port, not a second
control plane.

For iCourse, the v2 worker uses explicit `legacy` mode and launches the existing
v1 Server with the existing absolute command, cache path and Server ID. Native
v2 Fake and legacy iCourse pass the same worker/session Contract. Worker death
closes its pipes and is treated as a terminal generation failure; the parent is
the only component allowed to create the next generation.

### Per-Server Lifecycle And Schema Authority

`ManagedUnifiedMcpClient` holds isolated state per Server:

- an initialization lock, configured concurrency semaphore and close state;
- current definition revision, monotonically increasing generation and one
  session;
- last-known-good canonical Schema snapshot and current freshness/health;
- bounded failure timestamps, circuit state and a single half-open probe.

The first discover lazily connects, initializes and discovers. A fresh cached
snapshot may serve later callers without SDK cache authority. Explicit refresh,
expiry, disconnect or material configuration change retires the old session.
Reconnect always increments generation and performs initialize/discover before
use; no request may reuse a retired session.

Discovery canonicalizes all Server Tool facts. Calls require both the Server
Tool allowlist and the exact current Snapshot binding. New unallowlisted Tools
may update facts but grant no permission. Removing or changing the input/output
Schema of an allowlisted Tool under the same configuration revision is
incompatible: the observation is not published, last-known-good remains bound,
health becomes stale/unavailable and calls fail closed. A material accepted
configuration revision may establish a new baseline only after a complete
generation restart and successful discovery.

### Deadlines, Cancellation, Retry And Circuit

Every phase uses the minimum of the caller deadline, configured phase timeout
and global maximum. Cancellation races the transport operation and bounded
cleanup; it is never normalized into retryable timeout. Semaphore waiting,
backoff, reconnect and discovery all consume the same caller deadline.

A Tool call is attempted at most twice and only if configuration, caller retry
budget and operation semantics all allow it. Server business errors are not
transport retries. A disconnect before dispatch may retry read-only/idempotent
work; a failure during or after dispatch is `outcome_unknown` and never retries.
Non-idempotent calls require an explicit business idempotency key even for an
otherwise retryable classification. No retry changes the request digest.

Failures are kept in a bounded monotonic window per Server. Reaching the
configured threshold opens only that Server's circuit. After the open interval,
exactly one half-open connect/discovery probe may run; success closes the
circuit and failure reopens it. Config reload, clock rollback, resolver failure
and close all fail closed and never expose raw exception text.

### Result Normalization And Safety

The Client validates arguments against the published Tool input Schema using
the repository's existing JSON Schema dependency at the infrastructure edge;
Core also enforces structural and size ceilings. SDK content is converted to
bounded immutable DTOs. Unsupported content, invalid structured output,
oversized fields, remote Schema refs, open recursive shapes and unknown
result states are rejected before reaching a consumer.

Audit-facing evidence contains server/tool IDs, generation, snapshot/request
digests, stable reason codes and aggregate sizes only. It never contains
commands, cwd, URLs with credentials, secret values, raw stderr, stack traces or
full external content. MCP results remain untrusted Observations for S13.

### iCourse Migration And Rollback

Production configuration imports the existing `icourse` command and SQLite
path. Its transport allowlist contains only the six Tools with current
deterministic consumers: `icourse_stats`, `search_courses`, `get_course`,
`get_reviews`, `search_site_courses` and `crawl_course`. The other four
discovered management Tools are explicitly denied. Only
`icourse_stats`, `search_courses`, `get_course` and `get_reviews` are eligible
for the first S13 public read-only Capability mapping. Crawl/refresh, online
search, robots and export are never model Capabilities.

`get_course` is read-only only when `refresh=false`; `search_site_courses` and
`crawl_course` perform network/cache effects. The compatibility facade derives
operation semantics from the exact Tool arguments rather than the Tool name,
and effectful calls default to no retry. iCourse uses concurrency one, and the
Server reuses one crawler/limiter across its Tool lifecycle so a long Client
session cannot reset request-delay state on every call.

The repository AstrBot-native MCP template is disabled in the new release. It
has no Tool allowlist and would otherwise expose the raw ten-Tool surface as a
second business path. The file remains a rollback/host integration artifact;
re-enabling it is an explicit operator rollback, never an automatic Client
fallback or model decision. This branch does not read or mutate the running
container's copy.

The existing class becomes an `ICourseClient` compatibility facade. In unified
mode it creates a bounded service call context, discovers a fresh Schema and
forwards through `UnifiedMcpClient`; it never silently falls back after an
unknown call. The old per-call v1 implementation remains as
`LegacyICourseClient` and is selected only at composition/configuration time for
rollback. The new derived image selects unified mode when its locked worker is
present; missing or invalid infrastructure preserves plugin startup and selects
the explicit legacy implementation with a stable diagnostic.

Plugin termination closes the compatibility facade and all worker/server
processes idempotently, retrying failed cleanup on the next termination call.
Course commands repeat their existing blocked/role gates before every query or
management call; migration tests cover the refresh cooldown path so missing
imports and muted/disabled bypasses cannot hide behind formatting tests.
S22 may remove the legacy implementation only after consumer migration and a
recoverable previous Release are independently proven.

### Verification Boundary

Unit and Contract evidence covers strict DTO/config parsing, atomic Registry
reload, multi-Server isolation, long session reuse, concurrency, cancellation,
phase deadlines, retry eligibility, unknown outcomes, circuit/half-open,
generation/config change, Schema compatibility/expiry, result bounds,
redaction and idempotent close.

One native v2 Fake and the real local iCourse v1 empty-database fixture pass the
same isolated worker Contract with no network, real cache, credentials, AstrBot
container or QQ operation. An extension test adds a second Fake through config
and mapping fixture only. Plugin tests prove unified forwarding, explicit
rollback selection and lifecycle cleanup. Full dual-Python, build/import,
derived-image, secret, Web regression and whitespace gates remain required.
