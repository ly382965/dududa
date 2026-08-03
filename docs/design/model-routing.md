# 模型路由设计

## 1. 文档状态与目标

- 阶段：S08 selection-contracts 已集成；Registry、Estimator、Admission、Static Router、
  Recording Fake、严格 Codec 和保守 AstrBot Adapter 已在 `static-router` 分支实现，
  当前状态为完成分支验收与集成前的验证阶段。
- 目标代码：`packages/dududa-agent/src/dududa/models/`。
- 配置目标：`configs/models/` 下可提交的无凭据路由策略；真实 Provider 凭据继续只存在于 AstrBot 私有运行配置。

Model Router 按“任务角色”选择模型；Tool Router 按“外部能力”选择工具。二者必须分离：模型可以规划工具，但 Model Router 不注册或执行 MCP Tool，Tool Router 也不能决定调用哪个模型供应商。

## 2. 当前问题

现有三个自研插件有三套模型接入方式：

- 课程关键词抽取和评论总结调用 AstrBot 当前会话 Provider；
- TargetTalk 可按 `provider_id` 选择 AstrBot Provider，否则使用当前会话 Provider；
- 图片生成直接读取 AstrBot `cmd_config.json` 中 OpenAI Source 的 key，并用 `httpx` 调兼容接口。

此外，`/admin model route` 包含部分硬编码展示，`default_model_id`、用户 style 和群模式没有形成真正的路由输入。目标设计将这些调用统一到角色化端口，同时不复制或提交任何凭据。

## 3. 依赖与信任边界

```text
Message / Context
      |
      v
PERCEPTION bootstrap route (fixed HAIKU)
      |
      v
validated TaskComplexityAssessment
      |
      v
Runtime projection -> TierSelectionContext
      |
      v
DeterministicTierPolicy -> TierDecision
      |
      v
StaticModelRouter
  + immutable ModelRoutingSnapshot
  + bounded ModelOperationalSnapshot
  + deadline / privacy / budget / atomic admission
      |
      v
ModelProvider Protocol
      ^
      |
AstrBotModelProviderAdapter / future adapters
```

- Domain 和 Runtime 只依赖 `ModelRouter` Protocol 和结构化请求/响应；
- Provider Adapter 位于应用适配层或基础设施层，可以依赖 AstrBot API 或供应商 SDK；
- 未来的 `CredentialResolver` 只允许位于基础设施边界；当前 S08 Core 和 AstrBot Adapter
  都不解析、复制或保存凭据；
- 路由配置描述角色、能力、优先级和限制，不包含 key、Cookie、Token 或私有 API Header。
- S08-S11 不包含 Bandit、随机权重或基于动态成本/延迟的重新排序；相同输入与
  snapshot 必须产生相同决策。

## 4. 模型角色

```python
class ModelRole(StrEnum):
    PERCEPTION = "perception"
    SOCIAL_DECISION = "social_decision"
    TOOL_PLANNING = "tool_planning"
    DIRECT_CHAT = "direct_chat"
    RESPONSE_COMPOSITION = "response_composition"
    PERSONA_RENDERING = "persona_rendering"
    MEMORY_SUMMARY = "memory_summary"
    IMAGE_UNDERSTANDING = "image_understanding"
    IMAGE_GENERATION = "image_generation"
```

| 角色 | 主要职责 | 典型输出 |
| --- | --- | --- |
| `PERCEPTION` | 意图、实体、指代和工具需求识别 | 严格 `PerceptionResult` |
| `SOCIAL_DECISION` | 仅提供软决策候选，硬策略仍由代码执行 | 候选动作、置信度、reason codes |
| `TOOL_PLANNING` | 在 Top-K Capability 中生成有限步骤计划 | 严格 `ToolPlan` |
| `DIRECT_CHAT` | 不需要工具的直接内容草稿 | S08 可为文本；S10 投影为版本化 Draft Content |
| `RESPONSE_COMPOSITION` | 合并工具结果、来源、错误和不确定性 | `DraftResponse` |
| `PERSONA_RENDERING` | 在锁定事实与安全约束后改变表达 | 严格 `FinalResponse` |
| `MEMORY_SUMMARY` | 在已限定 Scope 内压缩记忆候选 | 结构化摘要，不负责写入 |
| `IMAGE_UNDERSTANDING` | 对受控图片引用生成描述或结构化观察 | `AttachmentSummary` |
| `IMAGE_GENERATION` | 根据已通过策略的描述生成图片 | `GeneratedAsset` |

同一个实际模型可以承担多个角色，但角色配置、超时、温度、输出 Schema 和隐私策略相互独立。

### 4.1 档位与思考深度

`ModelRole`、`ModelTier` 和 `ReasoningProfile` 是三个正交维度：

```python
class ModelTier(StrEnum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"

class ReasoningDepth(StrEnum):
    OFF = "off"
    LIGHT = "light"
    BALANCED = "balanced"
    DEEP = "deep"
    MAXIMUM = "maximum"
```

- Role 描述本次调用负责什么；
- Tier 是运营方配置的能力/成本档，不从模型名称推断；
- Reasoning Profile 描述本次调用需要的思考行为，由 Adapter 显式映射到供应商参数。

同一 Tier 可以包含多个 Provider Endpoint，同一实际模型也可以提供多个 Reasoning
Profile。枚举顺序不代表 fallback 顺序；跨档回退只能沿配置中的显式无环边执行。

