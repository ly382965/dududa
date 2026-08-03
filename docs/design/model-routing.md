# 模型路由设计

## 1. 文档状态与目标

- 阶段：Phase 1，目标设计，尚未实现。
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
Runtime / Perception / Planner / Composer
                   |
                   v
              ModelRouter
          + ModelRoutingRegistry snapshot
          + Health/Budget State
          + optional ContextualBanditPolicy
                   |
                   v
           ModelProvider Protocol
                   ^
                   |
     AstrBotProviderAdapter / ImageProviderAdapter / future adapters
```

- Domain 和 Runtime 只依赖 `ModelRouter` Protocol 和结构化请求/响应；
- Provider Adapter 位于应用适配层或基础设施层，可以依赖 AstrBot API 或供应商 SDK；
- `CredentialResolver` 只在基础设施边界使用，Core 只看到不可反查的 credential reference；
- 路由配置描述角色、能力、优先级和限制，不包含 key、Cookie、Token 或私有 API Header。

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
| `DIRECT_CHAT` | 不需要工具的直接内容草稿 | 结构化 Draft Content |
| `RESPONSE_COMPOSITION` | 合并工具结果、来源、错误和不确定性 | `DraftResponse` |
| `PERSONA_RENDERING` | 在锁定事实与安全约束后改变表达 | 严格 `FinalResponse` |
| `MEMORY_SUMMARY` | 在已限定 Scope 内压缩记忆候选 | 结构化摘要，不负责写入 |
| `IMAGE_UNDERSTANDING` | 对受控图片引用生成描述或结构化观察 | `AttachmentSummary` |
| `IMAGE_GENERATION` | 根据已通过策略的描述生成图片 | `GeneratedAsset` |

同一个实际模型可以承担多个角色，但角色配置、超时、温度、输出 Schema 和隐私策略相互独立。

## 5. 数据契约

### 5.1 能力声明

```python
@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    schema_version: int
    input_modalities: frozenset[Literal["text", "image", "audio", "file"]]
    output_modalities: frozenset[Literal["text", "image", "embedding"]]
    structured_output: bool
    max_context_tokens: int
    max_output_tokens: int
    supports_temperature: bool
    supports_streaming: bool
    supports_seed: bool
```

Provider Adapter 在启动时提供能力快照；路由不能仅根据模型名称猜测能力。

### 5.2 ModelRequest

```python
class ModelDataClassification(StrEnum):
    PUBLIC = "public"
    CONVERSATION = "conversation"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"

@dataclass(frozen=True, slots=True)
class ModelInputPart:
    part_id: str
    modality: Literal["text", "image", "audio", "file"]
    text: str | None
    content_ref: str | None
    content_digest: DigestString | None
    media_type: str | None
    attachment_access: AttachmentAccessRequest | None

@dataclass(frozen=True, slots=True)
class ModelPrivacyPolicy:
    data_classification: ModelDataClassification
    allow_external_provider: bool
    allowed_residencies: frozenset[str]
    allow_provider_retention: bool

@dataclass(frozen=True, slots=True)
class RouteHint:
    preferred_provider_id: str | None
    preferred_model_id: str | None

@dataclass(frozen=True, slots=True)
class ModelInput:
    schema_version: int
    parts: tuple[ModelInputPart, ...]
    source_refs: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ModelRequest(Generic[T]):
    schema_version: int
    request_id: str
    role: ModelRole
    input: ModelInput
    output_schema: SchemaRef | None
    max_output_tokens: int
    temperature: float | None
    privacy: ModelPrivacyPolicy
    random_seed: int | None
    idempotency_key: str | None
    route_hint: RouteHint | None = None
