# Branch Spec

Branch: layout-migration
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Purpose And Authority

S17 performs path-only ownership migration after S16 established a recoverable
release boundary. It does not redesign Agent, plugin, MCP, Web or operations
behavior. Canonical source paths become:

```text
apps/astrbot-plugins/*
services/mcp/icourse
services/mcp/unified-worker
configs/*
deploy/docker/*
deploy/compose/compose.yml
deploy/env/.env.example
ops/manage.sh
ops/cli/*
third_party/plugins.lock.json
third_party/patches/*
third_party/vendor/*
```

`apps/web` and `packages/dududa-agent` are already canonical and are not moved.
Flat test reorganization belongs to S18. Runtime data, `.env`, databases and
container state are never moved.

### Migration Batches

Every source ownership change uses `git mv`; each batch updates every known
consumer before the next batch:

1. move plugins, configs and both MCP services, then update Compose, Docker,
   Python workspace, tests, Dependabot and metadata links;
2. move Docker/Compose/environment assets and operations CLI, then make root
   `manage.sh` and `compose.yml` thin compatibility entrypoints;
3. move v1 third-party lock, patch and vendor content under `third_party`,
   update the installer and retain root `plugins.lock.json` as a one-release
   compatibility link.

Root `manage.sh` resolves and `exec`s `ops/manage.sh`. Canonical operations code
always resolves the repository root from `ops/`; scripts resolve it from
`ops/cli`. Root Compose includes the canonical Compose project; both root and
canonical invocations use the repository as Compose project directory, so
build contexts, bind mounts and relative private data remain unchanged. Root
`.env.example` remains a compatibility link to the canonical template.

### Stable Runtime Contracts

- Container plugin targets, plugin IDs, AstrBot decorator registration and
  `/AstrBot/data/plugin_data/*` remain unchanged.
- Container paths `/opt/dududa/config`, `/opt/dududa/scripts` and
  `/AstrBot/data/icourse-mcp` remain unchanged; only their host sources move.
- Distribution/import names `dududa-agent`, `icourse-mcp`,
  `dududa_unified_mcp_worker` and MCP server ID `icourse` do not change.
- `STACK_DATA_ROOT` and Web data roots still resolve relative to repository
  root through the root/canonical operation entrypoint.
- No old Client, Handler or behavior compatibility module is removed; S22 owns
  evidence-based cleanup.

### Third-Party Boundary

ADR 0005 requires verified source hashes, dependency locks and license evidence
before Manifest v2 can become installation authority. Those facts are not
available for every pinned plugin, especially Iris. S17 therefore moves the
current exact v1 lock without weakening it and records the v2 cutover as an
unmet supply-chain gate. It does not invent hashes, licenses or a second
editable authority.

### Focused Evidence

Use consumer scans plus representative contracts rather than a full suite:

- canonical paths exist and legacy implementation directories do not;
- root wrappers and canonical commands resolve the same project/data paths;
- root and canonical Compose render the same services, mounts, networks and
  Dockerfiles without starting containers;
- Python workspace/lock, iCourse, unified worker, plugin split and installer
  contracts consume canonical paths;
- one package/import/build smoke and focused secret/whitespace checks pass.

Web behavior is unchanged, so Web tests remain deferred to S19. Real container
recreation, QQ state and production data are outside S17.
