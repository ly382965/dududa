# Branch Spec

Branch: control-plane-foundation
Parent: control-plane

## Development Design

### First Executable Slice

Create `dududa.control_plane` with immutable versioned contracts and one
in-memory vertical slice:

```text
Fake Group Join -> pending repository -> authenticated query -> pending projection
                                           |
Fake operator session -> typed preview -> authorization -> Fake Catalog diff
                                           -> audit/receipt, no publication
```

This branch does not implement Profile activation. It records a deduplicated
join, previews one fixed Profile against Fake service facts and proves that the
pending group still has no Runtime services.

### Contracts

`GroupControlScope` binds platform, Core Bot/account isolation key and group ID.
The Web adapter maps its opaque account ID at this boundary. Authorization
projects the scope to the existing group `ConversationScope` with reserved
Persona `control-plane`; a candidate Profile Persona is never used for auth.

`ServiceDefinition`, `GroupServiceProfile`, `GroupServiceAssignment`,
`GroupJoinFact`, `GroupOnboardingRecord`, `OperatorSession`, typed Query/Command
envelopes, `CommandReceipt` and projection DTOs are frozen dataclasses with
bounded fields and stable reason codes. Profiles reference business services
and policy IDs; they never contain grants, MCP tools, endpoints, secrets or
real targets.

Pending is an onboarding record, not a partially empty Assignment. Assignment
exists only after Profile publication and may be `ACTIVE`, `PAUSED`,
`ROLLED_BACK` or `REVOKED`. A pending Runtime lookup returns no assignment and
therefore no service ownership.

### Reused Governance

An `OperatorSessionAuthenticator` port resolves an opaque session to the
existing `Actor`; a Fake adapter supplies offline sessions. The Command Gateway
uses the existing `AuthorizationPolicy`, decision verifier and Audit contracts.
Each action has an exact resource constraint. It validates Scope before
dispatch. A committed or exactly replayed mutation returns one typed receipt;
authorization, validation, not-found and pre-commit conflict paths raise the
existing stable `DududaError` contract without a success Receipt. The Web
Adapter maps that domain result and never treats HTTP status as authority.

The repository commits state, idempotency key/request digest, Command Receipt
and a low-sensitivity audit record under one lock. The generic `AuditSink`
receives a projection after commit and is not misrepresented as part of a
cross-Port transaction.

### Storage And Projection

Define a framework-neutral `ControlPlaneRepository` port and an in-memory
adapter with one lock, exact Scope keys, revision checks and command-result
replay. `GroupJoinService` creates or returns the same pending record for a
duplicate fact. A preview handler reads a fixed Profile/Fake Catalog, verifies
that both Profile and Catalog facts bind the requested revision and Scope, and
returns Desired/Effective service reasons without publishing Assignment or
Runtime state. `ControlPlaneProjector` reads repository facts and produces a
pending inbox and group summary without inventing health or permissions.

### Verification

Focused tests cover contract validation, duplicate joins, exact multi-account/
group isolation, session expiry, default-deny RBAC, Fake service eligibility,
command idempotency, Audit/Receipt binding, pending zero-service lookups and
import boundaries.
