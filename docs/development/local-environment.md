# 本地开发环境

## 1. 支持范围

本文给出 Ubuntu 24.04 上可重复的 Dududa 主仓开发环境。项目依赖必须从仓库锁文件安装，
不要把系统 Python、其他项目的 `node_modules` 或正在运行的 AstrBot 容器当作开发依赖来源。

锁定基线：

| 工具 | 主开发版本 | 兼容性门禁 |
| --- | --- | --- |
| uv | 0.12.1 | `uv.lock` 必须通过 `uv lock --check` |
| Python | 3.12.13 | 3.10.20 也必须跑完整 Python 测试 |
| SQLite | 3.53.1（uv Python 自带） | 并发 WAL 路径不得使用 3.51.2 及以下版本 |
| Node.js | 22.18.0 | 由根目录 `.node-version` 固定 |
| npm | 10.9.3 | `package-lock.json` 是唯一 Web 依赖输入 |
| Playwright | 1.62.1 | 安装其锁定的 Chromium，不依赖系统 Chrome |
| TreeWork | 0.1.7 | 保持当前 Alignment，不执行 `tw align end` |

根目录 `pyproject.toml` 定义 uv workspace 和完整 dev/test 依赖，`uv.lock` 锁定解析结果。
`httpx`、`jsonschema`、Pillow、MCP SDK 与两个本地 Python package 都由这一个入口安装。
裸系统 Python 缺少这些模块是正常的；项目命令必须通过 `.venv` 或 `uv run --locked` 执行。

## 2. 安装 uv 与 Python

若 `uv --version` 不是 `0.12.1`，从官方 Release 下载固定版本并校验 SHA-256。不要把
远程安装脚本直接通过管道交给 Shell。安装后确保 `$HOME/.local/bin` 位于 `PATH`：

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
uv python install 3.12.13 3.10.20
```

uv 管理的两个解释器都携带 SQLite 3.53.1。不要用 Ubuntu 自带的 Python 3.12.3 执行
Rollout Ledger 或未来 Scheduler 的并发 WAL 测试；该解释器携带 SQLite 3.45.1。

## 3. 创建锁定的 Python 环境

在仓库根目录运行：

```bash
./ops/cli/setup_dev.sh
source .venv/bin/activate
```

脚本会：

1. 安装或复用 Python 3.12.13；
2. 以 `uv sync --locked` 创建 `.venv`；
3. editable 安装 `dududa-agent` 与 `icourse-mcp`；
4. 验证 Dududa、MCP、HTTP、JSON Schema、HTML 解析和图片依赖都可导入。

它不会读取 `.env`、访问真实 QQ 数据、启动 Docker 服务或发送消息。

Unified MCP v2 worker 有独立 lock，且故意不进入根 workspace。首次运行 MCP Contract 前
还需创建它自己的环境：

```bash
uv lock --project services/mcp/unified-worker --check
uv sync --project services/mcp/unified-worker --locked --python 3.12.13
services/mcp/unified-worker/.venv/bin/python \
  -m unittest discover -s services/mcp/unified-worker/tests -v
```

日常验证：

```bash
uv lock --check
uv sync --locked --check
uv run --locked python -c \
  'import sqlite3, sys; print(sys.version); print(sqlite3.sqlite_version)'
PYTHONDONTWRITEBYTECODE=1 \
  uv run --locked python -m unittest discover -s tests

uv run --locked python -m dududa.evaluation.suite check \
  evals/suite-v1.json --profile committed-bundles \
  --receipt .TreeWork/out/eval-bundles.json
```

## 4. Python 3.10/3.12 干净环境门禁

发布前不要在同一个 `.venv` 中来回覆盖解释器。使用两个临时环境从同一锁文件安装：

```bash
UV_PROJECT_ENVIRONMENT=/tmp/dududa-py310 \
  uv sync --locked --python 3.10.20
UV_PROJECT_ENVIRONMENT=/tmp/dududa-py312 \
  uv sync --locked --python 3.12.13

PYTHONDONTWRITEBYTECODE=1 \
  /tmp/dududa-py310/bin/python -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 \
  /tmp/dududa-py312/bin/python -m unittest discover -s tests
