# academic-calendar-mcp

`academic-calendar-mcp` 是一个面向 AstrBot 的 MCP Server，读取并缓存中国科学技术大学教务处公开发布的**教学日历（校历）**。

数据源为公开页面，无需登录、不使用 Cookie、不绕过任何权限：

- 列表页：`https://www.teach.ustc.edu.cn/calendar`
- 详情页：`https://www.teach.ustc.edu.cn/calendar/<id>.html`

只缓存公开可见信息。所有访问遵守 `robots.txt`（当前允许普通爬虫访问该栏目），请求间隔默认 1 秒，建议低并发使用。

## 运行环境

在 Dududa 生产栈中，Compose 将 `services/academic-calendar-mcp/` 挂载到 AstrBot 容器内：

```text
/AstrBot/data/academic-calendar-mcp
```

MCP 运行时使用 AstrBot 统一容器环境：

```text
command: /usr/local/bin/python
server:  /AstrBot/data/academic-calendar-mcp/run_academic_calendar_mcp.py
package: installed in the derived AstrBot image
```

## AstrBot 接入

AstrBot 的 `mcp_server.json` 配置（生产栈模板）：

```json
{
  "mcpServers": {
    "academic_calendar": {
      "command": "/usr/local/bin/python",
      "args": [
        "/AstrBot/data/academic-calendar-mcp/run_academic_calendar_mcp.py",
        "--db-path",
        "/AstrBot/data/academic-calendar-cache/calendar.sqlite3",
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
  python /AstrBot/data/academic-calendar-mcp/scripts/check_mcp.py
```

本地开发自检（在 `services/academic-calendar-mcp/` 下创建 `.venv` 并安装依赖后）：

```bash
.venv/bin/python scripts/check_mcp.py
```

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `calendar_stats` | 查看本地缓存规模（已知学期、已抓取学期、事件数、日期范围）。 |
| `list_terms(refresh=false)` | 列出已知学期；`refresh=true` 重新抓取列表页。 |
| `get_term(term_name, refresh=false)` | 获取某个学期的完整日历（如 `2026年秋季学期`）。 |
| `get_current_term(refresh=false)` | 返回"今天处于哪个学期"、当天安排与学期说明。 |
| `get_events(date)` | 查询某天跨缓存的公开安排，`date` 支持 `YYYY-MM-DD` 或 `today`。 |
| `search_events(query, limit=20)` | 按关键词搜索缓存事件（如 `开学`、`假期`、`考试`）。 |
| `refresh_term(term_name)` | 重新抓取单个学期的公开页面并更新缓存。 |
| `check_robots` | 抓取并缓存 `robots.txt` 供审计。 |

所有工具只读公开数据并标注 `public_only: true`。`refresh_*` 请求间隔至少 1 秒，避免高频访问。

## 预热缓存

```bash
cd /AstrBot/data/academic-calendar-mcp   # 生产容器内
PYTHONPATH=/AstrBot/data/academic-calendar-mcp/src python -m academic_calendar_mcp.cli robots
PYTHONPATH=/AstrBot/data/academic-calendar-mcp/src python -m academic_calendar_mcp.cli listing --refresh
PYTHONPATH=/AstrBot/data/academic-calendar-mcp/src python -m academic_calendar_mcp.cli refresh
PYTHONPATH=/AstrBot/data/academic-calendar-mcp/src python -m academic_calendar_mcp.cli stats
```

## 数据文件

容器中的 SQLite 数据库在 `/AstrBot/data/academic-calendar-cache/calendar.sqlite3`；本地开发默认使用 `data/academic-calendar.sqlite3`。

导出 JSONL：

```bash
PYTHONPATH=/AstrBot/data/academic-calendar-mcp/src python -m academic_calendar_mcp.cli export --output /AstrBot/data/academic-calendar-cache/calendar.jsonl
```

## 解析说明

- 详情页 HTML 表格每行代表一周：`月`（中文数字，`rowspan` 跨整月）＋`教学周`（如 `秋1`）＋ 星期日至星期六每天两列 `[日号][事件]`。
- 事件单元格中的 `<i>*休</i>` 标记为休息/调休日（`is_off_day=true`），事件名单独保留，如 `元旦`。
- 日期重建：以学期名中的年份为基准年，月份 `一`/`二` 视为次年（秋季学期跨年），其余月份视为当年。
- 学期说明（开学注册、学期结束、假期等）来自页面 `<li>` 列表，随学期一并缓存。
- 已知局限：页面若改版导致表格结构变化，解析会失败并返回显式错误，不会静默产出错误日期；公开数据更新以教务处页面为准。

## 注意

- 只面向公开页面和个人/内部查询使用。
- 不建议高并发；默认请求间隔 1 秒。
- 如果 `robots.txt` 或站点规则变化，请停止抓取并重新评估。
