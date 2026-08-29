# 能力、工具运行时与 MCP 设计

## 1. 文档状态

- 阶段：S12 Unified Client/Registry、隔离 worker 和 iCourse compatibility facade，以及
  S13 Capability Runtime 均已完成本地实现与验证；S15C 只批准 source-neutral Contract、Fake
  Provider 和本地固定 fixture，不包含真实主动日报来源 Adapter。
- 目标代码：`packages/dududa-agent/src/dududa/capabilities/`。
- 当前真实 MCP Server：`icourse`、`ustc-young`、`ustc-academic`、`ustc-curriculum`、
  `ustc-shuttle`；后四者共享 `services/mcp/ustc-campus/` 实现包，但拥有独立 Registry
  身份和 Session。`ustc-curriculum` 只读取公开的非官方培养方案研究快照，不访问实时教务。
- 当前配置目录：`configs/capabilities/`、`configs/mcp/servers/`；旧路径只保留一 Release
  兼容链接。
- 兼容来源：`astrbot_plugin_dududa_core/course.py`、AstrBot 当前 MCP 配置和 iCourse service。

本文定义嘟嘟哒如何声明、检索、规划、执行和校验能力，以及如何通过统一 MCP Client 调用外部 MCP Server。S12/S13 已实现通用闭环；五个校园查询 Server 已接入超级管理员 Web Console，Dududa 2.0 Runtime 已闭环 iCourse、二课和培养方案研究的单步自然语言调用。教务开课/考试与校车的自然语言 Planner 仍未完成。本文不改变当前 `icourse` Server 名、SQLite 路径或作为兼容/诊断入口保留的 `/course` 命令。

接口权威以 `dududa/capabilities/contracts.py`、`dududa/ports/capabilities.py` 和严格 JSON
配置为准；本文代码块用于展示稳定公共形状和所有权，不替代构造校验、摘要函数或 Contract
Test。公共字段变化必须先更新这些权威类型及测试，再同步本文，不能长期维护第二套接口。

## 2. 目标与非目标

目标：

- 让 Planner 面向稳定的 Capability，而不是面对所有原始函数或 MCP Tool；
- 在模型看到工具前完成上下文、权限、隐私和风险过滤；
- 用显式、有限状态的 Planner/Executor/Validator 循环代替无限制 Agent 循环；
- 由一个 MCP Registry 和一个 Unified MCP Client 统一管理发现、连接、超时、重试、熔断和错误；
- 让内建能力和 MCP 能力使用相同的执行、审计和结果校验契约；
- 使 iCourse 成为首个标准 Capability Provider 和 MCP Server 样板；
- 为主动日报预留 source-neutral、公开只读、带来源与新鲜度的 Capability 边界，当前只用固定 fixture 证明；
- 允许 Bot Control Plane 的 `GroupServiceProfile` 请求业务服务，但仍由 Capability Registry、
  当前群授权、健康和 rollout 计算 Effective，Profile 本身不授予 Capability；
- 保留现有入口，在新链路验证完成前可按提交回滚。

非目标：

- 不让 MCP Server 解释完整自然语言请求或决定是否回复；
- 不允许 Persona、Prompt 或具体模型授予权限；
- 不把 AstrBot Event、MCP SDK 类型或具体 Server 实现放入 Domain；
- 不在本阶段训练 Tool Planner 模型；
- 不把批量抓取、文件导出和诊断工具默认暴露给模型。
- 不让 MCP 或 Capability Provider 创建订阅、决定发送时间/目标、生成发送授权或直接投递消息。
- 不让浏览器、Group Service Profile、Group Context、Plugin Descriptor 或模型把发现/期望服务
  直接升级为可调用 Capability。

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
    definition_digest: DigestString
    name: str
    description: str
    category: str
    provider: ProviderRef
    input_schema: SchemaRef
    output_schema: SchemaRef
    risk_level: RiskLevel
    privacy_level: PrivacyLevel
    allowed_contexts: frozenset[ConversationType]
    required_permissions: frozenset[str]
    cost_hint: CostHint
    latency_hint: LatencyHint
    tags: frozenset[str]
    idempotency: Idempotency
    side_effects: frozenset[SideEffect]
    enabled: bool = True