`PERCEPTION` 的启动路由固定为允许的 Haiku Endpoint，避免“需要先判断难度才能选择
感知模型、又需要先选择模型才能判断难度”的递归。普通 `DIRECT_CHAT` 默认 Sonnet；
Opus 不接受隐式升级流量。

### 4.2 难度判断边界

难度判断属于 S09 Perception/Tiering，不属于静态 Router：

1. Rule Perception 提取 mention、回复、命令、文本形态等确定性事实；
2. 固定 Haiku 的 Model Perception 只提供严格 Schema 的语义候选；
3. Merger 与 Validator 生成可信证据；
4. Complexity Assessor 输出 `TaskComplexityAssessment`；
5. Runtime 加入角色、隐私、预算和 token 上界，投影为 `TierSelectionContext`；
6. `DeterministicTierPolicy` 输出 `TierDecision`；
7. Static Router 只在所选 Tier 和显式 fallback DAG 内选择 Endpoint。

Assessment 只能包含 level、confidence、task kind、context pressure、reasoning depth、
预计工具步数、歧义、验证需求、冲突标记、reason codes、evidence refs 和 assessor
revision，不能包含 Tier、Provider 或 model ID。用户消息中的“使用 Opus”只是非可信文本，
不能进入 RouteHint。

初始 TierPolicy 采用保守规则：清晰低复杂度证据才使用 Haiku；低置信度、规则/模型冲突
和普通聊天默认 Sonnet；Opus 必须同时满足多个高复杂度证据、最低置信度、角色 allowlist
和预算。长上下文只产生容量压力，不能单独证明语义困难。

每个允许 Tier 都有版本化 `TierBudgetRequirement`，声明最少剩余 input token、总生成
token（已包含 reasoning）和 cost units。`TierDecision` 同时记录 `uncapped_tier` 与
`selected_tier`；只有 `BUDGET_CAPPED` 可以令二者不同，因此离线 Eval 能区分“本来就是
Sonnet”与“Opus 因预算降为 Sonnet”。Tier policy digest 和不含随机 ID/时间的 selection
fingerprint 与完整执行 receipt digest 分开保存。

## 5. 数据契约

### 5.1 能力声明

```python
class StructuredOutputSupport(StrEnum):
    NONE = "none"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"

@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    schema_version: int
    input_modalities: frozenset[ModelInputModality]
    output_modalities: frozenset[ModelOutputModality]
    native_structured_output: StructuredOutputSupport
    max_context_tokens: int
    max_input_tokens: int | None
    max_output_tokens: int
    supports_temperature: bool
    supports_streaming: bool
    supports_seed: bool

@dataclass(frozen=True, slots=True)
class ReasoningProfile:
    schema_version: int
    profile_id: str
    depth: ReasoningDepth
    max_reasoning_tokens: int | None
    required: bool
```

Provider Adapter 在启动时提供逐 Endpoint 能力快照；路由不能根据模型名称猜测能力。
`native_structured_output` 只声明供应商 API 的原生能力，区分无原生支持、JSON object 和
严格 JSON Schema；它不等同于“Core 是否必须校验 Schema”。AstrBot Endpoint 即使声明
`NONE`，仍可通过受限 JSON Prompt 生成候选，再由 Core Codec 按 `SchemaRef` 整体校验。
`max_input_tokens` 表达供应商独立输入上限；调用前还必须同时验证
`input_upper_bound + requested_output <= max_context_tokens`。必需 Reasoning Profile 无法
映射时，catalog 发布失败，Adapter 不得静默忽略。

每个 Endpoint 还绑定不可变 `EndpointTrafficPolicy`，声明并发、RPM、TPM、队列、P95、
429/error rate、观测窗口、最小样本、cooldown 和 snapshot 最大年龄。可变观测保存在独立
`EndpointLoadSnapshot`，不进入 descriptor digest。

### 5.2 ModelRequest

```python
@dataclass(frozen=True, slots=True)
class ModelInputPart:
    schema_version: int
    part_id: str
    modality: ModelInputModality
    text: str | None
    content_ref: str | None
    content_digest: DigestString | None
    media_type: str | None

@dataclass(frozen=True, slots=True)
class ModelPrivacyPolicy:
    schema_version: int
    data_classification: PrivacyLevel
    allow_external_provider: bool
    allowed_residencies: frozenset[str]
    allow_provider_retention: bool

@dataclass(frozen=True, slots=True)
class RouteHint:
    schema_version: int
    provider_id: str | None
    endpoint_id: str | None
    model_id: str | None

@dataclass(frozen=True, slots=True)
class ModelInput:
    schema_version: int
    parts: tuple[ModelInputPart, ...]
    source_refs: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ModelRequest:
    schema_version: int
    request_id: str
    role: ModelRole
    input: ModelInput
    output_schema: SchemaRef | None
    max_output_tokens: int
    content_input_tokens_upper_bound: int
    temperature: float | None
    privacy: ModelPrivacyPolicy
    reasoning_profile_id: str
    random_seed: int | None
    idempotency_key: str | None
    route_hint: RouteHint | None
```

`ModelInput` 只能包含该角色需要的数据。`SchemaRef` 使用稳定 Schema ID、版本和 digest，不能把 Python class 或供应商专属 Schema 对象传到进程外。Provider Adapter 负责将输入和 Schema 转换为供应商消息格式；Core 不构造 OpenAI 专属 payload。

