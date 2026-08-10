# Dududa Old-To-New Migration Map

状态：S01–S16 的既定本地/离线范围已完成。S17 物理路径迁移正在独立工作树进行：插件、
配置、MCP service 与 deploy/ops 两批已经提交，第三方 v1 资产批次仍未提交、未验证，整个
S17 尚未合并。现有插件 ID、容器目标路径、包名、MCP Server ID 和根兼容入口保持不变。

## Mapping Rules

- Prefer `git mv` when ownership changes without behavior changes.
- Prefer extraction plus a compatibility import when behavior is reused by a
  new package.
- Do not combine a path move, data migration, plugin-ID change, and behavior
  rewrite in one PR.
- A compatibility module is named `compatibility`, `legacy`, or `deprecated`
  and documents its removal gate.
- Existing public commands, plugin IDs, event priority, event-stop behavior,
  data paths, and root operation entry points stay authoritative until contract
  tests and a deliberate cutover say otherwise.

## Repository Path Map

| Current path | Target path | Migration mode | Compatibility requirement |
| --- | --- | --- | --- |
| `plugins/astrbot_plugin_dududa_core/` | `apps/astrbot-plugins/astrbot_plugin_dududa_core/` | S17 batch 1 已在分支提交，尚未合并 | Container target and plugin ID remain unchanged |
| `plugins/astrbot_plugin_reply_polish/` | `apps/astrbot-plugins/astrbot_plugin_reply_polish/` | S17 batch 1 已在分支提交，尚未合并 | Keep global result hook until output contracts cut over |
| `plugins/astrbot_plugin_target_talk/` | `apps/astrbot-plugins/astrbot_plugin_target_talk/` | S17 batch 1 已在分支提交，尚未合并 | Keep plugin ID, config path, and event behavior |
| New core | `packages/dududa-agent/` | Additive | Install in CI and image before any adapter import |
| `services/icourse-mcp/` | `services/mcp/icourse/` | S17 batch 1 已在分支提交，尚未合并 | Keep package and CLI names; update every path consumer together |
| `services/unified-mcp-worker/` | `services/mcp/unified-worker/` | S17 batch 1 已在分支提交，尚未合并 | Keep distribution/import name and isolated worker contract |
| `config/` | `configs/` | S17 batch 1 已在分支提交，旧路径保留兼容链接 | One canonical source; runtime semantics unchanged |
| `compose.yml` | `deploy/compose/compose.yml` | S17 batch 2 已在分支提交，根文件为兼容入口 | Root/canonical Compose must render equivalent contracts |
| `.env.example` | `deploy/env/.env.example` | S17 batch 2 已在分支提交，根路径保留兼容链接 | Root example remains readable for one Release |
| `docker/astrbot/` | `deploy/docker/astrbot/` | S17 batch 2 已在分支提交，旧路径保留兼容链接 | Compose and CI update in the same batch |
| `manage.sh` | `ops/manage.sh` plus root wrapper | S17 batch 2 已在分支提交 | Existing commands keep documented semantics |
| `scripts/` | `ops/cli/` | S17 batch 2 已在分支提交，旧路径保留兼容链接 | Root wrapper and repository-root resolution remain stable |
| `plugins.lock.json` | `third_party/plugins.lock.json` | S17 batch 3 在途：移动当前 v1 authority，不切换格式 | 根 v1 lock 保留一 Release 兼容链接，installer 只读 canonical v1 lock |
| `patches/` | `third_party/patches/` | S17 batch 3 在途、未提交/未验证 | v1 lock 使用 canonical patch path |
| `vendor/` | `third_party/vendor/` | S17 batch 3 在途、未提交/未验证 | Better Reminder tree and AGPL license remain byte-identifiable |
| 无 | `third_party/manifest.json`（Manifest v2） | 延期，尚未成为 authority | 需完整源码 hash、依赖 lock/SBOM 与许可证证据；不得伪造或静默切换 |
| Flat `tests/` | layered `tests/` directories | `git mv` by concern | Test discovery and CI stay green in each move |
| Existing docs | concern-specific docs plus archive | Fact-by-fact merge | No deletion until links and facts are mapped |

## Core Plugin Mapping

### Imports, registration, and construction: `main.py` lines 1-70

| Current element | Target | Method | Removal gate |
| --- | --- | --- | --- |
| AstrBot registration and `Star` lifecycle | App `main.py` composition root | Keep and shrink around injected services | All handlers delegated and plugin import smoke passes |
| `PendingAction` | `dududa.runtime` or application confirmation model | Add pure type, adapt current queue | Command contract and durable-scope tests pass |
| `ImageGenerationError` | `dududa.domain.errors` plus public error mapper | Extract typed error | Image adapter uses normalized errors |
| Construction of permission, audit, iCourse, state | App composition module | Introduce factories and Protocol injection | No domain use case constructs concrete adapters |

### Identity, policy, state, and confirmation: lines 72-139