```

最低字段与约束：

- `capability_id` 使用稳定命名空间，例如 `icourse.courses.search.v1`；显示名变化不得改变 ID；
- `definition_digest` 是除 digest 字段本身外对规范化完整定义计算的内容哈希；
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
    schema_version: int
    query_digest: DigestString
    intent_ids: tuple[str, ...]
    natural_language_goal: str
    entity_terms: tuple[str, ...]
    required_output_schema: SchemaRef | None
    preferred_categories: tuple[str, ...]
    excluded_side_effects: frozenset[SideEffect]
    maximum_risk_level: RiskLevel
```

`natural_language_goal` 是不可信输入，不能被拼接到 shell、SQL、文件路径或 Server 配置。权限和允许的风险级别来自 Runtime Policy，不接受模型自行上调。

### 4.3 Candidate 和摘要

Planner 只能看到经过过滤的摘要：

```python
@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    schema_version: int
    capability_id: str
    definition_digest: DigestString
    name: str
    description: str
    category: str
    provider: ProviderRef
    input_schema: SchemaRef
    output_schema: SchemaRef
    risk_level: RiskLevel
    privacy_level: PrivacyLevel
    cost_hint: CostHint
    latency_hint: LatencyHint
    idempotency: Idempotency
    side_effects: frozenset[SideEffect]
    rank_score: int
    reason_codes: tuple[str, ...]
    candidate_digest: DigestString
```

摘要不得包含 MCP 启动命令、环境变量、Server 凭据、内部 hostname 或用户无权访问的字段。

## 5. Capability Registry 与 Top-K Retrieval

### 5.1 Registry 端口

```python
@dataclass(frozen=True, slots=True)
class CapabilityProviderDescriptor:
    schema_version: int
    provider_id: str
    revision: ComponentRevision
    capability_ids: frozenset[str]
    provider_kind: Literal["builtin", "mcp", "http", "workflow"]

@dataclass(frozen=True, slots=True)
class CapabilityEndpointHealth:
    capability_id: str
    definition_digest: DigestString
    status: Literal["healthy", "degraded", "unavailable"]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CapabilityProviderHealth:
    schema_version: int
    provider_id: str
    provider_revision: ComponentRevision
    status: Literal["healthy", "degraded", "unavailable"]
    capabilities: tuple[CapabilityEndpointHealth, ...]
    checked_at: datetime
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CapabilityHealthSnapshot:
    schema_version: int
    snapshot_revision: str
    providers: tuple[CapabilityProviderHealth, ...]
    observed_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    schema_version: int
    snapshot_id: str
    catalog_revision: str
    mapping_revision: str
    provider_registry_revision: str
    definitions: tuple[CapabilityDefinition, ...]
    mappings: tuple["McpCapabilityMapping", ...]
    provider_descriptors: tuple[CapabilityProviderDescriptor, ...]
    acquired_at: datetime

class CapabilityRegistry(Protocol):
    def acquire_snapshot(self) -> CapabilityCatalogSnapshot: ...
    def get(
        self, snapshot: CapabilityCatalogSnapshot, capability_id: str
    ) -> CapabilityDefinition: ...
    def list_enabled(
        self, snapshot: CapabilityCatalogSnapshot
    ) -> Sequence[CapabilityDefinition]: ...

class CapabilityProviderRegistry(Protocol):
    def resolve(
        self, provider_id: str, expected_revision: ComponentRevision
    ) -> CapabilityProvider: ...
    def snapshot_revision(self) -> str: ...

class CapabilityHealthRegistry(Protocol):
    async def snapshot(
        self,
        providers: tuple[CapabilityProviderDescriptor, ...],
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> CapabilityHealthSnapshot: ...

@dataclass(frozen=True, slots=True)
class CapabilityCatalogUpdate:
    schema_version: int
    expected_revision: str
    definitions: tuple[CapabilityDefinition, ...]
    mcp_mappings: tuple["McpCapabilityMapping", ...]
    provider_descriptors: tuple[CapabilityProviderDescriptor, ...]

class CapabilityCatalogPublisher(Protocol):
    async def publish(
        self,
        update: CapabilityCatalogUpdate,
        *,
        call: PortCallContext,
    ) -> str: ...

class CapabilityProvider(Protocol):
    @property
    def descriptor(self) -> CapabilityProviderDescriptor: ...

    async def health(
        self, *, call: PortCallContext | ServiceCallContext
    ) -> CapabilityProviderHealth: ...

    async def invoke(
        self,
        request: "ProviderInvocation",
        *,
        call: PortCallContext,
    ) -> "CapabilityResult": ...
```

