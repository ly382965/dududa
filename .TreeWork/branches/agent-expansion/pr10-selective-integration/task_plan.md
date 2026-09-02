# Task Plan

Branch: pr10-selective-integration
Parent: agent-expansion
Title: PR10 Selective Plugin And MCP Integration

## Scope (owned work and boundary; not progress notes or implementation history)
- Select and port only non-duplicate PR #10 MCP assets into canonical service
  directories.
- Integrate bounded read-only Registry and Capability definitions/mappings,
  default-off in deployment templates.
- Add focused service/registry tests and update the technical/user-facing
  integration documentation.
- Push the verified result to the repository's `main` branch.
-

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [ ] No PR #10 duplicate Core/plugin, old Compose, hard-coded credential, or
      direct MCP client is present in the resulting diff.
- [ ] Selected services build/import and expose only documented bounded tools.
- [ ] Registry and Capability files validate, are default-off, and preserve the
      existing four real MCP services and local shuttle plugin.
- [ ] Focused tests and relevant repository contract tests pass.
- [ ] Design, migration, and README/status documents describe the integrated
      services and their limits accurately.
- [ ] Changes are committed and pushed to `origin/main`.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [ ] Review current canonical services and PR #10 selection against the spec.
- [ ] Port and adapt local-recs, training-plan, campus-events, college-notice,
      and library service code; remove unsafe refresh/write surfaces from the
      production tool allowlist.
- [ ] Add canonical server configs, capability schemas/mappings and generation
      or consistency checks.
- [ ] Add focused contract tests and run them under the locked Python setup.
- [ ] Update architecture, capability, deployment, migration, README and
      status documents.
- [ ] Review diff, run secret scan and relevant full checks; commit, merge to
      `main`, and push.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- PR #10's duplicate `astrbot_plugin_dududa_core` and social event monolith.
- Academic-calendar and generic USTC-notice duplicates.
- Live crawler scheduling, proactive delivery, model/image API integration,
  AMap credential provisioning, or real-group rollout.
- Replacement root Compose/Docker layouts and unrelated lint cleanup.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Current `main` canonical layout and Unified MCP/Capability contracts.
2. Public source URLs or local seed data; no live credential is required for
   the read-only first slice.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: Existing Core, NotifAI, USTC campus services, local shuttle and
  installer/Registry ownership; PR #10 is based on an obsolete layout.
- Reuse check: No existing branch owns selective PR integration or these new
  public reference services.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml` as one
  bounded integration slice so service selection, Registry changes and docs
  can be reviewed together.
