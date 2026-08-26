# Dududa Current State

Status: Phase 0 audit baseline
Baseline commit: `2767cc9768d4bce63d4b4ee811add951ebce6870`
Audit date: 2026-07-18

## Scope

This document describes the repository as it exists before the Dududa 2.0
refactor. It is evidence for migration decisions, not a claim that every
documented feature is fully implemented.

The repository is a Bot Runtime Monorepo. It owns AstrBot and NapCat
orchestration, three first-party AstrBot plugins, third-party plugin
installation, the iCourse MCP server, safe configuration templates, bootstrap
scripts, tests, CI, and security checks. General-purpose site infrastructure,
model-provider infrastructure, public gateways, and production runtime data
remain external.

At the audit baseline the repository contained 75 tracked files. The worktree
was clean, `main` tracked `origin/main`, and no business code was modified by
Phase 0.

## Post-Audit Dududa 2.0 Disposition

以下正文的 Runtime 图、插件清单和风险描述仍保留为“重构前基线证据”，不是 2026-08-16 的
默认运行设计。当前 S23 分支仍为 `paused / partial`，真实中文群聊风格尚未完成人工校准。

Dududa 2.0 的 WebUI 承载唯一 Bot Control Plane；管理员可通过它为新入群 Bot 选择初始
`GroupServiceProfile`。其中 `#/internal-test` 只是该控制台中的 Evaluation Adapter。Web 不复制
Router、权限、Memory、Tool 或 Output 决策权，所有配置变更仍通过 Core Command、Audit 和
Receipt 生效。Persona、群聊 channel rule 与 AnswerProfile 在一次生成中共同生效：人格通过措辞、节奏、关注点和信息取舍
自然表现，不复述人设、不自我介绍、不套固定口号、不机械卖萌，也不靠随机表情表现人格。

| AnswerProfile | QQ 发送形态 |
| --- | --- |
| SHORT | 始终普通消息，即使文本较长 |
| MEDIUM | 始终普通消息，即使文本较长 |
| LONG | 单段仍为普通消息；群聊中实际拆成至少两个纯文本 part 且无附件时合并转发；定向目标不另发 `@` |

| 插件 | Dududa 2.0 默认状态 | 资产处理 | 未来归属 |
| --- | --- | --- | --- |
| Meme Manager | deprecated，不再默认安装，不自动发表情 | 本轮不主动清理；若私有运行目录中存在图库、配置或源码则原状保留 | 用户显式触发的 Meme Capability |
| Reread | deprecated，不再默认安装，不概率复读 | 本轮不主动清理私有运行目录中的既有配置或数据 | 默认不提供自动复读 |
| PokePro | deprecated，不再默认安装，不自动戳一戳 | 本轮不主动清理私有运行目录中的既有配置或数据 | 可选显式交互 Capability |
| Target Talk | 退出默认 Compose 和入站路径 | 源码、配置保留 | S15E Governed Probe / 主动 Runtime |
| ReplyPolish | 1.0 LONG-only 兼容层，默认关闭 | 源码保留 | LONG-only legacy output |
| Iris Memory | 不拥有 2.0 Core Memory 控制面 | 既有数据保留 | S14 Memory 迁移或只读来源 |
| ChatSummary | 自动循环不进入 2.0 默认能力 | 历史数据保留 | 显式 Summary Capability |
| Better Reminder | 不拥有 2.0 Scheduler | 历史提醒数据保留 | S15B Scheduler / Capability |
| Dududa Core | 保留 | 源码、配置保留 | Dududa 2.0 AstrBot Adapter |
| Sub2API Readonly | 保留 | 源码、配置保留 | 显式只读 Capability |

`third_party/plugins.lock.json` 当前只保留 Iris、Better Reminder 和 ChatSummary v2；默认 Compose
不再挂载 Target Talk。退出默认安装、默认挂载或默认执行链，不等于删除源码、配置或持久数据。
本轮也没有修改或重启正在运行的 AstrBot/NapCat，因此以下历史运行态描述仍可能与私有数据目录
中实际已安装的旧插件并存。

## Repository Topology

