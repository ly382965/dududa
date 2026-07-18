# Agent Runtime 设计

## 1. 文档状态

- 阶段：Phase 1，目标设计，尚未实现。
- 目标代码位置：`packages/dududa-agent/src/dududa/runtime/`。
- 适用入口：AstrBot、后续 Web/测试入口以及不依赖具体平台的离线 Eval。
- 兼容约束：迁移期间保留 `astrbot_plugin_dududa_core`、`astrbot_plugin_target_talk`、`astrbot_plugin_reply_polish` 三个插件 ID、配置和事件语义。

本文定义一次嘟嘟哒 Agent 执行的边界、状态、端口和失败语义。它不规定某个模型供应商、MCP 进程或 AstrBot Event 的具体实现。

## 2. 目标与非目标

Runtime 的目标是把一次消息处理变成可观察、可中止、可测试的显式状态转换：

```text
MessageEnvelope + Actor
  -> Preprocess
  -> Scoped Memory Retrieval
  -> Context Builder
  -> Perception
  -> Social Decision
  -> Direct Reply | Capability/Tool Loop | No Reply
  -> Response Composer
  -> Persona Renderer
  -> RuntimeResult (READY_TO_EMIT or no-output terminal result)
  -> Output Adapter, when visible output exists
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

## 4. 核心数据契约

以下代码是设计契约，字段名在 Phase 2 实现前可通过 ADR 调整，但不得用无结构 `dict` 取代关键边界。

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
- `content_ref` 是由受信 Attachment Repository 解析的有界 opaque ID，不是任意本地路径或未校验 URL；
- Adapter 在构造失败时不得让半完整消息进入 Runtime。

全仓 Python 类型名统一为 `JsonValue`。它只允许 `None`、布尔、有限数字、字符串、不可变序列和字符串键的递归不可变映射；不允许 Event、Path、文件句柄、自定义 Provider 对象或任意可变容器。

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
```

AstrBot Adapter 从 Event 和受信配置解析 `Actor`；Runtime 校验 Actor 的 platform、Bot 和 user 与 Envelope 完全一致。`roles` 与 `deny_flags` 是已解析的确定性授权输入，不发送给 Perception 模型。

`ConversationScope` 是会话和上下文边界，不包含发言者身份，也不能直接当作 Memory 查询 selector。用户身份保留在 `MessageEnvelope` 和 `Actor`；Memory Policy 再根据 `memory_type` 构造包含可选或必填 `user_id` 的 `MemoryScope`。缺少该类型要求的任一字段时 fail closed。

### 4.3 RuntimeState

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
    run_id: str
    phase: RuntimePhase
    message: MessageEnvelope
    actor: Actor
    conversation_scope: ConversationScope
    budget: RuntimeBudget
    context: ContextSnapshot | None = None
    perception: PerceptionResult | None = None
    social_decision: SocialDecision | None = None
    candidate_capabilities: tuple[CapabilityCandidate, ...] = ()
    tool_plan: ToolPlan | None = None
    tool_observations: tuple[ToolObservation, ...] = ()
    draft_response: DraftResponse | None = None
    final_response: FinalResponse | None = None
    memory_candidates: tuple[MemoryCandidate, ...] = ()
    trace: tuple[TraceEvent, ...] = ()
```

状态对象以不可变快照或等价的受控 reducer 更新。禁止用模块级全局变量存储单次运行数据。进程级缓存、限流器和 Provider 健康状态必须通过独立端口管理。

可见输出使用两段式完成协议：`run()` 最多推进到 `READY_TO_EMIT` 并返回；Output Adapter 投递后，`acknowledge_delivery()` 才推进 `DELIVERY_ACKNOWLEDGED -> MEMORY_EVALUATED -> COMPLETED`。`NO_REPLY` 等无输出路径不伪造投递，直接从决策阶段经过 Memory Write Gate 到 `COMPLETED`。Runtime 实现必须为等待确认的运行保存有界、可过期的状态，并使重复 receipt 幂等。

`DEFERRED` 和 `FAILED` 同时也是 Outcome 语义。只有无法形成安全可见输出时才进入同名终态；如果存在安全的边界说明或错误回复，状态仍走 `READY_TO_EMIT` 和投递确认路径，Outcome 保留 `DEFERRED` 或 `FAILED`。

### 4.4 RuntimeResult

```python
class Outcome(StrEnum):
    NO_REPLY = "no_reply"
    REACTION = "reaction"
    RESPONSE = "response"
    DEFERRED = "deferred"
    FAILED = "failed"

class DeliveryStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    run_id: str
    status: DeliveryStatus
    acknowledged_at: datetime
    platform_message_ref: MessageReference | None
    error_code: str | None

@dataclass(frozen=True, slots=True)
class RuntimeResult:
    run_id: str
    outcome: Outcome
    final_response: FinalResponse | None
    reaction: Reaction | None
    reason_codes: tuple[str, ...]
    trace_summary: TraceSummary
    requires_delivery_ack: bool

