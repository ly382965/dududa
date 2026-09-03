# Task Plan

Branch: api-key-pools
Parent: agent-expansion
Title: Three-Tier LLM API Key Pools

## Acceptance

- [ ] Independent `/api-keys` route and left navigation entry are usable on
  desktop and mobile.
- [ ] Haiku/Luna, Sonnet/Terra and Opus/Sol each have an independent pool.
- [ ] Provider/Base URL/model/reasoning/timeout/budget fields and multiple key
  entries can be created, edited, disabled and removed.
- [ ] Secrets are accepted only on explicit writes, persisted outside the
  repository with mode `0600`, and never returned or logged.
- [ ] Existing Runtime tier and Control Plane behavior remain unchanged when a
  pool is empty or unavailable.
- [ ] Focused Web/server/security tests and typecheck/build pass.
- [ ] Design and operations documentation describe the contract and deployment
  path.

## Local Steps

- [ ] Add typed API-key DTO/schema and external secret store.
- [ ] Add Node server routes and upstream/runtime integration boundary.
- [ ] Add Vue route, rail item, pool management view and adapters.
- [ ] Add focused tests and update documentation.
- [ ] Run verification and record findings before handoff.
