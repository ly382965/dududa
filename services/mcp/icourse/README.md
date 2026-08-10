# icourse-mcp

`icourse-mcp` 是一个面向 AstrBot 的 MCP Server，用匿名公开页面从 `https://icourse.club/` 抓取并缓存结构化课程数据。

它只抓公开可见内容，不登录、不使用 Cookie、不绕过登录或学生身份限制。详情页中不可见的评课不会被抓取；如果站点显示的点评数和公开解析到的点评数不同，会记录 `missing_review_count_estimate`。

## 运行环境

在 Dududa 生产栈中，本项目不单独维护 Linux `.venv`。Compose 已将
`services/mcp/icourse/` 挂载到 AstrBot 容器内：

```text
/AstrBot/data/icourse-mcp
```

MCP 运行时使用 AstrBot 统一容器环境：

```text
command: /usr/local/bin/python
server: /AstrBot/data/icourse-mcp/run_icourse_mcp.py
package: installed in the derived AstrBot image
```

本地开发或 Windows 调试时，仍可以使用项目内 `.venv`，方便隔离依赖。

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Linux 本地开发:

```bash
chmod +x scripts/setup.sh scripts/start_mcp.sh
./scripts/setup.sh
```

如果 AstrBot 用本目录的 Docker 栈部署，不需要在容器内执行 `./scripts/setup.sh`。

## AstrBot 接入

在 AstrBot WebUI 的 MCP 配置中添加一个服务器。Windows 示例：

```json
{
  "command": "D:\\path\\to\\dududa\\services\\icourse-mcp\\.venv\\Scripts\\python.exe",
  "args": [
    "-m",
    "icourse_mcp.server",
    "--db-path",
    "D:\\path\\to\\dududa\\services\\icourse-mcp\\data\\icourse.sqlite3",
    "--request-delay",
    "1.0"
  ]
}
```

Linux 示例：

```json
{
  "command": "/usr/local/bin/python",
  "args": [
    "/AstrBot/data/icourse-mcp/run_icourse_mcp.py",
    "--db-path",
    "/AstrBot/data/icourse-cache/icourse.sqlite3",
    "--request-delay",
    "1.0"
  ]
}
```

也可以直接参考：

- `astrbot-mcp.example.windows.json`
- `astrbot-mcp.example.linux.json`

生产栈自检：

```bash
docker compose --env-file .env -f compose.yml exec -T astrbot \
  python /AstrBot/data/icourse-mcp/scripts/check_mcp.py
```

本地开发自检：

```bash
.venv/bin/python scripts/check_mcp.py
```

Windows:

```powershell
.venv\Scripts\python.exe scripts\check_mcp.py
```

## 预热缓存

MCP 工具默认比较克制，不会自动全站抓取。建议先手动预热少量数据：

生产栈中先进入容器内项目目录：

```bash
docker compose --env-file .env -f compose.yml exec -T astrbot sh
cd /AstrBot/data/icourse-mcp
PYTHONPATH=/AstrBot/data/icourse-mcp/src python -m icourse_mcp.cli robots
PYTHONPATH=/AstrBot/data/icourse-mcp/src python -m icourse_mcp.cli crawl-courses --start-page 1 --end-page 1 --per-page 50 --detail
PYTHONPATH=/AstrBot/data/icourse-mcp/src python -m icourse_mcp.cli stats
```

本地开发环境：

```bash
.venv/bin/python -m icourse_mcp.cli robots
.venv/bin/python -m icourse_mcp.cli crawl-courses --start-page 1 --end-page 1 --per-page 50 --detail
.venv/bin/python -m icourse_mcp.cli stats
```

Windows 对应：

```powershell
.venv\Scripts\python.exe -m icourse_mcp.cli robots
.venv\Scripts\python.exe -m icourse_mcp.cli crawl-courses --start-page 1 --end-page 1 --per-page 50 --detail
.venv\Scripts\python.exe -m icourse_mcp.cli stats
```

全量抓取请分批执行，建议 `--request-delay 1.0` 或更慢：

```bash
.venv/bin/python -m icourse_mcp.cli crawl-courses --start-page 1 --end-page 50 --per-page 50 --detail
```

## MCP 工具

- `icourse_stats`：查看本地缓存规模。
- `search_courses`：搜索本地课程缓存。
- `get_course`：获取课程详情；可传 `refresh=true` 先刷新公开页面。
- `get_reviews`：获取某门课缓存的公开点评。
- `crawl_course`：抓取单门课详情。
- `crawl_courses`：抓取课程列表页，默认只抓列表摘要；传 `detail=true` 抓详情。
- `crawl_latest_reviews`：根据全站最新公开点评刷新相关课程。
- `check_robots`：抓取并缓存 `robots.txt`。
- `export_dataset`：导出 JSONL。

## 数据文件

容器中的 SQLite 数据库在 `/AstrBot/data/icourse-cache/icourse.sqlite3`；
本地开发默认使用 `data/icourse.sqlite3`。导出 JSONL：

生产栈：

```bash
cd /AstrBot/data/icourse-mcp
PYTHONPATH=/AstrBot/data/icourse-mcp/src python -m icourse_mcp.cli export --output /AstrBot/data/icourse-cache/icourse_courses.jsonl
```

本地开发：

```bash
.venv/bin/python -m icourse_mcp.cli export --output data/icourse_courses.jsonl
```

## 注意

- 本项目只面向公开页面和个人/内部查询使用。
- 不建议高并发；默认请求间隔为 1 秒。
- 如果 `robots.txt` 或站点规则变化，请停止抓取并重新评估。