`content_input_tokens_upper_bound` 只描述进入路由前可知的内容上界，供 TierPolicy 做早期预算
门禁；它不是最终 Provider token 估算。调用前必须由 `ModelInvocationEstimator` 在具体
Endpoint 上加入 system/template、Schema 和 Provider wrapping，且最终 input estimate 不得
小于该内容上界。

`ModelInputPart` 按 modality 严格执行 one-of：文本只能有受限 `text`；附件引用只能是
opaque `content_ref + content_digest + media_type`。S08-S11 的首个 Runtime 只接受纯文本；
未来启用附件角色时，Adapter 必须在本地凭目的为 `MODEL_INPUT` 的
`AttachmentAccessRequest` 从 Attachment Repository 取得有界 stream，不能把本地路径、
任意 URL、base64、Event、授权对象或 Provider 对象放入请求。
`RESTRICTED` 数据在构造 ModelRequest 前已经被拒绝。
有效数据等级只有 `ModelPrivacyPolicy.data_classification` 一处；禁止在 Input 中保存第二份
可能不一致的分类。

`RouteHint` 只能表达允许的偏好，例如兼容 TargetTalk 的旧 `provider_id`；它没有 Tier
字段，也不能绕过角色 allowlist、隐私、能力、预算、健康或流量准入。

### 5.3 ModelResponse

```python
@dataclass(frozen=True, slots=True)
class ModelResponse:
    schema_version: int
    request_id: str
    role: ModelRole
    output_schema_digest: DigestString | None
    output: JsonValue
    finish_reason: str
    usage: ModelUsage | None
    latency_ms: int
    route_decision: RouteDecision
    safety_annotations: tuple[SafetyAnnotation, ...]
    processing: ModelProcessingReceipt
```

```python
@dataclass(frozen=True, slots=True)
class ModelUsage:
    schema_version: int
    input_tokens: int
    generated_tokens: int
    reasoning_tokens: int | None
    cached_input_tokens: int | None
    cost_units: Decimal | None

@dataclass(frozen=True, slots=True)
class ModelInvocationEstimate:
    schema_version: int
    model_request_digest: DigestString
    endpoint_descriptor_digest: DigestString
    reasoning_profile_id: str
    input_tokens_upper_bound: int
    generated_tokens_upper_bound: int
    reasoning_tokens_upper_bound: int
    total_context_tokens_upper_bound: int
    cost_units_upper_bound: Decimal | None
    estimator_revision: ComponentRevision

@dataclass(frozen=True, slots=True)
class RouteAttempt:
    schema_version: int
    attempt: int
    kind: RouteAttemptKind
    provider_id: str
    endpoint_id: str
    model_id: str
    tier: ModelTier
    invocation_estimate_digest: DigestString
    admission_reservation_id: str
    provider_request_digest: DigestString
    prompt_template_revision: ComponentRevision
    started_at: datetime
    latency_ms: int
    failure_kind: ModelFailureKind | None
    error: ErrorInfo | None

@dataclass(frozen=True, slots=True)
class SafetyAnnotation:
    schema_version: int
    code: str
    severity: str
    blocked: bool

@dataclass(frozen=True, slots=True)
class RouteDecision:
    schema_version: int
    decision_id: str
    request_id: str
    model_request_digest: DigestString
    model_request_fingerprint: DigestString
    role: ModelRole
    requested_tier: ModelTier
    selected_tier: ModelTier | None
    tier_authority_digest: DigestString
    tier_selection_fingerprint: DigestString
    routing_snapshot_id: str
    catalog_revision: str
    route_policy_revision: str
    operational_snapshot_id: str
    operational_snapshot_digest: DigestString
    output_schema_digest: DigestString | None
    output_codec_revision: ComponentRevision | None
    route_plan_fingerprint: DigestString
    candidate_plans: tuple[EndpointRouteCandidatePlan, ...]
    eligible_endpoints: tuple[ModelEndpointRef, ...]
    rejected_endpoints: tuple[EndpointRejection, ...]
    planned_endpoint: ModelEndpointRef | None
    selected_endpoint: ModelEndpointRef | None
    reasoning_profile: ReasoningProfile
    admission_results: tuple[EndpointAdmissionResult, ...]
    capacity_receipts: tuple[EndpointCapacityReceipt, ...]
    attempts: tuple[RouteAttempt, ...]
    terminal_failure_kind: ModelFailureKind | None
    terminal_error: ErrorInfo | None
    decided_at: datetime
```

结构化角色必须先通过 Schema Validator 才能构造成功响应。供应商自由文本、异常对象和原始 HTTP Response 不得穿透到 Runtime。

Assessment/Tier digest、catalog/route/load revision、Endpoint descriptor digest、Provider
revision、reasoning profile、Schema digest、公开采样参数、usage 和 latency 构成离线 Eval
的最小复现实验元数据。每个 attempt 必须绑定 eligible Endpoint 且序号连续，成功响应的
最终 attempt、selected Endpoint 和 processing receipt 必须一致。Trace 不记录 Credential、原始 Prompt、
隐藏推理或默认完整输出；同一固定请求集至少分别报告 Schema-valid rate、任务指标、
P50/P95、fallback 率和成本，不能只比较主观文案质量。

