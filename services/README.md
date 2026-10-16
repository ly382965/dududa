# 共享业务服务

`builtin/shuttle/` 是从 2.0 原样提取的只读校车服务和版本化时刻表。
3.0 的规则处理器直接调用它，Codex 通过同一服务的 MCP 包装调用。

`mcp/` 保留独立校园服务、传输 worker 和 Console；它们是业务服务，不是 Agent runtime。
3.0 只通过显式配置的 Console 地址调用已授权的公开能力；默认不开启远程校园查询。
这些服务仍使用各自的依赖环境和配置，根目录的 `uv sync` 只安装 3.0 runtime。
需要旧 Console 的 `dududa-agent` 业务契约依赖时，从
`legacy/2.0/packages/dududa-agent` 安装到 Console 的独立虚拟环境，不能恢复旧 Agent 主循环。

完整旧服务、测试和部署步骤仍封存在 `legacy/2.0/services/`、`legacy/2.0/deploy/`。
