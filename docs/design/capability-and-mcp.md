# 能力、工具运行时与 MCP 设计

## 1. 文档状态

- 阶段：Phase 1，目标设计，尚未实现。
- 目标代码：`packages/dududa-agent/src/dududa/capabilities/`。
- MCP Server 目标目录：`services/mcp/`。
- 配置目标目录：`configs/capabilities/`、`configs/mcp/`。
- 兼容来源：`astrbot_plugin_dududa_core/course.py`、AstrBot 当前 MCP 配置和 `services/icourse-mcp/`。

本文定义嘟嘟哒如何声明、检索、规划、执行和校验能力，以及如何通过统一 MCP Client 调用外部 MCP Server。本文不实现代码，不改变当前 `icourse` Server 名、SQLite 路径或现有 `/course` 命令。

## 2. 目标与非目标

目标：

- 让 Planner 面向稳定的 Capability，而不是面对所有原始函数或 MCP Tool；
- 在模型看到工具前完成上下文、权限、隐私和风险过滤；
- 用显式、有限状态的 Planner/Executor/Validator 循环代替无限制 Agent 循环；
- 由一个 MCP Registry 和一个 Unified MCP Client 统一管理发现、连接、超时、重试、熔断和错误；
- 让内建能力和 MCP 能力使用相同的执行、审计和结果校验契约；
- 使 iCourse 成为首个标准 Capability Provider 和 MCP Server 样板；
- 保留现有入口，在新链路验证完成前可按提交回滚。

非目标：

- 不让 MCP Server 解释完整自然语言请求或决定是否回复；
- 不允许 Persona、Prompt 或具体模型授予权限；
- 不把 AstrBot Event、MCP SDK 类型或具体 Server 实现放入 Domain；
- 不在本阶段训练 Tool Planner 模型；
- 不把批量抓取、文件导出和诊断工具默认暴露给模型。

## 3. 总体关系

```text
SocialDecision(USE_TOOLS)
          |
          v
   CapabilityQuery
          |
          v
Capability Registry -- deterministic policy filters
          |
          v
Capability Retrieval -- Top-K summaries
          |
          v
       Planner
          |
          v
       ToolPlan
          |
          v
Executor -> Capability Provider -> Built-in implementation
    |                |
    |                +-----------> Unified MCP Client
    |                                      |
    |                                      v
    |                                MCP Registry
    |                                      |
    |                                      v
    |                                 MCP Servers
    v
Observation -> Validator -> finish | continue | retry | clarify | abort
```

依赖方向为：

```text
runtime/application
    -> capability domain + Protocol
        <- built-in infrastructure adapters
        <- generic MCP infrastructure adapter

services/mcp/*
    -> MCP transport + service-owned domain/infrastructure
```

Agent Core 不得 import `mcp` SDK、`icourse_mcp`、AstrBot 或某个 Server 的启动脚本。具体实现由 composition root 注入。

## 4. Capability Domain

### 4.1 CapabilityDefinition

Capability 是上层可规划的原子业务能力。一个 Capability 可以由内建代码、一个 MCP Tool 或受控工作流提供，但必须有稳定 ID 和明确契约。

```python
@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    schema_version: int
    capability_id: str
    name: str
    description: str
    category: str
    provider: ProviderRef
    input_schema: JsonSchema
    output_schema: JsonSchema
    risk_level: RiskLevel
    privacy_level: PrivacyLevel
    allowed_contexts: frozenset[ConversationContext]
    required_permissions: frozenset[str]
    cost_hint: CostHint
    latency_hint: LatencyHint
    tags: frozenset[str]
    idempotency: Idempotency
    side_effects: frozenset[SideEffect]
    enabled: bool = True
```

最低字段与约束：