| Area | Current responsibility | Important constraint |
| --- | --- | --- |
| `plugins/` | Three first-party AstrBot plugin roots | AstrBot must see each root at `/AstrBot/data/plugins/<plugin-id>` |
| `services/icourse-mcp/` | Installable Python package and stdio MCP server | Installed into the derived AstrBot image and also bind-mounted as source |
| `config/` | Safe Persona and MCP templates | Runtime Provider credentials and identifiers are not stored here |
| `scripts/` | Plugin install, MCP merge, Persona seed, repository scan | Scripts know current root paths directly |
| `compose.yml` | AstrBot and NapCat runtime | Both services join private `bot_net` and external `edge` networks |
| `docker/` | Derived AstrBot image | Only iCourse is installed by the current Dockerfile |
| `plugins.lock.json` | Third-party plugin declaration | Supports Git lock, sparse checkout, vendor, and patch fields |
| `patches/` | Iris privacy changes | Applied after checking out one exact upstream commit |
| `vendor/` | Better Reminder v1.4 source | Upstream AGPL license must remain attached |
| `tests/` | Eight repository and initialization tests | Mostly structural; little behavior coverage exists |
| `.github/` | CI, Dependabot, ownership | CI does not build the image or import AstrBot plugins |
| `docs/` | Product, operation, and architecture notes | Several documents overlap and some statements have drifted |

## Dududa 1.0 Runtime At The Audit Baseline

The following diagram records the pre-refactor runtime. It does not describe the
Dududa 2.0 default code or deployment path, and it does not assert that a private
running AstrBot/NapCat instance has already unloaded legacy plugins.

```text
QQ user or group
    |
    v
NapCat container
    | OneBot v11 and shared /AstrBot/data
    v
AstrBot container
    |-- astrbot_plugin_dududa_core
    |-- astrbot_plugin_reply_polish
    |-- astrbot_plugin_target_talk
    |-- six installed third-party plugins
    |-- AstrBot Provider API
    `-- iCourse MCP stdio process
            `-- private SQLite cache
```

At the audit baseline, the three first-party plugins did not import one another.
Their interaction was implicit through AstrBot's event pipeline:

1. `DududaCorePlugin` registered commands and an all-message course interceptor.
2. `TargetTalkPlugin` independently observed AIOCQHTTP group events and could send
   a generated reply directly.
3. `ReplyPolishPlugin` decorated group-message results produced by all plugins,
   not only Dududa responses.

This ordering and the use of `event.stop_event()` were observable Dududa 1.0
compatibility behavior even though they were not expressed as internal interfaces.

## Dududa 1.0 Startup And Upgrade At The Audit Baseline

At the audit baseline, `./manage.sh up` performed:

```text
init
  -> create .env and private data directories
  -> merge the iCourse MCP template
plugins
  -> install six locked third-party plugins
ensure external edge network
docker compose up -d --build
seed Persona into AstrBot SQLite and select it in cmd_config.json
restart AstrBot
```

At the audit baseline, `./manage.sh upgrade` performed `plugins -> sync -> network -> pull -> up --build
-> seed`. It has no backup, health check, explicit rollback, or post-seed
restart. A changed lock marker also causes `install_plugins.py` to refuse an
existing plugin unless `--force` is supplied, but `manage.sh upgrade` exposes no
force path. Therefore the audited upgrade command could not reliably apply a
third-party plugin version change.

## Dududa 1.0 First-Party Plugin Inventory At The Audit Baseline

### Dududa Core

`plugins/astrbot_plugin_dududa_core/main.py` is 1,540 lines and combines the
AstrBot adapter, application services, persistence, Provider access, MCP access,
formatting, and security checks.

| Lines | Current responsibility | Target concern |
| --- | --- | --- |
| 1-70 | Imports, plugin registration, object construction, local errors | Composition root and adapter lifecycle |
| 72-139 | Event identity, blocking checks, JSON state, confirmation creation | Identity adapter, policies, repositories, confirmation service |
| 141-335 | Natural course interception, intent parsing, query cleanup | Event routing, perception, structured output |
| 337-480 | iCourse search/detail orchestration and LLM summaries | Capability provider, Model Router, response composition |
| 482-741 | Course ranking, parsing, cards, excerpts | iCourse presentation and domain helpers |
| 743-875 | Basic, privacy, lightweight memory, and style commands | Command adapters and preference/memory use cases |
| 876-970 | Explicit course commands | Command adapter calling a capability service |
| 972-1231 | Admin inspection and high-risk requests | Admin commands and application use cases |
| 1233-1341 | Confirmation execution, permission and model writes | Confirmation, permission, and config repositories |
| 1343-1430 | Third-party compatibility entries, image and entertainment | Compatibility commands and built-in capabilities |
| 1432-1540 | Provider credential lookup, image HTTP call, safety terms | Image Provider adapter and security policy |

