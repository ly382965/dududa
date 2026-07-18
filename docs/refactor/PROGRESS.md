# Dududa 2.0 Refactor Progress

Last updated: 2026-07-18
Baseline: `main@2767cc9768d4bce63d4b4ee811add951ebce6870`

## Current Phase

- Phase 0: audit and baseline - complete.
- Phase 1: target design and migration plan - complete.
- Phase 2 and later: not started.

No business source, runtime path, Compose behavior, or production state is
changed by Phases 0-1.

## Completed

- Recorded Git, toolchain, tracked-tree, and Compose baselines.
- Read all first-party plugin, iCourse, deployment, initialization, test,
  manifest, patch, vendor, configuration, and documentation areas.
- Mapped the real `up` and `upgrade` call chains.
- Decomposed the 1,540-line Core plugin by responsibility and line range.
- Inventoried commands, event hooks, persistent state, transient state, model
  paths, MCP paths, external dependencies, and plugin loading constraints.
- Ran the existing eight tests and all CI-equivalent local gates.
- Verified a clean temporary install of all six third-party plugins and a second
  idempotent install pass.
- Rebuilt the derived AstrBot image without starting production services.
- Verified all ten iCourse tools through an isolated, network-disabled MCP
  handshake container.
- Recorded current architecture, dependency graph, risks, and documentation
  ownership.
- Reconciled the canonical Actor, ConversationScope, MemoryScope, Envelope,
  Runtime State, response, delivery acknowledgement, Persona Renderer, and MCP
  Registry contracts before Phase 2 implementation.
- Assigned all physical source moves to Phase 8, while preserving the Phase 4
  behavior split and Phase 7 logical iCourse cutover as separate review units.

## Phase 0 Documents

- `docs/refactor/current-state.md`
- `docs/refactor/dependency-map.md`
- `docs/refactor/baseline.md`

## Phase 1 Documents

Completed outputs:

- `docs/refactor/target-architecture.md`
- `docs/refactor/migration-map.md`
- `docs/refactor/implementation-plan.md`
- Detailed design documents under `docs/design/`.
- Operation contracts under `docs/operations/`.
- Development extension guides under `docs/development/`.
- Architecture decisions under `docs/adr/`.

## Verified Baseline

| Gate | Result |
| --- | --- |
| Shell syntax | Pass |
| Python compilation | Pass |
| Unit and contract tests | 8 passed |
| Compose parse | Pass |
| Repository secret/runtime scan | Pass, 75 files |
| Plugin installation | Six installed; unchanged second run idempotent |
| Docker build | Pass |
| MCP handshake | Pass in isolated derived image |
| Remote GitHub Actions run | Not verified; private API access not used |

## Phase 1 Exit Verification

The documentation-only exit review was run on 2026-07-18 after contract and
path reconciliation:

| Gate | Result |
| --- | --- |
| Shell syntax | Pass: `bash -n manage.sh` |
| Python compilation | Pass: plugins, services, scripts, and tests |
| Unit and contract tests | Pass: 8 tests |
| Compose parse/services | Pass: `astrbot`, `napcat` only |
| Repository secret/runtime scan | Pass: 103 tracked/untracked files |
| Markdown required files, links, fences, and whitespace | Pass |
| Derived AstrBot image build | Pass |
| Network-disabled MCP handshake | Pass: all 10 tools and empty cache stats |
| Change scope | README and Phase 0/1 documents only; no business/runtime source |
| Phase 2 artifacts | Absent: no `apps/`, `packages/`, `deploy/`, `ops/`, or `third_party/` implementation tree |

The temporary six-plugin install and unchanged second pass remain the Phase 0
network baseline. Plugin source, manifest, installer, patch, and vendor content
have not changed since that test.

## Known Issues

### Safety and privacy

- Memory scope is not a first-class fail-closed domain type.
- Iris patch allows missing-user entries and global fallback paths.
- NapCat can access all AstrBot private data through a shared mount.
- TargetTalk records group context before all allowlist/target checks.
- Audit redaction is based on field names and has no rotation.
- iCourse export can target an arbitrary process-visible path.

### Reliability and operation

- `manage.sh upgrade` cannot apply a changed plugin marker without a force path.
- No health, backup, restore, or automatic rollback stages exist.
- Current `up` mixes MCP sync, plugin preparation, build/start, Persona seed,
  and restart in one implicit chain.
- The host Python lacks `pip`, `venv`, and MCP dependencies expected by some
  developer commands.
- Plugin Python/system dependencies are not installed or verified by the
  manifest installer.

### Architecture and testability

- Core imports AstrBot types and combines commands, policies, persistence,
  Provider calls, MCP process ownership, and rendering.
- Lightweight memory and Iris are disconnected implementations.
- Model selection has three paths; MCP has two paths.
- Current tests are structural and do not protect most user-visible behavior.
- Repository paths are duplicated across build, runtime, CI, docs, and scripts.

## Architecture Decisions

Decisions accepted for Phase 1 design:

1. Preserve the repository as one Bot Runtime Monorepo.
2. Preserve all three AstrBot plugin IDs and container target directories during
   migration; do not merge them mechanically.
3. Add the pure Agent package before moving plugin roots.
4. Install the pure package into the AstrBot image; do not rely on accidental
   host paths.
5. Make memory scope fail-closed and keep Iris behind `MemoryRepository`.
6. Use one `UnifiedMcpClient` and `McpServerRegistry`, with iCourse as the
   reference Capability Provider.
7. Keep root `manage.sh` and the current Compose entry compatible until the
   operation migration has behavior and rollback coverage.
8. Treat old command adapters as `compatibility` until removal gates pass.
9. Keep Actor identity/roles separate from conversation Scope; add user identity
   to Memory Scope only when its Memory Type requires it.
10. Use `DraftResponse -> FinalResponse -> RuntimeResult`; acknowledge platform
    delivery before committing delivery-dependent automatic memories.
11. Move plugin roots, iCourse source, deployment, operations, config, and
    third-party paths only in Phase 8 path-focused changes.

## Next Reviewable Change

After Phase 1 documents are approved, the recommended first implementation PR
is a narrow Phase 2 package skeleton:

- Add an installable `packages/dududa-agent` package.
- Add pure domain models, Protocols, Runtime State, typed config, and errors.
- Add unit tests and an import-boundary check.
- Install the package in CI and the derived image.
- Do not route production events to it yet.
- Do not move or delete any current plugin file.

## Stop Condition For This Task

Stop after Phase 0 and Phase 1 documents pass repository gates. Do not begin the
package skeleton, directory migration, compatibility wrapper, runtime wiring,
or production rollout in this task.
