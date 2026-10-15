# Branch Spec

Branch: control-plane
Parent: agent-expansion

## Development Design

### Authority And Package Boundary

S21 adds one `dududa.control_plane` application/domain package. It owns group
service profiles, assignments, operator commands, projections and Runtime
snapshots. It reuses the existing immutable Actor/Scope, authorization, audit,
confirmation, idempotency and canonical-codec contracts. It does not create a
second security stack, Router, Capability Registry, Scheduler or Output path.

The Node Web server is a typed adapter. It may authenticate a browser session,
proxy queries and commands, and render receipts, but it cannot compute
Effective services, write assignment storage or send an Agent draft through
NapCat. Python Core remains the only policy and mutation authority.

### Ordered Vertical Slices

S21A establishes immutable contracts, operator-session/RBAC ports, Fake facts,
pending join handling, Profile preview, a Command Gateway, Projector,
Audit/Receipt and an in-memory executable slice. S21B adds lifecycle commands,
durable CAS/LKG storage, immutable Runtime snapshots and the group onboarding
Web workflow. S21C adds read-only operational projections and only explicitly
bound Core mutations. The final audit removes browser-local Agent authority and
proves the integrated offline behavior.

### Scope And Service Semantics

Every record binds exact platform, Bot/account isolation key and group identity.
The current Web adapter maps its account ID to Core `bot_id`; Core does not store
a second synonymous account field. A newly observed binding is
`PENDING_PROFILE` and yields an empty Runtime service set.
Profiles contain stable business service IDs and policy references, never raw
MCP tools, physical model IDs, credentials or target identifiers.

Effective service resolution is deterministic:

```text
requested profile services
  intersect installed and healthy service definitions
  intersect current grants and group policy
  intersect rollout, budget and kill-switch eligibility
```

The projection preserves Desired services and stable exclusion reasons. Group
Context, plugins, models and Bandit are evidence consumers only and cannot
mutate an assignment or grant capability/send authority.

### Offline Evidence Boundary

All S21 behavior is proven with Fake joins, service facts, operator sessions,
synthetic Scopes, injected clocks and temporary SQLite. No real Provider,
Source, external corpus, QQ send or running-container mutation is permitted.
The current local Dududa history is replayed only if Connector/history/
Perception/session projection code changes.
