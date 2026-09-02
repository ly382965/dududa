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
services use canonical `services/mcp/*` paths, explicit Registry entries, and
remain disabled in the model-facing template until their Capability mappings
and source review pass.

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

### Registry And Capability Contract

Every selected MCP Server gets a canonical `configs/mcp/servers/<id>.json`
entry with `enabled: false`, an explicit environment allowlist, bounded
timeouts/concurrency, and an exact `allowed_tools` list. The AstrBot template
also remains default-off. Capability definitions and mappings are generated
from the server tool schemas with stable versioned IDs, public privacy, read
only idempotency, bounded result fields, and `capability.<namespace>.read`
permissions. The existing Unified MCP Client and Capability Provider are the
only execution path.

### Compatibility And Rollback

No current Core command, handler priority, Compose service, Web route, or data
file is replaced. The owned-plugin installer continues to manage only
`apps/astrbot-plugins/*`; this branch adds no duplicate Core plugin. Disabling
the new Registry entries and removing their capability mappings is sufficient
to roll back; the imported services have no migration of existing user state.

### Verification Strategy

Contract tests will prove tool discovery, input bounds, read-only allowlists,
standard result envelopes, local seed queries, and capability-definition /
mapping consistency. Repository tests will prove the existing service set and
Compose include remain unchanged apart from explicitly disabled additions.
Focused Python tests run before the broader repository checks. The branch does
not claim live source freshness or production deployment evidence.