- `capability_id` 使用稳定命名空间，例如 `icourse.search_courses.v1`；显示名变化不得改变 ID；
- `description` 只说明何时使用、输入和结果，不包含密钥、内部路径或 Prompt 注入文本；
- `input_schema` 和 `output_schema` 必须是受支持的 JSON Schema 子集，拒绝开放式任意对象作为核心契约；
- `provider` 只引用 Provider ID，不携带可执行对象；
- `risk_level`、`privacy_level`、权限和上下文由代码校验，模型不可修改；
- `side_effects` 至少区分 `none`、`network_read`、`persistent_write`、`external_write`、`message_send` 和 `file_write`；
- 定义变化若破坏输入输出兼容，必须发布新的版本化 `capability_id`。

建议枚举：

```python
class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class PrivacyLevel(StrEnum):
    PUBLIC = "public"
    CONVERSATION = "conversation"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"

class Idempotency(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    NON_IDEMPOTENT = "non_idempotent"
```

### 4.2 CapabilityQuery

Social Decision 只产生业务意图，不指定工具名：

```python
@dataclass(frozen=True, slots=True)
class CapabilityQuery:
    intent_ids: tuple[str, ...]
    natural_language_goal: str
    entities: tuple[EntityRef, ...]
    required_output: str | None
    preferred_categories: tuple[str, ...]
    excluded_side_effects: frozenset[SideEffect]
    max_risk_level: RiskLevel
```

`natural_language_goal` 是不可信输入，不能被拼接到 shell、SQL、文件路径或 Server 配置。权限和允许的风险级别来自 Runtime Policy，不接受模型自行上调。

### 4.3 Candidate 和摘要

Planner 只能看到经过过滤的摘要：

```python
@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    capability_id: str
    name: str
    description: str
    input_schema: JsonSchema
    output_summary: str
    risk_level: RiskLevel
    privacy_level: PrivacyLevel
    cost_hint: CostHint
    latency_hint: LatencyHint
    score: float
    reason_codes: tuple[str, ...]
```

摘要不得包含 MCP 启动命令、环境变量、Server 凭据、内部 hostname 或用户无权访问的字段。

## 5. Capability Registry 与 Top-K Retrieval

### 5.1 Registry 端口

```python
class CapabilityRegistry(Protocol):
    def get(self, capability_id: str) -> CapabilityDefinition: ...
    def list_enabled(self) -> Sequence[CapabilityDefinition]: ...
    def register_provider(self, provider: CapabilityProvider) -> None: ...

class CapabilityProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def invoke(
        self,
        capability_id: str,
        arguments: JsonObject,
        context: ExecutionContext,
    ) -> ProviderResult: ...
```

注册时必须校验唯一 ID、Schema、Provider 存在性、风险字段和配置来源。动态发现的 MCP Tool 不能自动成为模型可见 Capability；必须有显式映射和策略。

### 5.2 确定性预过滤

语义检索前按以下顺序 fail closed：

1. `enabled` 与配置版本；
2. 当前 Provider 和 Server 健康状态；
3. private/group/channel 等 `allowed_contexts`；
4. actor 权限与群策略；
5. 当前 Scope 是否满足能力的隐私要求；
6. 风险级别和 side effect 是否在本次 Policy 允许范围内；
7. 所需输入是否可能从当前 Context 获得；
8. 成本、延迟和总 deadline 是否可接受。

过滤结果为空时，返回稳定 reason code。不得扩大权限后重新检索。

### 5.3 Top-K 排序

第一阶段使用可解释的混合排序：

```text
score = semantic_similarity
      + intent_tag_match
      + entity/schema_match
      + provider_health_bonus
      - latency_penalty
      - cost_penalty
      - risk_penalty
```

- 默认 `K=8`，全局硬上限 `20`；
- 相同分数按稳定 `capability_id` 排序，保证测试可复现；
- 对同一 Provider 和同一类别设置数量上限，避免候选被重复工具占满；
- 检索日志记录 ID、分数和 reason code，不记录完整用户正文或敏感参数；
- Eval 分别计算目标能力 Recall@K、错误能力暴露率和权限过滤准确率；
- Top-K 只减少 Planner 上下文，不能代替执行前权限复核。

