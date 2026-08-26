# Agent Runtime 设计

## 1. 文档状态

- 阶段：S10 入站显式 @ 离线 Runtime、S11 本地 rollout、S15 ResponsePlan，以及 S15A-S15E
  独立主动出站 no-send 链已实现并验证；真实 Provider composition、Tool/Memory/Attachment
  产品接入和主动投递尚未完成。
- 目标代码位置：`packages/dududa-agent/src/dududa/runtime/`。
- 适用入口：AstrBot、后续 Web/测试入口以及不依赖具体平台的离线 Eval。
- 兼容约束：`astrbot_plugin_dududa_core` 保持正式 AstrBot Adapter；
  `astrbot_plugin_reply_polish` 仅保留为默认关闭的 Dududa 1.0 LONG-only 兼容层；
  `astrbot_plugin_target_talk` 源码和配置仅作迁移/回滚材料，不进入 Dududa 2.0
  默认 Compose 或入站路径。

本文定义一次嘟嘟哒 Agent 执行的边界、状态、端口和失败语义。它不规定某个模型供应商、MCP 进程或 AstrBot Event 的具体实现。

S21 Bot Control Plane 已提供群服务初始化和版本化 Assignment 基础。群聊 Runtime 只有在
Assignment 为 `ACTIVE` 且当前 revision/Scope/授权仍有效时才可取得执行所有权；缺 Profile、
pending、paused、revoked 或 snapshot 不一致均在模型/Memory/Tool 前停止。Group Context 只作为
Assignment 允许范围内的弱先验，不能改变服务、Capability、预算或发送权。
当前尚未落地的是生产 Runtime 对完整 Assignment 投影的 live 消费与执行接入，
不是 S21 的初始化、版本化和管理端合约。

## 2. 目标与非目标

Runtime 的目标是把一次消息处理变成可观察、可中止、可测试的显式状态转换：

```text
RuntimeStartRequest(ConnectorResult + options + digest)
  -> Preprocess
  -> Scoped Memory Retrieval
  -> Context Builder
  -> Perception
  -> Social Decision
  -> No Reply
     | Direct Reply: deterministic Response Planning -> user-visible model call
     | Capability/Tool Loop -> validated observations -> deterministic Response Planning
  -> optional hard-filtered Bandit ranking inside each owning model/capability router
  -> Response Composer
  -> Persona Renderer
  -> RuntimeResult + authoritative DeliveryRequest (when visible)
  -> Output Adapter
  -> DeliveryReceipt
  -> Memory Write Gate
  -> CompletionReceipt
```

Runtime 负责：

- 维护单次执行状态和阶段转换；
- 调用通过依赖注入提供的感知、社交决策、记忆、能力、模型和渲染端口；
- 执行总超时、工具最大步数、取消、幂等和降级策略；
- 生成不含敏感正文的 Trace；
- 返回平台无关的响应或明确的“不回复”结果；
- 在 Output Adapter 回传平台无关的投递结果后，提交依赖投递结果的自动记忆候选。

Runtime 不负责：

- 解析 `AstrMessageEvent`、OneBot CQ 码或 NapCat 数据；
- 直接发送 QQ 消息；
- 读取 AstrBot `cmd_config.json` 或 Provider key；
- 启动某个具体 MCP Server；
- 决定 Persona 的文学设定；
- 把安全、权限或事实正确性交给 Persona Prompt。
- 接受浏览器、模型、Group Context、Plugin 或 Bandit 直接修改群服务 Assignment；只有受治理的
  Control Plane Core Command 可以发布新 revision。
- 把定时器伪造成用户消息；无入站消息的日报和主动探测由独立
  `ProactiveDeliveryOrchestrator` 负责，见 `proactive-messaging.md`。

## 3. 依赖方向

目标依赖只能沿以下方向流动：

```text
apps/astrbot-plugins adapters
            |
            v
packages/dududa-agent runtime/application
            |
            v
domain models + Protocol ports
            ^
            |
infrastructure implementations
```

`packages/dududa-agent` 不得 import `astrbot`、NapCat、OneBot、Docker Compose、具体 MCP Server 包或具体模型供应商 SDK。基础设施实现通过构造函数注入。应用层可以依赖 Domain 类型和 Protocol，基础设施反向实现这些 Protocol。

共享类型位于无上游业务依赖的 `dududa.domain.primitives` 与
`dududa.domain.content`：`SchemaRef`、`ComponentRevision`、`ConversationType`、
`RiskLevel`、`PrivacyLevel`、`Sensitivity`、`SideEffect`、`ActionId`、`ResourceRef`、
`ResponseConstraints`、`ErrorInfo`、`DigestString`、`ResourceUsage`、受限 JSON、身份/Scope
引用和通用内容投影。Security、Capability、Perception、Memory、Model、Online Learning 与
Persona 只能 import 该共享层，不能互相反向 import
DTO 来形成环。各模块设计文档中的同名代码块是语义摘录，不表示类型由该模块私有拥有。

## 4. 核心数据契约

以下代码是设计契约，假定启用 `from __future__ import annotations`。字段名在 Phase 2
实现前可通过 ADR 调整，但不得用无结构 `dict` 取代关键边界。

### 4.1 MessageEnvelope

```python
class ConversationType(StrEnum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"

class AttachmentKind(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"

@dataclass(frozen=True, slots=True)
class MessageReference:
    platform: str
    bot_id: str
    conversation_id: str
    message_id: str

@dataclass(frozen=True, slots=True)
class AttachmentRef:
    attachment_id: str
    kind: AttachmentKind
    media_type: str
    size_bytes: int | None
    content_ref: str | None
    content_digest: DigestString | None
    summary: str | None

@dataclass(frozen=True, slots=True)
class Mention:
    platform: str
    user_id: str
    display_text: str | None

@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    schema_version: int
    message_id: str
    platform: str
    bot_id: str
    conversation_type: ConversationType
    conversation_id: str
    group_id: str | None
    user_id: str
    reply_to: MessageReference | None
    timestamp: datetime
    text: str
    attachments: tuple[AttachmentRef, ...]
    mentions: tuple[Mention, ...]
    metadata: Mapping[str, JsonValue]
```

要求：

- `message_id` 在同一平台和 Bot 下稳定，用于去重；
- Adapter 只接受受支持的 `schema_version`；
- `conversation_id` 必填，私聊不得使用含义模糊的固定值 `private`；
- `reply_to` 必须与当前 platform、Bot 和 conversation 一致；跨会话引用必须先由 Adapter 转为不带可访问句柄的普通上下文证据；
- `timestamp` 必须带时区；`metadata` 使用 allowlist，并在构造时递归复制为不可变值；
- `content_ref` 是由受信 Attachment Repository 解析的有界 opaque ID，不是任意本地路径或未校验 URL；存在正文时必须同时携带 Repository 计算的 `content_digest`；
- Adapter 在构造失败时不得让半完整消息进入 Runtime。

全仓 Python 类型名统一为 `JsonValue`。它只允许 `None`、布尔、有限数字、字符串、不可变序列和字符串键的递归不可变映射；不允许 Event、Path、文件句柄、自定义 Provider 对象或任意可变容器。

所有名为 `*_digest`、`*_hash` 或用于幂等键的规范化摘要都使用同一
`DigestString` 编码：`dududa-c14n-v1:<domain>:sha-256:<lowercase-hex>`。`c14n-v1`
先按 Schema 把 Enum 转为值、datetime 转为 UTC RFC 3339（固定微秒精度）、Decimal 转为
无指数规范十进制、字符串转为 Unicode NFC、mapping key 排序、set/frozenset 按元素规范
字节排序，再用 UTF-8 编码；禁止 NaN、Infinity、隐式本地时区、二进制值和重复规范键。
JSON Schema digest 对完整离线 bundle 计算，禁止在摘要阶段解析远程 `$ref`。domain 至少包含
DTO/Schema ID 与版本，防止同一字节在 candidate、authorization、delivery 等不同用途间复用。
`ops/cli/contract-vectors/` 必须提供 Python/TypeScript 共享正反测试向量；修改 codec 或算法要发布
新版本并保留旧版本 verifier/upcaster，不能静默重新计算已有授权证明。

### 4.2 Actor And ConversationScope

