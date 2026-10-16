# Task Plan

Branch: pr10-selective-integration
Parent: agent-expansion
Title: PR10 Selective Plugin And MCP Integration

## Scope (owned work and boundary; not progress notes or implementation history)
- Select and port only non-duplicate PR #10 MCP assets into canonical service
  directories.
- Integrate the non-duplicate social rules as an independent, explicit-command,
  default-off AstrBot plugin.
- Register bounded cache-only MCP Servers as default-off optional assets without
  adding Planner-facing Capability definitions/mappings.
- Add focused service/registry tests and update the technical/user-facing
  integration documentation.
- Prepare the verified branch for Lead integration and push to `main`.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] No PR #10 duplicate Core/plugin, old Compose, hard-coded credential, or
      direct MCP client is present in the resulting diff.
- [x] Selected services build/import and expose only documented bounded tools.
- [x] The social plugin uses only explicit namespaced commands, registers no
      catch-all handler or automatic send path, and remains disabled by default.
- [x] Registry files validate, are default-off, stay outside the Capability
      Catalog/Planner, and preserve the existing production MCP and shuttle
      composition.
- [x] Focused tests and relevant repository contract tests pass.
- [x] Design, migration, and README/status documents describe the integrated
      services and their limits accurately.
- [x] Branch changes and verification evidence are committed and ready for the
      Lead to merge and push to `origin/main`.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Review current canonical services and PR #10 selection against the spec.
- [x] Port and adapt local-recs, training-plan, campus-events, college-notice,
      and library service code; remove unsafe refresh/write surfaces from the
      production tool allowlist.
- [x] Integrate the social rules under an independent default-off plugin and add
      it to the owned-plugin installer.
- [x] Add canonical default-off Server configs without Capability schemas or
      mappings; package and mount the optional services without enabling them.
- [x] Add focused contract tests and run them under the locked Python setup.
- [x] Update architecture, capability, deployment, migration, README and
      status documents.
- [x] Review the diff, run the secret scan and relevant integration checks, and
      prepare the branch commit; Lead merge and push remain the next transition.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- PR #10's duplicate `astrbot_plugin_dududa_core`, catch-all social event
  monolith, and legacy short-command compatibility aliases.
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
