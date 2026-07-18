# Migration Plan

Status: Phase 1 design.

Dududa 2.0 is migrated additively and by behavior, not by creating a clean tree
first. The complete plan is split into:

- Current evidence: `../refactor/current-state.md`
- Dependency order: `../refactor/dependency-map.md`
- Old-to-new file and responsibility map: `../refactor/migration-map.md`
- Phase, risk, test, and rollback plan: `../refactor/implementation-plan.md`
- Progress ledger: `../refactor/PROGRESS.md`

## Migration Sequence

```text
baseline and design
  -> pure package contracts
  -> security/config extraction
  -> thin AstrBot adapters
  -> fail-closed Memory v2
  -> Agent Runtime
  -> Capability and MCP runtime
  -> operation/layout/manifest migration
  -> eval/tracing/CI
  -> compatibility cleanup
```

## Compatibility Strategy

- Preserve three plugin IDs and container target paths.
- Keep root `manage.sh` and Compose entry during the operation migration.
- Add wrappers before moving implementations.
- Use shadow execution only when it cannot send, write memory, or trigger tools.
- Cut over one command/capability/event class at a time behind rollback control.
- Mark every temporary module `compatibility`, `legacy`, or `deprecated` and
  attach a measurable removal gate.

## Data Strategy

Production state is never moved by a source-tree `git mv`. Memory, config,
Persona, audit, plugin receipt, and service cache migrations are separate,
schema-aware operations with inventory, backup, dry run, receipt, verification,
and rollback. Unknown-scope memory is quarantined rather than broadened.

## First Implementation Scope

The first implementation PR is Phase 2A: an installable framework-neutral core
contract package plus tests and image/CI import smoke. It does not move files or
receive production events.