```python
@dataclass(frozen=True, slots=True)
class Actor:
    platform: str
    bot_id: str
    user_id: str
    roles: frozenset[RoleId]
    deny_flags: frozenset[DenyFlag]

@dataclass(frozen=True, slots=True)
class ConversationScope:
    platform: str
    bot_id: str
    conversation_type: ConversationType
    conversation_id: str
    group_id: str | None
    persona_id: str

@dataclass(frozen=True, slots=True)
class ActorRef:
    platform: str
    bot_id: str
    opaque_actor_id: str

@dataclass(frozen=True, slots=True)
class ResolvedIdentityRef:
    identity_ref: str
    actor_ref: ActorRef
    evidence_message_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class PersonaRef:
    persona_id: str
    version: str
    source_digest: DigestString

@dataclass(frozen=True, slots=True)
class GroupPolicyView:
    schema_version: int
    scope_digest: DigestString
    mode: Literal["quiet", "normal", "active"]
    response_constraints: ResponseConstraints
    policy_revision: str
```

AstrBot Adapter 从 Event 和受信配置解析 `Actor`；Runtime 校验 Actor 的 platform、Bot 和 user 与 Envelope 完全一致。`roles` 与 `deny_flags` 是已解析的确定性授权输入，不发送给 Perception 模型。

`ConversationScope` 是会话和上下文边界，不包含发言者身份，也不能直接当作 Memory 查询 selector。用户身份保留在 `MessageEnvelope` 和 `Actor`；Memory Policy 再根据 `memory_type` 构造包含可选或必填 `user_id` 的 `MemoryScope`。缺少该类型要求的任一字段时 fail closed。

### 4.3 PortCallContext 与接入结果

入口应用服务在 Connector 成功后创建 run/trace root；Runtime 为每次 run-scoped 异步 Port
调用派生只读上下文，避免每个模块分别发明 deadline、取消、预算和 Trace 参数：

```python
@dataclass(frozen=True, slots=True)
class RuntimeBudget:
    model_calls_remaining: int
    tool_steps_remaining: int
    retries_remaining: int
    input_tokens_remaining: int
    output_tokens_remaining: int
    cost_units_remaining: Decimal | None

@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    parent_span_id: str | None

DigestString = NewType("DigestString", str)

@dataclass(frozen=True, slots=True)
class SchemaRef:
    schema_id: str
    schema_version: int
    digest: DigestString

@dataclass(frozen=True, slots=True)
class ComponentRevision:
    component_id: str
    implementation_version: str
    config_revision: str
    artifact_digest: DigestString

@dataclass(frozen=True, slots=True)
class PortOperationDescriptor:
    operation_id: str
    accepted_input_schemas: tuple[SchemaRef, ...]
    emitted_output_schemas: tuple[SchemaRef, ...]

@dataclass(frozen=True, slots=True)
class PortDescriptor:
    port_id: str
    protocol_version: str
    operations: tuple[PortOperationDescriptor, ...]
    supported_capability_flags: frozenset[str]
    component_revision: ComponentRevision

@dataclass(frozen=True, slots=True)
class PortOperationRequirement:
    operation_id: str
    input_schema: SchemaRef
    accepted_output_schemas: tuple[SchemaRef, ...]

@dataclass(frozen=True, slots=True)
class PortBindingRequirement:
    port_id: str
    protocol_major: int
    operations: tuple[PortOperationRequirement, ...]
    required_capability_flags: frozenset[str]

PortT = TypeVar("PortT")

@dataclass(frozen=True, slots=True)
class PortBinding(Generic[PortT]):
    requirement: PortBindingRequirement
    descriptor: PortDescriptor
    implementation: PortT

@dataclass(frozen=True, slots=True)
class NegotiatedBindingReceipt:
    schema_version: int
    port_id: str
    protocol_version: str
    operation_schema_digests: Mapping[str, tuple[DigestString, DigestString]]
    enabled_capability_flags: frozenset[str]
    component_revision: ComponentRevision
    negotiated_at: datetime

class CancellationToken(Protocol):
    @property
    def is_cancelled(self) -> bool: ...
    async def wait(self) -> None: ...

@dataclass(frozen=True, slots=True)
class PortCallContext:
    run_id: str
    trace: TraceContext
    deadline: datetime
    cancellation: CancellationToken
    budget: RuntimeBudget
    policy_snapshot_id: str

@dataclass(frozen=True, slots=True)
class ServicePrincipal:
    service_id: str
    instance_id: str
    roles: frozenset[str]

@dataclass(frozen=True, slots=True)
class ServiceCallContext:
    operation_id: str
    principal: ServicePrincipal
    operation_kind: str
    trace: TraceContext
    deadline: datetime
    cancellation: CancellationToken
    budget: RuntimeBudget
    policy_snapshot_id: str

@dataclass(frozen=True, slots=True)
class ConnectorResult:
    schema_version: int
    message: MessageEnvelope
    actor: Actor
    received_at: datetime
    adapter_revision: ComponentRevision

@dataclass(frozen=True, slots=True)
class StoredContentRef:
    schema_version: int
    content_ref: str
    content_digest: DigestString
    media_type: str
    size_bytes: int
    repository_revision: ComponentRevision

class AttachmentPurpose(StrEnum):
    PREPROCESS = "preprocess"
    MODEL_INPUT = "model_input"
    OUTPUT_DELIVERY = "output_delivery"

@dataclass(frozen=True, slots=True)
class AttachmentIngestRequest:
    schema_version: int
    content_id: str
    origin: Literal["platform_input", "model_generated", "tool_generated"]
    scope_digest: DigestString
    declared_media_type: str
    declared_size_bytes: int | None
    maximum_size_bytes: int
    sensitivity: Sensitivity
    expires_at: datetime
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class AttachmentAccessRequest:
    schema_version: int
    content_ref: str
    expected_content_digest: DigestString
    conversation_scope: ConversationScope
    purpose: AttachmentPurpose
    accepted_media_types: frozenset[str]
    maximum_size_bytes: int
    authorization: AuthorizationDecision

@dataclass(frozen=True, slots=True)
class AttachmentDescriptor:
    schema_version: int
    content_ref: str
    content_digest: DigestString
    media_type: str
    size_bytes: int
    scope_digest: DigestString
    sensitivity: Sensitivity
    created_at: datetime
    expires_at: datetime
    repository_revision: ComponentRevision

class BoundedAttachmentStream(Protocol):
    @property
    def descriptor(self) -> AttachmentDescriptor: ...
    def __aiter__(self) -> AsyncIterator[bytes]: ...

@dataclass(frozen=True, slots=True)
class AttachmentDeleteCommand:
    schema_version: int
    content_ref: str
    expected_content_digest: DigestString
    reason: str
    authorization: AuthorizationDecision
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class AttachmentDeleteReceipt:
    schema_version: int
    content_ref: str
    deleted: bool
    repository_revision: ComponentRevision
    deleted_at: datetime

@dataclass(frozen=True, slots=True)
class MessageDedupKey:
    platform: str
    bot_id: str
    conversation_id: str
    message_id: str

@dataclass(frozen=True, slots=True)
class PreprocessRequest:
    schema_version: int
    message: MessageEnvelope
    actor: Actor
    conversation_scope: ConversationScope
    attachment_access: tuple[AttachmentAccessRequest, ...]

@dataclass(frozen=True, slots=True)
class PreprocessResult:
    schema_version: int
    message_id: str
    producer: ComponentRevision
    attachment_summaries: tuple["AttachmentSummary", ...]
    degraded_components: tuple[str, ...]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class AttachmentSummary:
    schema_version: int
    attachment_id: str
    kind: AttachmentKind
    summary: str
    source_digest: DigestString
    sensitivity: Sensitivity
    truncated: bool
    producer: ComponentRevision
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ContextMessage:
    schema_version: int
    message_id: str
    actor_ref: ActorRef
    scope_digest: DigestString
    content_digest: DigestString
    timestamp: datetime
    text: str
    attachment_summaries: tuple[AttachmentSummary, ...]
    reply_to: MessageReference | None
    sensitivity: Sensitivity
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class Reaction:
    schema_version: int
    reaction_id: str
    kind: str
    target_message: MessageReference
    target_users: tuple[ResolvedIdentityRef, ...]

@dataclass(frozen=True, slots=True)
class ContentBlock:
    block_id: str
    kind: str
    content: JsonValue
    source_refs: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class DraftContent:
    schema_version: int
    blocks: tuple[ContentBlock, ...]
    producer: ComponentRevision
```

