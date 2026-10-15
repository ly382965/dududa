# Branch Spec

Branch: pr10-selective-integration
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Goal And Selection Rule

PR #10 is treated as a source of implementation material rather than a
mergeable release. This branch imports only capabilities that are not already
owned by the canonical Core, existing AstrBot plugins, NotifAI, or the USTC
academic/curriculum MCP services. The old Core duplicate, old repository paths,
replacement Compose file, direct model calls, and unrestricted refresh/write
tools remain excluded.

The selected first slice is a read-only local-recommendations MCP service and
the genuinely distinct public campus reference services: training-plan,
campus-events, college-notice, and library. The academic-calendar and
ustc-notice implementations are excluded because their responsibilities are
already covered by the current academic and NotifAI services. All imported
services use canonical `services/mcp/*` paths and explicit Registry entries.
They remain disabled and have no Capability definitions or mappings in this
slice, so they are not visible to the Planner and do not join the production
Provider health chain.

The non-duplicate social rules are retained as a separate
`astrbot_plugin_dududa_social` plugin. It owns only explicit
`/dududa-social` commands, is globally disabled by default, has feature flags
disabled by default, and registers no catch-all message handler, scheduler,
model call, MCP call, or automatic delivery path. The PR's duplicate Core and
social event monolith are not imported.

### Service Boundary

Each service keeps a small protocol adapter and a deterministic domain/storage
layer. It exposes only bounded read operations to the Unified MCP Client. Any
refresh, robots check, export, or write operation is retained as an operator
surface or omitted from the production allowlist; it is never automatically
visible to the Planner. External HTML and public notices are normalized into
bounded records carrying source and freshness metadata.

`local-recs` is seeded, local, and read-only in this branch. The AMap lookup
helper from PR #10 is not imported. No credential is committed, and no key is
placed in a URL. A future place-search adapter must use a SecretRef and an
explicit allowlist.

### Registry And Optional-Asset Contract

Every selected MCP Server gets a canonical `configs/mcp/servers/<id>.json`
entry with `enabled: false`, an explicit environment allowlist, bounded
timeouts/concurrency, and an exact one-tool `allowed_tools` list. Each tool
queries a bounded local cache and cannot refresh, crawl, write, or call an
arbitrary URL. The services are packaged and available to Unified MCP Registry
operators, but are intentionally absent from `configs/astrbot/mcp_server.json`
and `configs/capabilities/*`.

This separation is deliberate: the current production Capability composition
builds Provider descriptors and health for configured mappings even when a
definition is disabled. Adding mappings here would therefore make optional
Servers participate in the existing health path. A later branch may add
Capability definitions and mappings together with explicit source review and
an optional-provider loading contract; this branch does not silently change
Planner reachability or production health semantics.

### Compatibility And Rollback

No current Core command, handler priority, Compose service, Web route, or data
file is replaced. The owned-plugin installer continues to manage only
`apps/astrbot-plugins/*`; this branch adds the separate social plugin but no
duplicate Core plugin. Keeping the social plugin disabled and the five Registry
entries disabled preserves the current runtime behavior. Removing those
additions is sufficient to roll back; the imported services have no migration
of existing user state.

### Verification Strategy

Contract tests will prove tool discovery, input bounds, one-tool read-only
allowlists, standard result envelopes, local seed queries, default-off Registry
entries, and absence from the Planner-facing Capability catalog. Repository
tests will prove the existing Core, Compose, Web console and Unified MCP
services remain in place while packaging the optional additions. Focused
Python tests run before the broader repository checks. The branch does not
claim live source freshness, enabled production composition, proactive
delivery, or real-group evidence.
