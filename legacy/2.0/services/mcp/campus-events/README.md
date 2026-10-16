# Campus Events MCP

这是 PR #10 选择性整合的学校主页通知缓存服务，canonical 路径为
`services/mcp/campus-events/`。它是一个默认关闭的 Registry-only 可选 Server：当前没有
Capability definition/mapping，不会出现在 Planner，也不会加入生产 Provider health 链。

## MCP 边界

MCP 进程只暴露一个工具：

```text
campus_events_public_query(query: str, category: str = "", limit: int = 10)
```

查询只读本地 SQLite 缓存。`query` 最长 200 个字符，`category` 仅允许 `综合`、`教学`、
`科研`、`管理`，`limit` 为 1–20。结果包含有限长度的标题、摘要、官方来源 URL、附件和
`observed_at`（若缓存记录有抓取时间）。MCP 不提供 refresh、detail、robots 或任意 URL
工具；这些操作只属于运维 CLI。

来源固定为 `https://www.ustc.edu.cn` 的通知公告路径。缓存新鲜度取决于运维更新记录，不能
从本工具推断实时可用性。

## 本地运行

```bash
cd services/mcp/campus-events
PYTHONPATH=src python run_campus_events_mcp.py --db-path /tmp/campus-events.sqlite3
```

运维 CLI 可查看统计、刷新列表或执行本地搜索，例如：

```bash
PYTHONPATH=src python -m campus_events_mcp.cli --db-path /tmp/campus-events.sqlite3 stats
PYTHONPATH=src python -m campus_events_mcp.cli --db-path /tmp/campus-events.sqlite3 lists --refresh
```

刷新和 robots 请求会访问外部站点，只应由运维人员按来源策略执行。部署后的 MCP 自检脚本为
`scripts/check_mcp.py`；离线契约测试为：

```bash
PYTHONPATH=src uv run --with pytest python -m pytest -q tests/test_campus_events_contract.py
```

## Registry 与部署

`configs/mcp/servers/campus-events.json` 保持 `enabled: false`，只 allowlist
`campus_events_public_query`，没有 SecretRef。派生镜像会安装本包，Compose 将源码以只读方式
挂载到 `/AstrBot/data/campus-events-mcp`；这只是打包与运维可见性，不代表服务已启用。