Registered command families include:

- Basic: `/help`, `/dududa help`, `/about`, `/ping`, `/status`, `/privacy`.
- Local state: `/remember`, `/forget`, `/memory`, `/style`.
- Course: `/course stats|search|review|compare|refresh` plus a natural-language
  `/course` route and the explicit phrase `评课社区搜索`.
- Administration: `/admin status|plugins|mcp|group|user|memory|logs|backup|restart|model|permission|broadcast`.
- Confirmation: `/confirm`, `/cancel`.
- Compatibility and entertainment: `/remind`, `/reminders`, `/summary`, `/meme`,
  `/image`, `/fortune`, `/draw`, `/poke`, `/reread`.

Several Dududa 1.0 compatibility commands only told the user which third-party
plugin to use; they did not invoke that capability. In the Dududa 2.0 default
path, `/meme`, `/poke` and `/reread` only return legacy stop notices and are not
advertised by `/help`; `/image` remains an explicit image-generation capability.

### Reply Polish

At the audit baseline, `astrbot_plugin_reply_polish` did not perform semantic or
Persona rewriting. Its global hook split long QQ group plain-text results into
merged-forward nodes, could affect unrelated plugins, and could truncate content
at the node limit. Dududa 2.0 keeps its source only as a default-off, LONG-only
compatibility layer; the formal Runtime does not depend on it.

### Target Talk

At the audit baseline, `astrbot_plugin_target_talk` was the only approximation of
Social Decision. It recorded recent group messages and applied target matching,
allow/deny lists, keywords, probability, and cooldowns before asking an AstrBot
Provider for a short reply. It had no explicit action enum, confidence,
permission policy, tool path, or structured trace.

Its source and configuration remain as migration material, but old Target Talk
has exited the Dududa 2.0 default Compose and inbound paths. This repository
disposition does not claim that a running private AstrBot/NapCat instance has
already unloaded it.

## State And Privacy Inventory

| State | Scope today | Persistence | Finding |
| --- | --- | --- | --- |
| Core `user_state.json` | QQ user ID only | JSON file | No platform, Bot, conversation, group, or Persona scope |
| Core `group_state.json` | Group ID or literal `private` | JSON file | `mode`, reply rate, and meme rate are stored but not applied |
| Core audit log | Sender and group plus scrubbed detail | JSONL | No rotation; redaction is key-name based |
| Pending confirmations | Requester QQ ID | Process memory | No conversation scope; permission is not rechecked on execution |
| Course refresh cooldown | Course ID | Process memory | Lost on restart |
| TargetTalk history | Group ID | Process memory | No platform, Bot, Persona, TTL, or group-count bound |
| TargetTalk cooldowns | Target/group keys | Process memory | Lost on restart |
| Iris memory | Iris-specific stores | Runtime data | Core has no `MemoryRepository` abstraction or Iris adapter |
| AstrBot Persona/config | AstrBot SQLite and JSON | Runtime data | Seed overwrites the same Persona and selects it as default |
| iCourse data | One SQLite path | Runtime data | Cache is private, but export currently accepts an arbitrary path |
| NapCat login/config | NapCat directories | Runtime data | NapCat also receives the complete AstrBot data mount |

The lightweight `/remember` data is not retrieved into model context. The
current code therefore has two disconnected notions of memory: local command
CRUD and the independent Iris plugin. Neither is a scoped Agent Core interface.

The Iris patch improves isolation but is fail-open at two edges: L2 entries
without `user_id` remain eligible, and L3 falls back to global search when no
group ID or detailed API is available. Existing tests assert patch strings,
not cross-user or cross-group behavior.

## Model And Tool Paths

Model access is fragmented:

1. Course intent and summaries use AstrBot's current Provider.
2. TargetTalk optionally selects another AstrBot Provider.
3. Image generation bypasses the Provider abstraction, reads an OpenAI source
   from `cmd_config.json`, and calls the HTTP endpoint directly.

MCP access is also duplicated:

1. `config/astrbot/mcp_server.json` registers iCourse with AstrBot.
2. Core `ICourseClient` starts a fresh stdio server for each call.

