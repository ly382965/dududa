# 本地开发环境

## 1. 适用范围

本文说明如何在 Ubuntu 24.04 上准备嘟嘟哒仓库的 Python 开发环境，并运行
单元测试、MCP 握手和仓库级检查。所有 Python 包安装在仓库的 `.venv/` 中，
不修改系统 Python，也不需要把 `sudo pip` 用于项目依赖。

当前开发基线：

- Python 3.12；项目最低支持 Python 3.10；
- Docker Engine 与 Docker Compose v2；
- `uv 0.12.1`，安装在当前用户的 `~/.local/bin/`；
- `dududa-agent` 与 `icourse-mcp` 均以 editable 模式安装；后者同时提供测试所需的 `httpx`、
  `beautifulsoup4` 和 MCP SDK；
- MCP SDK 限制为 `>=1.2.0,<2.0.0`，因为当前服务使用 1.x 的
  `mcp.server.fastmcp` 接口。

`.venv/` 已由 `.gitignore` 排除，不能提交虚拟环境、缓存或运行数据。

## 2. 安装 uv

若 `uv --version` 已成功输出版本，可跳过本节。没有管理员权限时，可以把
固定版本的官方二进制安装到用户目录：

```bash
set -euo pipefail
UV_VERSION='0.12.1'
UV_SHA256='90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb'
UV_ARCHIVE="uv-x86_64-unknown-linux-gnu.tar.gz"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

curl -fsSL \
  "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_ARCHIVE}" \
  -o "$TMP_DIR/$UV_ARCHIVE"
printf '%s  %s\n' "$UV_SHA256" "$TMP_DIR/$UV_ARCHIVE" \
  | sha256sum --check --status
tar -xzf "$TMP_DIR/$UV_ARCHIVE" -C "$TMP_DIR"
mkdir -p "$HOME/.local/bin"
install -m 0755 \
  "$TMP_DIR/uv-x86_64-unknown-linux-gnu/uv" \
  "$HOME/.local/bin/uv"
install -m 0755 \
  "$TMP_DIR/uv-x86_64-unknown-linux-gnu/uvx" \
  "$HOME/.local/bin/uvx"
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

预期输出包含 `uv 0.12.1`。若新终端找不到 `uv`，确认 Shell 初始化文件中
包含：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

不要跳过 SHA-256 校验，也不要把安装脚本直接通过管道交给 Shell 执行。

## 3. 创建项目环境

进入仓库根目录后运行：

```bash
./scripts/setup_dev.sh
source .venv/bin/activate
```

脚本执行以下操作：

1. 使用系统 Python 3 创建并 seed `.venv`；
2. editable 安装 `packages/dududa-agent` 与 `services/icourse-mcp`；
3. 安装 iCourse 声明的 HTTP、HTML 解析和 MCP 依赖；
4. 检查依赖是否一致。

它不会启动 Docker 服务、读取 `.env`、访问生产数据库或修改 QQ 登录状态。

验证解释器与关键导入：

```bash
python --version
python -m pip --version
python -c 'import dududa, httpx, mcp, bs4, icourse_mcp; print("imports: ok")'
```

三个命令都应退出 `0`，最后一条输出 `imports: ok`。

## 4. 日常验证

每个新终端先进入仓库并激活环境：

```bash
cd "$HOME/Code/dududa"
source .venv/bin/activate
```

运行当前单元测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

命令必须发现根测试以及 `unit/`、`contracts/` 子目录中的测试并报告 `OK`；测试数量增加时
以全部测试通过为准，不把固定数量写进 CI 判定。

运行完整本地门禁：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m compileall -q packages plugins services scripts tests
python scripts/check_secrets.py
bash -n manage.sh scripts/setup_dev.sh
docker compose --env-file .env.example config --quiet
git diff --check
```

这些检查分别覆盖 Python 语法、仓库敏感文件、Shell 语法、Compose 配置和
Git 空白错误。Compose 检查只解析配置，不启动容器。

## 5. MCP 本地握手

iCourse MCP 握手使用临时 SQLite 文件，不需要生产数据：

```bash
MCP_TEST_DB="$(mktemp --suffix=.sqlite3)"
trap 'rm -f "$MCP_TEST_DB"' EXIT
ICOURSE_MCP_DB_PATH="$MCP_TEST_DB" \
  python services/icourse-mcp/scripts/check_mcp.py
```

预期完成 initialize、工具发现和 `icourse_stats` 调用。该检查默认不抓取
`icourse.club` 页面；临时数据库在 Shell 退出时删除。

## 6. 常见问题

### `No module named pip`

系统没有安装 `python3-pip` 或 `python3-venv`。不要向系统 Python 强制安装；
按本文安装 `uv`，再运行 `./scripts/setup_dev.sh`。

### `No module named icourse_mcp` 或 `No module named httpx`

当前命令没有使用项目虚拟环境，或 editable 安装未完成：

```bash
source .venv/bin/activate
uv pip install --python .venv/bin/python -e packages/dududa-agent -e services/icourse-mcp
```

### `No module named mcp.server.fastmcp`

环境错误安装了 MCP SDK 2.x。仓库已经声明 `<2.0.0` 上界；重新同步环境：

```bash
uv pip install --python .venv/bin/python -e services/icourse-mcp
python -c 'from mcp.server.fastmcp import FastMCP; print("FastMCP: ok")'
```

### Docker 命令权限不足

运行 `docker version`。若只能通过 `sudo docker` 使用 Docker，需要由机器管理员
配置 Docker 用户组；不要在项目脚本中硬编码 `sudo`。

## 7. 依赖变更规则

- iCourse 依赖同时维护在 `pyproject.toml` 和 `requirements.txt`，修改时必须
  同步两处；
- 当前没有 Python lockfile，版本范围变化后必须重新运行单测和 MCP 握手；
- 新增插件依赖时必须明确由哪个 package 或镜像声明，不能依赖其他组件偶然
  安装同名库；
- 不提交 `.venv`、`__pycache__`、SQLite、Token、Cookie、QQ 登录态或真实聊天
  数据。