```

两个命令都必须发现相同数量的测试并全部通过。最近一次完整双 Python 基线是在 S15C 的
`616 tests, 2 skipped`；S15D-S18 使用聚焦样本，S19 会通过 `ci-python` receipt 刷新完整
基线。数量不应硬编码进 CI。S19 的 policy、inventory、gate 和候选 receipt 命令见
[候选发布审计](../operations/release-candidate-audit.md)。

## 5. Node.js 与 Web

当前 Web 依赖中的 Vue Router/Babel 要求 Node 22.18.0 或更高兼容版本。Node 20 即使
部分命令能运行，也会产生 `EBADENGINE`，不属于支持环境。安装 Node 22.18.0 后确认：

```bash
node --version
npm --version
```

预期分别是 `v22.18.0` 和 `10.9.3`。然后执行：

```bash
cd apps/web
npm ci
npm audit --omit=dev --audit-level=high
npx playwright install chromium
npm test
npm run typecheck
npm run build
npm run test:e2e
```

Playwright 使用自身缓存中的 Chromium。E2E 临时监听 `127.0.0.1:4174` 和内部 API
端口 `8180`，结束后必须释放；它不会连接或替换运行在 `127.0.0.1:5173` 的 Web 容器。

2026-08-09 的基线为前端 66 项、服务端 42 项、Playwright 6 项全部通过，typecheck、
build 和生产依赖 audit 也通过。Vite 的大 chunk 提示和 `glob@10` 弃用提示是后续维护项，
不是当前环境失败。

## 6. TreeWork 0.1.7

TreeWork 可执行文件应固定到当前插件版本：

```bash
ln -sfn \
  "$HOME/.codex/plugins/cache/treework/treework/0.1.7/target/treework/tw" \
  "$HOME/.local/bin/tw"
tw version
tw graph render
```

预期输出 `tw 0.1.7`。不要继续运行 0.1.6 的 Project Map，也不要手工编辑
`.TreeWork/state/`、`events.jsonl` 或生成块。当前处于 `Stage: work_tree`；按现有 Tree 和
WIP=1 完成一个分支的 verify/complete/merge 后才能进入下一分支。

## 7. MCP 离线握手

旧 iCourse 握手只使用临时 SQLite 文件，不抓取真实网页：

```bash
MCP_TEST_DB="$(mktemp --suffix=.sqlite3)"
ICOURSE_MCP_DB_PATH="$MCP_TEST_DB" \
  uv run --locked python services/mcp/icourse/scripts/check_mcp.py
rm -f "$MCP_TEST_DB"
```

预期完成 initialize、工具发现和 `icourse_stats`。统一 Client 的持久 Session、Schema
Snapshot、取消和恢复由 root Contract 与隔离 worker Contract 证明；这个旧握手仅证明
iCourse compatibility path，不能替代统一 Client 验证。

## 8. Compose 只读检查

当前机器同时运行旧 AstrBot/NapCat Compose 与 Dududa Web Compose。只允许解析和只读检查：

```bash
mkdir -p .TreeWork/out
docker compose --project-directory . --env-file .env.example \
  -f deploy/compose/compose.yml config --format json \
  > .TreeWork/out/compose.json
.venv/bin/python ops/cli/dududa_ops.py compose-contract \
  --input .TreeWork/out/compose.json
docker compose ls
docker compose ps
```

不要在主仓直接执行完整 `docker compose up`。主仓的 AstrBot/NapCat 服务会在共享
`mmdustc-edge` 网络声明与旧栈相同的兼容别名，并复用 6185/6099 端口；并行启动会造成
名称解析或端口所有权冲突。正式切换必须等 production-shape 门禁闭合并单独授权。

## 9. 完整本地门禁

```bash
uv lock --check
uv sync --locked --check
PYTHONDONTWRITEBYTECODE=1 \
  uv run --locked python -m compileall -q packages apps services ops tests
PYTHONDONTWRITEBYTECODE=1 \
  uv run --locked python -m dududa.evaluation.suite check \
  evals/suite-v1.json --profile ci-python \
  --receipt .TreeWork/out/eval-python.json
services/mcp/unified-worker/.venv/bin/python \
  -m unittest discover -s services/mcp/unified-worker/tests -v
uv run --locked python ops/cli/check_secrets.py
bash -n manage.sh ops/manage.sh ops/cli/setup_dev.sh
sh -n services/mcp/icourse/scripts/setup.sh \
  services/mcp/icourse/scripts/start_mcp.sh
mkdir -p .TreeWork/out
docker compose --project-directory . --env-file .env.example \
  -f deploy/compose/compose.yml config --format json \
  > .TreeWork/out/compose.json
.venv/bin/python ops/cli/dududa_ops.py compose-contract \
  --input .TreeWork/out/compose.json
git diff --check
```

Web 门禁使用第 5 节命令。任何依赖变更必须同时更新声明和对应 lockfile，并在两个 Python
版本以及锁定 Node 版本上重新验证。

## 10. 常见问题

### `No module named httpx` 或 `No module named jsonschema`

命令使用了裸系统 Python。重新运行 `./ops/cli/setup_dev.sh`，随后使用 `uv run --locked`
或激活 `.venv`，不要向系统 Python 执行 `sudo pip install`。

### `npm ci` 出现 `EBADENGINE`

当前 Node 版本低于 22.18.0。按 `.node-version` 切换版本后重新执行 `npm ci`，不要用
`--force` 或关闭 engine 检查掩盖不兼容。

### Playwright 找不到浏览器

```bash
cd apps/web
npx playwright install chromium
npx playwright install --list
```

### Docker 端口或网络别名冲突

不要停止现有服务，也不要改写生产 Compose。先阅读
`../research/production-shape-preflight.md`，在下一阶段建立明确的迁移和回滚窗口。