入口创建 run/trace root；Runtime 在每次 Port 调用前派生新的只读 `PortCallContext`，保留
同一 run ID、创建子 span，并带入当时的剩余预算和 Policy snapshot。它是进程内调用能力，
不持久化 `CancellationToken`。Runtime 在调用前按
端口声明的最坏情况预留预算；成功结果或类型化错误可以报告实际 usage，缺少 usage 时按
全部预留量结算，不能乐观退还。Connector 在
Runtime 外部将具体平台 Event 转为 `ConnectorResult`，其中 Event 本身不得进入 Core。
`PreprocessResult` 只保存受控摘要和降级原因，不复制附件正文、URL、base64 或平台对象。
Connector、纯同步 Registry、进程 `close()`、健康/发现、离线 Eval 和跨 run Worker 不属于
run-scoped Port；它们必须改用有界 `ServiceCallContext`。Service principal 只证明哪个服务
在执行，不继承某个用户的权限；Worker 要执行用户发起的持久化命令时，必须复核命令自身
携带的 Authorization/Gate/Confirmation 证据、当前撤销状态和幂等键，不能伪造旧用户预算。

投递确认若跨进程或重启继续，由入口应用服务从 checkpoint 构造 derived
`PortCallContext`：保持同一 `run_id` 和 trace root，创建新的 span、deadline 与 cancellation，
按剩余预算恢复，并重新取得当前 Policy snapshot。旧 snapshot 只用于审计比较，不能覆盖
权限撤销；`CancellationToken` 本身永远不序列化。

Composition root 只通过 `PortBinding` 接收实现，并逐 operation 验证 Port ID、Protocol
major、请求 Schema digest、可接受响应 Schema 和
`required_capability_flags <= supported_capability_flags`；“有任意交集”不算兼容。成功后
生成 `NegotiatedBindingReceipt`，其 digest 随 checkpoint/Outbox 事件保存。无兼容交集时
拒绝绑定并保留 last-known-good，不允许 Adapter 静默忽略未知必填字段。可兼容新增字段必须
有默认值；持久化 DTO/Event 至少支持 N/N-1 reader 与显式 upcaster，调用方只发送双方协商
后的版本。

### 4.4 RuntimeState

```python
class RuntimePhase(StrEnum):
    RECEIVED = "received"
    PREPROCESSED = "preprocessed"
    CONTEXT_READY = "context_ready"
    PERCEIVED = "perceived"
    DECIDED = "decided"
    TOOLS_PLANNED = "tools_planned"
    TOOLS_EXECUTED = "tools_executed"
    VALIDATED = "validated"
    RESPONSE_PLANNED = "response_planned"
    COMPOSED = "composed"
    RENDERED = "rendered"
    READY_TO_EMIT = "ready_to_emit"
    DELIVERY_ACKNOWLEDGED = "delivery_acknowledged"
    MEMORY_EVALUATED = "memory_evaluated"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class RuntimeState:
    schema_version: int
    run_id: str
    phase: RuntimePhase
    message: MessageEnvelope
    actor: Actor
    received_at: datetime
    connector_revision: ComponentRevision
    invocation_options: RuntimeInvocationOptions
    start_digest: DigestString
    conversation_scope: ConversationScope
    budget: RuntimeBudget
    trace_context: TraceContext
    policy_snapshot_id: str
    negotiated_bindings: tuple[NegotiatedBindingReceipt, ...]
    preprocess_result: PreprocessResult | None = None
    memory_retrieval: MemoryRetrievalResult | None = None
    context_build: ContextBuildResult | None = None
    perception: PerceptionResult | None = None
    social_decision: SocialDecision | None = None
    response_plan: ResponsePlan | None = None
    capability_retrieval: CapabilityRetrievalResult | None = None
    tool_plan: ToolPlan | None = None
    tool_observations: tuple[ToolObservation, ...] = ()
    tool_validation: ToolValidationResult | None = None
    draft_response: DraftResponse | None = None
    final_response: ValidatedFinalResponse | None = None
    pending_result: RuntimeResult | None = None
    delivery_request: DeliveryRequest | None = None
    delivery_receipt: DeliveryReceipt | None = None
    reconciliation_expires_at: datetime | None = None
    pending_delivery_candidates: tuple[MemoryCandidate, ...] = ()
    memory_candidates: tuple[MemoryCandidate, ...] = ()
    memory_submissions: tuple[MemorySubmissionReceipt, ...] = ()
    trace: tuple[TraceEvent, ...] = ()
```

状态对象以不可变快照或等价的受控 reducer 更新。禁止用模块级全局变量存储单次运行数据。进程级缓存、限流器和 Provider 健康状态必须通过独立端口管理。

可见输出使用两段式完成协议：`run()` 最多推进到 `READY_TO_EMIT` 并返回；Output Adapter 投递后，`acknowledge_delivery()` 才推进 `DELIVERY_ACKNOWLEDGED -> MEMORY_EVALUATED -> COMPLETED`。`NO_REPLY` 等无输出路径不伪造投递，直接从决策阶段经过 Memory Write Gate 到 `COMPLETED`。Runtime 实现必须为等待确认的运行保存有界、可过期的状态，并使重复 receipt 幂等。

`DEFERRED` 和 `FAILED` 同时也是 Outcome 语义。只有无法形成安全可见输出时才进入同名终态；如果存在安全的边界说明或错误回复，状态仍走 `READY_TO_EMIT` 和投递确认路径，Outcome 保留 `DEFERRED` 或 `FAILED`。

调用方 cancellation 统一映射为 `Outcome.DEFERRED` 与稳定 reason code
`operation_cancelled`，不是随机实现成 `FAILED`。若还能安全生成边界说明，走正常投递路径；
否则原子保存当前可信 Observation（未确认副作用为 `UNKNOWN`）并进入 `DEFERRED` 终态。
在首个 state commit 前取消则不创建 run。取消后的自动恢复属于未来 durable workflow，当前
只能由显式新调用决定，不能偷偷继续旧 Tool/Model 请求。

### 4.5 RuntimeResult

```python
class Outcome(StrEnum):
    NO_REPLY = "no_reply"
    REACTION = "reaction"
    RESPONSE = "response"
    DEFERRED = "deferred"
    FAILED = "failed"

class DeliveryStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"

class DeliveryPartStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class DeliveryPartReceipt:
    schema_version: int
    part_id: str
    content_digest: DigestString
    status: DeliveryPartStatus
    platform_message_ref: MessageReference | None
    error_code: str | None

@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    schema_version: int
    delivery_id: str
    run_id: str
    delivery_request_digest: DigestString
    idempotency_key: str
    attempt: int
    adapter_revision: ComponentRevision
    status: DeliveryStatus
    parts: tuple[DeliveryPartReceipt, ...]
    acknowledged_at: datetime
    error_code: str | None

@dataclass(frozen=True, slots=True)
class TraceSummary:
    schema_version: int
    trace_id: str
    phases: tuple[RuntimePhase, ...]
    degraded_components: tuple[str, ...]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class RuntimeResult:
    schema_version: int
    run_id: str
    outcome: Outcome
    final_response: ValidatedFinalResponse | None
    reaction: Reaction | None
    delivery_request: DeliveryRequest | None
    completion: CompletionReceipt | None
    reason_codes: tuple[str, ...]
    trace_summary: TraceSummary

@dataclass(frozen=True, slots=True)
class CompletionReceipt:
    schema_version: int
    run_id: str
    final_phase: RuntimePhase
    delivery_status: DeliveryStatus
    completed_at: datetime
    memory_submissions: tuple[MemorySubmissionReceipt, ...] = ()
```

