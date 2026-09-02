# Training Plan MCP

这是 PR #10 选择性整合的本科专业设置缓存服务，canonical 路径为
`services/mcp/training-plan/`。它是默认关闭、Registry-only 的可选 Server，没有
Capability definition/mapping，不进入 Planner 或生产 Provider health 链。

## MCP 边界

唯一 MCP 工具为：

```text
training_programs_public_query(query: str, year: int | None = None,
                               college: str = "", limit: int = 20)
```

`query` 最长 160 个字符，年份限制在 2010–2100，学院字段最长 200 个字符，`limit` 为
1–30。工具只读取本地 SQLite 缓存，返回年度、学院、系、专业、代码、学位和停招标记。它
不是实时培养方案审核，也不提供 refresh、robots 或写入 MCP 工具。

来源固定为中国科大教务处公开页面
`https://www.teach.ustc.edu.cn/education/239.html`。抓取和缓存替换只通过运维 CLI 执行，
缓存新鲜度由运维元数据决定。

## 本地运行

```bash
cd services/mcp/training-plan
PYTHONPATH=src python run_training_plan_mcp.py --db-path /tmp/training-plan.sqlite3
```

运维 CLI 示例：

```bash
PYTHONPATH=src python -m training_plan_mcp.cli --db-path /tmp/training-plan.sqlite3 stats
PYTHONPATH=src python -m training_plan_mcp.cli --db-path /tmp/training-plan.sqlite3 refresh
```

刷新和 robots 会访问外部站点。部署后的 stdio 自检脚本为 `scripts/check_mcp.py`；离线契约
测试为：

```bash
PYTHONPATH=src uv run --with pytest python -m pytest -q tests/test_training_plan_contract.py
```

## Registry 与部署

`configs/mcp/servers/training-plan.json` 保持 `enabled: false`，只 allowlist
`training_programs_public_query`，没有 SecretRef。镜像会安装本包，Compose 以只读方式挂载
源码到 `/AstrBot/data/training-plan-mcp`；后续要进入 Agent 规划面必须另行完成来源审核和
Capability mapping。
