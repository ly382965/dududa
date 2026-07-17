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
    AstrBot ---------------- External OpenAI-compatible provider
      |
      +-- Dududa Core
      +-- Reply Polish
      +-- Target Talk
      +-- locked third-party plugins
      +-- icourse MCP -------- icourse.club public pages
```

Bot 和 NapCat 默认加入外部 Docker 网络 `mmdustc-edge`，并保留原主站使用的
网络别名。没有主站网关时，两个管理页面仍可通过本机回环端口使用。

## Repository Layout

```text
plugins/                 # 嘟嘟哒自研 AstrBot 插件
services/icourse-mcp/    # 评课社区 MCP 服务
vendor/                  # 无法从公开上游复现的第三方源码
patches/                 # 上游隐私修补
config/                  # 可提交的人格和 MCP 初始化模板
scripts/                 # 安装、同步、初始化和安全检查
docs/                    # 项目设计与路线图
compose.yml              # AstrBot + NapCat
plugins.lock.json        # 第三方插件精确版本
```

## Requirements

- Linux host with Docker Engine and Docker Compose v2
- Python 3.10 or newer
- Git, for installing locked upstream plugins
- An external OpenAI-compatible model provider

Provider URL and API key must be configured in the AstrBot WebUI after startup.
They belong in private runtime data, never in this repository.

The example environment pins the production-tested image digests through a
DaoCloud mirror. Teams may replace only the registry prefix in private `.env`
files while retaining the digest.

## Quick Start

```bash
cp .env.example .env
chmod 600 .env
./manage.sh up
```

`up` performs the complete clean-clone bootstrap:

1. Creates private runtime directories under `data/`.
2. Mounts the three owned plugins read-only from the repository.
3. Installs third-party plugins at the commits in `plugins.lock.json`.
4. Builds AstrBot with the `icourse-mcp` Python dependencies.
5. Starts AstrBot and NapCat.
6. Seeds the `dududa` persona and the `icourse` MCP definition.

Local management URLs:

- AstrBot: `http://127.0.0.1:6185`
- NapCat: `http://127.0.0.1:6099`

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
./manage.sh restart
./manage.sh upgrade
./manage.sh down
```

`upgrade` never deletes runtime data. Review changes to `plugins.lock.json` and
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

Sub2API, PostgreSQL, Redis, xray, Caddy and Authelia are explicitly outside this
repository. See [architecture.md](docs/architecture.md) for the ownership
boundary.

## Development

```bash
python -m pip install -e services/icourse-mcp
python -m compileall -q plugins services scripts
python -m unittest discover -s tests -v
python scripts/check_secrets.py
docker compose --env-file .env.example config --quiet
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and review workflow.

## Security And Privacy

No runtime database, conversation, memory, QQ identifier list, provider key,
Cookie, token or private key belongs in Git. The Iris plugin is pinned and
patched to preserve per-user L2 memory and per-group L3 graph isolation.

Report security issues according to [SECURITY.md](SECURITY.md). Third-party
components retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