Outcome 不变量固定如下：`NO_REPLY` 不含 response/reaction；`REACTION` 只含 reaction；
`RESPONSE` 必须含已经绑定 Render 校验结果的 `final_response`；`DEFERRED` 和 `FAILED` 可以
携带一条安全的 `final_response`。存在可见输出时，`delivery_request` 必须是 checkpoint 中
同一个不可变对象，且其中 run/outcome/response/reaction digest 与 `RuntimeResult` 完全一致，
`completion=None`；调用方把该请求原样交给 Adapter，不能重新构造
delivery ID、幂等键、Scope、约束或授权。无输出时 `delivery_request=None` 且
`completion` 必须存在；Runtime 自行完成，并在该 `CompletionReceipt` 中记录
`NOT_REQUIRED`，不伪造 `DeliveryReceipt`。`NO_REPLY` 是正常业务结果，不是异常。

真实 `DeliveryReceipt.status` 不能是 `NOT_REQUIRED`。单段或全部分段确认成功才是
`SUCCEEDED`；至少一段成功且仍有失败/未知段时是 `PARTIAL`。`UNKNOWN` 不等于失败，也
不允许盲目整条重发。Adapter 必须按稳定 `delivery_id + part_id` 幂等，并保留每段回执，
使 Runtime 可以只协调未确认部分而不重复发送已成功内容。

Social Action 到 Outcome 的映射固定为：`IGNORE -> NO_REPLY`、`REACT -> REACTION`、`DIRECT_REPLY | USE_TOOLS | ASK_CLARIFICATION -> RESPONSE`、`DEFER -> DEFERRED`。`FAILED` 只来自标准化的执行失败，不是 Social Decision 可以主动选择的动作。

## 5. Runtime 端口

```python
RawEventT = TypeVar("RawEventT")

class InputConnector(Protocol[RawEventT]):
    async def convert(
        self,
        event: RawEventT,
        *,
        operation: ServiceCallContext,
    ) -> ConnectorResult: ...

class AttachmentRepository(Protocol):
    async def ingest_input(
        self,
        request: AttachmentIngestRequest,
        source: AsyncIterator[bytes],
        *,
        operation: ServiceCallContext,
    ) -> StoredContentRef: ...

    async def ingest_generated(
        self,
        request: AttachmentIngestRequest,
        source: AsyncIterator[bytes],
        *,
        call: PortCallContext,
    ) -> StoredContentRef: ...

    async def describe(
        self,
        request: AttachmentAccessRequest,
        *,
        call: PortCallContext,
    ) -> AttachmentDescriptor: ...

    def open(
        self,
        request: AttachmentAccessRequest,
        *,
        call: PortCallContext,
    ) -> AsyncContextManager[BoundedAttachmentStream]: ...

    async def delete(
        self,
        command: AttachmentDeleteCommand,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> AttachmentDeleteReceipt: ...

class MultimodalPreprocessor(Protocol):
    async def preprocess(
        self,
        request: PreprocessRequest,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> PreprocessResult: ...

@dataclass(frozen=True, slots=True)
class RuntimeInvocationOptions:
    schema_version: int
    route_hint: RouteHint | None
    entrypoint_id: str
    feature_flags: Mapping[str, bool]
    feature_flag_revision: str

@dataclass(frozen=True, slots=True)
class RuntimeStartRequest:
    schema_version: int
    connector_result: ConnectorResult
    options: RuntimeInvocationOptions
    start_digest: DigestString

class AgentRuntime(Protocol):
    async def run(
        self,
        request: RuntimeStartRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeResult: ...

    async def acknowledge_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> CompletionReceipt: ...

    async def reconcile_delivery(
        self,
        receipt: DeliveryReceipt,
        *,
        call: PortCallContext,
    ) -> "DeliveryReconciliationReceipt": ...

@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    schema_version: int
    state: RuntimeState
    revision: int
    expires_at: datetime

class RuntimeCommitDisposition(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DUPLICATE = "duplicate"

@dataclass(frozen=True, slots=True)
class RuntimeCommitResult:
    schema_version: int
    disposition: RuntimeCommitDisposition
    checkpoint: RuntimeCheckpoint

@dataclass(frozen=True, slots=True)
class RuntimeDedupRecord:
    schema_version: int
    message_dedup_key: MessageDedupKey
    run_id: str
    last_revision: int
    outcome: Outcome | None
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class RuntimeCommitRequest:
    schema_version: int
    run_id: str
    message_dedup_key: MessageDedupKey
    expected_revision: int | None
    next_state: RuntimeState
    expires_at: datetime
    reliable_events: tuple["DomainEvent", ...] = ()

class RuntimeStateStore(Protocol):
    async def commit(
        self,
        request: RuntimeCommitRequest,
        *,
        call: PortCallContext,
    ) -> RuntimeCommitResult: ...

    async def load(
        self,
        run_id: str,
        *,
        call: PortCallContext,
    ) -> RuntimeCheckpoint | None: ...

    async def delete(
        self,
        run_id: str,
        expected_revision: int,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> None: ...

    async def lookup_dedup(
        self,
        key: MessageDedupKey,
        *,
        call: PortCallContext,
    ) -> RuntimeDedupRecord | None: ...

@dataclass(frozen=True, slots=True)
class ContextWriteReceipt:
    schema_version: int
    message_id: str
    scope_digest: DigestString
    content_digest: DigestString
    idempotency_key: str
    revision: int
    store_revision: ComponentRevision
    stored_at: datetime

class ContextAccessPurpose(StrEnum):
    APPEND = "append"
    BUILD_CONTEXT = "build_context"
    RESOLVE_REPLY = "resolve_reply"

@dataclass(frozen=True, slots=True)
class ContextAccessRequest:
    schema_version: int
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    purpose: ContextAccessPurpose
    resource_digest: DigestString
    reference: MessageReference | None
    as_of: datetime
    maximum_items: int

@dataclass(frozen=True, slots=True)
class ContextAccessGrant:
    schema_version: int
    grant_id: str
    request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    purpose: ContextAccessPurpose
    resource_digest: DigestString
    maximum_items: int
    policy_revision: str
    expires_at: datetime
    integrity_digest: DigestString

@dataclass(frozen=True, slots=True)
class ContextAppendCommand:
    schema_version: int
    message: MessageEnvelope
    message_digest: DigestString
    conversation_scope: ConversationScope
    sensitivity: Sensitivity
    expires_at: datetime
    grant: ContextAccessGrant
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class ContextTruncationReceipt:
    schema_version: int
    input_tokens: int
    retained_tokens: int
    omitted_item_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

class ContextAccessPolicy(Protocol):
    async def issue(
        self,
        request: ContextAccessRequest,
        *,
        call: PortCallContext,
    ) -> ContextAccessGrant: ...

class ConversationContextStore(Protocol):
    async def append(
        self,
        command: ContextAppendCommand,
        *,
        call: PortCallContext,
    ) -> ContextWriteReceipt: ...

    async def recent(
        self,
        grant: ContextAccessGrant,
        *,
        before: datetime,
        limit: int,
        call: PortCallContext,
    ) -> tuple[ContextMessage, ...]: ...

    async def reply_chain(
        self,
        reference: MessageReference,
        grant: ContextAccessGrant,
        *,
        limit: int,
        call: PortCallContext,
    ) -> tuple[ContextMessage, ...]: ...

@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    schema_version: int
    message: MessageEnvelope
    scope: ConversationScope
    preprocess: PreprocessResult
    recent_messages: tuple[ContextMessage, ...]
    reply_chain: tuple[ContextMessage, ...]
    memory_retrieval: MemoryRetrievalResult
    group_policy: GroupPolicyView
    user_preferences: UserPreferenceView
    persona: PersonaRef
    capability_categories: tuple[str, ...]
    max_tokens: int

@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    schema_version: int
    snapshot: ContextSnapshot
    truncation: ContextTruncationReceipt
    producer: ComponentRevision

class ContextBuilder(Protocol):
    async def build(
        self,
        request: ContextBuildRequest,
        *,
        call: PortCallContext,
    ) -> ContextBuildResult: ...

@dataclass(frozen=True, slots=True)
class ComposeRequest:
    schema_version: int
    message: MessageEnvelope
    context: ContextSnapshot
    decision: SocialDecision
    response_plan: ResponsePlan
    direct_content: DraftContent | None
    verified_observations: tuple[ToolObservation, ...]
    tool_validation: ToolValidationResult | None
    response_constraints: ResponseConstraints

class ResponseComposer(Protocol):
    async def compose(
        self,
        request: ComposeRequest,
        *,
        call: PortCallContext,
    ) -> DraftResponse: ...

@dataclass(frozen=True, slots=True)
class DeliveryConstraints:
    schema_version: int
    max_parts: int
    max_bytes_per_part: int
    allow_forward_bundle: bool
    allowed_attachment_schemes: frozenset[str]
    reconciliation_window: timedelta

@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    schema_version: int
    delivery_id: str
    run_id: str
    request_digest: DigestString
    payload_digest: DigestString
    idempotency_key: str
    attempt: int
    outcome: Outcome
    response: ValidatedFinalResponse | None
    reaction: Reaction | None
    scope: ConversationScope
    reply_to: MessageReference | None
    constraints: DeliveryConstraints
    authorization: AuthorizationDecision
    attachment_access: tuple[AttachmentAccessRequest, ...]
    adapter_binding: NegotiatedBindingReceipt

class OutputAdapter(Protocol):
    async def deliver(
        self,
        request: DeliveryRequest,
        *,
        call: PortCallContext,
    ) -> DeliveryReceipt: ...

class DeliveryReconciliationAction(StrEnum):
    NO_CHANGE = "no_change"
    IMPROVED = "improved"
    CONFLICT = "conflict"
    EXPIRED = "expired"

@dataclass(frozen=True, slots=True)
class DeliveryReconciliationReceipt:
    schema_version: int
    run_id: str
    delivery_id: str
    action: DeliveryReconciliationAction
    previous_status: DeliveryStatus
    current_status: DeliveryStatus
    memory_submissions: tuple[MemorySubmissionReceipt, ...]
    reason_codes: tuple[str, ...]
    reconciled_at: datetime

@dataclass(frozen=True, slots=True)
class DomainEvent:
    schema_version: int
    event_id: str
    idempotency_key: str
    event_type: str
    aggregate_id: str
    occurred_at: datetime
    run_id: str
    aggregate_revision: int
    trace_id: str
    payload_schema: SchemaRef
    payload: Mapping[str, JsonValue]
    payload_digest: DigestString
    sensitivity: Sensitivity

class TraceEventKind(StrEnum):
    START = "start"
    END = "end"
    INSTANT = "instant"

class TraceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class TraceEvent:
    schema_version: int
    event_id: str
    run_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    operation_id: str
    phase: RuntimePhase
    event_type: str
    event_kind: TraceEventKind
    status: TraceStatus | None
    occurred_at: datetime
    duration_ms: int | None
    outcome: Outcome | None
    usage: ResourceUsage | None
    component_revisions: tuple[ComponentRevision, ...]
    reason_codes: tuple[str, ...]
    sanitized_attributes: Mapping[str, JsonValue]
    sensitivity: Sensitivity

class OutboxPublishOutcome(StrEnum):
    PUBLISHED = "published"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"

@dataclass(frozen=True, slots=True)
class OutboxRecord:
    schema_version: int
    event: DomainEvent
    lease_id: str
    attempts: int

@dataclass(frozen=True, slots=True)
class OutboxPublishReceipt:
    schema_version: int
    event_id: str
    outcome: OutboxPublishOutcome
    attempts: int
    next_attempt_at: datetime | None

class DomainEventOutbox(Protocol):
    async def claim(
        self,
        limit: int,
        *,
        lease_until: datetime,
        operation: ServiceCallContext,
    ) -> tuple[OutboxRecord, ...]: ...

    async def acknowledge(
        self,
        event_id: str,
        lease_id: str,
        outcome: OutboxPublishOutcome,
        *,
        operation: ServiceCallContext,
    ) -> OutboxPublishReceipt: ...
```

