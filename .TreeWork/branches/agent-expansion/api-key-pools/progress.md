# Progress

<!-- treework:status:start -->
Branch: api-key-pools
Parent: agent-expansion
Status: complete
Verification: verified
Last sync: unix:1788576635
<!-- treework:status:end -->

## Current Reality

The Web console now exposes an independent `/api-keys` workbench in the left
rail. It maintains isolated Luna/Haiku, Terra/Sonnet and Sol/Opus pools with
provider metadata, multiple credentials, deterministic priority ordering,
health probes and accessible desktop/mobile CRUD flows.

The Node gateway owns a versioned, atomically replaced private store outside
the checkout (the example host path is `../dududa-state/api-keys`). Public
responses are allow-listed and masked; malformed snapshots, permissive file
modes, oversized snapshots, stale revisions and failed persistence are
rejected without changing the in-memory or on-disk committed state. Compose shares the
store read/write with Web and read-only with AstrBot, while operations commands
provision and validate the UID/mode boundary before startup.

The Python adapter validates the same three-pool snapshot and can project one
pool to AstrBot 4.26.2 OpenAI Chat or Anthropic Source/Provider records. It is
an explicit deployment adapter only: saving in the page does not hot-reload a
live AstrBot process and does not change `TierPolicy` or Control Plane routing.

## Open Issues

- A production deployment may separately wire the documented projection into
  a controlled AstrBot Provider Manager reload after validating model IDs and
  conformance evidence. This branch deliberately does not install that hook.
- The repository-wide `ci-python` evaluation profile still stops at discovery
  because the default local environment omits the existing optional `joblib`
  corpus dependency. Focused Python contracts for this branch pass; this known
  mainline environment gap was not expanded into dependency work here.
- The raw Key Store is intentionally outside the standard plaintext operations
  backup. Disaster recovery depends on deployment Secret Manager reinjection
  and upstream credential rotation, as recorded in the deployment runbook.

## Exit Notes

- No real provider credential was read, written to Git or used in verification.
- Runtime/model routing behavior remains owned by the existing descriptors and
  conformance evidence; pool metadata alone is not evidence of live sync.