Provider 对象只在 composition root 注册；配置热加载通过
`CapabilityCatalogPublisher` 一次校验并原子发布完整 immutable snapshot。一次 Retrieval
只能使用同一个 `CapabilityCatalogSnapshot` 和一个有时间界限的 health snapshot；Definition、
Mapping 和 Provider descriptor 不能分别读取“最新值”后拼成混合 revision。Executor 通过
Candidate 固定的 Provider revision 重解析实例，漂移时拒绝或重新检索。发布时校验唯一 ID、
Schema、Provider 存在性、风险字段、MCP mapping 和配置来源；失败保留 last-known-good
revision。动态发现的 MCP Tool 不能自动成为模型可见 Capability；必须有显式映射和策略。

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
- Contextual Bandit 只能在上述确定性过滤完成后重排仍合法、语义可替代的候选；正式契约见
  `online-learning.md`。它不能恢复被过滤能力、改变 K/风险或 live 探索高风险副作用，且动作
  前必须记录完整候选集与 propensity；第一阶段保持关闭或 shadow-only。

正式检索 Port 不向模型暴露被拒绝的定义：

```python
@dataclass(frozen=True, slots=True)
class CapabilityRetrievalRequest:
    schema_version: int
    request_digest: DigestString
    query: CapabilityQuery
    actor: Actor
    conversation_scope: ConversationScope
    data_classification: PrivacyLevel
    available_input_schemas: tuple[SchemaRef, ...]
    maximum_latency_ms: int
    limit: int

@dataclass(frozen=True, slots=True)
class CapabilityRetrievalResult:
    schema_version: int
    result_digest: DigestString
    request_digest: DigestString
    query_digest: DigestString
    candidates: tuple[CapabilityCandidate, ...]
    catalog_snapshot_id: str
    catalog_digest: DigestString
    policy_revision: str
    health_snapshot_id: str
    health_snapshot_digest: DigestString
    retriever_revision: ComponentRevision
    reason_codes: tuple[str, ...]

class CapabilityRetriever(Protocol):
    async def retrieve(
        self,
        request: CapabilityRetrievalRequest,
        *,
        call: PortCallContext,
    ) -> CapabilityRetrievalResult: ...
```

`limit` 必须在全局上限内。`CapabilityRetrievalResult` 只包含通过确定性过滤的候选；
禁止用空结果触发“放宽权限后重试”。相同输入、Registry/Mapping revision、Policy
revision 和健康快照必须产生稳定顺序。Candidate 的 definition digest 与 Provider revision 固定本次
计划看到的能力；Executor 若发现 Registry/Provider 已漂移，必须重新检索或显式拒绝，
不能静默执行另一份定义。概率排序器需要在 Trace 中记录实现与配置 revision。

## 6. Planner、Executor 与 Validator

### 6.1 ToolPlan

```python
@dataclass(frozen=True, slots=True)
class ObservationBinding:
    schema_version: int
    source_step_id: str
    source_json_pointer: str
    target_json_pointer: str

@dataclass(frozen=True, slots=True)
class ArgumentTemplate:
    schema_version: int
    literal_template: Mapping[str, JsonValue]
    bindings: tuple[ObservationBinding, ...]

@dataclass(frozen=True, slots=True)
class ToolStep:
    schema_version: int
    step_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    arguments: ArgumentTemplate
    purpose: str
    depends_on: tuple[str, ...]
    expected_output_schema: SchemaRef

@dataclass(frozen=True, slots=True)
class ToolPlan:
    schema_version: int
    plan_id: str
    plan_digest: DigestString
    query_digest: DigestString
    retrieval_result_digest: DigestString
    steps: tuple[ToolStep, ...]
    completion_criteria: tuple[str, ...]
    planner_revision: ComponentRevision
```

