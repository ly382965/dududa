# college-notice-mcp

`college-notice-mcp` 是一个面向 AstrBot 的 MCP Server，抓取并缓存中国科学技术大学**各学院官网公开发布的通知公告**。

数据源为各学院公开页面，无需登录、不使用 Cookie、不绕过任何权限：

- 数学科学学院：`https://math.ustc.edu.cn/tzgg/list.htm`
- 计算机科学与技术学院：`https://cs.ustc.edu.cn/20166/list.htm`
- 物理学院：`https://physics.ustc.edu.cn/tzgg/list.htm`

各学院站采用校建统一 WebPlus 模板，通知详情 URL 形如 `/yyyy/mm/dd/c{col}a{id}/page.htm`。只缓存公开可见信息，请求间隔默认 1 秒，建议低并发使用。

## 运行环境

在 Dududa 生产栈中，Compose 将 `services/college-notice-mcp/` 挂载到 AstrBot 容器内：

```text
/AstrBot/data/college-notice-mcp
```

MCP 运行时使用 AstrBot 统一容器环境：

```text
command: /usr/local/bin/python
server:  /AstrBot/data/college-notice-mcp/run_college_notice_mcp.py
package: installed in the derived AstrBot image
```

## AstrBot 接入

`mcp_server.json` 配置（生产栈模板）：

```json
{
  "mcpServers": {
    "college_notice": {
      "command": "/usr/local/bin/python",
      "args": [
        "/AstrBot/data/college-notice-mcp/run_college_notice_mcp.py",
        "--db-path",
        "/AstrBot/data/college-notice-cache/notices.sqlite3",
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
  python /AstrBot/data/college-notice-mcp/scripts/check_mcp.py
```

本地开发自检（在 `services/college-notice-mcp/` 下创建 `.venv` 并安装依赖后）：

```bash
.venv/bin/python scripts/check_mcp.py
```

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `college_notice_stats` | 查看本地缓存规模（已知通知数、已抓详情数、各学院计数）。 |
| `list_colleges` | 列出已配置的学院通知源。 |
| `refresh_lists(college_key)` | 重新抓取全部（或指定）学院的通知列表页。 |
| `get_notices(college_key, limit)` | 读取缓存中最新公开学院通知；可按学院过滤。 |
| `get_notice_detail(notice_id, refresh)` | 获取某条通知全文（自动抓取详情页并缓存）。 |
| `search_notices(query, college_key, limit)` | 按关键词搜索缓存通知（标题＋正文）。 |
| `check_robots(college_key)` | 抓取并缓存各学院站 `robots.txt` 供审计。 |

所有工具只读公开数据并标注 `public_only: true`。`refresh_*` 请求间隔至少 1 秒，避免高频访问。

## 预热缓存

```bash
cd /AstrBot/data/college-notice-mcp   # 生产容器内
PYTHONPATH=/AstrBot/data/college-notice-mcp/src python -m college_notice_mcp.cli robots
PYTHONPATH=/AstrBot/data/college-notice-mcp/src python -m college_notice_mcp.cli lists --refresh
PYTHONPATH=/AstrBot/data/college-notice-mcp/src python -m college_notice_mcp.cli stats
```

## 数据文件

容器中的 SQLite 数据库在 `/AstrBot/data/college-notice-cache/notices.sqlite3`；本地开发默认使用 `data/college-notice.sqlite3`。

## 解析说明

- 列表页通过详情 URL 规则 `/yyyy/mm/dd/c{col}a{id}/page.htm` 识别通知条目；标题取链接文本，日期从条目附近文本提取。
- 详情页标题取自 `<title>`，正文优先取 `#vsb_content` / `.v_news_content` / `article` 等容器；附件按常见文档扩展名识别。
- 已知局限：各学院若改版导致结构变化，解析会失败并返回显式错误，不会静默产出错误数据；学院通知以各学院官网为准。

## 注意

- 只面向公开页面和个人/内部查询使用。
- 不建议高并发；默认请求间隔 1 秒。
- 如果 `robots.txt` 或站点规则变化，请停止抓取并重新评估。
