# Branch Spec

Branch: agent-expansion
Parent: root

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Purpose And Sequence

This epic completes the offline S12-S22 release-required chain and the bounded
S20 foundation without reading user data, enabling real Providers, fetching
live sources or sending messages. Work remains WIP=1 and follows the dependency
chain recorded in `tree.yaml`. Branch-local completion never upgrades an
external quality or production claim.

### Shared Authority Boundaries

- deterministic Core code owns identity, Scope, permissions, budgets, policy,
  scheduling, state transitions and every side effect;
- model, MCP and learned components return proposals or bounded Observations;
- iCourse is the only real MCP Server, while Fakes prove future extension;
- source fixtures prove contracts but not live availability or content rights;
- Shadow object graphs lack delivery and persistent-write capabilities;
- every public contract is versioned, additive where possible, digest-bound and
  keeps a compatible reader or rollback path until S22 evidence allows removal.

### Evidence Boundary

Each leaf branch owns focused Unit, Contract, negative, cancellation/deadline
and failure evidence. S18 consolidates repeatable fixtures and CI, S19 audits
the integrated offline release, and S22 removes only proven-unused compatibility
surfaces. S23 remains pending and outside this Goal. S20 does not become an S23
dependency and cannot train or execute an online policy.
