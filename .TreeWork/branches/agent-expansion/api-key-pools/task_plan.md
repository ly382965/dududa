# Task Plan

Branch: api-key-pools
Parent: agent-expansion
Title: Three-Tier LLM API Key Pools

## Acceptance

- [x] Independent `/api-keys` route and left navigation entry are usable on
  desktop and mobile.
- [x] Haiku/Luna, Sonnet/Terra and Opus/Sol each have an independent pool.
- [x] Provider/Base URL/model/reasoning/timeout/budget fields and multiple key
  entries can be created, edited, disabled and removed.
- [x] Secrets are accepted only on explicit writes, persisted outside the
  repository with mode `0600`, and never returned or logged.
- [x] Existing Runtime tier and Control Plane behavior remain unchanged when a
  pool is empty or unavailable.
- [x] Focused Web/server/security tests and typecheck/build pass.
- [x] Design and operations documentation describe the contract and deployment
  path.

## Local Steps

- [x] Add typed API-key DTO/schema and external secret store.
- [x] Add Node server routes and upstream/runtime integration boundary.
- [x] Add Vue route, rail item, pool management view and adapters.
- [x] Add focused tests and update documentation.
- [x] Run verification and record findings before handoff.
