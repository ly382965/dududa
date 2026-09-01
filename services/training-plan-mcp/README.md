# training-plan-mcp

`training-plan-mcp` 是一个面向 AstrBot 的 MCP Server，抓取并缓存中国科学技术大学教务处公开发布的**学院、系与本科专业设置一览表**（含 2013/2015/2019-2026 等多个入学年级版本）。

数据源为公开页面，无需登录、不使用 Cookie、不绕过任何权限：

- 一览页：`https://www.teach.ustc.edu.cn/education/239.html`

只缓存公开可见信息。请求间隔默认 1 秒，建议低并发使用。专业的**培养方案详细课程列表**目前只在 `catalog.ustc.edu.cn`（前端渲染的 SPA）提供，本服务缓存的是稳定的院系/专业/专业代码/学位门类一览表。

## 运行环境

在 Dududa 生产栈中，Compose 将 `services/training-plan-mcp/` 挂载到 AstrBot 容器内：

```text
/AstrBot/data/training-plan-mcp
```

MCP 运行时使用 AstrBot 统一容器环境：

```text
command: /usr/local/bin/python
server:  /AstrBot/data/training-plan-mcp/run_training_plan_mcp.py
package: installed in the derived AstrBot image
```

## AstrBot 接入

`mcp_server.json` 配置（生产栈模板）：

```json
{
  "mcpServers": {
    "training_plan": {
      "command": "/usr/local/bin/python",
      "args": [
        "/AstrBot/data/training-plan-mcp/run_training_plan_mcp.py",
        "--db-path",
        "/AstrBot/data/training-plan-cache/plans.sqlite3",
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
  python /AstrBot/data/training-plan-mcp/scripts/check_mcp.py
```

本地开发自检（在 `services/training-plan-mcp/` 下创建 `.venv` 并安装依赖后）：

```bash
.venv/bin/python scripts/check_mcp.py
```

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `plan_stats` | 查看本地缓存规模（年份数、总行数、学院数、专业数）。 |
| `get_program_years(refresh)` | 列出已有的入学年级版本；`refresh=true` 重新抓一览页。 |
| `get_majors(year)` | 某一年级全部专业行；缺省取最新版本。 |
| `get_college_majors(college, year)` | 单个学院的专业（如 `数学科学学院`）。 |
| `search_majors(query, year, limit)` | 按专业名/学院/系/代码模糊搜索（如 `计算机`、`070301`）。 |
| `list_colleges` | 列出缓存中所有学院。 |
| `refresh_programs` | 重新抓一览页并整体重建缓存。 |
| `check_robots` | 抓取并缓存 `robots.txt` 供审计。 |

所有工具只读公开数据并标注 `public_only: true`。`refresh_*` 请求间隔至少 1 秒，避免高频访问。

## 预热缓存

```bash
cd /AstrBot/data/training-plan-mcp   # 生产容器内
PYTHONPATH=/AstrBot/data/training-plan-mcp/src python -m training_plan_mcp.cli robots
PYTHONPATH=/AstrBot/data/training-plan-mcp/src python -m training_plan_mcp.cli refresh
PYTHONPATH=/AstrBot/data/training-plan-mcp/src python -m training_plan_mcp.cli years
PYTHONPATH=/AstrBot/data/training-plan-mcp/src python -m training_plan_mcp.cli stats
```

## 数据文件

容器中的 SQLite 数据库在 `/AstrBot/data/training-plan-cache/plans.sqlite3`；本地开发默认使用 `data/training-plan.sqlite3`。

## 解析说明

- 一览页包含多张 `table2` 表格，每张对应一个入学年级，`caption` 中带 `(从XXXX年开始执行)` 或 `（从XXXX级开始执行）`。
- 表格四列：学院／系／专业／专业代码＋学位门类；`rowspan` 跨行的学院/系/专业会被正确展开，一个单元格内多个专业用 `<br>` 分隔、按行对齐到专业代码。
- 专业代码形如 `070101`，学位门类括号内如 `理`/`工`/`文`/`管`/`经`/`医`/`史`；表脚 `已停止招生本科专业：N` 会写入该年级的 `discontinued_count`。
- 已知局限：`em` 标记的“已停止招生”专业当前以普通专业入库，如需精确区分可在后续版本扩展；页面改版导致表格结构变化时会显式报错。

## 注意

- 只面向公开页面和个人/内部查询使用。
- 不建议高并发；默认请求间隔 1 秒。
- 如果 `robots.txt` 或站点规则变化，请停止抓取并重新评估。