`RuntimeStartRequest.start_digest` 对除自身外的完整规范请求计算。Runtime 必须验证
`connector_result.message/actor` 身份一致、`received_at` 合法、Adapter revision 可解析、
`call.run_id` 尚未使用，并把这些证据与 options 原样保存到首个 checkpoint。
`RuntimeInvocationOptions` 只允许携带已校验的逻辑提示，例如 Model Router 的 `RouteHint`、
兼容入口标识和带 revision 的 feature flag 快照；不得包含 AstrBot Event、UMO、Provider
对象、凭据或任意平台句柄。AstrBot Adapter 必须在进入 Core 前把 UMO 解析为允许的逻辑
Provider 引用。

Connector 是唯一允许处理平台附件 URL/句柄的组件。它在返回 Envelope 前通过
`AttachmentRepository.ingest_input()` 流式写入正文；Repository 强制总字节上限、超时、
MIME sniff、digest、Scope、Sensitivity、TTL 和幂等，不接受模型提供的 URL/Path。
`open()` 只接受与当前 run/purpose、Scope、payload digest 和最新 AuthorizationDecision 匹配的
`AttachmentAccessRequest`，返回有界异步 stream；stream 不得进入 State、模型 DTO、Trace
或异常。Preprocessor、Model Provider Adapter 和 Output Adapter 只能通过各自 purpose 读取。
生成资产通过 `ingest_generated()` 先归档再返回 opaque ref。删除必须幂等并服从保留/审计
策略；更换本地对象存储、S3 或数据库 Blob Adapter 不改变 Core DTO。

`RuntimeStateStore.commit()` 以 `expected_revision=None` 创建运行，否则执行 CAS；它不决定
合法 phase，状态机仍由 Runtime reducer 持有。`reliable_events` 必须与新 checkpoint 在
同一事务中写入 Outbox，任一失败则两者都不提交。无法提供该原子性的 Adapter 不能承载
可靠 Memory 写入等业务事件，只能运行不依赖 Outbox 的功能。等待 Delivery 的 checkpoint
必须有 TTL，重复或过期 commit 返回类型化冲突。`ConversationContextStore` 是短期、按
会话隔离的近期消息来源，不是长期 Memory Repository。Policy 根据当前 Actor、Scope、
purpose、具体 resource、as-of 和硬上限签发完整性保护的 `ContextAccessGrant`；Store 在后端
查询内复核 request/Actor/Scope/resource digest、purpose、expiry 与数量上限。Append 只能
使用绑定该 message digest 的 `APPEND` grant；reply-chain grant 必须绑定具体
MessageReference；
保存 message/scope/content digest、Sensitivity、TTL 与幂等键；读取只能使用对应 purpose
grant。缺字段、过期 grant 或越界记录使整批失败并审计，不能先全局读取再由 Python 过滤。
正文按数据分类加密，TTL/删除不影响长期 Memory。

初次 commit 对 `(platform, bot_id, conversation_id, message_id)` 的 `MessageDedupKey` 建立
唯一约束；不假定新平台的 message ID 在整个 Bot 下全局唯一。并发重复消息返回
`RuntimeCommitResult(DUPLICATE, existing_checkpoint)`，不创建第二个运行，也不依赖“先查
再写”的竞态窗口。Checkpoint 清理后，`lookup_dedup()` 仍在保留期内返回最小 tombstone；
它只用于幂等判断，不能恢复消息正文或权限。

删除或 TTL 清理 checkpoint 不得级联删除尚未 PUBLISHED/DEAD_LETTER 的 Outbox record；
反过来，Outbox ack 也不能删除 Runtime State。两类记录分别满足完成/保留条件后由 GC
清理，并保留最小 tombstone 使晚到 receipt 与重复 event 仍可幂等识别。

`DeliveryReceipt.run_id` 是 acknowledgement 的唯一运行绑定；端口不再接收第二份 run
ID。Runtime 校验 receipt 对应一条等待确认的运行，delivery request digest、`delivery_id`、
幂等键和 attempt 匹配，
时间带时区，每个成功引用属于目标 platform/Bot/conversation，并使重复或晚到 receipt
按单调规则合并：已确认成功的 part 不得退回失败/未知，互相冲突的成功引用触发审计而非
覆盖。每个 part 还必须回传实际规范内容 digest；同一 part ID 对应不同 digest 或 Adapter
binding revision 漂移时返回冲突，不能猜测哪一份已发送。`FAILED`、`PARTIAL` 或 `UNKNOWN`
仍可推进 `DELIVERY_ACKNOWLEDGED`，但不得生成
“已送达”记忆。Receipt 不包含原始 Event、平台异常正文或凭据。