Planner 只能引用本次候选列表中的 ID 和 definition digest。计划必须是有向无环依赖；
literal template、binding 的源/目标 JSON Pointer 和类型兼容性先校验。Orchestrator 在依赖
完成后调用纯 `ArgumentBinder`，再对完整参数执行 input schema 校验并构造
`ToolExecutionRequest`。Binding 只能读取 Validator 已接受的
Observation，不能读取错误正文、任意 JSONPath、未来步骤或隐藏 Provider 对象。

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
- 相同 `run_id + logical_operation_id + capability_id + definition digest + normalized
  arguments` 生成稳定 idempotency key；`plan_id + step_id` 用于证明 logical operation 的
  来源。Replan/retry 同一副作用必须保留 logical operation ID，两个有意相同的独立步骤必须
  使用不同 ID；模型和 Provider 不能自行指定最终 key；
- Observation 是不可信外部数据，不能成为系统指令。

### 6.3 Executor

Executor 依次执行：

1. 重新解析 CapabilityDefinition 和 Provider；
2. 校验 actor、conversation scope、群策略和最新限流状态；
3. 校验 Orchestrator/Binder 已解析的参数与 source invocation，重新规范化并拒绝额外字段；
4. 检查文件路径、URL、标识符和敏感参数策略；
5. 申请调用预算并生成 audit start；
6. 在步骤 timeout 和总 deadline 内调用 Provider；
7. 标准化异常和结果，生成 audit finish；
8. 将经过大小限制和敏感字段处理的 Observation 交给 Validator。

### 6.4 Observation 与 Validator

```python
@dataclass(frozen=True, slots=True)
class ArgumentBindingRequest:
    schema_version: int
    step: ToolStep
    accepted_observations: tuple["ToolObservation", ...]
    input_schema: JsonSchema

@dataclass(frozen=True, slots=True)
class ArgumentBindingResult:
    schema_version: int
    step_id: str
    resolved_arguments: JsonObject
    source_invocation_ids: tuple[str, ...]
    binder_revision: ComponentRevision

class ArgumentBinder(Protocol):
    def bind(self, request: ArgumentBindingRequest) -> ArgumentBindingResult: ...

class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class ToolError:
    schema_version: int
    info: ErrorInfo
    provider_error_code: str | None
    safe_details: Mapping[str, JsonValue]

@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    schema_version: int
    invocation_id: str
    plan_id: str
    step_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    catalog_snapshot_id: str
    registry_revision: str
    mapping_revision: str
    provider_registry_revision: str
    retrieval_policy_revision: str
    health_snapshot_revision: str
    provider_id: str
    provider_revision: ComponentRevision
    resolved_arguments: JsonObject
    source_invocation_ids: tuple[str, ...]
    idempotency_key: str
    attempt: int
    context: ExecutionContext

@dataclass(frozen=True, slots=True)
class ProviderInvocation:
    schema_version: int
    invocation_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    provider_id: str
    provider_revision: ComponentRevision
    arguments: JsonObject
    idempotency_key: str
    attempt: int
    context: ExecutionContext
    authorization: AuthorizationDecision

@dataclass(frozen=True, slots=True)
class ToolObservation:
    schema_version: int
    invocation_id: str
    plan_id: str
    step_id: str
    logical_operation_id: str
    capability_id: str
    definition_digest: DigestString
    catalog_snapshot_id: str
    registry_revision: str
    mapping_revision: str
    provider_registry_revision: str
    provider_revision: ComponentRevision
    policy_revision: str
    idempotency_key: str
    attempt: int
    status: ToolExecutionStatus
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

@dataclass(frozen=True, slots=True)
class ToolPlanningRequest:
    schema_version: int
    query: CapabilityQuery
    retrieval: CapabilityRetrievalResult
    prior_observations: tuple[ToolObservation, ...]
    remaining_steps: int

@dataclass(frozen=True, slots=True)
class ToolValidationRequest:
    schema_version: int
    retrieval: CapabilityRetrievalResult
    plan: ToolPlan
    observations: tuple[ToolObservation, ...]

@dataclass(frozen=True, slots=True)
class ToolValidationResult:
    schema_version: int
    action: ValidationAction
    accepted_observations: tuple[ToolObservation, ...]
    retry_step_id: str | None
    clarification: str | None
    reason_codes: tuple[str, ...]
    validator_revision: ComponentRevision

class ToolPlanner(Protocol):
    async def plan(
        self,
        request: ToolPlanningRequest,
        *,
        call: PortCallContext,
    ) -> ToolPlan: ...

class ToolExecutor(Protocol):
    async def execute(
        self,
        request: ToolExecutionRequest,
        *,
        call: PortCallContext,
    ) -> ToolObservation: ...

class ToolResultValidator(Protocol):
    async def validate(
        self,
        request: ToolValidationRequest,
        *,
        call: PortCallContext,
    ) -> ToolValidationResult: ...
```