## 6. Planner、Executor 与 Validator

### 6.1 ToolPlan

```python
@dataclass(frozen=True, slots=True)
class ToolStep:
    step_id: str
    capability_id: str
    arguments: JsonObject
    purpose: str
    depends_on: tuple[str, ...]
    expected_output: str

@dataclass(frozen=True, slots=True)
class ToolPlan:
    schema_version: int
    goal: str
    steps: tuple[ToolStep, ...]
    completion_criteria: tuple[str, ...]
```

Planner 只能引用本次候选列表中的 ID。计划必须是有向无环依赖，参数必须通过对应 input schema。初始计划不能借未来 Observation 伪造参数；需要后续结果的步骤应明确 `depends_on`，由下一轮规划填充。

### 6.2 显式循环

```text
RETRIEVE
  -> PLAN
  -> AUTHORIZE
  -> EXECUTE
  -> OBSERVE
  -> VALIDATE
       +-> FINISH
       +-> CONTINUE -> PLAN
       +-> RETRY ----> AUTHORIZE
       +-> CLARIFY
       +-> ABORT/DEGRADE
```

不变量：

- 默认最大执行步数为 `4`，全局硬上限为 `8`；重试也计入步数；
- 单个步骤默认最多重试 `1` 次，除非能力明确只读或幂等；
- 达到最大步数、deadline 或取消信号后不得继续调用工具；
- Planner 不能直接调用 Provider；所有执行必须经过 Executor；
- 每次重试前重新校验权限、Scope、Server 状态和参数；
- `NON_IDEMPOTENT` 能力默认不自动重试；
- 相同 `capability_id + normalized arguments + run_id` 可生成 idempotency key；
- Observation 是不可信外部数据，不能成为系统指令。

### 6.3 Executor

Executor 依次执行：

1. 重新解析 CapabilityDefinition 和 Provider；
2. 校验 actor、conversation scope、群策略和最新限流状态；
3. 校验并规范化参数，拒绝额外字段；
4. 检查文件路径、URL、标识符和敏感参数策略；
5. 申请调用预算并生成 audit start；
6. 在步骤 timeout 和总 deadline 内调用 Provider；
7. 标准化异常和结果，生成 audit finish；
8. 将经过大小限制和敏感字段处理的 Observation 交给 Validator。

### 6.4 Observation 与 Validator

```python
@dataclass(frozen=True, slots=True)
class ToolObservation:
    step_id: str
    capability_id: str
    ok: bool
    data: JsonValue | None
    error: ToolError | None
    source_refs: tuple[SourceRef, ...]
    observed_at: datetime
    latency_ms: int
    cache_status: str | None
    sensitivity: PrivacyLevel
    truncated: bool

class ValidationAction(StrEnum):
    FINISH = "finish"
    CONTINUE = "continue"
    RETRY = "retry"
    CLARIFY = "clarify"
    ABORT = "abort"
    DEGRADE = "degrade"
```

Validator 必须检查 output schema、业务错误、来源、空结果、跨步骤一致性、事实完整度、敏感度和 completion criteria。它不能修改权限，也不能把 schema 不匹配结果当成功。重试建议必须包含可执行 reason code，例如 `transient_timeout`，不能只给自然语言。

## 7. MCP Registry

### 7.1 ServerDefinition

```python
@dataclass(frozen=True, slots=True)
class McpServerDefinition:
    schema_version: int
    server_id: str
    transport: Literal["stdio", "streamable_http"]
    endpoint: StdioEndpoint | HttpEndpoint
    secret_refs: tuple[SecretRef, ...]
    allowed_tools: frozenset[str]
    denied_tools: frozenset[str]
    connect_timeout_ms: int
    discovery_timeout_ms: int
    default_call_timeout_ms: int
    max_call_timeout_ms: int
    retry_policy: RetryPolicy
    circuit_breaker: CircuitBreakerPolicy
    max_concurrency: int
    enabled: bool

class McpServerRegistry(Protocol):
    def get(self, server_id: str) -> McpServerDefinition: ...
    def list_enabled(self) -> tuple[McpServerDefinition, ...]: ...
    def config_revision(self) -> str: ...
```

