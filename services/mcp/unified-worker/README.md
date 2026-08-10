# Dududa Unified MCP Worker

该包把 `mcp==2.0.0` 隔离在独立解释器中，为 Dududa 的 Core-owned
`UnifiedMcpClient` 提供 initialize、discover、call、cancel 和 close 传输适配。

worker 不拥有 Server Registry、Capability 权限、Schema freshness、重试、熔断、调度、
目标或发送决策。主环境、AstrBot 和 iCourse Server 继续使用 `mcp==1.29.0`；iCourse 由
worker 的 legacy mode 连接。

本地验证：

```bash
uv sync --locked
uv run --locked python -m unittest discover -s tests
```

测试只使用注入 Fake；Streamable HTTP Contract 不访问网络。