Validator 必须检查 output schema、业务错误、来源、空结果、跨步骤一致性、事实完整度、
敏感度和 completion criteria。它不能修改权限，也不能把 schema 不匹配结果当成功。
重试建议必须包含可执行 reason code，例如 `transient_timeout`，不能只给自然语言。
`UNKNOWN` 表示调用可能已产生外部副作用：只读或下游真正支持同一幂等键的幂等写才可
重试；非幂等写必须停止并进入人工查询/补偿流程，绝不能换一个 invocation ID 重放。

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

@dataclass(frozen=True, slots=True)
class McpCapabilityMapping:
    schema_version: int
    capability_id: str
    capability_definition_digest: DigestString
    server_id: str
    tool_name: str
    discovered_schema_digest: DigestString
    argument_mapping_revision: str
    result_mapping_revision: str
    enabled: bool

class McpCapabilityMappingRegistry(Protocol):
    def get(self, capability_id: str) -> McpCapabilityMapping: ...
    def snapshot_revision(self) -> str: ...

@dataclass(frozen=True, slots=True)
class McpRuntimeSnapshot:
    schema_version: int
    snapshot_id: str
    server_config_revision: str
    mapping_revision: str
    servers: tuple[McpServerDefinition, ...]
    mappings: tuple[McpCapabilityMapping, ...]
    acquired_at: datetime

class McpRuntimeRegistry(Protocol):
    def acquire_snapshot(self) -> McpRuntimeSnapshot: ...
    def get_server(
        self, snapshot: McpRuntimeSnapshot, server_id: str
    ) -> McpServerDefinition: ...
    def get_mapping(
        self, snapshot: McpRuntimeSnapshot, capability_id: str
    ) -> McpCapabilityMapping: ...
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
@dataclass(frozen=True, slots=True)
class McpToolDescriptor:
    schema_version: int
    server_id: str
    tool_name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema | None
    schema_digest: DigestString
    server_revision: str
    discovered_at: datetime

@dataclass(frozen=True, slots=True)
class McpHealth:
    schema_version: int
    server_id: str
    status: Literal["healthy", "degraded", "unavailable"]
    snapshot_revision: str
    checked_at: datetime
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class McpToolCallRequest:
    schema_version: int
    invocation_id: str
    server_id: str
    server_config_revision: str
    tool_name: str
    discovered_schema_digest: DigestString
    arguments: JsonObject
    idempotency_key: str
    attempt: int
    context: ExecutionContext
    authorization: AuthorizationDecision

@dataclass(frozen=True, slots=True)
class McpToolResult:
    schema_version: int
    invocation_id: str
    status: ToolExecutionStatus
    data: JsonValue | None
    error: ToolError | None
    server_revision: str
    tool_schema_digest: DigestString
    idempotency_key: str
    attempt: int

