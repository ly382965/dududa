# campus-events-mcp

`campus-events-mcp` 是一个面向 AstrBot 的 MCP Server，抓取并缓存中国科学技术大学学校主页**通知公告**栏目聚合页（讲座、活动、竞赛、招聘等公开通知）。

数据源为公开页面，无需登录、不使用 Cookie、不绕过任何权限：

- 通知公告聚合页（主页）：`https://www.ustc.edu.cn/tzgg.htm`
- 教学类通知：`https://www.ustc.edu.cn/tzgg/jxltz.htm`
- 科研类通知：`https://www.ustc.edu.cn/tzgg/kyltz.htm`
- 管理类通知：`https://www.ustc.edu.cn/tzgg/glltz.htm`

只缓存公开可见信息。请求间隔默认 1 秒，建议低并发使用。

## 运行环境

在 Dududa 生产栈中，Compose 将 `services/campus-events-mcp/` 挂载到 AstrBot 容器内：

```text
/AstrBot/data/campus-events-mcp
```

MCP 运行时使用 AstrBot 统一容器环境：

```text
command: /usr/local/bin/python
server:  /AstrBot/data/campus-events-mcp/run_campus_events_mcp.py
package: installed in the derived AstrBot image
```

## AstrBot 接入

`mcp_server.json` 配置（生产栈模板）：

```json
{
  "mcpServers": {
    "campus_events": {
      "command": "/usr/local/bin/python",
      "args": [
        "/AstrBot/data/campus-events-mcp/run_campus_events_mcp.py",
        "--db-path",
        "/AstrBot/data/campus-events-cache/events.sqlite3",
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
  python /AstrBot/data/campus-events-mcp/scripts/check_mcp.py
```

本地开发自检（在 `services/campus-events-mcp/` 下创建 `.venv` 并安装依赖后）：

```bash
.venv/bin/python scripts/check_mcp.py
```

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `event_stats` | 查看本地缓存规模（已知通知数、已抓详情数、分类计数）。 |
| `list_categories` | 列出本服务跟踪的通知聚合类别。 |
| `refresh_lists` | 重新抓取教学/科研/管理三类通知聚合页。 |
| `get_events(category, limit)` | 读取缓存中的最新公开通知；可按类别过滤（教学/科研/管理）。 |
| `get_event_detail(event_id, refresh)` | 获取某条通知全文（自动抓取详情页并缓存），id 形如 `1360/25272`。 |
| `search_events(query, category, limit)` | 按关键词搜索缓存通知（标题＋正文）。 |
| `check_robots` | 抓取并缓存 `robots.txt` 供审计。 |

所有工具只读公开数据并标注 `public_only: true`。`refresh_*` 请求间隔至少 1 秒，避免高频访问。

## 预热缓存

```bash
cd /AstrBot/data/campus-events-mcp   # 生产容器内
PYTHONPATH=/AstrBot/data/campus-events-mcp/src python -m campus_events_mcp.cli robots
PYTHONPATH=/AstrBot/data/campus-events-mcp/src python -m campus_events_mcp.cli lists --refresh
PYTHONPATH=/AstrBot/data/campus-events-mcp/src python -m campus_events_mcp.cli stats
```

## 数据文件

容器中的 SQLite 数据库在 `/AstrBot/data/campus-events-cache/events.sqlite3`；本地开发默认使用 `data/campus-events.sqlite3`。

## 解析说明

- 列表页每行一条通知：标题链接（`/info/<栏目>/<id>.htm`）＋日期（`MM-DD`）。年份按“不超过今天”推断，跨年时回退一年。
- 类别由条目 URL 中的栏目号与抓取来源页共同推断：`1360/1361` 教学、`1362/1363` 科研、`1364/1365` 管理。
- 详情页正文优先取 `#vsb_content` / `.v_news_content` / `article`；附件按常见文档扩展名识别。
- 已知局限：列表只展示每页可见条数，更多历史条目需分页抓取（本服务默认抓首页）；学校主页改版可能导致结构变化，届时解析会显式报错。

## 注意

- 只面向公开页面和个人/内部查询使用。
- 不建议高并发；默认请求间隔 1 秒。
- 如果 `robots.txt` 或站点规则变化，请停止抓取并重新评估。