配置规则：

- 可提交配置只能包含 `SecretRef`，不得包含 Token、Cookie、API key 或真实账号；
- stdio command、工作目录和环境变量使用 allowlist，不接受消息或模型生成值；
- HTTP transport 必须限制 scheme、host、重定向和私网访问策略；
- `allowed_tools` 是发现后的第二道 allowlist；未声明工具默认不可用；
- 一个 MCP Tool 只有映射成 Capability 后才可进入 Planner；
- Registry 是 Server 连接配置的唯一来源，负责版本、连接信息和启用状态，不包含业务路由 Prompt；健康状态由 Unified Client 基于该配置维护。

### 7.2 发现与 Schema 缓存

Server 首次连接或配置版本变化时执行 Tool Discovery。缓存键至少包含 `(server_id, server_config_hash, server_version)`，缓存内容包含工具名、输入 schema、可用 output schema 和发现时间。

发现规则：

- 新增、删除或不兼容 Schema 变化默认使对应 Capability 不健康；
- 生产不因 Server 临时多返回一个工具就自动暴露；
- Schema 缓存有 TTL，但配置变更立即失效；
- 发现失败不得使用来源不明的旧缓存无限运行；可在明确 stale 上限内降级并告警。

## 8. Unified MCP Client

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

唯一生产 Client 在构造时注入 `McpServerRegistry`。Runtime、Planner、模型和 Capability 参数只能引用 `server_id`，不能旁路 Registry 提供 command、URL、环境变量或 SecretRef。

统一 Client 负责：

- 复用受控生命周期内的 MCP session，不为每次工具调用重复启动进程；
- transport 建连、初始化、发现、并发控制和关闭；
- 参数 schema 预校验和结果大小上限；
- 超时、取消、有限重试、熔断和健康状态；
- SDK 异常到 Domain Error 的标准化；
- 敏感参数脱敏、审计和统计；
- 将 MCP content/structuredContent 转换为稳定的 `McpToolResult`。

Client 不负责 Capability Retrieval、业务权限定义、自然语言规划或 Persona 渲染。

### 8.1 默认可靠性策略

建议默认值：

| 阶段 | 默认 | 硬上限/策略 |
| --- | ---: | --- |
| connect | 10 秒 | 30 秒 |
| initialize/discovery | 10 秒 | 30 秒 |
| 普通 tool call | 30 秒 | 每能力最高 120 秒 |
| 自动重试 | 1 次 | 仅只读、幂等或明确未送达 |
| 连续失败熔断 | 5 次/60 秒 | open 120 秒后 half-open 单探测 |
| 单 Server 并发 | 4 | 由 Server 定义收窄 |

超时、取消、协议错误、Schema 错误、权限拒绝和业务错误必须区分。超时后无法证明未执行的写操作不得自动重试。

## 9. 权限、隐私与审计

### 9.1 执行上下文

```python
@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    actor: Actor
    conversation_scope: ConversationScope
    granted_permissions: frozenset[str]
    policy_snapshot_id: str
    deadline: datetime
    trace_id: str
```

Provider 不接受裸管理员布尔值。`Actor` 是授权主体；`ActorRef` 仅可作为目标引用或脱敏审计投影，不能替代权限输入。权限由统一 PermissionPolicy 生成 snapshot，Executor 以该 snapshot 和最新撤销状态复核。

### 9.2 风险分层

