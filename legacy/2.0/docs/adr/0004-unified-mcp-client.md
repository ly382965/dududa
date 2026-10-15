# ADR 0004：Agent Core 只使用统一 MCP Client

- 状态：已接受，S12 已实施
- 日期：2026-07-18
- 决策范围：Agent Runtime 到 MCP Server 的发现、连接、调用和治理

实施状态（2026-08-10）：S12 已完成严格 JSON `configs/mcp/servers/*.json`、Core-owned
`UnifiedMcpClient`、独立 MCP 2.0 worker、iCourse compatibility facade 和 TreeWork
Verification。S22 已删除插件内每次调用新建进程/Session 的专用 Client 和运行时 legacy
选择；Unified 缺失时 fail closed，回滚使用精确 S19 Release。iCourse Server 仍通过隔离 worker
使用 MCP v1，这不形成第二套 Client。Capability Registry/Provider 仍属于 S13，discovery
不授予能力。

## 背景

作出本 ADR 时，iCourse 有两条调用路径：

1. `config/astrbot/mcp_server.json` 将 `icourse` 注册给 AstrBot 的 MCP 运行时；
2. `astrbot_plugin_dududa_core/course.py` 自行构造 `StdioServerParameters`，每次 `call` 或 `list_tools` 都启动新的 MCP 子进程和 session。

第二条路径中的 `timeout_hint` 没有生效，进程内抓取限速会随每次新进程重置。两条路径分别承担 discovery、生命周期和错误处理，无法统一执行权限、审计、重试、熔断和调用统计。若以后每个校园服务都复制一个 Client，Runtime 将直接知道具体 Server、命令、SQLite 路径和 MCP SDK。

目标架构要求 Agent Core 不 import 具体 MCP Server，也不依赖 AstrBot 才能单元测试。Planner 应面对 Capability，而不是 MCP Tool；MCP 是 Capability Provider 的基础设施实现。

## 决策

### 1. 一个 Domain 端口，一个基础设施实现

在 `packages/dududa-agent` 定义平台无关的 `UnifiedMcpClient` Protocol，并提供唯一生产实现。Runtime、Planner 和业务 Provider 不直接 import MCP SDK。

```python
class UnifiedMcpClient(Protocol):
    async def discover(self, server_id: str) -> tuple[McpToolDescriptor, ...]: ...
    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: JsonObject,
        context: McpCallContext,
    ) -> McpToolResult: ...
    async def health(self, server_id: str) -> McpHealth: ...
    async def close(self) -> None: ...
```

Client 实现由 AstrBot composition root 注入 Agent Runtime。离线测试注入 fake；其他平台可复用同一端口和实现。

### 2. Server Registry 是唯一连接来源

MCP command、args、cwd、transport、SecretRef、Tool allowlist、timeout、retry、circuit breaker 和并发上限由 `configs/mcp/servers/*.json` 的严格 Registry 定义。消息、模型和 Capability 参数不能生成或覆盖连接配置。

```python
class McpServerRegistry(Protocol):
    def get(self, server_id: str) -> McpServerDefinition: ...
    def list_enabled(self) -> tuple[McpServerDefinition, ...]: ...
    def config_revision(self) -> str: ...
```

唯一生产 `UnifiedMcpClient` 在构造时注入该 Registry；不存在第二套旁路连接配置。

Registry 与 Capability Registry 分开：

- MCP Registry 说明“怎样连接 Server、Server 有哪些允许的 Tool”；
- Capability Registry 说明“当前 actor 和上下文可规划哪些业务能力”；
- 动态发现的 Tool 不自动成为 Capability。

### 3. 复用受控 session

Client 按 Server 管理 session 生命周期：

- 首次需要时建连、initialize 和 discover；
- 在配置版本和健康状态允许时复用 session；
- 限制每 Server 并发；
- 在进程退出、配置变化或不可恢复错误时显式关闭；
- Server 崩溃时有限重建，不为每个调用正常重启进程。

这不要求所有 Server 永久在线。生命周期策略可以按 stdio 或 HTTP transport 调整，但对上层保持相同端口。

### 4. 统一可靠性策略

默认策略：

- connect 和 discovery 各 10 秒；
- 普通 tool call 30 秒，每能力硬上限 120 秒；
- 只读或幂等操作最多自动重试 1 次；
- 非幂等操作在不能证明未执行时不自动重试；
- 60 秒内连续 5 次失败打开熔断 120 秒，之后单探测 half-open；
- timeout、retry 都计入 Runtime 总 deadline 和最大 4 步工具预算。

具体能力可以在安全上限内收窄，不能通过配置移除全局 deadline 或无限重试。

### 5. 每次执行仍做权限和 Schema 校验

Capability Retrieval 的预过滤不代替执行检查。调用前 Executor 必须：

1. 确认 Capability、Provider、Server 和 Tool 映射仍有效；
2. 重新校验 actor 权限、ConversationScope、群策略、风险和限流；
3. 对参数执行 Capability 和 MCP Tool Schema 校验；
4. 应用 URL、路径、敏感字段和结果大小策略；
5. 生成脱敏审计 start/finish。

Client 不接受裸 `is_admin`，而接收带 `run_id`、policy snapshot、deadline 和 trace 的调用上下文。

### 6. 标准化结果和错误

Client 将 MCP SDK 的 text、image、resource 和 structured content 转为受限 Domain 类型，并区分：

- 连接不可用；
- initialize/discovery/protocol 失败；
- Tool timeout/cancel；
- 参数和结果 Schema 错误；
- Server 返回的业务错误；
- 结果过大或含禁止内容。

原始异常、stack trace、命令、环境变量和凭据不直接返回 Planner 或用户。

### 7. iCourse 使用 Compatibility Adapter 渐进迁移