`ModelInvocationEstimator` 必须读取完整 `ModelRequest`、Endpoint 和 ReasoningProfile；输入
上界包含 system/template、用户内容、Schema 与 Provider wrapping，不能只估算用户文本。
`generated_tokens` 是供应商计入 Context/账单的全部生成 token，已经包含 reasoning；
`reasoning_tokens` 是其中可选的可观测子集，绝不能再次相加。Context 与 Runtime 的
`output_tokens_remaining` 都扣减 `generated_tokens`。估算同样要求
`reasoning_tokens_upper_bound <= generated_tokens_upper_bound`，未知 cost 不能当作零。

### 5.4 Provider 与 Route DTO

```python
class ModelProcessingBoundary(StrEnum):
    LOCAL = "local"
    EXTERNAL = "external"

class ModelRetentionMode(StrEnum):
    NO_RETENTION = "no_retention"
    PROVIDER_MANAGED = "provider_managed"

@dataclass(frozen=True, slots=True)
class ModelEndpointDescriptor:
    schema_version: int
    endpoint_id: str
    model_id: str
    descriptor_digest: DigestString
    tier: ModelTier
    capabilities: ModelCapabilities
    reasoning_profiles: tuple[ReasoningProfile, ...]
    default_reasoning_profile_id: str
    allowed_data_classes: frozenset[PrivacyLevel]
    processing_boundary: ModelProcessingBoundary
    available_data_residencies: frozenset[str]
    supported_retention_modes: frozenset[ModelRetentionMode]
    quota_pool_id: str
    traffic_policy: EndpointTrafficPolicy
    enabled: bool

@dataclass(frozen=True, slots=True)
class ModelProviderDescriptor:
    schema_version: int
    provider_id: str
    revision: ComponentRevision
    endpoints: tuple[ModelEndpointDescriptor, ...]

@dataclass(frozen=True, slots=True)
class ModelProcessingReceipt:
    schema_version: int
    provider_id: str
    provider_revision: ComponentRevision
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    model_id: str
    provider_request_digest: DigestString
    processing_boundary: ModelProcessingBoundary
    data_residency: str
    retention_mode: ModelRetentionMode
    requested_reasoning_profile_id: str
    effective_reasoning_profile_id: str
    requested_seed: int | None
    effective_seed: int | None

@dataclass(frozen=True, slots=True)
class ProviderRequest:
    schema_version: int
    request_id: str
    provider_id: str
    provider_revision: ComponentRevision
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    model_id: str
    selected_tier: ModelTier
    tier_authority_digest: DigestString
    invocation_estimate_digest: DigestString
    route_policy_revision: str
    attempt: int
    attempt_kind: RouteAttemptKind
    prompt_template_revision: ComponentRevision
    selected_data_residency: str
    required_retention_mode: ModelRetentionMode
    role: ModelRole
    input: ModelInput
    output_schema: SchemaRef | None
    max_output_tokens: int
    temperature: float | None
    privacy: ModelPrivacyPolicy
    reasoning_profile: ReasoningProfile
    random_seed: int | None
    idempotency_key: str | None

@dataclass(frozen=True, slots=True)
class ProviderResponse:
    schema_version: int
    request_id: str
    provider_id: str
    endpoint_id: str
    model_id: str
    provider_revision: ComponentRevision
    output: JsonValue
    finish_reason: str
    usage: ModelUsage | None
    safety_annotations: tuple[SafetyAnnotation, ...]
    processing: ModelProcessingReceipt

@dataclass(frozen=True, slots=True)
class ModelEndpointHealth:
    schema_version: int
    endpoint_id: str
    endpoint_descriptor_digest: DigestString
    status: EndpointHealthStatus
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ModelProviderHealth:
    schema_version: int
    provider_id: str
    status: EndpointHealthStatus
    endpoints: tuple[ModelEndpointHealth, ...]
    snapshot_revision: str
    checked_at: datetime
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ModelEndpointRef:
    schema_version: int
    provider_id: str
    endpoint_id: str
    model_id: str
    endpoint_descriptor_digest: DigestString
    tier: ModelTier
    priority: int

@dataclass(frozen=True, slots=True)
class ModelRoutePolicy:
    schema_version: int
    policy_id: str
    role: ModelRole
    default_tier: ModelTier
    allowed_tiers: frozenset[ModelTier]
    candidate_endpoints: tuple[ModelEndpointRef, ...]
    requirements: ModelCapabilitiesRequirement
    allowed_data_classes: frozenset[PrivacyLevel]
    fallback: ModelFallbackPolicy
    tier_fallback_edges: tuple[TierFallbackEdge, ...]
    policy_revision: str

@dataclass(frozen=True, slots=True)
class ModelCapabilitiesRequirement:
    schema_version: int
    input_modalities: frozenset[ModelInputModality]
    output_modalities: frozenset[ModelOutputModality]
    minimum_native_structured_output: StructuredOutputSupport
    requires_schema_validation: bool
    minimum_context_tokens: int
    minimum_output_tokens: int
    reasoning_profile_id: str

@dataclass(frozen=True, slots=True)
class ModelFallbackPolicy:
    schema_version: int
    max_retries_per_endpoint: int
    max_same_tier_failovers: int
    max_tier_hops: int
    max_total_attempts: int
    max_schema_repairs: int
    retryable_failure_kinds: frozenset[ModelFailureKind]
    deterministic_fallback_id: str

@dataclass(frozen=True, slots=True)
class TierFallbackEdge:
    schema_version: int
    from_tier: ModelTier
    to_tier: ModelTier
    failure_kinds: frozenset[ModelFailureKind]
```