- 公开缓存读取可以是低风险模型能力；
- 公开网络刷新至少是中风险，需要频率和权限控制；
- 私人数据、账号操作和外部写入至少是高风险，并要求明确授权；
- 任意文件写、shell、批量数据导出和凭据管理不得作为通用 Planner 能力；
- 群聊中的个人或敏感能力必须按策略拒绝、降级或引导私聊。

### 9.3 审计事件

每次调用至少记录：

```text
timestamp, trace_id, run_id, actor_ref_hash, conversation_scope_hash,
capability_id, provider_id, server_id, tool_name, permission_decision,
policy_snapshot_id, argument_shape, redacted_argument_hash,
result_status, error_code, latency_ms, retry_count, circuit_state
```

默认不记录完整消息、评论正文、Token、Cookie、文件内容和原始 MCP payload。审计存储和业务数据存储分离，并有 TTL 与访问控制。

## 10. 错误模型

| Domain Error | 来源 | 默认动作 |
| --- | --- | --- |
| `CapabilityNotFoundError` | Registry/Planner | 重新检索或澄清，不猜工具名 |
| `CapabilityDeniedError` | Policy | 不执行；返回边界或保持静默 |
| `CapabilitySchemaError` | Planner/Provider | 标记计划无效，有限重规划 |
| `McpServerUnavailableError` | Registry/Client | 熔断并选择显式替代能力 |
| `McpProtocolError` | Client | 不把原始协议错误直接给用户 |
| `ToolTimeoutError` | Client/Provider | 仅按幂等策略有限重试 |
| `ToolBusinessError` | Server | Validator 依据稳定 code 决定澄清或降级 |
| `ToolResultInvalidError` | Validator | 结果不可用于事实回答 |
| `ToolBudgetExceededError` | Runtime | 停止循环并基于可信结果降级 |

所有用户可见消息由 Response Composer 生成。MCP Server 的异常字符串和外部页面内容不能直接成为系统提示或最终回复。

## 11. iCourse 标准迁移

### 11.1 当前事实

当前 iCourse 同时被 AstrBot MCP 配置和 `ICourseClient` 直连。直连客户端每次调用启动一个新的 stdio Server，`timeout_hint` 未生效。Server 暴露缓存查询、联网抓取、robots 诊断和任意路径 JSONL 导出共十个工具；输出 envelope 不一致，批量抓取与导出不适合作为普通模型能力。

### 11.2 目标 Capability 映射

| Capability | MCP Tool/实现 | 风险 | Planner 可见性 |
| --- | --- | --- | --- |
| `icourse.search_courses.v1` | `search_courses` | low/public/read-only | 默认可见 |
| `icourse.get_course.v1` | `get_course(refresh=false)` | low/public/read-only | 默认可见 |
| `icourse.get_reviews.v1` | `get_reviews` | low，但正文不可信 | 默认可见，结果需净化 |
| `icourse.compare_courses.v1` | 新增受控组合能力 | low | 默认可见 |
| `icourse.refresh_course.v1` | `crawl_course` 或新原子工具 | medium/network/write-cache | trusted/admin，带冷却 |
| `icourse.bulk_refresh.v1` | `crawl_courses`、`crawl_latest_reviews` | high/批量网络 | 仅运维入口 |
| `icourse.export_dataset.v1` | `export_dataset` | high/file-write | 不进入 Planner |
| `icourse.check_robots.v1` | `check_robots` | admin/diagnostic | 不进入 Planner |

`export_dataset` 必须限制到配置好的私有 export root，拒绝绝对路径、`..`、符号链接逃逸和覆盖关键运行文件。迁移完成前，能力层不得映射该工具。

### 11.3 标准结果

iCourse Provider 将现有不一致结果转换为统一 envelope：

```python
@dataclass(frozen=True, slots=True)
class CapabilityResult:
    ok: bool
    data: JsonValue | None
    error: ToolError | None
    source_refs: tuple[SourceRef, ...]
    observed_at: datetime
    cache_status: Literal["hit", "miss", "refreshed", "unknown"]
    warnings: tuple[str, ...]
```