class UnifiedMcpClient(Protocol):
    async def discover(
        self,
        server_id: str,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> tuple[McpToolDescriptor, ...]: ...

    async def call_tool(
        self,
        request: McpToolCallRequest,
        *,
        call: PortCallContext,
    ) -> McpToolResult: ...

    async def health(
        self,
        server_id: str,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> McpHealth: ...
    async def close(self) -> None: ...
```

唯一生产 Client 在构造时注入 `McpRuntimeRegistry`；一次 discovery/call/health 使用同一个
`McpRuntimeSnapshot`，不能分别读取 Server 与 Mapping 的最新值。Runtime、Planner、
模型和 Capability 参数只能引用已经固定 revision/digest 的逻辑 ID，不能旁路 Registry
提供 command、URL、环境变量或 SecretRef。发现结果只有经过显式 mapping、Schema digest
匹配和原子 Registry snapshot 发布后才可能成为 Capability。

统一 Client 负责：

- 复用受控生命周期内的 MCP session，不为每次工具调用重复启动进程；
- transport 建连、初始化、发现、并发控制和关闭；
- 参数 schema 预校验和结果大小上限；
- 超时、取消、有限重试、熔断和健康状态；
- SDK 异常到 Domain Error 的标准化；
- 敏感参数脱敏、审计和统计；
- 将 MCP content/structuredContent 转换为稳定的 `McpToolResult`。

Client 不负责 Capability Retrieval、业务权限定义、自然语言规划或 Persona 渲染。

### 8.1 后台来源调用（S15C 预留）

定时日报是 `proactive-messaging.md` 拥有的 initiated-run。Scheduler 只产生
`ScheduleOccurrence`；它不能直接调用 Tool。Proactive Orchestrator 在订阅和主动读取授权仍有效
时构造**固定只读 Capability Plan**，通过与入站 Runtime 相同的 Executor、Provider 和 Unified
MCP Client 执行。

后台 `ServiceCallContext` 只标识 Worker，不替代创建订阅的 Actor/管理员授权证据。每次调用仍
绑定 exact target Scope、subscription/occurrence digest、Capability definition revision、总
deadline、预算和审计。动态发现的 Tool、任意 URL、私人校园数据、外部写和 `message_send` 不得
进入该 Plan。

下表只是未来 Adapter 的候选映射，不表示对应 MCP Server、Capability 或实时来源已经存在：

| Capability | 允许输入 | 标准输出 | 风险 |
| --- | --- | --- | --- |
| `campus.list_public_notices.v1` | 预审单位、时间窗、数量上限 | 官方通知 SourceItem | public/network-read |
| `research.list_recent_arxiv.v1` | 预审分类/关键词、时间窗、数量上限 | arXiv SourceItem | public/network-read |
| `industry.list_allowlisted_updates.v1` | 预审 Feed/source ID、时间窗、数量上限 | 行业 SourceItem | public/network-read |

标准结果必须包含 source/external ID、规范 URL、published/observed time、source revision、内容
digest、引用和 warning。Provider 对来源 host/redirect/大小/新鲜度执行硬限制；外部摘要仍为不
可信 Observation。无 ID 时的 URL/digest 去重、订阅条目账本、日报排序和是否发送由 Proactive
模块负责，不放入 Unified Client。

### 8.2 默认可靠性策略

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
    actor: Actor
    conversation_scope: ConversationScope
```

Provider 不接受裸管理员布尔值。`ToolExecutionRequest.context` 只携带 Actor 与 Scope；
Executor 重新授权成功后才构造绑定完整 `AuthorizationDecision` 的 Provider/MCP request。
`Actor` 是授权主体；`ActorRef` 仅可作为目标引用或脱敏
审计投影，不能替代权限输入。统一 `AuthorizationPolicy` 生成带 policy revision、action、
resource、Scope 和有效期的 decision；Executor 在每次实际调用前重新授权。若它与
`PortCallContext.policy_snapshot_id` 指向的初始策略不再兼容，则拒绝或重新检索，不能取
两者中更宽松的一份。run ID、deadline、cancellation 和 trace 从同一次调用的
`PortCallContext` 获取，不在多个 DTO 中复制。

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
| `ToolOutcomeUnknownError` | timeout/cancel/断连后无法确认副作用 | 不自动重放非幂等写；查询、补偿或人工处理 |
| `ToolBusinessError` | Server | Validator 依据稳定 code 决定澄清或降级 |
| `ToolResultInvalidError` | Validator | 结果不可用于事实回答 |
| `ToolBudgetExceededError` | Runtime | 停止循环并基于可信结果降级 |

所有用户可见消息由 Response Composer 生成。MCP Server 的异常字符串和外部页面内容不能直接成为系统提示或最终回复。
每个 `ToolError` 都包装 Runtime 定义的 `ErrorInfo(code, category, retryable,
outcome_unknown, public_message_key, reason_codes)`；Adapter 私有错误码只能作为受控辅助字段，
不能决定重试或直接显示给用户。

## 11. iCourse 标准迁移

### 11.1 当前事实

当前 iCourse 保留 AstrBot MCP 配置和 Unified-backed `ICourseClient` facade。正常入口复用
统一 Client 的长生命周期 Session；S22 已删除插件内逐调用 stdio Client 和运行时 legacy
选择。Unified 基础设施缺失时使用 fail-closed unavailable facade，回滚恢复精确上一 Release。
Server 仍包含缓存查询、联网抓取、robots 诊断和 JSONL 导出等管理工具，但 S13 Catalog 只映射
批准的公开缓存只读查询。

### 11.2 正式 Capability 映射

| Capability | MCP Tool/实现 | 风险 | Planner 可见性 |
| --- | --- | --- | --- |
| `icourse.stats.read.v1` | `icourse_stats` | low/public/read-only | 授权后可见 |
| `icourse.courses.search.v1` | `search_courses` | low/public/read-only | 授权后可见 |
| `icourse.course.get.v1` | `get_course(refresh=false)` | low/public/read-only | 授权后可见 |
| `icourse.reviews.get.v1` | `get_reviews` | low，但正文不可信 | 授权后可见，结果需净化 |

`search_site_courses`、crawl/refresh、robots、bulk 和 export 等管理工具不在模型 Capability
Catalog 中。未来即使实现运维入口，`export_dataset` 也必须限制到配置好的私有 export root，
拒绝绝对路径、`..`、符号链接逃逸和覆盖关键运行文件。

### 11.3 标准结果

iCourse Provider 将现有不一致结果转换为统一 envelope：

```python
@dataclass(frozen=True, slots=True)
class CapabilityResult:
    schema_version: int
    result_digest: DigestString
    provider_invocation_digest: DigestString
    invocation_id: str
    capability_id: str
    definition_digest: DigestString
    provider: ProviderRef
    status: ToolExecutionStatus
    data: JsonValue | None
    error: ToolError | None
    source_refs: tuple[str, ...]
    sensitivity: PrivacyLevel
    usage: ResourceUsage
    observed_at: datetime
    truncated: bool
    untrusted: bool = True
```

评课评论是第三方不可信文本，必须限制长度、标记来源、隔离 HTML，并防止其中内容被解释为指令。`public_only` 不等于无隐私风险或事实正确。

### 11.4 渐进步骤

1. 已为现有工具建立 transport contract fixture 和错误基线，不改变 Server；
2. 已创建 Unified MCP Client、Registry 和 iCourse compatibility facade；
3. 已将 `ICourseClient` 组合转发统一 Client；S22 已删除显式 Legacy Client；
4. 已通过通用 MCP Provider 映射四个公开缓存只读 Capability；
5. `/course` 兼容命令继续使用 facade，crawl/refresh 管理路径不冒充模型 Capability；
6. 新原子能力或统一 Server envelope 需要独立 Spec，不能由 discovery 自动发布；
7. S22 已在消费者迁移和上一 Release 恢复证据齐全后删除插件直连 Legacy；
8. S17 已用 `git mv` 将 iCourse 移到 `services/mcp/icourse`，并同步 Docker、Compose、CI 和
   配置路径；S22 已删除旧主机路径别名。

当前 Release 不做跨 transport fallback。若统一路径不满足门禁，恢复精确 S19 Release；SQLite
路径和 schema 在独立迁移前保持不变。隔离 worker 的 `protocol_mode=legacy` 仅表示连接当前
iCourse MCP v1 Server，不是第二套插件 Client。

## 12. 测试与 Eval

### Unit

- Capability Schema、ID 唯一性和配置加载；
- 确定性 Policy 过滤与 Top-K 稳定排序；
- Planner 不得引用候选外 ID；
- Registry/Provider/Schema revision 漂移必须触发重新检索或拒绝；
- 最大步数、重试计数、deadline，以及 logical operation 区分“重试同一副作用”和“有意重复步骤”的幂等规则；
- timeout/cancel 后 `UNKNOWN` 的只读、幂等写和非幂等写分支；
- Validator 对空结果、Schema 错误、提示注入和敏感数据的处理；
- MCP 错误标准化、参数脱敏和熔断状态机。

### Contract

- 每个 Capability 的 input/output schema；
- MCP Tool Discovery snapshot 与显式 allowlist；
- MCP Tool 到 Capability mapping 的 Schema digest、原子 snapshot 与 last-known-good；
- Provider 到 MCP Tool 的参数和结果映射；
- Capability Provider descriptor/health、Catalog/Mapping/Provider 原子 snapshot 与精确 revision resolve；
- AuthorizationPolicy、AuditSink 和 SecretResolver 端口；
- `CapabilityRetriever`、`ToolPlanner`、`ArgumentBinder`、`ToolExecutor`、
  `ToolResultValidator` 和 `UnifiedMcpClient` 使用同一 Fake/真实实现 Contract Test；
- iCourse 十个旧工具兼容契约及目标安全子集。

### Integration

- Capability Retrieval -> Planner -> Executor -> Validator 完整循环；
- 持久 stdio session 的启动、并发、超时、取消和关闭；
- 重复 invocation/idempotency key、晚到结果和非幂等写断连不重复执行；
- Server 崩溃、协议损坏、慢调用、半开熔断和恢复；
- iCourse fixture HTTP -> parser -> SQLite -> MCP -> CapabilityResult；
- 无权限、群聊敏感场景和 export path 逃逸必须 fail closed。

### Eval 与 Smoke

- 课程查询意图的 Recall@K、参数抽取和错误工具选择；
- 不应调用工具的普通聊天不得产生调用；
- 权限不足时工具暴露率必须为零；
- 固定数据集记录 Registry、Policy、Retriever、Planner、Validator、Model 和 Schema
  revision，分别报告 Recall@K、错误暴露率、Plan/参数合法率、完成率、平均步数、
  P50/P95 和成本；
- 若启用 Bandit shadow，记录 action set、behavior/candidate propensity，只报告候选覆盖、
  策略一致率、日志完整率和延迟；IPS/SNIPS/DR、有效样本量、最大 importance weight 与
  paired effect 只对历史受控探索或安全 canary 产生的、有 propensity/support 的日志报告；
- 数据按意图、风险、权限、会话类型和错误注入分层，报告样本量/分母、固定 seeds、
  repeated-run variance、paired bootstrap 95% 置信区间和预先冻结的最小效果量；
- 未授权暴露/调用、确认绑定失败、非幂等重复写和预算越界分别报告观测违规数、分母与
  单侧置信上界，任何一次观测违规都阻断 canary；
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

当前已有 iCourse、二课、教务、培养方案研究和校车五个独立 Registry Server、严格 JSON Registry、统一
Client 与隔离 v2 worker；`ICourseClient` 只作为借用共享 Client 的兼容 facade。S13 通用
Catalog/Retrieval/Planner/Executor/Observation Validator 已实现，16 个映射可由 Web 超级管理员
按 Schema 直调。2.0 Agent 已自动规划 iCourse 五种、二课四种和培养方案研究八种高层操作；
Discovery 仍不授予能力。教务/校车 Planner、可信失败用户答复和实时资讯 Source 尚未实现。

后续新增校园通知或其他 MCP 时，必须复用本契约。每个 Server 可以拥有自己的领域模型和
存储，但不得复制新的上层 MCP Client、权限体系或无限工具循环。
