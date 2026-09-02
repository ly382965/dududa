# College Notice MCP

这是 PR #10 选择性整合的学院官网通知缓存服务，canonical 路径为
`services/mcp/college-notice/`。它是默认关闭的 Registry-only 可选 Server，尚未进入
Capability Catalog、Planner 或生产 Provider health 链。

## MCP 边界

MCP 进程只暴露：

```text
college_notices_public_query(query: str, college_key: str = "", limit: int = 10)
```

`query` 最长 200 个字符，学院键必须来自配置清单，`limit` 为 1–20。结果返回有限长度的
通知标题、摘要、发布日期、学院键、官方 HTTPS URL、最多十个官方附件和已有的
`observed_at`。MCP 只读本地缓存，不提供 lists/detail/robots/refresh 或任意 URL 工具；抓取
和缓存写入只通过运维 CLI 进行。

默认学院来源为：

- 数学科学学院：`https://math.ustc.edu.cn/tzgg/list.htm`；
- 计算机科学与技术学院：`https://cs.ustc.edu.cn/tzgg_35904/list.htm`；
- 物理学院：`https://physics.ustc.edu.cn/3584/list.htm`。

来源域名和链接必须是匹配的 USTC HTTPS 主机；消息或模型不能传入任意来源。

## 本地运行

```bash
cd services/mcp/college-notice
PYTHONPATH=src python run_college_notice_mcp.py --db-path /tmp/college-notice.sqlite3
```

运维 CLI 示例：

```bash
PYTHONPATH=src python -m college_notice_mcp.cli --db-path /tmp/college-notice.sqlite3 stats
PYTHONPATH=src python -m college_notice_mcp.cli --db-path /tmp/college-notice.sqlite3 lists --refresh
```

刷新、详情和 robots 会产生外部读取或缓存写入，只属于运维边界。部署后的 stdio 自检脚本为
`scripts/check_mcp.py`；离线契约测试为：

```bash
PYTHONPATH=src uv run --with pytest python -m pytest -q tests/test_college_notice_contract.py
```

## Registry 与部署

`configs/mcp/servers/college-notice.json` 保持 `enabled: false`，只 allowlist
`college_notices_public_query`，没有 SecretRef。镜像会安装本包，Compose 以只读方式挂载源码
到 `/AstrBot/data/college-notice-mcp`；只有后续显式启用和 Capability 审核完成后才可能进入
Agent 规划面。
