# Branch Spec

Branch: production-shape
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Goal And Starting Point

Close the four known production-shape gaps without enabling a real Endpoint or
redesigning the S08 Static Router. The current plugin leaves
`rollout_bridge=None`; Runtime requests force `temperature=0` while the AstrBot
Adapter accepts only `None`; Adapter health has no evidence path out of
`UNKNOWN`; and the rollout ledger forces WAL on SQLite versions inside the
known WAL-reset hazard.

### Persistence Strategy

This branch selects rollback journal plus existing `BEGIN IMMEDIATE`/CAS as the
portable default. The ledger configuration exposes a closed journal-mode enum,
rejects WAL unless an explicit runtime SQLite-version gate proves 3.51.3 or
newer, and verifies the effective mode after connection. Existing databases
remain readable and no production database is opened or migrated by tests.

### Sampling And Health Evidence

Perception and Direct Chat create requests with `temperature=None`. A future
non-null sampling value requires separate Endpoint conformance and cannot be
silently dropped by an Adapter.

Health remains fail-closed. A clock-injected publisher accepts only validated,
descriptor-bound probe receipts, transitions `UNKNOWN -> AVAILABLE`, and
returns to `UNKNOWN` when evidence expires or a probe fails. Stable reason codes
and snapshot revisions make every transition replayable. The production
AstrBot Adapter stays UNKNOWN until a real probe artifact exists; Fakes provide
the AVAILABLE evidence used by offline composition tests.

### Single Composition And Lifecycle

One composition root owns Registry, Provider, Router, Perception, Direct Chat,
Offline Runtime, rollout bridge and closeable resources. Default configuration
is `off`; missing Endpoint evidence leaves invocation unavailable rather than
falling back to an optimistic route. Initialization is transactional: any
failure closes already-created resources and preserves the legacy owner.
Repeated initialization cannot install a second bridge. Termination closes the
bridge, Provider/health resources and ledger idempotently.

The `off` smoke proves zero model and delivery calls. `shadow` receives no
Output capability and writes only sanitized receipts. No test reads running
container configuration, restarts a service or sends a message.

### Compatibility

Existing S08-S11 contracts, Router rejection behavior, rollout configuration
and legacy Handler remain authoritative. Changes are additive except for the
two incorrect defaults: forced sampling and unsafe WAL. Rollback restores the
previous code/config release without touching runtime data.