初始 acknowledgement 可以让原 run 完成；之后的回执不执行 `COMPLETED -> phase` 跳转，
而是在 `DeliveryConstraints.reconciliation_window` 内调用独立、幂等的
`reconcile_delivery()`，读取保留的 bounded checkpoint/reconciliation evidence 并按 CAS
合并。记录必须保存原 DeliveryRequest digest、逐 part digest/状态、当前 receipt、仍待
`SUCCESS_REQUIRED` 的 candidate 与证据，以及 policy/component revision；按 Sensitivity
加密并在窗口结束后删除。窗口内不得只留下无法重做 Gate 的最小 dedup tombstone。若状态
改善为完整 SUCCEEDED，Reconciler 只对这些 candidate 重新授权并执行 Write Gate。相同
receipt 不重复写，冲突回执触发审计，窗口外只记录 EXPIRED。

`DomainEventOutbox` 不提供独立 `append()`；可靠事件只能随
`RuntimeStateStore.commit()` 原子进入 Outbox。Dispatcher 使用 lease claim、按 event ID
幂等发布并显式 acknowledge；同一 aggregate 按 `aggregate_revision` 有序消费，consumer 在
处理前校验 payload Schema/digest 并使用显式 upcaster。超时 lease 可重领，失败有最大 retry
与 dead-letter 状态。
它不能推进同步 phase、授予权限、调用 Tool 或发送平台消息。可丢失的 Trace/指标走独立
best-effort Sink，不伪装成可靠 Outbox 事件。

可靠业务事件的数据策略是“完成校验并最小化”，不等同于把业务所需字段全部打码。
Memory write event 只能携带已经授权的规范化 record、最小 evidence 引用和 Gate decision；
`RESTRICTED` 内容禁止入队，Personal/Sensitive payload 必须加密存储、按消费者授权、设置
TTL 并在 dead-letter 中保持同等保护。任何日志、Trace 或指标投影都必须另外经过 Redactor。

Perception、Social Decision、Memory、Capability、Tool Runtime、Model Router 和 Persona 的
run-scoped 端口由各自设计文档定义，并接收 `PortCallContext`；显式声明的 health/discovery/
worker/artifact 操作接收 `ServiceCallContext`。Orchestrator 只依赖端口，不依赖实现类。

## 6. 状态转换与不变量

### 6.1 入口与预处理

1. 入口应用校验 ConnectorResult、创建 run ID/root context，并把完整
   `RuntimeStartRequest` 交给 Runtime。
2. 校验 Envelope 版本、必填身份、Actor 一致性、接入 revision 和消息大小。
3. 用 `(platform, bot_id, conversation_id, message_id)` 做幂等去重。
4. 计算 `ConversationScope`；无法确定 Scope 时拒绝读取附件、Memory 和隐私能力。
5. 为任务所需附件取得按 purpose 绑定的授权，再调用可选预处理器；只保存受控摘要。

不变量：原始 Event 不进入 Agent State；预处理器不能直接写长期记忆。

### 6.2 记忆与上下文

1. 由可信策略根据 ConversationScope、Actor、Persona 和 Memory Type 构造完整 `MemoryScope` selector。
2. 先以完整 Memory Scope 过滤 Memory Repository。
3. 再在已过滤集合中做语义召回。
4. Context Builder 合并当前消息、最近消息、回复链、附件摘要、群策略、用户偏好、Persona 元数据、Scoped Memory 和能力摘要。

不变量：Context Builder 只读；任何长期写入必须在回复形成后经过 Memory Write Gate。

### 6.3 感知与社交决策

Perception 输出结构化语义信号；Social Decision 将其与确定性权限、限流、群策略和对话信号组合，输出 `IGNORE`、`REACT`、`DIRECT_REPLY`、`USE_TOOLS`、`ASK_CLARIFICATION` 或 `DEFER`。具体契约见 `perception-and-social.md`。

不变量：Persona 不参与是否回复和是否允许调用工具的判断。

### 6.4 回答档位规划

只有可见动作进入 `ResponseProfilePolicy`。策略输入当前消息中的明确简短/详细证据、经过校验的
TaskComplexityAssessment、SocialDecision、会话/群策略、允许的用户偏好、平台限制和 Runtime
Budget，输出版本化 `ResponsePlan(SHORT | MEDIUM | LONG)`。

每条可见路径只形成一个最终 ResponsePlan：直接回答在 Social Decision 后、构造用户可见
ModelRequest 前生成；工具路径在 Observation Validator 完成后、进入
`RESPONSE_COMPOSITION` 前生成。Tool Planner 不消费 Answer Profile，也不存在随后悄悄扩大
预算的“初始计划”。当前消息明确要求优先于持久偏好，安全警告、拒绝原因、必要引用和平台
上限始终优先。

状态转换是分支汇合，而不是固定把 RESPONSE_PLANNED 放在工具之前：

```text
DECIDED
  -> DIRECT_REPLY -> RESPONSE_PLANNED
  -> TOOLS_PLANNED -> TOOLS_EXECUTED -> VALIDATED -> RESPONSE_PLANNED
RESPONSE_PLANNED -> COMPOSED -> RENDERED -> READY_TO_EMIT
```

不变量：Answer Profile 不选择 Model Tier 或 Provider。Runtime 只把可见输出上限、Response
Plan digest 和结合 Reasoning Profile 后的总生成预算投影给 TierPolicy/Router。Renderer 不得
扩展到计划之外，Final Validator 必须检查实际 Unicode grapheme、可见 Token、投递分片及必要
内容保持。

### 6.5 能力与工具循环

仅当动作是 `USE_TOOLS` 时进入：

```text
Capability Retrieval -> Planner -> Executor -> Observation -> Validator
                                     ^                         |
                                     +---- continue/retry -----+
```

- Planner 只看到 Top-K 能力摘要，不看到所有原始工具；
- 每次执行前重新校验权限、上下文和敏感参数；
- 默认最大工具步数为 4，配置只能在全局安全上限内调整；
- Validator 只能要求继续、重试、澄清或结束，不能绕过最大步数；
- 每个 Observation 标记来源、耗时、错误和数据敏感级别。

### 6.6 合成、人格与输出

Response Composer 先生成事实稳定的 `DraftResponse`，包括正文语义、来源、警告、错误和
不可修改约束。Persona Renderer 只调整表达。Runtime 返回同时含验证后内容与权威
`DeliveryRequest` 的 `RuntimeResult` 并停在 `READY_TO_EMIT`；调用方只能把该 request 原样
交给绑定 revision 的 Output Adapter。QQ 的 `Plain`、`At`、`Image`、`Nodes` 由 Adapter 创建。

Composer 和 Persona 都消费同一 `ResponsePlan`。内容短于上限不代表 Profile 正确；Validator
还需验证 SHORT/MEDIUM/LONG 的结构目标、明确用户详略要求、必要事实/引用和冗余边界。

### 6.7 记忆写入

Output Adapter 投递后调用 `acknowledge_delivery()`。Runtime 先记录受控
`DeliveryReceipt`，再让 Memory Write Gate 对自动候选逐一判断来源、事实性、敏感度、
未来价值、冲突、TTL、Scope 和是否需要用户确认。同步落盘返回 `PERSISTED`；异步路径把
授权写命令随 checkpoint 原子写入 Outbox，只返回 `QUEUED` submission，不把排队说成已经
持久化。输出失败、部分成功或未知时不得记录“已成功告知用户”一类事件。显式
`/remember` 等用户事务可走独立、可审计的写入用例，不依赖回复投递成功。

### 6.8 无入站消息的主动出站边界

定时日报和 Conversation Probe 不进入 `AgentRuntime.run(RuntimeStartRequest)`，因为它们没有
真实 ConnectorResult、用户 Actor 或入站 message ID。独立 `ProactiveDeliveryOrchestrator`
使用 target-bound `InitiatedRunRequest`、服务主体与原订阅/操作员授权证据，复用 Capability、
Composer、Persona、Output 和 Delivery reconciliation。

Scheduler 只能产生 occurrence，不能调用 MCP 或发送；现有 `DomainEventOutbox` 也继续禁止调用
Tool 和平台消息。主动发送使用独立持久 Dispatch Store、CAS claim 和
`message.send.proactive` 权限，并在发送前复核 quiet hours、频控、订阅 revision、授权与 kill
switch。完整契约见 `proactive-messaging.md`。

