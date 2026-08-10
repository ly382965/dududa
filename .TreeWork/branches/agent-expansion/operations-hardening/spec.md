# Branch Spec

Branch: operations-hardening
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Scope And Reuse

S16 implements the already accepted operations design without changing Agent
Domain contracts or moving repository paths. The current root `manage.sh`,
Compose file, data root and plugin IDs remain compatible. Complex behavior is a
standard-library Python operations core under `scripts/`; S17 may move it to
`ops/cli` by `git mv` after its command contract is proven.

### Release And State Authority

A release manifest is immutable, versioned and digest-bound. It identifies the
source revision, previous release, image references, component/config digests
and data schema; it never contains secret values or runtime data. Mutable
operation state is kept separately as atomic state and append-only receipts.
Only a successful health result may advance the current release pointer.

The operations root owns private `releases/`, `receipts/`, `staging/` and
`state.json` below `STACK_DATA_ROOT/.dududa`; verified backup payloads remain in
`STACK_DATA_ROOT/backups/` as established by the deployment design. Bootstrap
is idempotent and never creates or overwrites `.env`.

### Operations Model

- `health` is read-only and combines deterministic release/data checks with an
  injected deployment probe. `healthy`, `degraded` and `unhealthy` remain
  distinct; missing external QQ or Provider evidence is never upgraded to
  healthy.
- `backup` inventories declared relative paths, rejects symlinks/path escape,
  uses the SQLite backup API for SQLite data, records size/mode/digest and
  publishes a verified backup atomically.
- `restore` always verifies the backup and produces a deterministic plan first.
  Apply is limited to an explicit disposable/empty destination in S16; in-place
  production overwrite remains an external operator action.
- `upgrade` is a bounded state machine over injected `prepare`, `start`,
  `health` and `rollback` stages. It requires a verified pre-upgrade backup,
  writes a stage receipt after every transition and promotes the target only
  after health succeeds.
- Failure after activation invokes rollback once, verifies rollback health and
  preserves the failed target plus all receipts. Rollback never guesses a
  schema downgrade and refuses a missing previous release.

The CLI exposes bootstrap, manifest, health, backup, restore-plan/restore,
upgrade and rollback over these contracts. A fixture driver proves orchestration
without invoking Docker; production Docker/HTTP/MCP probes are additive
drivers and are not fabricated in this branch.

### Deployment Surface Boundaries

S16 adds a static Compose contract check for loopback-published WebUI ports,
read-only source/config mounts, private data mounts and explicit `bot_net` /
`edge` membership. It does not narrow the shared NapCat mount without upstream
evidence and does not restart or inspect the running stack during verification.

### Focused Evidence

Use temporary roots, a small SQLite fixture, a fake clock and a recording
driver. Sampling is limited to one complete
`bootstrap -> start -> health -> backup -> upgrade -> restore -> rollback`
lifecycle plus representative manifest tamper, backup tamper/restore boundary
and failed-health rollback cases. Web and full-repository suites remain for
S19 because S16 does not change Web behavior.