@dataclass(frozen=True, slots=True)
class CompletionReceipt:
    run_id: str
    final_phase: RuntimePhase
    delivery_status: DeliveryStatus
    memory_write_receipts: tuple[MemoryWriteReceipt, ...] = ()
```

Outcome 不变量固定如下：`NO_REPLY` 不含 response/reaction；`REACTION` 只含 reaction；`RESPONSE` 必须含 `final_response`；`DEFERRED` 和 `FAILED` 可以携带一条安全的 `final_response`。存在可见输出时 `requires_delivery_ack=true`，Adapter 必须回传 `DeliveryReceipt`；无输出路径由 Runtime 自行完成。`NO_REPLY` 是正常业务结果，不是异常。

Social Action 到 Outcome 的映射固定为：`IGNORE -> NO_REPLY`、`REACT -> REACTION`、`DIRECT_REPLY | USE_TOOLS | ASK_CLARIFICATION -> RESPONSE`、`DEFER -> DEFERRED`。`FAILED` 只来自标准化的执行失败，不是 Social Decision 可以主动选择的动作。

## 5. Runtime 端口

```python
class AgentRuntime(Protocol):
    async def run(
        self,
        message: MessageEnvelope,
        actor: Actor,
        *,
        options: RuntimeInvocationOptions | None = None,
        deadline: datetime | None = None,
        cancellation: CancellationToken | None = None,
    ) -> RuntimeResult: ...

    async def acknowledge_delivery(
        self,
        receipt: DeliveryReceipt,
    ) -> CompletionReceipt: ...

class ContextBuilder(Protocol):
    async def build(
        self,
        message: MessageEnvelope,
        scope: ConversationScope,
        memories: Sequence[MemoryRecord],
    ) -> ContextSnapshot: ...

class PerceptionEngine(Protocol):
    async def perceive(self, context: ContextSnapshot) -> PerceptionResult: ...

class SocialDecisionEngine(Protocol):
    async def decide(
        self,
        context: ContextSnapshot,
        perception: PerceptionResult,
        signals: DecisionSignals,
    ) -> SocialDecision: ...

class ResponseComposer(Protocol):
    async def compose(self, state: RuntimeState) -> DraftResponse: ...

class PersonaRenderer(Protocol):
    async def render(
        self,
        draft: DraftResponse,
        context: RenderContext,
    ) -> FinalResponse: ...