## 7. 超时、取消与错误

统一错误分类建议放在 `domain/errors.py`：

```python
@dataclass(frozen=True, slots=True)
class ErrorInfo:
    schema_version: int
    code: str
    category: ErrorCategory
    retryable: bool
    outcome_unknown: bool
    public_message_key: str
    reason_codes: tuple[str, ...]

class DududaError(Exception):
    info: ErrorInfo
```

所有 Adapter 都必须把 SDK、HTTP、数据库和平台异常归一化为 `ErrorInfo`。`retryable`
只是错误分类，Runtime 仍需同时检查幂等性、预算和 deadline；`outcome_unknown=true`
表示外部副作用可能已经发生，不能当作普通失败自动重试。公开错误只使用稳定
`public_message_key`，不携带供应商正文、路径、命令或凭据。

| 错误 | 默认处理 |
| --- | --- |
| `ConnectorConversionError` | 不进入 Runtime；记录平台、Adapter revision 和脱敏 reason code |
| `InvalidEnvelopeError` | 不进入 Runtime，Adapter 记录脱敏诊断 |
| `PreprocessUnavailableError` | 文本足够时降级；任务依赖附件时进入澄清或安全失败 |
| `ScopeResolutionError` | 隐私相关能力 fail closed；可返回澄清 |
| `RuntimeStateConflictError` | 重新加载 checkpoint 并按幂等规则处理；不得覆盖较新 revision |
| `MemoryUnavailableError` | 不带记忆继续，并在 Trace 标记 degraded |
| `ModelUnavailableError` | 使用该角色允许的确定性降级，不跨隐私边界换 Provider |
| `CapabilityDeniedError` | 不执行工具，返回权限说明或静默 |
| `ToolTimeoutError` | Validator 决定有限重试或降级，不无限循环 |
| `CompositionError` | 用结构化工具结果生成最小事实回复 |
| `PersonaRenderError` | 返回未渲染但安全的 Draft，不丢失事实与拒绝 |
| `DeliveryError` | 返回 `PARTIAL`、`FAILED` 或 `UNKNOWN` Receipt；不得推断为成功投递 |
| `OutboxUnavailableError` | 非关键遥测可降级；可靠业务事件未持久化时不得宣称完成 |
| `DeadlineExceededError` | 停止新步骤，按当前可信状态返回降级结果 |
| `OperationCancelledError` | 映射 `DEFERRED/operation_cancelled`；停止新步骤，未确认副作用保持 `UNKNOWN` |

安全和权限检查失败必须 fail closed。记忆、个性化和非关键渲染失败可以 fail soft。禁止捕获所有异常后伪装成成功；未知异常标准化为 `RuntimeInternalError`，仅向用户返回稳定错误码。

## 8. Trace 与可观察性

每次运行生成 `run_id`，每个阶段记录：

- 阶段、开始/结束时间、耗时和 outcome；
- 使用的模型角色、Provider/模型公开标识及 token 统计；
- 候选能力 ID、工具 ID、重试次数和标准化错误；
- Memory Scope 哈希和命中数量，不记录完整记忆正文；
- 社交决策 reason codes；
- 降级路径。

默认不记录原始消息、Prompt、工具敏感参数、模型完整输出、QQ 号、Cookie、Token 或附件内容。需要诊断采样时必须显式启用、设置 TTL、执行脱敏并限制访问。

可复现实验使用版本化 manifest，而不是只在日志里写几个字符串：

```python
@dataclass(frozen=True, slots=True)
class EvalManifest:
    schema_version: int
    experiment_id: str
    dataset_id: str
    dataset_revision: str
    split_digest: DigestString
    sample_count: int
    strata: Mapping[str, int]
    component_revisions: tuple[ComponentRevision, ...]
    policy_revisions: tuple[str, ...]
    snapshot_revisions: Mapping[str, str]
    schema_digests: tuple[str, ...]
    artifact_digests: tuple[str, ...]
    random_seeds: tuple[int, ...]
    repetitions: int
    primary_metric_ids: tuple[str, ...]
    metric_directions: Mapping[str, Literal["higher", "lower"]]
    minimum_effects: Mapping[str, Decimal]
    frozen_thresholds: Mapping[str, Decimal]
    zero_tolerance_risk_bounds: Mapping[str, Decimal]
    baseline_ids: tuple[str, ...]
    confidence_level: Decimal
    resampling_method: Literal["paired_bootstrap", "cluster_bootstrap", "hierarchical_bootstrap"]
    resampling_unit: str
    cluster_keys: tuple[str, ...]
    resamples: int
    minimum_stratum_counts: Mapping[str, int]
    multiple_comparison_method: str | None
    target_power: Decimal | None
    minimum_detectable_effect: Decimal | None
    started_at: datetime

@dataclass(frozen=True, slots=True)
class ArtifactRef:
    schema_version: int
    component_id: str
    revision: str
    digest: DigestString
    immutable_uri: str

@dataclass(frozen=True, slots=True)
class EvalMetric:
    metric_id: str
    stratum_id: str | None
    baseline_id: str | None
    direction: Literal["higher", "lower"]
    value: Decimal
    effect_size: Decimal | None
    numerator: int | None
    denominator: int | None
    confidence_level: Decimal
    confidence_low: Decimal | None
    confidence_high: Decimal | None
    interval_method: str
    resampling_unit: str

@dataclass(frozen=True, slots=True)
class ZeroToleranceGateResult:
    gate_id: str
    stratum_id: str | None
    observed_violations: int
    denominator: int
    confidence_level: Decimal
    one_sided_upper_bound: Decimal
    frozen_risk_threshold: Decimal
    passed: bool

@dataclass(frozen=True, slots=True)
class EvalReport:
    schema_version: int
    experiment_id: str
    metrics: tuple[EvalMetric, ...]
    zero_tolerance_gates: tuple[ZeroToleranceGateResult, ...]
    repeated_run_variance: Mapping[str, Decimal]
    report_digest: DigestString

@dataclass(frozen=True, slots=True)
class EvalArtifactReceipt:
    schema_version: int
    experiment_id: str
    manifest_digest: DigestString
    report_digest: DigestString
    stored_at: datetime

class RevisionedArtifactStore(Protocol):
    async def resolve(
        self,
        revision: ComponentRevision,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> ArtifactRef: ...

class EvalArtifactStore(Protocol):
    async def put(
        self,
        manifest: EvalManifest,
        report: EvalReport,
        *,
        call: ServiceCallContext,
    ) -> EvalArtifactReceipt: ...
```

Artifact Store 必须按 digest 返回不可变配置、Prompt 模板、模型/Provider descriptor、
Registry snapshot 和评测代码引用；无法解析任一 revision 的运行只能标为不可完全重放。
`immutable_uri` 是 Artifact Store 签发的 opaque locator，不接受模型/消息提供的路径或 URL。
数据许可、同意/脱敏状态和保留期属于 dataset revision 元数据。测试集在阈值冻结前隔离，
不能根据最终结果反复调参。群聊样本默认以 conversation/group 为 cluster，不得把同群消息
当独立同分布样本做普通 bootstrap。所有 primary endpoint、方向、最小效果量、分层最低样本、
重采样单位、功效目标和多重比较方法在运行前冻结。零容忍 Gate 只有在观测违规为 0 且单侧
置信上界低于冻结风险阈值时通过；“本次没看到违规”不等于证明风险为零。模型 seed 必须进入
请求并记录 Provider 是否实际支持；不支持确定性 seed 时用预注册的重复运行估计方差。

## 9. AstrBot 兼容层

AstrBot 兼容面按 Dududa 2.0 默认路径与历史迁移材料区分：

### 9.1 `astrbot_plugin_dududa_core`

- 保留插件 ID、命令名、中文回复和配置文件兼容；
- `main.py` 逐步只负责 Event -> Envelope、命令注册、Runtime 调用和 ValidatedFinalResponse -> AstrBot Result；
- `/course`、`/admin` 等命令可先调用新 application use case，不强制经过社交决策；
- `ALL priority=8` 和 `stop_event()` 行为在契约测试证明等价前不改变。

### 9.2 `astrbot_plugin_target_talk`

