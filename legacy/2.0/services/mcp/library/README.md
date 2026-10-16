# Library Hours MCP

这是 PR #10 选择性整合的中国科大图书馆开放时间缓存服务，canonical 路径为
`services/mcp/library/`。它是默认关闭、Registry-only 的可选 Server，没有 Capability
definition/mapping，不进入 Planner 或生产 Provider health 链。

## MCP 边界

唯一 MCP 工具为：

```text
library_hours_public_query(query: str, campus: str = "", limit: int = 20)
```

`query` 最长 120 个字符，`campus` 最长 32 个字符，`limit` 为 1–30。工具只读取本地
SQLite，返回有限长度的校区、地点、业务内容、工作日/周末时段和电话。MCP 不暴露 refresh、
robots 或写入工具，抓取和缓存替换只由运维 CLI 执行。

来源固定为 `https://lib.ustc.edu.cn/?p=5916`，不会接受消息或模型提供的任意 URL。缓存记录
没有统一伪造的 freshness 字段；是否新鲜应以运维元数据为准。

## 本地运行

```bash
cd services/mcp/library
PYTHONPATH=src python run_library_mcp.py --db-path /tmp/library.sqlite3
```

运维 CLI 示例：

```bash
PYTHONPATH=src python -m library_mcp.cli --db-path /tmp/library.sqlite3 stats
PYTHONPATH=src python -m library_mcp.cli --db-path /tmp/library.sqlite3 refresh
```

刷新和 robots 会访问外部站点。部署后的 stdio 自检脚本为 `scripts/check_mcp.py`；离线契约
测试为：

```bash
PYTHONPATH=src uv run --with pytest python -m pytest -q tests/test_library_contract.py
```

## Registry 与部署

`configs/mcp/servers/library.json` 保持 `enabled: false`，只 allowlist
`library_hours_public_query`，没有 SecretRef。镜像会安装本包，Compose 以只读方式挂载源码到
`/AstrBot/data/library-mcp`，并为缓存提供独立数据目录；安装和挂载不等于启用。
