# Branch Spec

Branch: group-onboarding
Parent: control-plane

## Development Design

### Catalog And Effective Resolution

Add a versioned Profile Catalog and service-fact resolver. For each requested
business service the resolver records whether its definition is installed,
healthy, granted and rollout-eligible. Desired remains the Profile request;
Effective contains only fully eligible IDs and each exclusion has one stable
reason. Unknown services cannot be activated. Strict Profiles reject any
exclusion; permissive Profiles activate only with the explicit diff.

### Preview And Lifecycle Commands

`preview` is read-only and binds exact Scope, Catalog/service-fact revisions,
the current assignment revision and a short expiry. `activate` consumes a
matching preview plus confirmation and expected revision. `update`, `pause`,
`resume` and `rollback` all use the same Command Gateway, authorization,
idempotency, Audit and receipt path.

Activation publishes one whole immutable assignment. Validation or persistence
failure leaves a new group pending or an active group on its last-known-good
revision. Resume re-resolves current grants, health, rollout and kill switch.
Rollback targets a retained compatible LKG revision and never loops.

### Durable Repository And Runtime Read

Implement a standard-library SQLite repository with transactions, unique
command IDs and assignment CAS. It stores pending bindings, Catalog/Profile
snapshots, assignment history, LKG and command receipts. Reopening the database
must reproduce the same current/LKG projections. Runtime uses a read-only
`GroupServiceSnapshotProvider`; it receives a frozen assignment snapshot and
cannot access mutable repository or command APIs.

### Typed Web Adapter

Add typed Core API routes and a Node server-side client/proxy for pending inbox,
Catalog, preview and lifecycle commands. The Vue Control Plane renders the
server projection, Desired/Effective diff and receipt status. It does not edit
`AgentConfig` locally or call NapCat for Agent behavior. Tests inject Fake
operator sessions and temporary storage; a production identity adapter remains
an explicit deployment input.

### Verification

Prove pending zero service, eligibility diffs, stale preview/revision, duplicate
command, two-admin CAS, restart/LKG, failed activation, pause/resume/rollback,
cross-account/group isolation and a rendered onboarding workflow.
