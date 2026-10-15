# Local Recommendations MCP

这是 PR #10 选择性整合的本地推荐缓存服务，canonical 路径为
`services/mcp/local-recs/`。它使用仓库内 JSONL 种子和运维维护的 SQLite 数据，属于默认关闭、
Registry-only 的可选 Server；没有 Capability definition/mapping，不进入 Planner 或生产
Provider health 链。

## MCP 边界

唯一 MCP 工具为：

```text
local_recommendations_public_query(
    query: str, kind: str = "", campus: str = "", meal_time: str = "",
    price_level: str = "", limit: int = 3, exclude_ids: list[int] | None = None
)
```

`query` 最长 120 个字符，`kind`、餐次和价位只能使用代码定义的枚举，`limit` 为 1–10，
排除 ID 最多 50 个正整数。工具从高分候选中返回有限条随机样本；查询不会更新
`recommended_count`，没有写副作用，也不调用地图或任意外部 URL。结果包含餐饮/活动/学习
条目的有限字段、种子来源、校区、餐次、价位和营业时间。

## 种子与运维边界

`run_local_recs_mcp.py` 在空数据库启动时导入 `seed/food.jsonl`、`activity.jsonl` 和
`seed/study.jsonl`。这是初始化写入，只发生在本地缓存为空时；MCP 工具本身始终只读。
`src/local_recs_mcp/cli.py` 保留 `add`、`import`、`template` 等运维写入命令，但这些命令
不是 MCP Tool，不会出现在 Registry allowlist。PR #10 的外部地图搜索和高德凭据没有导入。

## 本地运行

```bash
cd services/mcp/local-recs
PYTHONPATH=src python run_local_recs_mcp.py --db-path /tmp/local-recs.sqlite3
PYTHONPATH=src python -m local_recs_mcp.cli --db-path /tmp/local-recs.sqlite3 stats
```

离线契约测试为：

```bash
PYTHONPATH=src uv run --with pytest python -m pytest -q tests/test_local_recs_contract.py
```

部署后的 stdio discovery/query 自检可运行 `scripts/check_mcp.py`。

## Registry 与部署

`configs/mcp/servers/local-recs.json` 保持 `enabled: false`，只 allowlist
`local_recommendations_public_query`，没有 SecretRef。镜像会安装本包，Compose 以只读方式挂载
源码到 `/AstrBot/data/local-recs-mcp`，并把运行缓存放在独立目录；打包和挂载不表示启用。
