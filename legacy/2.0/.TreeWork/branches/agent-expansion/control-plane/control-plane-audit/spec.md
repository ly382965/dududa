# Branch Spec

Branch: control-plane-audit
Parent: control-plane

## Development Design

### Audit Purpose

This branch proves the integrated S21 offline outcome and removes residual
browser-local Agent authority. It does not redesign the Control Plane or add
features merely to broaden a matrix.

### Required Negative Evidence

Audit exact Bot/account/group isolation, unknown/expired operator sessions,
stale preview and assignment revisions, duplicate commands, concurrent admins,
restart/LKG, failed projection providers, rollback and pending zero-service.
Direct attempts by Group Context, Plugin, Model or Bandit data to alter an
assignment must be rejected by type/command boundaries.

Delete or replace `approveDraft()` direct NapCat delivery and local
`respondPermission()`/`saveSettings()` success mutation. Human QQ send remains
the existing typed NapCat client workflow; Agent Output remains a separate
governed command and returns unavailable until its real composition exists.

### Proportionate Verification

Run focused Python Control Plane tests, relevant import boundaries, Web unit/
server tests, typecheck/build and a small onboarding/operations E2E. Re-run the
private NapCat history only if history/Connector/Perception/session projection
changed. Do not run S23, use external data or mutate running containers.