Provider request 只携带已选择模型所需字段，并重复携带已冻结 endpoint/Provider/Route
revision 与完整 `ModelPrivacyPolicy`。Adapter 必须检查 external boundary、所选 residency、
所需 retention mode 和 endpoint capability；`selected_data_residency` 必须来自 Policy 与
Endpoint 的交集；`allow_provider_retention=false` 时只能选择并实际配置
`NO_RETENTION`，不能把“不知道供应商怎么处理”当成功。S08-S11 首个运行闭环不启用生成
资产；未来启用图片输出时必须新增绑定 Scope/Sensitivity/MIME/大小/TTL 的授权目标契约，
Adapter 把响应流写入 Attachment Repository 后才可返回 opaque ref，原始 URL/base64
不能穿透。总 deadline、取消、Trace、Policy
snapshot 和预算仍来自 `PortCallContext`。Provider response 通过
`ModelProcessingReceipt` 证明实际边界、驻留、retention 和 seed；Router 在 Schema、安全、
大小及 receipt 一致性校验后才构造公开 `ModelResponse`。

每个 Provider attempt 还必须绑定完整估算、attempt kind 和精确 Prompt artifact revision。
`SCHEMA_REPAIR` 必须携带同一输出 Schema 和独立 repair Prompt revision；未知 revision、
artifact digest 不匹配或 repair 无 Schema 都在下游调用前拒绝。

## 6. Protocol

```python
class ModelRouter(Protocol):
    async def invoke(
        self,
        request: ModelRequest,
        tier_authority: BootstrapTierDecision | TierDecision,
        *,
        call: PortCallContext,
    ) -> ModelResponse: ...

class ModelProvider(Protocol):
    @property
    def descriptor(self) -> ModelProviderDescriptor: ...

    async def generate(
        self,
        request: ProviderRequest,
        *,
        call: PortCallContext,
    ) -> ProviderResponse: ...

    async def health(
        self, *, call: PortCallContext | ServiceCallContext
    ) -> ModelProviderHealth: ...
    async def close(self) -> None: ...

@dataclass(frozen=True, slots=True)
class ModelRoutingSnapshot:
    schema_version: int
    snapshot_id: str
    catalog_revision: str
    provider_descriptors: tuple[ModelProviderDescriptor, ...]
    route_policies: tuple[ModelRoutePolicy, ...]
    acquired_at: datetime

class ModelRoutingRegistry(Protocol):
    def acquire_snapshot(self) -> ModelRoutingSnapshot: ...
    def resolve_provider(
        self,
        snapshot: ModelRoutingSnapshot,
        provider_id: str,
        expected_revision: ComponentRevision,
    ) -> ModelProvider: ...
    def list_enabled(
        self, snapshot: ModelRoutingSnapshot
    ) -> tuple[ModelProviderDescriptor, ...]: ...
    def policy_for(
        self, snapshot: ModelRoutingSnapshot, role: ModelRole
    ) -> ModelRoutePolicy: ...

@dataclass(frozen=True, slots=True)
class ModelCatalogUpdate:
    schema_version: int
    expected_revision: str
    provider_descriptors: tuple[ModelProviderDescriptor, ...]
    route_policies: tuple[ModelRoutePolicy, ...]

class ModelCatalogPublisher(Protocol):
    async def publish(
        self,
        update: ModelCatalogUpdate,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ModelCatalogPublishReceipt: ...

class ModelAdmissionController(Protocol):
    async def reserve(...) -> EndpointAdmissionResult: ...
    async def settle(
        self,
        lease: EndpointCapacityLease,
        usage: ModelUsage | None,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> EndpointCapacityReceipt: ...
    async def release(...) -> EndpointCapacityReceipt: ...

class ModelOperationalStateRegistry(Protocol):
    def acquire_snapshot(self) -> ModelOperationalSnapshot: ...

class ModelOutputCodec(Protocol):
    @property
    def revision(self) -> ComponentRevision: ...
    def validate(
        self, output: JsonValue, schema: SchemaRef
    ) -> JsonValue: ...

class ModelInvocationEstimator(Protocol):
    def estimate(
        self,
        request: ModelRequest,
        endpoint: ModelEndpointDescriptor,
        reasoning_profile: ReasoningProfile,
    ) -> ModelInvocationEstimate: ...

# 未来基础设施接口；当前 S08 代码尚未提供该 Protocol。
class CredentialResolver(Protocol):
    async def resolve(
        self,
        reference: str,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ProviderCredential: ...
```

`CredentialResolver` 是未来基础设施扩展点，不是当前代码镜像，也不属于 `dududa.domain`
的可调用能力；未来不得注入 Planner、Persona 或 MCP，只能由 Provider Adapter 使用。

Provider 实例只由 composition root 注册。配置更新通过 `ModelCatalogPublisher` 完整校验
角色、逐 endpoint descriptor、隐私、Schema 能力和 fallback DAG 后原子发布；失败保留
last-known-good revision。Router 对一次请求只取得一个 `ModelRoutingSnapshot`，Provider
descriptor 与 Route Policy 都从该 handle 读取，禁止把两个“最新 revision”拼接。Provider
实例按 snapshot 中的 ComponentRevision 精确解析；执行中发生配置漂移只影响下一次请求，
旧 revision 无法解析时显式拒绝而不是调用新实现。

