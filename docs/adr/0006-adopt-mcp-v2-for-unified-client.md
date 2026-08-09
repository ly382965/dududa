# ADR 0006：S12 统一 MCP 基础设施采用 MCP Python SDK v2

- 状态：已接受（ADOPT）
- 日期：2026-08-09
- 决策范围：S12 `UnifiedMcpClient` 的 Python SDK 与迁移边界
- 证据：`spikes/mcp-v2/report.json`
- 证据摘要：`sha-256:ddebd93ef0b32cb00618c2df29caef7d61b3d3f523683736353357c5fad32590`

## 背景

ADR 0004 已决定由一个 Core Port 和一个受治理的基础设施实现统一 MCP
连接，但当时没有证明 MCP Python SDK v2 能否兼容现有 iCourse v1 Server，
也没有验证长生命周期 session、取消、崩溃、未知调用结果和 Schema 漂移。
直接升级根依赖会使当前使用 v1 FastMCP API 的 iCourse Server 无法启动。

因此 S12A 在生产实现之前设置 fail-closed Spike。根 workspace 与 iCourse
继续固定 `mcp==1.29.0`，v2 Client/Server 只存在于 PEP 723 隔离环境中。

## 决策

S12 的统一 MCP Client 与新的本地 Fake Server 采用 `mcp==2.0.0`。迁移期
通过 v2 Client 的显式 `mode="legacy"` 连接当前 iCourse v1 Server；不得先
升级 iCourse Server 或删除 v1 回滚路径。

该决定只选择 S12 基础设施所使用的 SDK 和兼容方向。`UnifiedMcpClient 尚未实现`，
`McpServerRegistry`、Capability Provider、生产 session manager、重试、熔断和
Schema store 仍由后续 S12 分支负责。

## 证据

同一套 discovery、call 和 close lifecycle harness 分别验证了原生 v2 Fake 与
legacy iCourse fixture：

- 原生协议协商为 `2026-07-28`，legacy 协商为 `2025-11-25`；
- 一个进程和一个 session 完成 100 次顺序调用，discovery 只发生一次；
- 20 次并发调用受四路 semaphore 限制，实测最大 active 为 4；
- connect、discovery、call timeout 均被稳定分类，关闭后无残留子进程；
- effect 前崩溃为 `safe_retry_eligible`，副作用为 0；effect 后崩溃为
  `outcome_unknown`，副作用为 1，且自动重试次数为 0；
- 崩溃 generation 被销毁，新 generation 重新握手、发现并成功调用；
- 兼容的新 Tool discovery 可以发布事实，不兼容的已映射 Tool Schema 不发布；
  过期 Snapshot 进入 `unavailable`，发现过程产生 0 个 Capability grant；
- legacy 子进程被 socket deny 和 SQLite allow-path guard 约束，观测到 0 次网络
  尝试和 0 次越界数据库打开；
- Python 3.10.20 与 3.12.13 使用独立 uv cache 串行运行，生成逐字节相同报告。

全部 13 项硬门禁通过。提交报告不包含 PID、临时路径、时长、stderr、正文或凭据。

## S12 实施约束

1. Core 只定义框架无关 DTO、错误和 `UnifiedMcpClient` Port，不 import MCP SDK。
2. v2 SDK 只能存在于基础设施 Adapter；每个 Server 独立拥有 session、generation、
   health 与 Schema Snapshot。
3. iCourse 仍是唯一真实 MCP Server。其他 Server 本轮只能用 Fake、配置和 Contract
   Test 证明扩展性，不能被写成已经存在的校园、arXiv 或行业 MCP。
4. Discovery 只更新 Server 事实；Capability Registry 的显式映射才可授权业务能力。
5. effect 后断连继续归类为未知结果，不得自动重试；只读或已证明 effect 前失败的
   操作才可能按预算重试。
6. Schema cache 不成为权限来源。配置变化、断线、过期或不兼容变更必须使旧
   generation 失效并 fail closed。
7. iCourse legacy 直连作为回滚保留到 S22，删除前需要全部消费者迁移证据和可恢复
   的上一 Release。

## 未被本 ADR 证明的事项

- Unified Client、Registry 或 Capability Runtime 已完成；
- iCourse 已升级为 v2 Server，或其所有消费者已经迁移；
- 真实 HTTP transport、凭据、Provider Endpoint 或生产负载可用；
- 除 iCourse 外存在任何真实 MCP Server；
- 校园资讯、arXiv、行业资讯或 QQ 推送已经接入；
- 真实群聊质量、在线 Bandit 或 S23 发送已经验证。

这些事项继续受各自 Sxx 门禁约束。iCourse 仍是唯一真实 MCP Server。

## 被否决的方案

### 立即升级根 workspace 与 iCourse Server

否决。v2 已移除当前 iCourse 使用的 `mcp.server.fastmcp` 路径，先升级会同时改变
Server API 和 Client lifecycle，失去可回滚的迁移顺序。

### 长期固定 v1 并复制专用 Client

否决。当前每次调用新建进程和 session 的路径无法统一 generation、并发、Schema、
超时和错误语义，也会使每个新 Server 复制第二套控制面。

### 把 Spike harness 直接作为生产 Client

否决。Spike 的 journal、fake clock 和故障进程只用于决策证据，不拥有生产配置、
权限、审计或可靠性策略。

## 回滚与复审

S12 实施期间如 v2 Adapter 无法满足 ADR 0004 的全部 Port、资源关闭或兼容要求，保留
根 v1 lock 和旧 iCourse 路径并回退到本 ADR 前一 Release。若 MCP v2 的协议、SDK API
或 legacy mode 发生不兼容变化，必须重新运行锁定 Spike、更新证据摘要并提出新 ADR，
不能在业务 Provider 内增加旁路 Client。
