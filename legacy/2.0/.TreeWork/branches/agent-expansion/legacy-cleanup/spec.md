# Branch Spec

Branch: legacy-cleanup
Parent: agent-expansion

## Development Design

### Purpose And Evidence Boundary

S22 removes only compatibility surfaces whose consumers can be migrated on the
current branch and whose previous release is independently recoverable. The
authoritative baseline is the S19 offline candidate `e303dc8`, its 18-gate
receipt and the S18/S19 source archives. A S19 `remove_candidate` is an intake
signal, not automatic deletion authority.

This is a focused compatibility cleanup. It does not redesign Domain, Runtime,
Router, Capability, Memory, proactive behavior or Web; read production data;
change running containers; call a Provider; fetch a source; or send QQ output.

### Removal Set

The following ten tracked path aliases are removed after every repository,
CI, documentation and test consumer is switched to the canonical S17 layout:

- `.env.example` -> `deploy/env/.env.example`;
- `config` -> `configs`;
- `docker` -> `deploy/docker`;
- `plugins` -> `apps/astrbot-plugins`;
- `scripts` -> `ops/cli`;
- `patches` -> `third_party/patches`;
- `vendor` -> `third_party/vendor`;
- `plugins.lock.json` -> `third_party/plugins.lock.json`;
- `services/icourse-mcp` -> `services/mcp/icourse`;
- `services/unified-mcp-worker` -> `services/mcp/unified-worker`.

Tests import AstrBot plugin packages from the canonical
`apps/astrbot-plugins` source root. A test bootstrap may add that one canonical
directory to `sys.path`; no root `plugins` compatibility package or second
source tree is created.

### Dedicated iCourse Client Removal

S12 made `ICourseClient` a facade over `UnifiedMcpClient`, and S19 proved the
registry, isolated worker, Compose mounts, image build and previous-release
rollback. S22 therefore removes `LegacyICourseClient`, its per-call MCP v1
Session/process creation, the `icourse_mcp_mode` switch and automatic direct
fallback.

Missing, disabled or invalid Unified infrastructure does not crash unrelated
plugin functions and does not silently call another transport. Composition
returns a small fail-closed unavailable iCourse facade whose call/discovery
methods reject with a stable reason and whose close is idempotent. The normal
production path has one mode, `unified`; status surfaces may report
`unavailable` but cannot select `legacy`.

The isolated Unified worker still keeps `protocol_mode=legacy` for the actual
iCourse MCP 1.29 Server. This is a server-protocol compatibility requirement,
not the removed dedicated AstrBot Client.

### Explicit Retains

S22 retains these live surfaces and records why:

- root `manage.sh` and `compose.yml` operator wrappers;
- `RolloutAdmissionAction.LEGACY`, because off/shadow still leave delivery
  ownership with the existing Handler until S23;
- `LegacyRolePolicy`, because current permissions/TargetTalk/ReplyPolish still
  consume it;
- `JsonMemoryRepository`, because the production `/remember` path has not
  migrated to S14 storage;
- Unified worker `protocol_mode=legacy`, because iCourse is still MCP v1;
- the old AstrBot `AuditLog`, which remains distinct from S18 Runtime Trace and
  requires a later production privacy migration.

Retained surfaces are not renamed to hide them from scans and are not counted
as S22 failures.

### Documentation And Operations Cutover

All active examples and commands use canonical paths. Root operator wrappers
remain documented where they are still public, but root `.env.example` is not:
Compose commands and `ops/manage.sh` use `deploy/env/.env.example`. Historical
baseline/review prose may mention an old path only when explicitly labeled as
historical, not as a current command.

The S19 legacy catalog remains an immutable record of pre-S22 evidence. S22
records final removed/retained decisions in migration/progress documents and
repository contracts rather than mutating the S19 catalog digest.

### Verification And Rollback

Verification proves:

1. removed aliases are absent from Git and filesystem;
2. active code, tests, CI, Compose and operator docs use canonical paths;
3. plugin tests use the canonical test import root;
4. Unified iCourse is the only callable client and unavailable composition
   produces zero direct MCP calls;
5. all explicit retains still have consumers and their tests remain intact;
6. canonical/root Compose rendering remains equivalent with the canonical env;
7. focused Python 3.10, complete Python 3.12 repository discovery, worker,
   package/import, image smoke, secret and whitespace gates pass.

S22 does not repeat the complete S19 Web/Eval/30-day matrix because it changes
no Web, Eval policy, Scheduler or proactive behavior. The previous S19 source
archive is regenerated from exact commit `e303dc8`; its digest and the S19
candidate receipt provide rollback evidence. Failure of any removal contract
keeps the branch incomplete rather than restoring an alias locally.