| Current element | Target | Method | Compatibility/test |
| --- | --- | --- | --- |
| `_sender`, `_group` | App `adapters/message.py` | Convert Event to `MessageEnvelope` and `Actor` | Event fixture contract |
| `_blocked`, `_require_admin`, `_require_owner` | `security/permissions.py` | Extract policy over domain Actor/Scope | Existing role matrix plus default-deny tests |
| User/group JSON access | Memory/preference/group policy repositories | Wrap existing JSON first | Same files and values; corruption/concurrency tests |
| `_new_confirmation` | confirmation service | Bind Actor, Scope, action, payload digest, permission | Cross-conversation and role-recheck tests |

### Natural course flow: lines 141-741

| Current responsibility | Target | Method | Compatibility/test |
| --- | --- | --- | --- |
| Event interception and stop behavior | `commands/course.py` and event router | Keep adapter decorator, call use case | Priority and stop-event contract |
| Regex and query cleanup | iCourse capability query normalizer | Extract pure functions first | Fixture table preserves outputs |
| Provider JSON intent extraction | Perception structured-output adapter | Wrap current Provider call | Schema-invalid/fallback tests |
| Search/detail/review orchestration | iCourse Capability Provider | Move fixed calls behind capability interface | Golden observation fixtures |
| Repeated stdio calls | Unified MCP Client and Registry | Compatibility `ICourseClient` delegates | One process/registry path contract |
| Review summarization | Model Router `RESPONSE_COMPOSITION` role | Replace direct Provider lookup | Fallback and citation tests |
| Ranking/cards/excerpts | iCourse presentation plus Response Composer | Extract pure functions | Snapshot/golden text tests |

### User and memory commands: lines 743-875

| Current | Target | Method | Removal gate |
| --- | --- | --- | --- |
| Help/basic/privacy commands | `commands/basic.py` | Move decorators and adapt use cases | Command text/permission tests |
| `/remember`, `/forget`, `/memory` | `commands/memory.py` -> Write Gate/Repository | First preserve legacy JSON through adapter | Scoped export/delete and migration complete |
| `/style` | user preference use case; later OC Renderer input | Preserve storage before making behavior effective | Renderer behavior explicitly approved |

### Course command group: lines 876-970

Decorators move to `commands/course.py`. They construct typed requests and call
the same iCourse Capability Provider used by natural requests. Permission and
refresh policy are centralized and tested before current handlers are removed.

### Administration: lines 972-1231

| Current command area | Target use case/port |
| --- | --- |
| Status, plugins, MCP | Query services over health/plugin/MCP registries |
| Group and user state | GroupPolicy and UserPreference repositories |
| Memory | Scoped memory administration use case |
| Logs | Audit query service with category/severity filtering |
| Backup/restart | Runtime operations gateway; never shell execution in core |
| Model | Model policy repository and Router configuration |
| Permission | Authorization policy repository |
| Broadcast | Explicit unsupported/approval workflow until an executor exists |

Decorators move to `commands/admin/`. Each high-risk use case uses confirmation
binding and an injected gateway. Current no-op safety behavior for restart and
broadcast remains until a separately approved executor exists.

### Confirmation and model/permission writes: lines 1233-1341

Extract the confirmation state machine and repositories without changing
visible messages first. Direct AstrBot JSON writes remain in an outer runtime
config adapter. Removal requires atomic-write, backup, stale-role, stale-payload,
expiry, replay, and rollback tests.

### Compatibility, image, and entertainment: lines 1343-1540

| Current | Target |
| --- | --- |
| Third-party hint commands | `commands/compatibility.py`, then Capability entries |
| Fortune/draw | Pure built-in capabilities |
| Image prompt policy | security content policy |
| Provider source/key lookup | AstrBot Model Gateway; credentials never enter core |
| Image HTTP call | Provider adapter for `IMAGE_GENERATION` role |
| AstrBot `Image` construction | Output adapter |

The direct image implementation is removed only after the new gateway preserves
timeout, model selection, safety denial, base64/URL output, and public error
behavior without exposing credentials.

## Supporting Core Files

| Current file | Current responsibility | Target ownership | Migration approach |
| --- | --- | --- | --- |
| `permissions.py` | Event-to-role and policy | `domain/identities.py`, `security/permissions.py`, AstrBot identity adapter | Extract pure policy; old module delegates |
| `audit.py` | Event-based JSONL audit and key scrubbing | `security/audit.py`, `security/redaction.py`, JSONL sink adapter | Add domain event and sink Protocol; preserve current file path |
| `course.py` | Concrete stdio MCP process and formatting | MCP Client/Registry, iCourse provider, presentation | Old `ICourseClient` wraps new client until handlers move |
| `help_menu.py` | Static menus | App help commands; later generated capability summaries | Move only after command inventory contract exists |
| `config.py` | Paths, broad-error JSON, AstrBot config writes | typed config, repository ports, AstrBot runtime config adapter | Keep constants/paths in compatibility adapter |
| `_conf_schema.json` | AstrBot WebUI config | App-owned schema plus typed translation | Keep keys and defaults until a config migration exists |
| `metadata.yaml` | Plugin identity | App plugin root | Never change ID implicitly |

