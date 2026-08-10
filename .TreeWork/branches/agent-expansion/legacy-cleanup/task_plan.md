# Task Plan

Branch: legacy-cleanup
Parent: agent-expansion
Title: S22 Evidence-Based Legacy Cleanup

## Scope

- Remove the ten S17 path aliases after migrating active consumers.
- Remove the dedicated iCourse v1 Client/fallback while preserving a
  fail-closed unavailable facade and the worker's required iCourse v1 mode.
- Freeze removed/retained evidence and an exact S19 rollback artifact.

## Acceptance

- [ ] All ten declared aliases are absent and no active code, CI, test,
  Compose, operation or current documentation command consumes them.
- [ ] Test imports resolve canonical `apps/astrbot-plugins` packages without a
  root compatibility package or symlink.
- [ ] `LegacyICourseClient`, `icourse_mcp_mode` and per-call plugin MCP v1
  Session/process code are absent; Unified is the only callable client.
- [ ] Missing/disabled/invalid Unified iCourse composition is stable,
  fail-closed and makes zero direct MCP calls while unrelated plugin lifecycle
  can still initialize and terminate.
- [ ] Root `manage.sh`/`compose.yml`, legacy Handler/Role/Memory/Audit and worker
  `protocol_mode=legacy` are retained with direct consumer evidence.
- [ ] Repository, iCourse/composition, import, Compose, package, image, secret
  and whitespace gates pass at the scoped S22 level.
- [ ] Exact S19 candidate source is independently archived and the removal
  matrix/documentation accurately records removed and retained surfaces.
- [ ] Progress, Findings and Verification are synchronized; all changes are
  locally committed without push.

## Local Steps

- [x] Read S19 inventory/rollback evidence and freeze S22 Spec/Plan.
- [ ] Migrate canonical path/import/config/document consumers and remove the ten
  aliases as one focused path-cutover commit.
- [ ] Remove the dedicated iCourse Client and add fail-closed composition tests
  as a separate focused commit.
- [ ] Run scoped cross-version/package/image/Compose verification and create the
  S19 rollback archive.
- [ ] Update removal evidence and project status, commit, verify and return.

## Out Of Scope

- Removing or rewriting any explicitly retained surface.
- Migrating production Memory/Audit data or changing rollout ownership.
- Upgrading the real iCourse Server to MCP v2.
- Bandit, Provider/source/QQ access, Web features or S23 execution.

## Dependencies

1. S19 is complete/verified and merged; candidate `e303dc8` and its previous
   release evidence are available.
2. Canonical S17 paths remain the only intended source authorities.

## Branch Intake Gate

- Inspect: S19 inventory, migration map, repository contracts, symlinks,
  iCourse composition/facade and current active consumers.
- Reuse check: S19 audit owns the pre-removal inventory and S16 owns release
  recovery; S22 adds no second audit or deployment framework.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