Provider Adapter 失败时抛出只含 `ModelFailureKind + ErrorInfo` 的
`ModelProviderError`，不能把 SDK/HTTP 异常穿透 Port。Router 用 failure kind 执行显式
retry/failover DAG；终止时抛出 `ModelInvocationError`，其中携带完整且已脱敏的
`RouteDecision`，使 Runtime 即使在失败路径也能保存 attempts 和 revision 证据。

Provider 可以合法返回 `usage=None`。Admission Controller 此时必须按 reservation ceiling
结算并在 receipt 中返回实际扣账的 `ModelUsage`，不能因为 AstrBot 未报告 usage 而泄漏容量
或把未知值当作零。

## 7. 路由策略

### 7.1 配置示例

建议的可提交配置只记录逻辑引用：

```yaml
schema_version: 1
routes:
  perception:
    default_tier: haiku
    allowed_tiers: [haiku]
    candidates:
      - provider_id: astrbot
        endpoint_id: perception-haiku-primary
        model_id: provider-native-flash
        tier: haiku
        priority: 10
    require:
      minimum_native_structured_output: none
      requires_schema_validation: true
      input_modalities: [text]
      reasoning_profile_id: quick
    cross_tier_fallback: []

  direct_chat:
    default_tier: sonnet
    allowed_tiers: [haiku, sonnet, opus]
    candidates:
      - {provider_id: astrbot, endpoint_id: chat-haiku, tier: haiku, priority: 10}
      - {provider_id: astrbot, endpoint_id: chat-sonnet, tier: sonnet, priority: 10}
      - {provider_id: astrbot, endpoint_id: chat-opus, tier: opus, priority: 10}
    require:
      input_modalities: [text]
      output_modalities: [text]
      reasoning_profile_id: balanced
    cross_tier_fallback:
      - {from: opus, to: sonnet, failures: [timeout, provider_unavailable]}
```

`provider_id` 是 Registry 中的稳定逻辑标识，不是 API URL 或 credential；
`endpoint_id` 再绑定 Provider-native `model_id` 和精确 descriptor revision。生产覆盖配置保存在
Git 忽略的运行目录。

### 7.2 选择顺序

1. 校验请求 Role 与 `BootstrapTierDecision | TierDecision`，确定本次 Tier；
2. 从同一不可变 snapshot 读取角色策略和候选 Endpoint；
3. 应用 Tier allowlist、数据分类、external processing、驻留和 retention；
4. 验证输入/输出模态、Structured Output、Reasoning Profile、输入/总 Context 和输出上限；
5. 检查总 deadline、调用/token/cost 预算；
6. 排除不健康、cooldown、过期/未知 load 和超过硬流量阈值的候选；
7. 合法 `route_hint` 只能重排仍然 eligible 的 Endpoint；
8. 按静态 `priority`，再按 `endpoint_id` 稳定排序；
9. 调用前对共享 `quota_pool_id` 原子 reserve；
10. 仅按该角色声明的次数、failure kind 和显式跨档边执行 retry/failover。

模型不可用时不能把 `IMAGE_GENERATION` 路由到文本模型，也不能把要求本地处理的敏感内容自动发送给外部 Provider。

Admission reservation 必须绑定 model request/estimate digest、Endpoint descriptor digest、
traffic policy ID/revision，并预留 input、visible output、reasoning token 和 cost。共享 quota
pool 的所有 Endpoint 必须发布完全相同的 Traffic Policy；load/health 观测不得晚于其
Operational Snapshot 的 `acquired_at`。

`EndpointLoadSnapshot.counter_scope` 在 S08 固定为
`EXTERNAL_TO_ADMISSION_CONTROLLER`：快照只报告本 controller 之外的负载，本地
in-flight/RPM/TPM/window 由原子 Admission 状态单独累计，禁止重复扣算。排队唤醒后必须
重新检查 stale、sample、cooldown、P95、deadline；原生 task cancellation 也必须恰好移除
waiter，并使每个已发 lease 最终得到一个 `SETTLED | RELEASED` receipt。

### 7.3 路由与成本

每个角色可配置：

- 最大请求/输出 token；
- 总超时和单候选超时；
- 每次 Runtime 最大调用次数；
- 可接受成本等级；
- 是否允许流式输出；
- 是否允许带图片或敏感数据；
- fallback 候选和确定性降级。

S08-S11 中成本和延迟只参与硬预算/资格判断，不参与动态排序。它们不能降低权限、事实和
隐私要求，也不能让过载状态把任务重新解释成另一个难度。

### 7.4 Contextual Bandit（S08-S11 不接入）

本阶段没有 Bandit Policy、随机权重、propensity 或在线更新接口。Router 只输出可复现的
静态决策收据，供未来 S20 在单独设计评审后离线使用。届时即使加入 Bandit，也只能位于
所有硬过滤之后，并必须有独立 shadow、回滚和因果评估门禁；不能改变本阶段的隐私、权限、
Schema、容量和显式 fallback 不变量。

## 8. Structured Output

`PERCEPTION`、`SOCIAL_DECISION`、`TOOL_PLANNING`、`RESPONSE_COMPOSITION`、
`PERSONA_RENDERING` 和 `MEMORY_SUMMARY` 必须使用带版本的严格 Schema。S08 Router 允许
`DIRECT_CHAT` 返回文本，以便独立验证 Provider/路由边界；S10 Runtime 接入 Composer 时
才强制把 Direct Chat 结果投影为版本化内容容器：

