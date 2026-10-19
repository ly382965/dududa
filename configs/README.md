# 3.x 配置

- `runtime-v3.example.json`：Host 的模型注册与默认、规则、会话白名单、频率限制及 `features.*` 配置示例；字段说明见 [运维手册](../docs/operations/v3.md#配置字段)。
- `personas/`：共享人格资产；Host 使用 `personas/dududa.md` 作为 Agent 系统提示。
- `capabilities/`、`console-capabilities/`、`mcp/`：复用业务服务的目录和 MCP Console 配置。原有服务器路径为旧部署路径，独立部署时须按实际环境配置。

2.0 的 AstrBot 和发布配置位于 `legacy/2.0/configs/`。旧配置不会控制 3.x Host。