## Reply Polish Mapping

| Current responsibility | Target | Migration |
| --- | --- | --- |
| Plain-text split functions | Pure output formatting utility | Extract with property/golden tests |
| QQ Node/Nodes creation | AstrBot/QQ Output Adapter | Keep framework types outside core |
| Global decoration hook | Compatibility plugin | Remains until all affected plugins are understood |
| Threshold/config parsing | Typed adapter config | Preserve existing schema keys |

The final design may still keep ReplyPolish as a separate plugin if operators
want global QQ behavior. It is not automatically merged into OC Renderer.

## Target Talk Mapping

| Current responsibility | Target | Migration |
| --- | --- | --- |
| AIOCQHTTP Event extraction | AstrBot Message Envelope adapter | Contract fixtures before replacement |
| Target, allowlist, keyword, probability rules | Legacy Social Decision policy | Extract pure deterministic function |
| Recent group history | ConversationContextStore | Add bounded, scoped storage; stop pre-filter capture |
| Cooldowns | Rate-limit service | Preserve per-target/global semantics |
| Provider selection and prompt | Model Router `DIRECT_CHAT` role | Inject gateway and structured context |
| Direct `event.send()` | Runtime response -> Output Adapter | Preserve timing/order in selective cutover |

The plugin remains separately loadable until its global event contract and
rollback flag are proven. Its current behavior is not the complete Social
Decision implementation.

## iCourse Service Mapping

The first service move keeps distribution/import names stable.

| Current file | Target service concern | Notes |
| --- | --- | --- |
| `run_icourse_mcp.py` | compatibility launcher | Retain while source is bind-mounted |
| `server.py` | `transport/mcp.py` | Atomic tools and envelope conversion only |
| `crawler.py` | application crawl/query service | Apply explicit limits and error model |
| `fetcher.py` | infrastructure HTTP | External-data, robots, Cookie, timeout policy |
| `parser.py` | infrastructure HTML parser | Add captured public fixtures |
| `storage.py` | infrastructure SQLite repository | Fix export root and comment replacement semantics |
| `models.py` | iCourse service domain | Do not move course entities to generic Agent domain |
| `cli.py` | service operator CLI | Separate model-eligible tools from admin crawling/export |
| MCP examples | `configs/mcp/servers/icourse.json` and service examples | Strict JSON Registry is canonical; S17 batch 1 moves the template without changing Server ID |

Core receives an `ICourseCapabilityProvider` over generic MCP contracts. It
never imports service modules.

## Operations Mapping

| Current | Target stage |
| --- | --- |
| `manage.sh init` | `bootstrap` plus config `prepare` |
| `manage.sh plugins` | `prepare --plugins-only` |
| `manage.sh sync` | `prepare --config-only` |
| Compose build inside `up` | explicit `build` |
| Compose start inside `up` | explicit `start` |
| `seed` | explicit idempotent `seed`, once per intended release |
| No current command | `health`, `backup`, `restore`, release staging |
| `upgrade` | staged `preflight -> backup -> prepare -> build -> activate -> offline migrations -> start -> post-start seed -> health -> commit`, rollback on failure |
| Root `manage.sh` | compatibility wrapper around Python operation CLI |

## Third-Party Mapping

The current installation authority remains v1 `third_party/plugins.lock.json`
after S17 batch 3, with the root v1 path retained as a one-Release compatibility
link. The planned `third_party/manifest.json` v2 would normalize Git, sparse,
vendor, patch and image items and bind source/tree/patch hashes, license evidence
and Python/system dependency locks, but it is not implemented or authoritative.

Better Reminder remains isolated AGPL vendor code. Iris remains a patched
third-party backend; its code and uncertain license are not copied into the MIT
core package. Missing Iris license evidence is a v2 cutover blocker, not a fact
that S17 may invent.

## Data Migration Map

| Current data | Future handling | Rule |
| --- | --- | --- |
| Core user JSON | Compatibility repository -> scoped migration | Never infer group/private visibility silently |
| Core group JSON | Group policy/preference repository | Preserve IDs and values; inactive settings stay inactive until approved |
| Audit JSONL | Legacy sink then versioned audit events | No rewrite without backup/integrity plan |
| Iris stores | Iris adapter and offline Scope migration | Missing Scope quarantined |
| AstrBot config/Persona DB | Runtime config and Persona adapters | Keep schema-aware backup and idempotent seed |
| iCourse SQLite | Service-owned repository | Cache may be rebuilt; do not treat as Agent memory |
| NapCat login/config | Remains operator-private | Never migrate through Agent package |

## Legacy Removal Checklist

A legacy module or path may be removed only when all are true:

- New implementation is the production entry for the same behavior.
- Unit, contract, integration, and relevant isolation tests pass.
- Configuration and persisted data migration is complete or unnecessary.
- No import, Compose mount, script, CI, doc, or operator command uses the old
  path.
- A rollback artifact and procedure exist and have been exercised.
- Documentation and `PROGRESS.md` record the cutover.
- Removal is a focused PR, not bundled with unrelated behavior.