- 优先使用 Provider 原生 Structured Output；
- 不支持时由 Adapter 使用受限 JSON 模式，但仍执行完整 Schema 校验；
- 禁止用正则从任意说明文本中截取 JSON 后接受部分字段；
- 校验失败只允许在预算内以修复提示重试一次；
- 第二次失败以 `ModelInvocationError(failure_kind=OUTPUT_INVALID)` 终止，并保留完整
  `RouteDecision`；
- 原始无效输出默认不写日志，仅记录长度、哈希和错误路径。

自然语言内容也应返回结构化容器，例如正文段落、事实锚点、来源 ID 和警告，避免 Persona Renderer 只能处理一个不可验证字符串。

## 9. Provider Adapter

### 9.1 AstrBotModelProviderAdapter

它负责：

- 接收 composition root 注入的单一 AstrBot Provider 和单 Endpoint descriptor，不在
  Adapter 内读取 UMO、Event、Context 或私有 Provider 配置；
- 用 `AstrBotProviderBindingEvidence` 精确绑定 host/Provider ID、model ID、输出上限、
  residency、retention、单次请求、下游 deadline/cancellation enforcement 和日志脱敏
  证据；Adapter 本地有界返回不能替代下游 enforcement 证据；
- 按 `ProviderRequest.prompt_template_revision` 解析 digest-bound Prompt artifact，区分
  primary 与 schema-repair artifact；
- 把 `text_chat` completion/usage 和结构化错误标准化为 Provider-neutral DTO；
- 对成功结果和 outcome-unknown 失败维护有界 TTL/LRU 幂等账本；同一 key/digest
  重放 tombstone 而不再次调用下游，固定锁分片和 `close()` 清理限制内容驻留；
- 只提供被动 `UNKNOWN` health，避免在路由热路径调用默认模型探活；
- AstrBot 拥有 Provider 生命周期，因此 `close()` 是幂等 no-op。

MessageEnvelope 不携带 AstrBot UMO。composition root 在进入 Core 前解析并注册精确
Provider revision；旧 `provider_id` 偏好只能转成无 Tier 权限的合法 `RouteHint`。不得把
Event、UMO、Provider 对象或不透明平台句柄塞进 Domain。离线测试直接注入 Recording Fake
或符合共享 conformance suite 的 AstrBot-compatible harness。

固定镜像 AstrBot 4.26.2 的 OpenAI/Anthropic 实现尚不能证明 `max_tokens` 真实下传、内部
只有一次请求、下游 deadline/cancellation 确实终止网络请求以及完整日志脱敏，因此不能
生成 permits-enablement evidence，生产 Endpoint 保持 disabled；签名接受参数或 Adapter
在 deadline 后返回不等于能力证据。

### 9.2 ImageProviderAdapter

现有 `_openai_source()` 和直接 `httpx` 调用应迁移到基础设施 Adapter：

- key 和自定义 Header 只在 Adapter 内解析；
- 支持 key 轮换、超时、HTTP 错误标准化和内容策略错误；
- 返回 `GeneratedAsset`，不返回 AstrBot `Image`；
- AstrBot Output Adapter 最终转换为 `Image.fromBase64` 或安全 URL；
- 不把图片 base64、生成 Prompt 或 key 写入 Trace。

不得把真实 key 搬到 `configs/models/`、环境示例或 Package 测试中。

## 10. 错误与回退

标准错误：

```python
class ModelProviderError(DududaError):
    failure_kind: ModelFailureKind

class ModelInvocationError(DududaError):
    failure_kind: ModelFailureKind
    route_decision: RouteDecision
```

Adapter 必须把 AstrBot、HTTP、SDK 和解析错误映射为携带稳定 `ErrorInfo` 的
`ModelProviderError`；Router 终止时再构造携带完整 receipt 的 `ModelInvocationError`。
Core 不信任 Provider 自带的公开错误字段，只保留已校验的 `failure_kind` 和
`outcome_unknown`，并用固定 code/message/reason 重建 attempt 与 terminal receipt。
`retryable` 只描述错误类别，Router 仍需检查角色 fallback policy、数据边界、总 deadline、
预算和请求幂等键；`outcome_unknown` 既不能被当成普通失败重复计费，也必须在 Adapter
幂等账本中形成 tombstone，阻止同一 key/digest 再次发起未知副作用。异常 `repr` 与用户文案
不得包含 URL query、Header、key、文件路径、Prompt 或 Provider 原始正文。

| 角色 | 默认回退 |
| --- | --- |
| Perception | 规则感知，降低主动回复范围 |
| Social Decision | 确定性 Policy Chain |
| Tool Planning | 简单已知命令走固定计划，否则澄清/暂不可用 |
| Direct Chat | 简短服务不可用说明，不编造答案 |
| Response Composition | 用可信工具结果和模板生成最小回复 |
| Persona Rendering | 确定性 Finalizer 生成候选，再走 Render Validator 与 Content Safety |
| Memory Summary | 跳过自动摘要和写入，不保存原文替代摘要 |
| Image Understanding | 说明无法读取图片，不猜测内容 |
| Image Generation | 返回明确失败，不用文本冒充图片 |

认证错误不尝试其他未明确允许的凭据；内容安全拒绝不通过改写规避；429/超时可以在策略允许时尝试一个候选，但必须服从总 deadline。