```

`RuntimeInvocationOptions` 只允许携带已校验的逻辑提示，例如 Model Router 的 `RouteHint`、兼容入口标识和 feature flag 快照；不得包含 AstrBot Event、UMO、Provider 对象、凭据或任意平台句柄。AstrBot Adapter 必须在进入 Core 前把 UMO 解析为允许的逻辑 Provider 引用。

`DeliveryReceipt.run_id` 是 acknowledgement 的唯一运行绑定；端口不再接收第二份 run ID。Runtime 校验 receipt 对应一条等待确认的运行，时间带时区，成功引用匹配目标 platform/Bot/conversation，并使重复 receipt 幂等。`FAILED` 或 `UNKNOWN` 仍推进 `DELIVERY_ACKNOWLEDGED`，但不得生成“已送达”记忆。Receipt 不包含原始 Event、平台异常正文或凭据。

Memory、Capability、Tool Runtime 和 Model Router 的端口由各自设计文档定义。Orchestrator 只依赖端口，不依赖实现类。

## 6. 状态转换与不变量

### 6.1 入口与预处理

1. 校验 Envelope 版本、必填身份、Actor 一致性和消息大小。
2. 用 `(platform, bot_id, message_id)` 做幂等去重。
3. 对图片、文件和回复链调用可选预处理器，结果写入受控附件摘要。
4. 计算 `ConversationScope`；无法确定 Scope 时拒绝读取记忆和调用隐私能力。

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

### 6.4 能力与工具循环

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

### 6.5 合成、人格与输出

Response Composer 先生成事实稳定的 `DraftResponse`，包括正文语义、来源、警告、错误和不可修改约束。Persona Renderer 只调整表达。Runtime 以 `RuntimeResult.final_response` 返回平台无关内容并停在 `READY_TO_EMIT`；QQ 的 `Plain`、`At`、`Image`、`Nodes` 由 Output Adapter 创建。

### 6.6 记忆写入

Output Adapter 投递后调用 `acknowledge_delivery()`。Runtime 先记录受控 `DeliveryReceipt`，再让 Memory Write Gate 对自动候选逐一判断来源、事实性、敏感度、未来价值、冲突、TTL、Scope 和是否需要用户确认，最后返回 `CompletionReceipt`。输出失败时不得记录“已成功告知用户”一类事件。显式 `/remember` 等用户事务可走独立、可审计的写入用例，不依赖回复投递成功。

## 7. 超时、取消与错误

统一错误分类建议放在 `domain/errors.py`：

| 错误 | 默认处理 |
| --- | --- |
| `InvalidEnvelopeError` | 不进入 Runtime，Adapter 记录脱敏诊断 |
| `ScopeResolutionError` | 隐私相关能力 fail closed；可返回澄清 |
| `MemoryUnavailableError` | 不带记忆继续，并在 Trace 标记 degraded |
| `ModelUnavailableError` | 使用该角色允许的确定性降级，不跨隐私边界换 Provider |
| `CapabilityDeniedError` | 不执行工具，返回权限说明或静默 |
| `ToolTimeoutError` | Validator 决定有限重试或降级，不无限循环 |
| `CompositionError` | 用结构化工具结果生成最小事实回复 |
| `PersonaRenderError` | 返回未渲染但安全的 Draft，不丢失事实与拒绝 |
| `DeadlineExceededError` | 停止新步骤，按当前可信状态返回降级结果 |

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

## 9. AstrBot 兼容层

迁移期间保留三个现有插件：

### 9.1 `astrbot_plugin_dududa_core`

- 保留插件 ID、命令名、中文回复和配置文件兼容；
- `main.py` 逐步只负责 Event -> Envelope、命令注册、Runtime 调用和 FinalResponse -> AstrBot Result；
- `/course`、`/admin` 等命令可先调用新 application use case，不强制经过社交决策；
- `ALL priority=8` 和 `stop_event()` 行为在契约测试证明等价前不改变。

### 9.2 `astrbot_plugin_target_talk`

- 第一阶段保留现有白名单、目标配置、概率、冷却、Provider override 和 `stop_event`；
- 将确定性规则包装为 `LegacyTargetTalkPolicy`，再逐步接入 Social Decision；
- 用消息幂等键避免它与通用 Runtime 对同一 Event 重复回复。

### 9.3 `astrbot_plugin_reply_polish`

- 保留结果装饰钩子和配置；
- 纯分段函数可先抽入 Package，`Nodes` 等 AstrBot 类型仍留在 Adapter；
- 它是输出格式兼容层，不是 Persona Renderer。

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
- Scope 构造、幂等键、总 deadline 和取消；
- 六种 Social Action 的分支；
- 工具最大步数、重试上限和 Validator 终止；
- Persona 失败返回安全 Draft；
- Memory 读取失败的无记忆降级。

### Contract

- `ContextBuilder`、`PerceptionEngine`、`SocialDecisionEngine`、`ModelRouter`、Memory Repository、Capability Provider；
- AstrBot Event/Result 与 MessageEnvelope/FinalResponse 的双向转换；
- Protocol 实现的错误必须归一化，不能泄漏供应商异常类型。

### Integration

- AstrBot Event -> Runtime -> AstrBot Result；
- 直接回复、工具回复、澄清、忽略和降级；
- iCourse MCP 调用的超时、错误和来源标注；
- Response -> Memory Write Gate；
- TargetTalk 与通用入口对同一消息不重复回复。

### Privacy/Eval

- A 群、B 群、私聊、不同用户和不同 Persona 的隔离矩阵；
- Trace 和错误日志无原文、凭据及真实标识；
- 是否应回复、工具选择、参数抽取和 OC 一致性的 JSONL Eval。

## 12. 当前实现状态与迁移顺序

| 能力 | 当前状态 | 首个迁移动作 |
| --- | --- | --- |
| Message Envelope | 不存在，直接读取 AstrBot Event | 新增 Domain 类型和 AstrBot Adapter 测试 |
| Runtime State/Orchestrator | 不存在，流程散在插件方法 | 建立不改变行为的状态骨架 |
| Context Builder | TargetTalk 有进程内最近消息拼接 | 抽象只读 Context 端口 |
| Perception | `/course` 有局部 LLM JSON 解析 | 迁入结构化 Perception Adapter |
| Social Decision | TargetTalk 有规则版 ignore/reply | 先包装 Legacy Policy |
| Tool Runtime | iCourse 是固定手工流程 | 抽为首个 Capability Provider |
| Response Composer | 课程和 TargetTalk 各自拼接 | 建立 DraftResponse 契约 |
| Persona Renderer | 由 AstrBot Persona Prompt 承担 | 增加独立 Renderer，先透传 |
| Trace | 只有日志和 JSONL 审计 | 新增脱敏阶段事件 |

建议顺序：Domain 契约 -> Runtime 空骨架 -> AstrBot Adapter 合约 -> 安全/配置端口 -> TargetTalk/ReplyPolish 纯逻辑抽取 -> 课程 Capability -> 完整工具循环。每一步保持原命令和部署可运行。

## 13. 扩展点

- 新平台只新增 Input/Output Adapter；
- 新预处理器通过 `AttachmentPreprocessor` 注册；
- 新 Memory 后端实现 `MemoryRepository`，Iris 是其中之一；
- 新能力通过 Registry 和 Provider 注册，不改 Orchestrator；
- 新模型供应商只实现 Model Provider Adapter；
- 新 Persona 通过 Registry 加载，不修改权限和工具逻辑；
- 后续可增加 durable workflow，但必须保持相同 RuntimeState 和幂等契约。
