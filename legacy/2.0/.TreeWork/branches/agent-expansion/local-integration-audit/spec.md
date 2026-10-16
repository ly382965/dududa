# Branch Spec

Branch: local-integration-audit
Parent: agent-expansion

## Development Design

### Purpose And Evidence Boundary

S19 proves one clean, release-candidate-shaped offline repository after S01-S18
and the accepted Web epic. It reuses the S18 suite runner, S16 release/backup/
rollback contracts, the existing Web scripts and the canonical Dockerfiles. It
does not add a second test framework, contact a Provider, fetch a live source,
read production data, send QQ messages or modify the running NapCat/AstrBot
stack.

Passing S19 means the committed candidate is reproducible and locally
recoverable. It does not mean real Chinese quality, Provider latency/cost,
production health, live-source freshness or S23 behavior has passed.

### Candidate Identity And Evidence Package

The candidate is one clean Git revision. Evidence binds the source revision,
root and MCP worker locks, Compose/config/plugin-lock digests, SLO policy,
Python/Eval receipts, Web gates, image IDs, disposable smoke results, rollback
artifacts and the S22 consumer inventory. Generated artifacts live under an
ignored or temporary 0700 directory; receipts are atomically written as 0600.

A small standard-library audit tool owns strict parsing and aggregation. It has
fixed gate IDs and never accepts arbitrary commands. It records status, count,
bounded reason code and evidence digest, not stdout/stderr, absolute paths,
environment variables, host/container names, source text, credentials or real
identifiers. Missing required gates, dirty source, digest drift, duplicate gate
IDs or an `external_pending` result presented as measured success fail closed.

### Pilot SLO Policy

S19 commits a strict versioned pilot policy rather than inventing production
measurements. It freezes:

- zero tolerance for wrong target, duplicate delivery, post-revoke/quiet-hour
  delivery, unauthorized Capability, cross-Scope Memory and sensitive Trace;
- the existing SHORT/MEDIUM/LONG visible-output token ceilings;
- provisional latency and recovery ceilings clearly labeled `pilot_default`;
- explicit `external_pending` fields for Provider cost, real QQ latency,
  human-quality and interruption measurements.

The audit validates the policy and records its digest. A pilot default can
close S19 but leaves `s23_ready=false`; user-approved numeric Provider/cost and
real-behavior thresholds must replace or approve it before S23.

### Execution Matrix

The release audit runs expensive gates once at this boundary:

1. Python 3.10.20 and 3.12.13 each use the locked root environment and a worker
   environment synchronized from its own lock. `ci-python` performs complete
   repository discovery and emits one low-sensitivity receipt per interpreter.
   Worker-local tests run separately. Test counts must agree except for the
   same documented host-only skips.
2. Python 3.12 replays all committed Eval bundles and explicitly samples the
   30-day Scheduler plus day 1/2/30 Digest and Probe no-send paths.
3. A fixed failure sample covers Router cancellation/timeout, MCP crash/schema
   drift, Capability UNKNOWN, Memory tombstone/restore, Scheduler rollback,
   Source cancellation, kill switch and failed-health single rollback. Full
   discovery remains the broader evidence.
4. Web production dependency audit, Unit/Server tests, typecheck/build and
   Playwright run once from the locked Node/npm inputs. Ports are checked before
   E2E so an unrelated process cannot be mistaken for the test server.
5. Package wheel/import/pip, compile, Ruff, Shell, rendered Compose, import
   boundaries, secret scan, lock checks and whitespace remain required.

### Disposable Image And Container Smoke

The canonical AstrBot and Web Dockerfiles build under unique local tags. Build
network use is limited to locked dependency acquisition; runtime smoke uses
`--network none`, unique disposable containers and a guaranteed cleanup trap.
It never invokes `docker compose up`, restarts an existing container or uses a
production volume.

AstrBot smoke verifies the installed agent package, MCP v1/v2 separation,
plugin import/composition and `pip check` with repository plugin sources mounted
read-only. Web smoke starts the built runtime with only a temporary token file
and verifies `/api/health` over container loopback. The receipt records image
IDs/digests and bounded statuses only.

### Rollback And S22 Handoff

S19 identifies the integrated S18 revision as the previous release and the S19
HEAD as the candidate. It generates digest-bound manifests and a recoverable
previous-source artifact, then exercises S16 backup/upgrade/failed-health/
single-rollback against disposable state. Candidate and previous manifests,
backup verification, restore plan and rollback summary must agree.

S19 also produces a tracked consumer inventory for each proposed S22 legacy
surface. The inventory distinguishes `remove_candidate`, `retain_live` and
`blocked_unknown`; it never deletes anything. In particular, the legacy
AstrBot Handler, legacy Memory path, compatibility Role policy and MCP worker
`protocol_mode=legacy` remain live unless separate evidence proves otherwise.
The old AstrBot audit sink is classified separately because its sender/group
fields are not S18 Runtime Trace.

### Failure And Recovery

- A failed required gate still writes a bounded failure receipt and the
  candidate remains unapproved.
- Image/container cleanup runs in `finally`/trap paths, including failed health.
- Missing Docker/Playwright/build dependencies are environment failures, not
  silent skips; the branch stays incomplete until rerun.
- A failed rollback, unverifiable previous artifact or consumer inventory gap
  blocks S19 completion and therefore S22 entry.
- No generated receipt may be committed as proof if it embeds host-specific or
  sensitive data; Verification records only stable digests and counts.