- 已退出默认 Compose 和 Dududa 2.0 入站路径；
- 旧白名单、目标配置、概率、冷却和 Prompt 只作为迁移/回滚材料保留；
- 主动参与由 S15E Governed Probe / 主动 Runtime 承担，不能通过旧插件绕过群级服务、授权、预算和发送边界。

### 9.3 `astrbot_plugin_reply_polish`

- 默认关闭，仅作为 Dududa 1.0 LONG-only 输出兼容层保留；
- SHORT、MEDIUM、缺失或未知 AnswerProfile 始终普通发送；
- LONG 单段仍普通发送，只有群聊、多纯文本 part 且无附件时才允许合并转发；定向目标保留在响应契约中，但转发呈现不另发 `@`；
- 它不是 Persona Renderer，正式 Dududa 2.0 Runtime 不依赖它。

新 Package 必须在 AstrBot 派生镜像中安装；不得通过让 Domain import 相对插件路径来规避打包。

## 10. 隐私与安全

- Scope 构造和权限检查发生在任何记忆、模型或工具调用之前；
- 外部消息、网页、MCP 输出和附件摘要一律视为不可信数据；
- Runtime State 不保存 Provider 凭据，路由只携带 credential reference；
- 私聊数据不得进入群聊 Context，跨群数据不得合并；
- 模型和工具仅收到完成任务所需的最小字段；真实 QQ 和群号默认不发送给模型；
- 输出前执行事实约束、安全策略和目标会话校验；
- Trace、Eval fixture 和失败快照只能使用脱敏或合成数据。

## 11. 测试设计

### Unit

- 每个合法和非法阶段转换；
- RuntimeStartRequest provenance/start digest、Connector conformance、Scope 构造、四元组幂等键、总 deadline 和取消；
- canonical codec 跨语言 golden vectors、domain separation、旧版本 verifier/upcaster；
- PortBinding 的逐 operation Protocol/Schema、required/offered capability 协商、receipt、不兼容拒绝和 last-known-good；
- AttachmentRepository 的流式大小/MIME/digest、Scope/purpose 授权、TTL、删除和恶意文件负向测试；
- Preprocess 降级、RuntimeStateStore 原子 state/event commit、revision/CAS/TTL 和重复 Delivery Receipt；
- 晚到 Delivery 单调 reconciliation、窗口过期、冲突引用和 SUCCESS_REQUIRED 候选只提交一次；
- ContextAccessGrant 完整性/过期/purpose，以及 ConversationContextStore 的跨 Scope、TTL、Sensitivity 负向矩阵与有界读取；
- 六种 Social Action 的分支；
- ResponseProfilePolicy 优先级、3x3 Complexity/Profile 正交矩阵、动态预算和 Final Profile
  Validator；
- 工具最大步数、重试上限和 Validator 终止；
- Persona 失败走确定性 Finalizer，且输出仍通过 Render Validator 与 Content Safety；
- Memory 读取失败的无记忆降级。

### Contract

- `InputConnector`、`AttachmentRepository`、`MultimodalPreprocessor`、`RuntimeStateStore`、
  `ContextAccessPolicy`、`ConversationContextStore`、`ContextBuilder`、`PerceptionEngine`、
  `SocialDecisionEngine`、`ModelRouter`、Memory Repository、Capability Provider、
  `MemoryCandidateExtractor`、`MemoryWriteGate`、`MemoryAdministration`、
  `ResponseProfilePolicy`、`ResponseComposer`、`PersonaRenderer`、`RenderValidator`、`OutputAdapter`、
  `DomainEventOutbox` 及 security.md 定义的 Safeguard Ports；
- AstrBot Event/Result 与 MessageEnvelope/FinalResponse 的双向转换；
- Protocol 实现的错误必须归一化，不能泄漏供应商异常类型。

### Integration

- AstrBot Event -> Runtime -> AstrBot Result；
- 直接回复、工具回复、澄清、忽略和降级；
- iCourse MCP 调用的超时、错误和来源标注；
- Response -> Memory Write Gate；
- Output Adapter 分片/部分成功/未知回执 -> checkpoint CAS -> CompletionReceipt；
- Outbox lease 重领、发布幂等、重复 Event ID、dead-letter 和 state/event 原子写入失败；
- ServiceCallContext Worker 不能继承用户权限，queued Memory command 必须重验原授权；
- TargetTalk 与通用入口对同一消息不重复回复。
- initiated-run 不接受伪造 ConnectorResult，Proactive Scheduler/Policy/Dispatch 与普通
  Runtime/DomainEventOutbox 权限和幂等空间严格分离；

### Privacy/Eval

- A 群、B 群、私聊、不同用户和不同 Persona 的隔离矩阵；
- Trace 和错误日志无原文、凭据及真实标识；
- 是否应回复、Answer Profile、工具选择、参数抽取和 OC 一致性的 JSONL Eval。
- 主动日报/Probe 的 fake-clock、来源新鲜度/引用、错误目标、重复/quiet-hour/退订后发送和
  no-send Shadow Eval；
- 仅在独立 S20 获批并实施时，验证 Bandit action-set/propensity/before-action 日志、
  IPS/SNIPS/DR、删失反馈、群级 bootstrap 与 baseline 回滚；它不是 S18/S19 或主动出站门禁。

## 12. 当前实现状态与迁移顺序

| 能力 | 当前状态 | 首个迁移动作 |
| --- | --- | --- |
| Message Envelope/Connector | S01-S04 已实现版本化 Domain 类型和 AstrBot Adapter | 真实 Attachment Source 与第二平台仍未实现 |
| Runtime State/Orchestrator | S10 已实现显式 @ 闭环；S23 又闭合一条默认关闭的 iCourse 单步 Tool 路径 | 运行中部署、Memory/Attachment、其他 Tool Schema 和主动出站未闭合 |
| Context Builder | S09/S10 有界当前消息 Context 已实现 | 可信多轮、附件与生产 Memory 接入未完成 |
| Perception/Social Decision | S09 契约与策略已实现；S23 Production 使用 Luna/Haiku Hybrid Perception | 真实数据校准、近期群聊、多轮和附件证据仍缺 |
| Tool Runtime | iCourse 已作为首个自然语言 Capability 纵切，通过确定性单步 Planner 和 Unified MCP 执行 | 教务、校车、二课 Schema Planner、失败答复和运行中部署未完成 |
| Response Composer/Persona | S15 已实现 ResponsePlan、typed 资产、generation-bound Persona 和 Validator；S23 Tool Observation 已进入 DirectChat/Persona 单次输出 | 多 Persona 产品资产和人工中文风格 Eval |
| Trace/Rollout | S10 receipt 与 S11 脱敏指标/持久 claim 已实现 | 后续模块、真实 SLO 和最终授权证据 |
| Proactive Orchestrator | S15A-S15E 离线 no-send 链已实现 | 真实 Source/Projection/Output 与授权发送未实现 |

后续顺序以 `../refactor/implementation-plan.md` 为准：S12-S15 -> S15A-S15E -> S16-S19 ->
S22 -> 最终 S23。每一步保持原命令和部署可运行。

## 13. 扩展点

- 新平台只新增 Input/Output Adapter；
- 新预处理器通过 `MultimodalPreprocessor` 注册；
- 新 Memory 后端实现 `MemoryRepository`，Iris 是其中之一；
- 新能力通过 Registry 和 Provider 注册，不改 Orchestrator；
- 新模型供应商只实现 Model Provider Adapter；
- 新附件存储实现 `AttachmentRepository`，不向 Core 暴露 Path/URL/stream；
- Contextual Bandit 只实现硬过滤后的排序 Port，不能修改 Orchestrator 或授权链；
- 新 Persona 通过 Registry 加载，不修改权限和工具逻辑；
- 后续可增加 durable workflow，但必须保持相同 RuntimeState 和幂等契约。

任何新公开 Port 的顶层请求、结果、持久化记录和事件都必须使用版本化、不可变 DTO；
run-scoped 异步 Port 使用 `PortCallContext`，明确列出的 lifecycle/background 例外使用带
Service Principal 的 `ServiceCallContext`。每个 Port 提供 Fake 与至少一个真实 Adapter 的共享 Contract Test，并将
供应商异常转换为 Domain Error。破坏性 Schema 变化发布新版本；不得通过在 `metadata`
中塞入平台对象来规避版本升级。