```

`ModelInput` 只能包含该角色需要的数据。`SchemaRef` 使用稳定 Schema ID、版本和 digest，不能把 Python class 或供应商专属 Schema 对象传到进程外。Provider Adapter 负责将输入和 Schema 转换为供应商消息格式；Core 不构造 OpenAI 专属 payload。

`ModelInputPart` 按 modality 严格执行 one-of：文本只能有受限 `text`；附件必须同时携带
受信的 opaque `content_ref + content_digest + media_type` 和目的为 `MODEL_INPUT` 的
`AttachmentAccessRequest`。Provider Adapter 只在本地用授权请求从 Attachment Repository
取得有界 stream，绝不把授权对象发给外部供应商。本地路径、任意 URL、base64、Event 或
Provider 对象不能作为输入 part。`RESTRICTED` 数据在构造 ModelRequest 前已经被拒绝。
有效数据等级只有 `ModelPrivacyPolicy.data_classification` 一处；禁止在 Input 中保存第二份
可能不一致的分类。

`RouteHint` 只能表达允许的偏好，例如兼容 TargetTalk 的旧 `provider_id`，不能绕过角色 allowlist、隐私规则或健康检查。

### 5.3 ModelResponse

```python
@dataclass(frozen=True, slots=True)
class ModelResponse(Generic[T]):
    schema_version: int
    request_id: str
    role: ModelRole
    route_policy_revision: str
    router_revision: ComponentRevision
    provider_id: str
    model_id: str
    provider_revision: ComponentRevision
    prompt_template_revision: ComponentRevision
    output_schema_digest: DigestString | None
    output: T
    finish_reason: str
    usage: ModelUsage | None
    latency_ms: int
    route_attempts: tuple[RouteAttempt, ...]
    safety_annotations: tuple[SafetyAnnotation, ...]
    processing: ModelProcessingReceipt
```

```python
@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int | None
    cost_units: Decimal | None

@dataclass(frozen=True, slots=True)
class RouteAttempt:
    provider_id: str
    model_id: str
    started_at: datetime
    latency_ms: int
    error: ErrorInfo | None

@dataclass(frozen=True, slots=True)
class SafetyAnnotation:
    code: str
    severity: str
    blocked: bool

@dataclass(frozen=True, slots=True)
class GeneratedAsset:
    asset_id: str
    content_ref: str
    media_type: str
    size_bytes: int
    source_digest: DigestString
```

结构化角色必须先通过 Schema Validator 才能构造成功响应。供应商自由文本、异常对象和原始 HTTP Response 不得穿透到 Runtime。

`route_policy_revision`、Router/Provider/Prompt revision、`provider_id`、`model_id`、Schema digest、公开采样参数、usage
和 latency 构成离线 Eval 的最小复现实验元数据。Trace 不记录 Credential、原始 Prompt、
隐藏推理或默认完整输出；同一固定请求集至少分别报告 Schema-valid rate、任务指标、
P50/P95、fallback 率和成本，不能只比较主观文案质量。

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
    model_id: str
    descriptor_digest: DigestString
    capabilities: ModelCapabilities
    allowed_data_classes: frozenset[ModelDataClassification]
    processing_boundary: ModelProcessingBoundary
    available_data_residencies: frozenset[str]
    supported_retention_modes: frozenset[ModelRetentionMode]

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
    endpoint_descriptor_digest: DigestString
    processing_boundary: ModelProcessingBoundary
    data_residency: str
    retention_mode: ModelRetentionMode
    requested_seed: int | None
    effective_seed: int | None

@dataclass(frozen=True, slots=True)
class GeneratedAssetTarget:
    schema_version: int
    scope_digest: DigestString
    sensitivity: Sensitivity
    allowed_media_types: frozenset[str]
    maximum_size_bytes: int
    expires_at: datetime
    authorization: AuthorizationDecision
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class ProviderRequest:
    schema_version: int
    request_id: str
    provider_id: str
    provider_revision: ComponentRevision
    endpoint_descriptor_digest: DigestString
    route_policy_revision: str
    selected_data_residency: str
    required_retention_mode: ModelRetentionMode
    role: ModelRole
    model_id: str
    input: ModelInput
    output_schema: SchemaRef | None
    max_output_tokens: int
    temperature: float | None
    privacy: ModelPrivacyPolicy
    random_seed: int | None
    generated_asset_target: GeneratedAssetTarget | None
    idempotency_key: str | None

@dataclass(frozen=True, slots=True)
class ProviderResponse:
    schema_version: int
    request_id: str
    provider_id: str
    model_id: str
    provider_revision: ComponentRevision
    output: JsonValue | GeneratedAsset
    finish_reason: str
    usage: ModelUsage | None
    safety_annotations: tuple[SafetyAnnotation, ...]
    processing: ModelProcessingReceipt

@dataclass(frozen=True, slots=True)
class ModelEndpointHealth:
    model_id: str
    endpoint_descriptor_digest: DigestString
    status: Literal["healthy", "degraded", "unavailable"]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ModelProviderHealth:
    schema_version: int
    provider_id: str
    status: Literal["healthy", "degraded", "unavailable"]
    endpoints: tuple[ModelEndpointHealth, ...]
    snapshot_revision: str
    checked_at: datetime
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ModelEndpointRef:
    provider_id: str
    model_id: str
    endpoint_descriptor_digest: DigestString

@dataclass(frozen=True, slots=True)
class ModelRoutePolicy:
    schema_version: int
    role: ModelRole
    candidate_endpoints: tuple[ModelEndpointRef, ...]
    requirements: ModelCapabilitiesRequirement
    allowed_data_classes: frozenset[ModelDataClassification]
    fallback: ModelFallbackPolicy
    policy_revision: str

@dataclass(frozen=True, slots=True)
class ModelCapabilitiesRequirement:
    input_modalities: frozenset[str]
    output_modalities: frozenset[str]
    structured_output: bool
    minimum_context_tokens: int

@dataclass(frozen=True, slots=True)
class ModelFallbackPolicy:
    maximum_attempts: int
    retryable_error_codes: frozenset[str]
    deterministic_fallback_id: str
```

