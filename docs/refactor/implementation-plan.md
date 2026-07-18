# Dududa 2.0 Implementation Plan

Status: Phase 1 plan; this task stops before Phase 2 implementation.

## Delivery Rules

Every PR must state:

- objective and phase;
- files added, moved, or modified;
- user-visible behavior held invariant;
- risks and explicit non-goals;
- verification commands and evidence;
- rollback method;
- compatibility code and its removal gate.

At every phase boundary run shell syntax, Python compilation, all unit/contract
tests, Compose parse, repository scan, and `git diff --check`. Broaden Docker,
plugin-import, MCP, memory-isolation, integration, eval, and smoke gates as soon
as their corresponding surfaces change.

## Phase 0: Audit And Baseline

Status: complete in this documentation change.

Outputs:

- `current-state.md`
- `dependency-map.md`
- `baseline.md`
- initial `PROGRESS.md`

Evidence includes eight passing existing tests, six-plugin temporary install,
Docker build, and network-disabled MCP handshake. Known failures and blind spots
are preserved in the baseline rather than normalized away.

Rollback: documentation-only revert.

## Phase 1: Target Design And Migration Plan

Status: complete when all linked design, operation, development, ADR, mapping,
and plan documents pass review and repository gates.

No runtime behavior, source path, plugin ID, or production state changes.

Rollback: documentation-only revert.

## Phase 2: Establish The Core Python Package

### Objective

Add an installable, framework-neutral package with domain models, Protocols,
Runtime State, typed config, and errors. Do not route existing events through it.

### Expected files

```text
packages/dududa-agent/pyproject.toml
packages/dududa-agent/src/dududa/domain/*
packages/dududa-agent/src/dududa/runtime/state.py
packages/dududa-agent/src/dududa/config/*
tests/unit/domain/*
tests/unit/runtime/test_state.py
tests/contracts/test_import_boundaries.py
```

CI and the Dockerfile install the package. Existing plugin files do not move.

### Invariants

- Existing commands and plugin imports are unchanged.
- Package imports without AstrBot installed.
- No concrete filesystem, Provider, MCP, or Iris implementation enters domain.

### Risks

- Over-designing interfaces before one adapter proves them.
- Package not installed the same way in CI and image.
- Mutable metadata or optional Scope fields weakening later guarantees.

### Verification

- Package build and editable install.
- Unit tests for envelope, identity, response, Scope validation, state
  transitions, config parsing, and typed errors.
- Forbidden-import contract.
- Docker build plus `python -c 'import dududa'`.
- All Phase 0 gates.

### Rollback

Remove additive package/tests and revert CI/Docker install lines. No production
data or import points are affected.

## Phase 3: Extract Security And Common Logic

### Objective

Extract Actor/permission policy, redaction, audit contracts, typed config, and
common errors. Existing plugin modules become compatibility wrappers.

### Behavior held invariant

- Role order, owner/admin fallback, muted behavior, current audit location, and
  command-visible errors stay unchanged unless a security fix is isolated and
  explicitly approved.

### Main risks

- Accidentally granting on missing config.
- Changing plugin config keys or data paths.
- Redacting too little or breaking required operator attribution.

### Verification

- Permission matrix, default-deny, Actor conversion, nested/value redaction,
  audit sink, corrupt-config, atomic-write, and compatibility import tests.
- Existing command contract fixtures.

### Rollback

Compatibility wrappers can switch back to legacy implementations; no path is
moved in this phase.

## Phase 4: Split The AstrBot Plugins

### Objective

Make Core `main.py` a composition and registration layer. Move handlers into
event adapter, basic/admin/memory/course/compatibility commands, lifecycle, and
runtime bridge modules. Extract pure ReplyPolish and TargetTalk logic while
keeping three separately loadable plugin roots.

### File-size target

`main.py` should contain registration, dependency assembly, and handler imports,
normally below 300-400 lines. The goal is ownership boundaries, not arbitrary
line splitting.

### Invariants

- Plugin IDs, metadata, schema keys, container target paths, event priority,
  decorators, command names, stop/send behavior, and state paths stay stable.

### Risks

- AstrBot decorator discovery and import order.
- Global ReplyPolish impact on unrelated plugins.
- TargetTalk direct-send timing and internal AIOCQHTTP dependency.

### Verification

- AstrBot import/registration smoke in derived image.
- Event-to-command/result contract fixtures.
- Reply splitting property/golden tests.
- TargetTalk deterministic decision, context-capture, and cooldown tests.
- Clean Compose bootstrap smoke without production data.

### Rollback

Keep a release image and a configuration flag selecting legacy handler
assembly. Do not delete legacy modules in this phase.

## Phase 5: Memory v2 Boundary

### Objective

Implement Memory Scope, records, repository contracts, exact retrieval, Write
Gate, compatibility JSON repository, and fail-closed Iris adapter.

### Invariants

- Existing memories are not rewritten automatically.
- Missing metadata is quarantined, not treated as shared.
- Feature begins disabled or shadow-only for production responses.

### Risks

- Privacy leakage, legacy data disappearance, irreversible migration, and
  conflicting semantics between JSON and Iris.

### Verification

- Full cross-group/user/private/Bot/Persona negative matrix.
- Repository contract against JSON and Iris adapters.
- Write Gate sensitivity, TTL, duplicate, conflict, and confirmation tests.
- Offline migration dry-run and rollback fixtures.

### Rollback

Disable retrieval/write flags and return to untouched legacy stores. Migration
tools require backup and reversible receipts.

## Phase 6: Agent Runtime Skeleton

### Objective