评课评论是第三方不可信文本，必须限制长度、标记来源、隔离 HTML，并防止其中内容被解释为指令。`public_only` 不等于无隐私风险或事实正确。

### 11.4 渐进步骤

1. 为当前 10 个工具建立 contract fixture 和错误基线，不改变 Server；
2. 创建 Unified MCP Client、Registry 和 iCourse Capability 映射；
3. 让旧 `ICourseClient` 成为标记为 compatibility 的包装层，内部转发统一 Client；
4. 将 `/course` 命令切到 Capability Provider，保持命令文本、权限和输出兼容；
5. 将模型可见工具收窄为查询能力，刷新走 trusted/admin Policy；
6. 在 Server 内引入统一错误和结果 schema，再新增 `compare_courses`、`refresh_course` 原子工具；
7. 验证 AstrBot 入口只使用统一 Client 后，删除重复 stdio 启动逻辑；
8. Phase 8 再用 `git mv` 将 `services/icourse-mcp` 移到 `services/mcp/icourse`，同步 Docker、Compose、CI 和配置路径。

任何一步失败都可以将调用入口切回旧 `ICourseClient`，SQLite 路径和 schema 在独立迁移前保持不变。

## 12. 测试与 Eval

### Unit

- Capability Schema、ID 唯一性和配置加载；
- 确定性 Policy 过滤与 Top-K 稳定排序；
- Planner 不得引用候选外 ID；
- 最大步数、重试计数、deadline 和幂等规则；
- Validator 对空结果、Schema 错误、提示注入和敏感数据的处理；
- MCP 错误标准化、参数脱敏和熔断状态机。

### Contract

- 每个 Capability 的 input/output schema；
- MCP Tool Discovery snapshot 与显式 allowlist；
- Provider 到 MCP Tool 的参数和结果映射；
- PermissionPolicy、AuditSink 和 SecretResolver 端口；
- iCourse 十个旧工具兼容契约及目标安全子集。

### Integration

- Capability Retrieval -> Planner -> Executor -> Validator 完整循环；
- 持久 stdio session 的启动、并发、超时、取消和关闭；
- Server 崩溃、协议损坏、慢调用、半开熔断和恢复；
- iCourse fixture HTTP -> parser -> SQLite -> MCP -> CapabilityResult；
- 无权限、群聊敏感场景和 export path 逃逸必须 fail closed。

### Eval 与 Smoke

- 课程查询意图的 Recall@K、参数抽取和错误工具选择；
- 不应调用工具的普通聊天不得产生调用；
- 权限不足时工具暴露率必须为零；
- Docker 构建、MCP 握手、Schema snapshot、`icourse_stats` 和只读查询；
- Trace、日志和测试 fixture 中不出现真实密钥、QQ ID、Cookie 或聊天数据。

## 13. 可观测性

至少暴露：

- capability retrieval 候选数、Recall@K Eval 和过滤 reason code；
- 每 Capability/Server 的调用量、成功率、P50/P95 延迟和错误分类；
- timeout、retry、budget exceeded 和 circuit open 次数；
- Schema 变化、发现缓存年龄和 Provider 健康状态；
- Planner 平均步数、最大步数终止率和 Validator 决策分布。

指标标签不得包含 user_id、group_id、query 原文或高基数字段。Trace 通过随机 `trace_id` 与受控审计关联。

## 14. 当前状态与扩展点

当前仍是 Phase 1 设计。尚未创建 Capability Registry、Unified MCP Client 或 Tool Runtime，也没有改变 iCourse 行为。

后续新增教务、第二课堂、校园通知、开课查询和培养方案 MCP 时，必须复用本契约。每个 Server 可以拥有自己的领域模型和存储，但不得复制新的上层 MCP Client、权限体系或无限工具循环。