Provider request 只携带已选择模型所需字段，并重复携带已冻结 endpoint/Provider/Route
revision 与完整 `ModelPrivacyPolicy`。Adapter 必须检查 external boundary、所选 residency、
所需 retention mode 和 endpoint capability；`selected_data_residency` 必须来自 Policy 与
Endpoint 的交集；`allow_provider_retention=false` 时只能选择并实际配置
`NO_RETENTION`，不能把“不知道供应商怎么处理”当成功。产生图片等资产时，ProviderRequest
必须携带已授权、绑定 Scope/Sensitivity/MIME/大小/TTL 的 `GeneratedAssetTarget`；Adapter
把响应流写入 Attachment Repository 后才返回 opaque `GeneratedAsset`，原始 URL/base64
不能穿透。总 deadline、取消、Trace、Policy
snapshot 和预算仍来自 `PortCallContext`。Provider response 通过
`ModelProcessingReceipt` 证明实际边界、驻留、retention 和 seed；Router 在 Schema、安全、
大小及 receipt 一致性校验后才构造公开 `ModelResponse[T]`。

## 6. Protocol

```python
class ModelRouter(Protocol):
    async def invoke(
        self,
        request: ModelRequest[T],
        *,
        call: PortCallContext,
    ) -> ModelResponse[T]: ...

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
    ) -> str: ...

class CredentialResolver(Protocol):
    async def resolve(
        self,
        reference: str,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ProviderCredential: ...
```

`CredentialResolver` 不属于 `dududa.domain` 的可调用能力，不得注入 Planner、Persona 或 MCP。它只能由 Provider Adapter 使用。

Provider 实例只由 composition root 注册。配置更新通过 `ModelCatalogPublisher` 完整校验
角色、逐 endpoint descriptor、隐私、Schema 能力和 fallback DAG 后原子发布；失败保留
last-known-good revision。Router 对一次请求只取得一个 `ModelRoutingSnapshot`，Provider
descriptor 与 Route Policy 都从该 handle 读取，禁止把两个“最新 revision”拼接。Provider
实例按 snapshot 中的 ComponentRevision 精确解析；执行中发生配置漂移只影响下一次请求，
旧 revision 无法解析时显式拒绝而不是调用新实现。

## 7. 路由策略

### 7.1 配置示例

建议的可提交配置只记录逻辑引用：

```yaml
schema_version: 1
routes:
  perception:
    candidates:
      - provider_ref: astrbot/current
        model_ref: default
    require:
      structured_output: true
      input_modalities: [text]
    timeout_seconds: 15
    max_output_tokens: 512
    fallback: deterministic_rules

  image_generation:
    candidates:
      - provider_ref: astrbot/openai
        model_ref: gpt-image-2
    require:
      output_modalities: [image]
    timeout_seconds: 420
    fallback: unavailable
```

`provider_ref` 是 Adapter 可解析的逻辑名称，不是 API URL 或 credential。生产覆盖配置保存在 Git 忽略的运行目录。

### 7.2 选择顺序

1. 读取角色策略和候选列表；
2. 应用数据分类、会话策略和用户许可；
3. 验证输入/输出模态、Structured Output、上下文及输出上限；
4. 排除熔断、限流或不健康候选；
5. 检查 `PortCallContext` 中的 Runtime deadline 和成本预算；
6. 应用合法 `route_hint`；
7. 对仍然合法的候选可调用 Contextual Bandit；未启用、日志失败或不允许探索时使用静态
   baseline 顺序；
8. 调用选中候选；
9. 仅按该角色声明的错误类型和次数 fallback。

模型不可用时不能把 `IMAGE_GENERATION` 路由到文本模型，也不能把要求本地处理的敏感内容自动发送给外部 Provider。

### 7.3 路由与成本

