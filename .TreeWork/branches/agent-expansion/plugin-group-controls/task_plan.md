# Task Plan

Branch: plugin-group-controls
Parent: agent-expansion
Title: PR12 And Per-Group Plugin Controls

## Scope (owned work and boundary; not progress notes or implementation history)

- PR12 integration, real per-group plugin controls and verified current Bot-only deployment.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] PR12 head ancestry is merged and published, with relevant tests and actual plugin loading verified.
- [x] Group-only plugin switches persist through the existing Scope Policy and gate real handlers before effects; unrelated groups/accounts and existing restrictions are preserved.
- [x] Current Bot services use verified integrated/stable artifacts; no superseded Bot service remains active; private rollback and excluded services are retained.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Review PR and connect policy controls through UI and handlers; add focused tests.
- [x] Verify, publish and deploy versioned artifacts; record actual running versions and any limitations.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Other sites (including docs), proxies/auth/databases, real QQ test sends, B50 reactivation and broad model-quality tuning.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Completed bot-release-convergence, current external policy/keys/login state and existing authorized Git remote.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: The preceding release and its children are complete; PR12 introduces a new plugin while existing Reread bypasses group policy.
- Reuse check: S23 owns human/live-group quality, not this integration and UI/handler configuration change.
- New branch rationale: One bounded successor owns this new request without reopening completed release acceptance or adding parallel implementation branches.
