# library-mcp

`library-mcp` 是一个面向 AstrBot 的 MCP Server，抓取并缓存中国科学技术大学图书馆公开发布的**日常开放时间**（东区、西区、高新区）。

数据源为公开页面，无需登录、不使用 Cookie、不绕过任何权限：

- 开放时间页：`https://lib.ustc.edu.cn/?p=5916`

只缓存公开可见信息。请求间隔默认 1 秒，建议低并发使用。馆藏检索（OPAC）为交互式系统，不在本服务范围内。

## 运行环境

在 Dududa 生产栈中，Compose 将 `services/library-mcp/` 挂载到 AstrBot 容器内：

```text
/AstrBot/data/library-mcp
```

MCP 运行时使用 AstrBot 统一容器环境：

```text
command: /usr/local/bin/python
server:  /AstrBot/data/library-mcp/run_library_mcp.py
package: installed in the derived AstrBot image
```

## AstrBot 接入

`mcp_server.json` 配置（生产栈模板）：

```json
{
  "mcpServers": {
    "library": {
      "command": "/usr/local/bin/python",
      "args": [
        "/AstrBot/data/library-mcp/run_library_mcp.py",
        "--db-path",
        "/AstrBot/data/library-cache/library.sqlite3",
        "--request-delay",
        "1.0"
      ],
      "disabled": false
    }
  }
}
```

生产栈自检：

```bash
docker compose --env-file .env -f compose.yml exec -T astrbot \
  python /AstrBot/data/library-mcp/scripts/check_mcp.py
```

本地开发自检（在 `services/library-mcp/` 下创建 `.venv` 并安装依赖后）：

```bash
.venv/bin/python scripts/check_mcp.py
```

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `library_stats` | 查看本地缓存规模（条目数、各校区计数）。 |
| `get_opening_hours(campus)` | 读取缓存的开放时间；可按校区过滤（东区/西区/高新区）。 |
| `search_hours(query, limit)` | 按业务/地点关键词搜索（如 `自习室`、`服务台`）。 |
| `refresh_hours` | 重新抓取开放时间页并重建缓存。 |
| `check_robots` | 抓取并缓存 `robots.txt` 供审计。 |

所有工具只读公开数据并标注 `public_only: true`。`refresh_*` 请求间隔至少 1 秒，避免高频访问。

## 预热缓存

```bash
cd /AstrBot/data/library-mcp   # 生产容器内
PYTHONPATH=/AstrBot/data/library-mcp/src python -m library_mcp.cli robots
PYTHONPATH=/AstrBot/data/library-mcp/src python -m library_mcp.cli refresh
PYTHONPATH=/AstrBot/data/library-mcp/src python -m library_mcp.cli stats
```

## 数据文件

容器中的 SQLite 数据库在 `/AstrBot/data/library-cache/library.sqlite3`；本地开发默认使用 `data/library.sqlite3`。

## 解析说明

- 开放时间页含一张大表格，按东区/西区/高新区三个校区分组，`rowspan` 标记校区/共享时间范围。
- 每行含：校区、楼层位置、业务内容、周一至周五时间、周末时间、联系电话。`colspan=4` 的时间单元格表示周中与周末一致；`——` 表示该时段闭馆。
- 已知局限：若页面改版导致表格结构变化，解析会失败并返回显式错误，不会静默产出错误数据；开放时间以图书馆官网为准。

## 注意

- 只面向公开页面和个人/内部查询使用。
- 不建议高并发；默认请求间隔 1 秒。
- 如果 `robots.txt` 或站点规则变化，请停止抓取并重新评估。