每个角色可配置：

- 最大请求/输出 token；
- 总超时和单候选超时；
- 每次 Runtime 最大调用次数；
- 可接受成本等级；
- 是否允许流式输出；
- 是否允许带图片或敏感数据；
- fallback 候选和确定性降级。

成本只影响候选排序，不能降低权限、事实和隐私要求。

### 7.4 Contextual Bandit

Bandit 是 Route Policy 的可选后排序器，正式契约见 `online-learning.md`。Model Router 先按
角色、Endpoint capability、隐私边界、驻留、retention、健康、deadline 和预算生成完整
`eligible_actions`；Bandit 只能从该集合选择。第一版建议使用 LinUCB 或 Thompson Sampling，
Context 仅含任务类别、长度/预算 bucket、是否需实时信息和会话类型等最小特征。

决策必须在调用 Provider 前记录 action set、propensity、Feature/Policy/Reward revision；
记录失败走静态 baseline。`SENSITIVE/RESTRICTED`、无合法 Provider、强制本地处理和高风险
场景 exploration probability 为 0。上线依次经过合成/replay estimator 测试、shadow 和极小
conservative canary；只有 canary 或历史受控探索日志具有 propensity/support 时，才能用
IPS/SNIPS/DR 评估并决定放量。质量增益不能抵消隐私、权限、Schema 或事实 Gate 违规。

## 8. Structured Output

`PERCEPTION`、`SOCIAL_DECISION`、`TOOL_PLANNING`、`RESPONSE_COMPOSITION`、
`PERSONA_RENDERING` 和 `MEMORY_SUMMARY` 必须使用带版本的严格 Schema；`DIRECT_CHAT`
也返回版本化内容容器而不是裸字符串：

- 优先使用 Provider 原生 Structured Output；
- 不支持时由 Adapter 使用受限 JSON 模式，但仍执行完整 Schema 校验；
- 禁止用正则从任意说明文本中截取 JSON 后接受部分字段；
- 校验失败只允许在预算内以修复提示重试一次；
- 第二次失败返回 `ModelOutputValidationError`，由上层确定性降级；
- 原始无效输出默认不写日志，仅记录长度、哈希和错误路径。

自然语言内容也应返回结构化容器，例如正文段落、事实锚点、来源 ID 和警告，避免 Persona Renderer 只能处理一个不可验证字符串。

## 9. Provider Adapter

### 9.1 AstrBotProviderAdapter

它负责：

- 将逻辑 `astrbot/current` 解析为当前 UMO 的 Provider；
- 将允许的旧 `provider_id` hint 映射为 AstrBot Provider；
- 把 `text_chat` 响应标准化；
- 隔离 AstrBot Context、Provider 类型和异常；
- 提供健康和能力快照。

MessageEnvelope 不携带 AstrBot UMO。AstrBot Adapter 应在进入 Core 前使用 UMO 解析当前
Provider 的逻辑引用，再通过 `RuntimeInvocationOptions.route_hint` 传入；不得把 Event、
UMO、Provider 对象或不透明平台句柄塞进 Domain。离线测试可直接注入 Fake Provider 和
合法 RouteHint。

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
class ModelError(DududaError): ...
class ModelRouteNotFoundError(ModelError): ...
class ModelCapabilityMismatchError(ModelError): ...
class ModelUnavailableError(ModelError): ...
class ModelTimeoutError(ModelError): ...
class ModelRateLimitedError(ModelError): ...
class ModelAuthenticationError(ModelError): ...
class ModelSafetyRejectedError(ModelError): ...
class ModelOutputValidationError(ModelError): ...
```

Adapter 必须把 AstrBot、HTTP、SDK 和解析错误映射为携带 Runtime `ErrorInfo` 的上述类型。
`retryable` 只描述错误类别，Router 仍需检查角色 fallback policy、数据边界、总 deadline、
预算和请求幂等键；`outcome_unknown` 不能被当成普通失败重复计费。异常 `repr` 与用户文案
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

- Fake AstrBot Provider 的输入输出归一化；
- `ModelRoutingRegistry` 与 Catalog Publisher 的原子 snapshot、revision 冲突和回滚；
- 每个 model endpoint 独立能力、处理边界、驻留和 retention Contract；
- ProviderRequest/Response 的隐私 receipt、attachment grant 和 seed 一致性；
- Provider 异常不泄漏 AstrBot/SDK 类型；
- usage、finish reason 和安全标记映射；
- Router/Provider/Prompt/Schema artifact revision 可由 Artifact Store 解析；
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
