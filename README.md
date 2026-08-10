# dududa

嘟嘟哒 QQ Agent 的独立协作仓库。仓库只管理 Bot 组件：AstrBot、NapCat、
自研插件、第三方插件版本锁和 USTC 评课 MCP。LLM 网关、数据库、反向代理
与主站基础设施不在本仓库中。

## Architecture

```text
QQ / QQ Group
      |
    NapCat
      | OneBot v11
      +---------------------- Dududa Web multi-account workspace
      |
    AstrBot ---------------- External OpenAI-compatible provider
      |
      +-- Dududa Core
      +-- Reply Polish
      +-- Target Talk
      +-- Sub2API Readonly ---- Sub2API admin UI read-only JSON endpoints
      +-- locked third-party plugins
      +-- icourse MCP -------- icourse.club public pages
```

Bot 和 NapCat 默认加入外部 Docker 网络 `mmdustc-edge`，并保留原主站使用的
网络别名。没有主站网关时，两个管理页面仍可通过本机回环端口使用。

## Repository Layout

```text
apps/astrbot-plugins/          # 嘟嘟哒自研 AstrBot 插件
apps/web/                      # Mew/NapCat 多账号 Web 工作台
packages/dududa-agent/         # 框架无关的 Dududa 2.0 核心契约包
services/mcp/                  # iCourse 与隔离 Unified MCP worker
configs/                       # 可提交、无凭据的配置模板
deploy/                        # Compose、Dockerfile 与环境模板
ops/                           # 管理入口、CLI 和运维工具
third_party/                   # v1 lock、patch 与必要 vendor 源码
docs/                          # 项目设计、开发与运维文档
manage.sh / compose.yml        # 一 Release 根兼容入口
third_party/plugins.lock.json  # 第三方插件唯一 v1 安装权威
```

旧 `plugins/`、`config/`、`docker/`、`scripts/`、`vendor/`、`patches/` 和根
`plugins.lock.json` 在一个 Release 内仅作为 symlink 兼容入口；新代码和文档不得把它们当作
第二权威。Manifest v2 尚未启用。

## Dududa 2.0 Refactor

Phase 0–1 的审计与目标设计见
[Dududa 2.0 设计总览](docs/design/dududa-2.0-overview.md)。S01–S16 的既定本地/离线范围已沿
既有 Tree 完成并验证，覆盖核心契约、安全边界、静态路由、离线 Runtime、统一 MCP、
Capability Runtime、Memory 生命周期/检索、三档回答、默认关闭的主动出站链和离线运维事务。
S17 路径迁移的三批实现已完成，正在执行最终 Verification；旧 AstrBot
Handler 仍是生产权威入口，Memory v2 尚未接入 Context Builder 或生产命令。当前实现证据、
残余边界和下一步以 [重构进度](docs/refactor/PROGRESS.md) 和
[阶段报告](docs/refactor/checkpoint-report-2026-08-10.md) 为准；真实质量和生产阶段需要的资料
见 [外部输入准备清单](docs/refactor/external-input-checklist.md)。

## Requirements

- Linux host with Docker Engine and Docker Compose v2
- uv 0.12.1 with the locked Python 3.10.20/3.12.13 development matrix
- Node.js 22.18.0 and npm 10.9.3 for Web development
- Git, for installing locked upstream plugins
- An external OpenAI-compatible model provider

Provider URL and API key must be configured in the AstrBot WebUI after startup.
They belong in private runtime data, never in this repository.

The example environment pins the production-tested image digests through a
DaoCloud mirror. Teams may replace only the registry prefix in private `.env`
files while retaining the digest.

## Quick Start

The full-stack command below is for a clean host that does not already run an
AstrBot/NapCat stack. On the current development machine, use only the Web or
local test commands: the legacy stack already owns ports 6185/6099 and the
compatibility aliases on `mmdustc-edge`. See the
[production-shape preflight](docs/research/production-shape-preflight.md).

```bash
cp .env.example .env
chmod 600 .env
./manage.sh up
```

`up` performs the complete clean-clone bootstrap:

1. Creates private runtime directories under `data/`.
2. Mounts the four owned plugins read-only from the repository.
3. Installs third-party plugins at the commits in `third_party/plugins.lock.json`.
4. Builds AstrBot with the `icourse-mcp` Python dependencies.
5. Starts AstrBot and NapCat.
6. Seeds the `dududa` persona and the `icourse` MCP definition.

Local management URLs:

- AstrBot: `http://127.0.0.1:6185`
- NapCat: `http://127.0.0.1:6099`
- Dududa Web: `http://127.0.0.1:5173`

NapCat requires an interactive QQ login. Its login state remains under
`data/napcat/` and is ignored by Git.

Meme Manager is installed without its large upstream sample gallery. Add or
sync meme images through the plugin after startup; those files stay in private
runtime data.

## Operations

```bash
./manage.sh config
./manage.sh ps
./manage.sh logs astrbot
./manage.sh logs napcat
./manage.sh web-up
./manage.sh web-connect
./manage.sh restart
./manage.sh upgrade
./manage.sh down
```

`upgrade` never deletes runtime data. Review changes to `third_party/plugins.lock.json` and
the Iris privacy patch before forcing any plugin replacement.

## Existing Deployment

Production data is intentionally not copied into Git. To reuse an existing data
directory, back it up first and set an absolute `STACK_DATA_ROOT` in `.env`.
Run `./manage.sh sync` to merge the `icourse` MCP entry. Owned plugins are
read-only bind mounts, so source updates take effect after an AstrBot restart;
the command does not copy provider credentials, databases or QQ login state.

## External Contracts

- LLM: any OpenAI-compatible provider configured privately in AstrBot.
- Gateway: optional external `mmdustc-edge` network. Stable aliases are
  `bot-astrbot-qq-astrbot:6185` and `bot-astrbot-qq-napcat:6099`.
- Course data: public pages from `https://icourse.club/`, with a local SQLite
  cache excluded from Git.
- Sub2API statistics: optional access to the same read-only JSON endpoints used
  by the Sub2API admin UI. Credentials live only in private runtime config; QQ
  commands are denied unless their group or private user is explicitly allowed.

Sub2API, PostgreSQL, Redis, xray, Caddy and Authelia are explicitly outside this
repository. See [architecture.md](docs/architecture.md) for the ownership
boundary.

## Development

For the reproducible Ubuntu setup and troubleshooting steps, see
[本地开发环境](docs/development/local-environment.md).

```bash
./ops/cli/setup_dev.sh
uv lock --check
uv run --locked python -m compileall -q packages apps services ops tests
uv run --locked python -m unittest discover -s tests
uv run --locked python ops/cli/check_secrets.py
docker compose --env-file .env.example config --quiet
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and review workflow.

## Security And Privacy

No runtime database, conversation, memory, QQ identifier list, provider key,
Cookie, token or private key belongs in Git. The Iris plugin is pinned and
patched to preserve per-user L2 memory and per-group L3 graph isolation.

Report security issues according to [SECURITY.md](SECURITY.md). Third-party
components retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