可靠性计数严格分为三类：同 Endpoint retry、同 Tier failover、沿显式 DAG 的跨 Tier
fallback；三者分别受限并共享 `max_total_attempts`。`RouteAttemptKind` 必须与相邻 attempt
的 Provider/Endpoint/Tier 变化一致。每次重试或换 Endpoint 都重新检查 deadline、预算、
隐私、能力和原子容量。认证、非法请求、安全拒绝、取消以及第二次结构化输出失败立即停止。

## 11. 隐私、安全和审计

- 路由前按 `PUBLIC`、`CONVERSATION`、`PERSONAL`、`SENSITIVE` 分类输入；
- 每个 Provider 声明允许的数据等级和模态；
- 默认用匿名引用替代 QQ、群号和真实姓名；
- Prompt 只包含完成角色任务所需的最小 Context；
- 私聊和记忆数据不得因 fallback 改发到更宽松的 Provider；
- 外部内容用清晰数据边界包装，不能成为 system instruction；
- Persona Prompt 不能包含 credential reference，更不能包含实际凭据；
- 审计记录角色、公开 Provider/模型 ID、耗时、usage、结果类型和错误码；
- 默认不记录 Prompt、completion、图片、工具参数或模型思维链；
- `/admin model` 修改路由需 owner、二次确认、配置校验、备份和审计。

## 12. 测试设计

### Unit

- 每个角色的候选筛选、能力不匹配和无路由；
- `route_hint` 不能绕过 allowlist；
- Registry/Route snapshot 固定、热更新原子发布与 last-known-good；
- deadline、单候选超时、总尝试次数和成本预算；
- Structured Output 首次失败、修复重试和最终失败；
- 敏感数据不允许的 Provider 被排除；
- 熔断、429、认证、安全拒绝的不同回退语义。

### Provider Contract

- Recording Fake 与 AstrBot-compatible harness 的共享输入输出 conformance；
- `ModelRoutingRegistry` 与 Catalog Publisher 的原子 snapshot、revision 冲突和回滚；
- 每个 model endpoint 独立能力、处理边界、驻留和 retention Contract；
- ProviderRequest/Response 的隐私 receipt、Prompt revision 和 seed 一致性；
- Provider 异常不泄漏 AstrBot/SDK 类型；
- usage、finish reason 和安全标记映射；
- Registry 精确解析 Provider revision，AstrBot Adapter 精确解析 Prompt artifact，
  `JsonSchemaDocumentRegistry` 精确解析本地 `SchemaRef`；通用 Artifact Store 属于后续扩展；
- 图片响应流经大小/MIME/digest 校验写入 Attachment Repository，再转 `GeneratedAsset` opaque ref；
- 凭据和自定义 Header 不出现在异常、`repr` 或 Trace。

### Integration

- 当前 Provider 的课程感知和总结；
- TargetTalk `provider_id` override 的兼容路径；
- gpt-image 类超时、401、403、429、5xx 和内容拒绝；
- Route Policy 热加载失败时保留最后一份有效配置；
- Persona Rendering 与 Response Composition 可独立配置、回退和评测；
- 无 Provider 的完整 Runtime 降级。

### Security

- 合成 key canary 不出现在日志、结果和快照；
- Prompt Injection 不能改变角色或路由；
- 私聊数据不会被路由到群聊结果或未授权 Provider；
- 配置与仓库密钥扫描继续通过。

## 13. 当前实现到角色的映射

| 当前调用 | 目标角色 | 迁移方式 |
| --- | --- | --- |
| `/course <自然语言>` 关键词抽取 | `PERCEPTION` | 严格 Intent Schema + AstrBot Adapter |
| 公开课程评论总结 | `RESPONSE_COMPOSITION` | 保留固定事实输入和来源，去掉手工 JSON 截取 |
| TargetTalk 短回复 | `DIRECT_CHAT` | 保留旧 Provider hint 和字数约束 |
| `/image` 原始 HTTP 调用 | `IMAGE_GENERATION` | Image Provider Adapter，不再由插件读 key |
| AstrBot 默认聊天 | `DIRECT_CHAT` | 先由兼容 Adapter 透传，后接统一 Runtime |
| `/admin model set default` | 路由配置管理 | 兼容期仍可写 AstrBot 配置，最终调用配置 Repository |

## 14. 三插件兼容约束

- `dududa_core` 保留命令和配置字段，内部逐项改为构造 `ModelRequest`；
- `target_talk` 保留 `provider_id`，但将其降级为受策略约束的 `RouteHint`；
- `reply_polish` 不调用模型，不属于 Model Router；
- 三个插件都不能 import 具体 Provider Adapter 实现，只能由组合根注入 Router；
- 在新路由通过行为、错误和密钥泄漏测试前，旧路径可由 feature flag 回滚；
- 移除旧图片路径前必须证明输出组件、超时、内容拒绝和错误文案有兼容方案。

## 15. 扩展点

- 增加本地小模型承担 Perception/Social Decision；
- 增加 OCR、语音和多模态 Provider Adapter；
- 增加按群策略、成本预算或延迟 SLO 的候选排序；
- 增加 Provider 健康探针、熔断和调用统计；
- 增加离线录制响应的 Replay Provider，fixture 必须脱敏；
- 增加 A/B 路由，但权限、隐私和用户可见行为必须可审计；
- Provider 迁移只修改 Adapter 和配置，不改变 Runtime、Tool Runtime 或 Persona。