Implement Context Builder, Perception interface, Social Decision, Runtime
Orchestrator/State transitions, Response Composer, OC boundary, and trace.

### Migration mode

Start with pure fixtures, then shadow execution with redacted comparisons.
Legacy output remains authoritative until one selected path is approved.

### Risks

- Duplicate replies during shadow mode.
- Model nondeterminism being mistaken for state control.
- Persona altering facts or decisions.
- Traces retaining raw messages.

### Verification

- Transition and budget tests.
- Structured-output invalid/fallback tests.
- Social action decision table and eval fixtures.
- Response fact/error/citation guard and OC consistency tests.
- Shadow mode proves it never sends or writes memory.

### Rollback

Disable the runtime bridge flag; legacy adapters remain complete.

## Phase 7: Unified Capabilities And MCP

### Objective

Implement Capability Registry/Retrieval, planner, executor, validator, unified
MCP Client/Server Registry, and iCourse Capability Provider. Eliminate the
double iCourse client path after selective cutover.

### Invariants

- Current course commands and output remain available.
- iCourse stays an independent service package.
- Planner cannot see ineligible/high-risk tools.

### Risks

- Infinite/repeated calls, process churn, crawler overload, schema drift,
  arbitrary file export, and model prompt injection from reviews.

### Verification

- Capability eligibility and Top-K tests.
- Planner/executor/validator bounded-loop integration.
- MCP schema cache, timeout, error, restart, retry, and circuit tests.
- iCourse transport contracts and captured parser fixtures.
- Export-root and crawl-limit negative tests.

### Rollback

Per-capability feature flag routes course commands to the compatibility client.
Do not remove old MCP config/client until one-client metrics and smoke pass.

## Phase 8: Deployment And Third-Party Layout

### Objective

Move canonical paths into `apps/astrbot-plugins/`, `deploy/`, `ops/`,
`third_party/`, `configs/`, and `services/mcp/`; add operation stages and
manifest v2 while preserving root entry points. Plugin host-source moves are
path-only changes after the Phase 4 adapter split; their container targets and
plugin IDs stay unchanged.

### Invariants

- `./manage.sh up`, root Compose use, plugin IDs, and persistent data root remain
  compatible or print a tested migration instruction.
- Moves use `git mv`; runtime data never moves implicitly.

### Risks

- Hard-coded path missed in CI/docs/Compose/Docker.
- Changed manifest unable to upgrade current receipts.
- Partial upgrade without backup or health.
- Shrinking mounts breaking upstream NapCat/AstrBot assumptions.

### Verification

- Path-consumer contract, manifest schema/integrity/license tests.
- Clean bootstrap, prepare, build, start, seed, health, upgrade, backup, restore,
  and rollback smoke against disposable data.
- Root wrapper compatibility tests.
- Container mount/network contract and security review.

### Rollback

Versioned release directories, pre-upgrade consistent backup, previous image
digests, manifest receipts, and root compatibility wrappers.

## Phase 9: Eval, Tracing, And CI

### Objective

Add versioned eval datasets, runtime trace, MCP/model metrics, memory isolation
regressions, import/layer checks, and full smoke jobs.

### Required eval dimensions

Reply decision, target, intent, references, tool choice, arguments, isolation,
result validation, fallback, and OC consistency. Fixtures use synthetic IDs and
public/synthetic text only.

### Verification

CI runs unit, contract, integration, eval, image build, plugin install/import,
Persona seed, MCP handshake, Compose, repository scan, and selected disposable
container smoke. Flaky model tests use deterministic gateways or explicit
non-blocking evaluation policy.

### Rollback

Tracing can be disabled independently. Required security and isolation tests
cannot be removed to restore green status.

## Phase 10: Compatibility Cleanup

### Objective

Delete legacy modules and old canonical paths only after every removal checklist
item in `migration-map.md` passes.

### Required evidence

- Production entry uses new implementation.
- Corresponding behavior tests and docs are current.
- No old import, mount, script, CI path, or operator workflow remains.
- Data migration and rollback are complete.
- A focused removal PR has an independently testable rollback release.

## Recommended First Implementation PR

Title: **Add framework-neutral Dududa core contracts**

This PR is Phase 2A only. It should:

1. Add `packages/dududa-agent` packaging.
2. Add immutable Message Envelope, Attachment/Mention, Actor,
   ConversationScope, DraftResponse/FinalResponse/RuntimeResult, MemoryScope,
   Capability descriptor, typed errors, Runtime Phase/State, delivery receipt,
   and configuration models.
3. Add Protocol definitions without concrete adapters.
4. Add unit and forbidden-import tests.
5. Install the package in CI and the derived image and add an import smoke.
6. Leave every current plugin file and event path untouched.

It must not extract permissions, move directories, connect Iris, add model
calls, alter commands, or change Compose services. That keeps the review focused
and rollback purely additive.

## Phase Acceptance Matrix

| Phase | New authoritative surface | Required new gate before exit |
| --- | --- | --- |
| 2 | Domain contracts/package | Package/import/layer tests |
| 3 | Security/config primitives | Behavior and negative security tests |
| 4 | AstrBot adapters/commands | Plugin import and event contracts |
| 5 | Memory boundary | Full isolation and migration rollback |
| 6 | Runtime decisions/composition | State, eval, shadow-no-side-effect tests |
| 7 | Capability/MCP runtime | Bounded tool loop and MCP contracts |
| 8 | Operations/layout/manifest | Disposable full lifecycle and rollback |
| 9 | Trace/eval/CI | Complete CI matrix and privacy-safe fixtures |
| 10 | No compatibility dependency | No old users plus rollback release |