迁移顺序：

1. 给当前 iCourse Tool 建立契约测试；
2. 将现有配置导入 MCP Registry；
3. 创建 iCourse Capability Provider；
4. 将旧 `ICourseClient` 标记为 compatibility，并让其内部转发 Unified MCP Client；
5. `/course` 命令切到 Capability Provider，保持权限、文本和数据库路径；
6. AstrBot MCP 配置只作为宿主集成，不再形成独立业务调用实现；
7. 所有消费者迁移且生产验证后删除旧的每调用一进程代码。

该迁移阶段没有移动 `services/icourse-mcp`，没有改变 `icourse` Server ID，也没有迁移
SQLite schema。S17 后源码位于 `services/mcp/icourse`；S22 删除运行时旧 Adapter，回滚改为
恢复精确 S19 Release，而不是在同一 Release 内切换 transport。

### 8. 定时推送只把 MCP 作为公开数据 Provider

校园公开信息、arXiv 和行业 allowlist 日报仍通过 Capability Provider 和本 ADR 的唯一
`UnifiedMcpClient` 调用。Scheduler 只产生版本化 occurrence，不直接调用 Tool；MCP Client
不创建订阅、不选择目标/时间、不决定是否发送，也不持有 Output Adapter。

后台 Worker 的 `ServiceCallContext` 不能替代创建订阅或启用群策略的 Actor 授权证据。每次
调用绑定订阅/occurrence、精确目标 Scope、固定只读 Capability、deadline、预算和审计；动态
发现的 Tool 不自动可用。首版只允许显式映射的公开只读能力，禁止任意 URL、私人校园数据、
外部写和 `message_send` Tool。

MCP 结果必须标准化为带 source/external ID、规范 URL、published/observed time、source
revision、content digest、引用和 warning 的 `SourceItem`。网页、Feed 和 structured content
均视为不可信 Observation；来源净化、新鲜度、条目/订阅去重、摘要、发送授权和 Delivery
reconciliation 由上层拥有。完整设计见 `../design/proactive-messaging.md`。

## 安全约束

- 模型不可指定 command、server URL、cwd、env 或 SecretRef；
- 新发现 Tool 默认不可用，必须同时通过 Server allowlist 和 Capability 映射；
- 文件导出、shell、批量抓取和管理 Tool 默认不进入 Planner；
- HTTP Server 执行 scheme、host、redirect 和私网访问策略；
- 审计记录 ID、shape、hash、状态和延迟，不记录完整正文或凭据；
- Server 返回内容一律视为不可信 Observation；
- 权限、隐私、风险和最大步数由确定性代码执行。
- 定时 Worker 不得伪造用户 Actor；Scheduler/MCP 不得拥有订阅、目标、发送决策或投递能力；

## 被否决的方案

### 保留每个插件自己的 MCP Client

否决原因：连接、timeout、错误和权限策略会持续漂移；每新增一个 Server 都复制一套 SDK 和进程逻辑。

### 完全依赖 AstrBot 内置 MCP 调用

否决原因：Agent Core 将无法脱离 AstrBot 测试，且无法保证其他入口使用相同的 Capability、权限、审计和 Validator 契约。AstrBot 仍可作为宿主和 transport 集成，但不是 Domain 边界。

### 将全部 MCP Tool 直接交给 Planner

否决原因：模型会看到管理型和高风险工具，候选上下文膨胀，并绕过 Capability 的权限、隐私、Top-K 和稳定版本语义。

### 每次调用启动一个 stdio 进程

否决原因：启动开销大，连接和 discovery 重复，进程内限速及健康状态失效，并难以正确管理并发和熔断。

### 为每个业务 Server 直接集成供应商 SDK

否决原因：会把具体供应商、认证和错误类型带入 Agent Core，失去 MCP 的进程与语言隔离。Server 内部仍可使用供应商 SDK。

## 影响

正面影响：

- MCP 生命周期、发现、超时、重试、熔断、权限、审计和统计一致；
- Agent Core 可用 fake Client 脱离 AstrBot 测试；
- Planner 只看到经过 Top-K 和 Policy 的稳定 Capability；
- iCourse 以及后续校园服务可以复用同一基础设施；
- 可以按 Server 隔离故障和并发。

代价：

- 需要维护 Registry、session manager、Schema cache 和错误映射；
- 迁移期会同时存在旧 Adapter 和新 Client；
- 持久 session 需要处理子进程退出、取消和优雅关闭；
- AstrBot 原生 MCP 配置与 Agent Registry 需要明确同步责任，避免双源漂移。

## 验证要求

- Unit：timeout、retry、circuit breaker、Schema、redaction 和 lifecycle 状态机；
- Contract：initialize、list_tools、call_tool、错误和 Schema snapshot；
- Integration：并发、崩溃重启、取消、half-open 恢复和多 Server 隔离；
- Security：未授权调用次数为零，任意路径和未声明 Tool 被拒绝；
- iCourse：旧命令行为、缓存路径、查询结果和 refresh 权限保持兼容；
- Smoke：派生镜像中持久 stdio session 可以启动、调用并关闭。
- Proactive source：固定公开 Capability、订阅/occurrence/Scope 绑定、来源 allowlist、
  provenance/freshness、Prompt Injection、重复条目和 Scheduler 不可直调 Tool 的契约测试。

## 重新评估条件

出现以下情况时提出新 ADR，而不是在 Provider 中复制 Client：

- MCP 协议或 SDK 出现无法在统一端口表达的重大变化；
- 某 transport 需要独立进程级安全边界；
- session 复用被可靠数据证明不适合某类 Server；
- AstrBot 提供了可注入、平台无关且覆盖本决策全部治理要求的统一实现。