There is no shared model-role configuration, MCP registry, schema cache,
timeout policy, retry policy, circuit breaker, call budget, or result validator.

## Data And Container Boundaries

- Management ports default to host loopback, but both services join the
  external `mmdustc-edge` network. Other containers on that network can still
  reach the aliases.
- NapCat mounts the complete `${STACK_DATA_ROOT}/astrbot` directory at
  `/AstrBot/data`, giving it access to AstrBot databases, Provider configuration,
  memory, and audit files.
- First-party code, iCourse source, safe config, and scripts are mounted
  read-only. Runtime state remains under the ignored data root.
- Containers use `no-new-privileges`, but no health checks, capability drops,
  read-only root filesystems, resource limits, or explicit non-root users are
  declared.

## Existing Test Reality

The eight tests cover repository shape, plugin lock membership, three Iris
patch strings, one MCP template, read-only mounts, Persona seed idempotence,
iCourse table creation, and MCP merge preservation. They do not cover command
behavior, event ordering, permission decisions, redaction, plugin import,
plugin installation, MCP handshake, memory isolation behavior, Docker health,
upgrade/rollback, TargetTalk decisions, or ReplyPolish formatting.

## Documentation Map

No existing document is deleted during Phases 0-1.

| Existing document | Useful content | Long-term destination | Removal condition |
| --- | --- | --- | --- |
| `README.md` | Quick start and repository contract | Keep as concise entry point | Never remove; update after canonical paths move |
| `docs/architecture.md` | Bot ownership and persistent-data boundary | `docs/design/repository-layout.md`, security design | Merge only after all links are updated |
| `docs/DUDUDA.md` | Product behavior, Persona, command inventory | Design documents by concern | Remove duplication only after fact-by-fact review |
| `docs/ROADMAP.md` | Historical implementation checklist | `docs/refactor/implementation-plan.md` and roadmap archive | Archive after all open items are mapped |
| Plugin READMEs | AstrBot-facing configuration and behavior | Keep beside each compatibility adapter | Update when plugin behavior changes |
| `services/icourse-mcp/README.md` | Standalone MCP operation and tool list | Keep with service, then move with `git mv` | Never discard service-specific operation notes |
| `CONTRIBUTING.md` | Review and lock-change rules | Keep at root | Extend when test layers exist |
| `SECURITY.md` | Secret and runtime-data exclusions | Keep at root; link detailed security design | Never remove |

## Risk Register

### P0: must be addressed before production entry uses Agent Runtime v2

1. Memory identity and conversation scopes are not explicit or fail-closed.
2. NapCat can access the complete AstrBot private data directory.
3. `upgrade` cannot reliably replace a changed plugin lock and has no health or
   rollback gate.
4. Image generation reads Provider credentials directly in plugin business
   code.
5. iCourse `export_dataset` can write to an arbitrary process-visible path.
6. Confirmation execution is scoped only by requester ID, not conversation,
   action authorization at execution time, or durable state.

### P1: architecture and reliability

1. AstrBot types are imported by permission and audit policy code.
2. MCP and model access each have multiple uncoordinated paths.
3. JSON reads swallow broad exceptions and can turn corruption into empty
   state; writes have no inter-process or async coordination.
4. Course queries may launch many sequential MCP processes and refresh calls.
5. TargetTalk records text before completing allowlist and target checks.
6. Runtime has no explicit state machine, trace, call-step budget, retry policy,
   result validator, or rate-limit service.
7. Python dependency ranges make the image less reproducible than the pinned
   base image suggests.

### P2: maintainability and documentation

1. The core plugin is a 1,540-line change hotspot.
2. Help text, capability metadata, and implementation are separate sources of
   truth.
3. Repository paths are hard-coded across Compose, Docker, CI, Dependabot,
   scripts, and documentation.
4. Existing design and roadmap documents overlap and contain drift.

## Migration Invariants

Until an explicit compatibility gate says otherwise:

- Keep the three AstrBot plugin IDs and runtime target directories unchanged.
- Keep `./manage.sh` and the root Compose entry usable.
- Preserve current command names, event priority, and visible stop/send
  behavior, or document and test an intentional change.
- Never migrate `.env`, Provider credentials, QQ identifiers, memory databases,
  login state, attachments, or audit data into Git.
- Do not let Agent Core import AstrBot, OneBot, NapCat, Docker, a concrete MCP
  server, or a Provider SDK.
