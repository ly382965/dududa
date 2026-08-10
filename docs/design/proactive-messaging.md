# 主动消息、订阅推送与定时摘要设计

状态：S15A-S15E 的离线契约、持久 Scheduler、固定来源 fixture、Digest Shadow 和 Probe
Shadow 已完成并验证；真实 Source/Projection/Output 和 QQ 发送尚未实现，也未获授权。

目标阶段：S15A-S15E；依赖 S11 Controlled Rollout、S12 Unified MCP、S13 Capability
Runtime 和 S15 Response/Persona 产品化。首版不依赖 Memory；未来若使用个性化 Memory，必须
先满足 S14 的 Scope、Write Gate 和效果门禁。

## 1. 目标与边界

嘟嘟哒需要从“收到消息后决定是否回答”扩展为两类受控出站行为：

1. `CONVERSATION_PROBE`：在显式启用的群中，低频发出一次与当前公共话题相关的轻量探测；
2. `SCHEDULED_DIGEST`：按显式订阅，每日推送校园公开信息、行业最新信息和 arXiv 日报。

这两类行为都不是普通消息 Runtime 的隐式分支，也不是 MCP 的职责。它们必须满足：

- 默认关闭，目标 Scope 明确，空白名单不解释为全部允许；
- 调度、内容获取、是否发送、内容合成、权限、投递和回执各有唯一 Owner；
- 真实发送前重新检查订阅/群策略、授权、quiet hours、限流、kill switch 和目标绑定；
- 同一次 occurrence、同一批来源、同一目标和同一内容不能重复发送；
- 失败、重启、并发、退订和回执未知不会造成补发风暴；
- 外部来源均为不可信数据，必须保留来源、新鲜度和引用，不能成为系统指令；
- Shadow 没有 `OutputAdapter`，不具备发送、停止事件、Tool 写操作或 Memory 写入能力。

## 2. 明确非目标

首版不做：

- 未经订阅的私聊推送、主动 `@` 某个群成员或基于个人画像选择目标；
- 自动连续追问、无人回应后再次催促、跨群复制同一探测；
- 让 LLM 选择目标群、发送时间、订阅主题、频率、权限或是否发送；
- 让 Bandit 探索 `SEND/SKIP`、目标、时间、频率、Answer Profile 或后续追问；
- 读取个人/敏感校园数据，或将课表、成绩、账号、健康、位置等内容推到群聊；
- MCP `message_send`、任意 URL 抓取、任意爬虫、动态发现即授权或由 MCP 自行调度；
- 自动使用长期 Memory 生成探测，或把“用户没有回应”写入 Memory；
- 启动恢复时批量补发过期任务；
- 自动生成长篇探测消息。探测固定 `SHORT`；日报默认 `MEDIUM`。

## 3. 与现有 Runtime 的关系

### 3.1 不伪造入站消息

当前 `AgentRuntime` 从真实 `ConnectorResult` 启动，入站 Actor、消息、提及和引用都来自
Connector。定时器没有用户 Actor，也没有真实消息，因此禁止构造假的 `MessageEnvelope`、
系统用户或伪造 mention 来复用入口。

新增独立应用边界：

```text
Inbound Event
  -> AgentRuntime(RuntimeStartRequest)

Timer / bounded public-topic trigger
  -> ProactiveDeliveryOrchestrator(InitiatedRunRequest)
```

两个 Orchestrator 可复用 Capability、Model Router、Response Composer、Persona、Content
Safety、Output Adapter 和 Delivery reconciliation，但拥有不同的入口契约、授权动作、幂等键和
rollout 配置。

### 3.2 总体数据流

```text
Durable Scheduler                         Conversation Opportunity Detector
  -> ScheduleOccurrence                     -> ConversationOpportunitySnapshot
                 \                         /
                  -> ProactiveTrigger
                  -> persistent CAS claim
                  -> ProactiveInitiationPolicy
                  -> fixed public read-only Capability plan
                  -> Capability Provider
                  -> Unified MCP Client
                  -> allowlisted MCP Server
                  -> SourceBatch normalization/validation/dedup
                  -> deterministic ResponsePlan
                  -> Probe/Digest Composer
                  -> Persona Renderer + Render/Profile/Content validators
                  -> authorization/quiet-hour/rate/kill-switch recheck
                  -> PreparedDispatch + durable dispatch claim
                  -> DeliveryRequest
                  -> OutputAdapter
                  -> DeliveryReceipt/reconciliation
                  -> ProactiveRunReceipt
```

### 3.3 Preview 不是发送演练

订阅预览使用独立入口，不能伪装成一次 occurrence，也不能进入投递状态机：

```text
Authorized operator adapter
  -> ProactivePreviewPort(ProactivePreviewRequest, mode=PREVIEW)
  -> public read-only Capability + SourceBatch
  -> ResponsePlan + Composer + Persona/validators
  -> ValidatedFinalResponse
  -> authorized caller only

Never creates:
  ScheduleOccurrence / PreparedDispatch / DeliveryRequest / DeliveryReceipt
```

预览正文只存在于受权限保护的同步结果中。普通 Trace、`ProactiveRunReceipt` 和 Audit receipt
只能保存 digest、档位、条目数、reason code、耗时和调用者/Scope 的脱敏引用，不能保存预览正文。
`ProactiveDeliveryOrchestrator.run()` 必须拒绝 `PREVIEW`；只有 `ProactivePreviewPort.preview()`
可以处理该模式，从类型和组装两层阻止预览获得 `OutputAdapter`。

## 4. 行为类型

### 4.1 Conversation Probe

首版探测只允许群聊，且需同时满足：

- 群在主动消息 allowlist 中，群策略为显式 `active`；
- 存在仍新鲜的公共话题快照，且不含个人/敏感内容；
- 最近没有 Bot 发言、没有未完成 probe、没有待确认投递；
- 达到最小群静默时间，但没有超过话题新鲜度上限；
- 当前不在 quiet hours，群/全局日预算和长冷却均有余额；
- 内容能形成一个不针对个人、无需私人信息、无需高风险工具的短问题或信息补充；
- 最新配置、授权、限流器、审计和 Output 健康均可用。

探测最多一次。若在归因窗口内没有明确回复，只记录 `CENSORED/NO_OBSERVED_RESPONSE` 的
运行指标并进入长冷却，不发送第二条消息。沉默不是负奖励，也不触发更积极的探测。

### 4.2 Scheduled Digest

日报由显式订阅产生。一个订阅至少绑定：

- 创建者授权证据和当前可解析的订阅 Owner；
- active `ProactiveTargetPolicyRef`、精确 `ConversationScope`、允许的会话类型和 Bot；
- `campus | industry | arxiv` 类别及版本化来源集合；
- IANA 时区、当地发送时间、星期、quiet hours 和 misfire 策略；
- 新鲜度、每来源/总条目、文本、Token 和投递分片上限；
- Answer Profile、语言、Persona、配置/policy revision；
- `active | paused | revoked` 状态和 last-known-good revision。

首个生产候选只支持显式允许的群订阅。私聊订阅未来可增加，但必须由目标用户本人显式创建或
确认，并使用独立权限矩阵；不得从群设置推导私聊授权。

### 4.3 订阅控制用例

命令、WebUI 或运维 CLI 都只能作为 Adapter 调用同一 `ProactiveSubscriptionService`，不得各自
写配置文件。首版至少提供：

- 创建并验证订阅，但默认仍需显式 enable；
- 列出当前 Actor 有权查看的订阅及 last-run/next-run 健康摘要；
- 更新来源、日程、Answer Profile 或目标时生成新 revision；
- `pause`、`resume`、`revoke/unsubscribe`，其中 revoke 保留最小 tombstone；
- `preview` 只生成脱敏预览，不创建发送授权或 DeliveryRequest；
- 操作者显式 manual-canary 物化一次可审计 occurrence，仍经过全部发送前 Gate。

所有 mutation 都需要 typed request、完整 digest、Actor/Scope 授权、幂等键、Audit receipt 和
revision CAS。适配器不得用“文件写成功”代替订阅服务回执。

## 5. 核心契约

以下代码块是设计语义，不代表当前实现已存在。

```python
class ProactiveTriggerKind(StrEnum):
    CONVERSATION_PROBE = "conversation_probe"
    SCHEDULED_DIGEST = "scheduled_digest"

class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKED = "revoked"

class ProactiveRunMode(StrEnum):
    OFF = "off"
    COLLECT = "collect"
    SHADOW = "shadow"
    PREVIEW = "preview"
    CANARY = "canary"

DeliveryRunMode: TypeAlias = Literal[
    ProactiveRunMode.OFF,
    ProactiveRunMode.COLLECT,
    ProactiveRunMode.SHADOW,
    ProactiveRunMode.CANARY,
]
PreviewRunMode: TypeAlias = Literal[ProactiveRunMode.PREVIEW]

class SourceCategory(StrEnum):
    CAMPUS = "campus"
    INDUSTRY = "industry"
    ARXIV = "arxiv"

class ProactiveTargetPolicyStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKED = "revoked"

class ProactiveGrantKind(StrEnum):
    OPERATOR_ENABLE_TARGET = "operator_enable_target"
    GROUP_POLICY_ENABLE = "group_policy_enable"
    SUBSCRIPTION_OWNER = "subscription_owner"

@dataclass(frozen=True, slots=True)
class ProactiveAuthorizationGrantRef:
    schema_version: int
    grant_id: str
    revision: int
    authorization_decision_digest: DigestString
    policy_revision: str
    grant_digest: DigestString

@dataclass(frozen=True, slots=True)
class ProactiveTargetPolicy:
    schema_version: int
    target_policy_id: str
    revision: int
    status: ProactiveTargetPolicyStatus
    target_scope: ConversationScope
    operator_authorization_grant_ref: ProactiveAuthorizationGrantRef
    group_policy_grant_ref: ProactiveAuthorizationGrantRef
    allowed_trigger_kinds: frozenset[ProactiveTriggerKind]
    activated_at: datetime
    expires_at: datetime | None
    target_policy_digest: DigestString

@dataclass(frozen=True, slots=True)
class ProactiveTargetPolicyRef:
    schema_version: int
    target_policy_id: str
    revision: int
    target_scope_digest: DigestString
    target_policy_digest: DigestString

@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    schema_version: int
    timezone: str
    local_time: time
    weekdays: frozenset[int]
    quiet_hours: tuple[LocalTimeWindow, ...]
    misfire_grace: timedelta
    schedule_revision: str

@dataclass(frozen=True, slots=True)
class ProactiveSubscription:
    schema_version: int
    subscription_id: str
    revision: int
    status: SubscriptionStatus
    owner_ref: ActorRef
    authorization_grant_ref: ProactiveAuthorizationGrantRef
    target_scope: ConversationScope
    target_policy_ref: ProactiveTargetPolicyRef
    categories: frozenset[SourceCategory]
    source_policy_id: str
    schedule: ScheduleSpec
    answer_profile: AnswerProfile
    maximum_items: int
    maximum_age: timedelta
    created_at: datetime
    updated_at: datetime
    subscription_digest: DigestString

@dataclass(frozen=True, slots=True)
class ScheduleOccurrence:
    schema_version: int
    occurrence_id: str
    subscription_id: str
    subscription_revision: int
    origin: Literal["scheduled", "manual_canary"]
    local_date: date
    scheduled_for: datetime
    eligible_until: datetime
    occurrence_digest: DigestString

@dataclass(frozen=True, slots=True)
class ConversationOpportunitySnapshot:
    schema_version: int
    opportunity_id: str
    scope: ConversationScope
    target_policy_ref: ProactiveTargetPolicyRef
    topic_refs: tuple[str, ...]
    topic_summary: str
    sensitivity: Sensitivity
    last_human_activity_at: datetime
    last_bot_activity_at: datetime | None
    expires_at: datetime
    producer_revision: ComponentRevision
    snapshot_digest: DigestString

@dataclass(frozen=True, slots=True)
class ProactiveTrigger:
    schema_version: int
    trigger_id: str
    kind: ProactiveTriggerKind
    target_scope: ConversationScope
    occurrence: ScheduleOccurrence | None
    opportunity: ConversationOpportunitySnapshot | None
    target_policy_ref: ProactiveTargetPolicyRef
    trigger_digest: DigestString
    created_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class ProactiveAuthorizationGrant:
    schema_version: int
    grant_id: str
    revision: int
    grant_kind: ProactiveGrantKind
    issuer_ref: ActorRef
    issuer_actor_digest: DigestString
    target_scope_digest: DigestString
    action: Literal["message.send.proactive"]
    allowed_trigger_kinds: frozenset[ProactiveTriggerKind]
    allowed_categories: frozenset[SourceCategory]
    authorization_decision_digest: DigestString
    policy_revision: str
    issued_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    grant_digest: DigestString

@dataclass(frozen=True, slots=True)
class InitiatedRunRequest:
    schema_version: int
    run_id: str
    trigger: ProactiveTrigger
    target_policy_ref: ProactiveTargetPolicyRef
    mode: DeliveryRunMode
    config_snapshot_id: str
    source_policy_revision: str
    response_policy_revision: str
    start_digest: DigestString

@dataclass(frozen=True, slots=True)
class ProactivePreviewRequest:
    schema_version: int
    preview_id: str
    mode: PreviewRunMode
    requested_by: Actor
    action: Literal["proactive.subscription.preview"]
    subscription_id: str
    subscription_revision: int
    target_scope: ConversationScope
    target_policy_ref: ProactiveTargetPolicyRef
    config_snapshot_id: str
    source_policy_revision: str
    response_policy_revision: str
    request_digest: DigestString

@dataclass(frozen=True, slots=True)
class ProactivePreviewResult:
    schema_version: int
    preview_id: str
    mode: PreviewRunMode
    disposition: str
    request_digest: DigestString
    target_scope_digest: DigestString
    authorization_decision_digest: DigestString
    final_response: ValidatedFinalResponse | None
    validated_response_digest: DigestString | None
    response_plan_digest: DigestString | None
    source_batch_digest: DigestString | None
    reason_codes: tuple[str, ...]
    result_digest: DigestString
    completed_at: datetime
```

`ScheduleOccurrence` 和 `ConversationOpportunitySnapshot` 严格 one-of。话题摘要只来自已授权的
同一群公共上下文，禁止包含真实用户 ID、私聊来源或 Memory Record；过期 snapshot 整体拒绝。
Grant 只是创建时证据，不是永久通行证；每个 run 和发送前都要按当前 Actor/Scope/policy 重验。

`ProactiveTargetPolicy.target_policy_digest` 的 canonical 输入必须覆盖 operator/group-policy grant
Ref 各自的 ID、revision、authorization decision、policy revision 和 digest，以及精确
`ConversationScope`、allowed trigger kinds、status、expiry 和 policy revision。Ref 只是不可变
定位符，不能内嵌一份可漂移的策略副本。创建 Opportunity Snapshot、物化/claim Trigger、启动 run
以及发送前都必须重新解析同一 Ref，并验证记录仍 active、两个 grant 仍有效、Scope digest 与当前
目标完全一致。Probe 的 Snapshot、Trigger 和 InitiatedRunRequest 必须携带 canonical-equal 的 Ref；
日报的 Subscription、Trigger 和 InitiatedRunRequest 也必须满足同一约束。缺失、解析失败或任一
revision/digest 不一致均 fail closed。

解析必须满足 `digest(resolved_policy.target_scope) == ref.target_scope_digest`，且 resolved policy
的 ID/revision/digest 与 Ref 完全一致。三个 Grant Ref 分别只接受预期的 `grant_kind`；resolved
grant 的 ID/revision/digest、`message.send.proactive` action、Scope、policy revision、expiry 和
revocation 状态都要重验，不能仅比较字符串 ID，也不能把 operator grant 当作 group-policy grant。

`ProactivePreviewRequest` 不创建 `ScheduleOccurrence`。Preview Port 必须使用 request 中的完整
`Actor` 对独立 `proactive.subscription.preview` 动作实时授权，不能接受调用者自报的授权摘要，
该权限也不能转换成 `message.send.proactive` 或 `PreparedDispatch`。Result 的 request/Scope/
authorization/response digest 必须与实际输入和 `final_response` 一致；`result_digest` 覆盖除自身
以外的全部字段。`final_response` 只返回给请求者，持久记录仅保留 digest 和脱敏元数据。
Preview 的 `AuthorizationDecision` 必须绑定 action、Actor、精确 Scope、完整 request digest、
policy revision 和 expiry；缺失、过期或 effect 非 `ALLOW` 时不得读取来源或调用模型。

### 5.1 来源结果

```python
@dataclass(frozen=True, slots=True)
class SourceItem:
    schema_version: int
    source_id: str
    external_id: str | None
    category: SourceCategory
    title: str
    summary: str
    canonical_url: str
    published_at: datetime | None
    observed_at: datetime
    source_revision: str
    content_digest: DigestString
    citations: tuple[Citation, ...]
    warnings: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class SourceBatch:
    schema_version: int
    batch_id: str
    items: tuple[SourceItem, ...]
    succeeded_sources: tuple[str, ...]
    failed_sources: tuple[SourceFailure, ...]
    source_snapshot_revision: str
    batch_digest: DigestString
    observed_at: datetime
```

`canonical_url` 必须经过 source-specific allowlist、scheme、redirect 和规范化规则。正文、网页、
RSS、API 和 MCP structured content 一律是不可信 Observation。HTML、Prompt 指令、跟踪参数、
超长摘要和无来源项在进入 Composer 前处理或拒绝。

### 5.2 Policy 与投递

```python
@dataclass(frozen=True, slots=True)
class ProactivePolicyDecision:
    schema_version: int
    decision_id: str
    trigger_digest: DigestString
    target_policy_ref: ProactiveTargetPolicyRef
    allowed: bool
    target_scope_digest: DigestString
    answer_profile: AnswerProfile
    maximum_items: int
    authorization_decision_digest: DigestString
    interaction_lease_id: str | None
    reason_codes: tuple[str, ...]
    policy_revision: str
    decided_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class PreparedDispatch:
    schema_version: int
    dispatch_id: str
    trigger_digest: DigestString
    target_policy_ref: ProactiveTargetPolicyRef
    policy_decision_digest: DigestString
    source_batch_digest: DigestString | None
    item_set_digest: DigestString | None
    response_plan_digest: DigestString
    validated_response_digest: DigestString
    target_scope: ConversationScope
    idempotency_key: str
    adapter_binding: NegotiatedBindingReceipt
    prepared_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class ProactiveRunReceipt:
    schema_version: int
    run_id: str
    trigger_id: str
    mode: DeliveryRunMode
    disposition: str
    policy_decision_digest: DigestString | None
    source_batch_digest: DigestString | None
    prepared_dispatch_digest: DigestString | None
    delivery_receipt_digest: DigestString | None
    reason_codes: tuple[str, ...]
    completed_at: datetime

@dataclass(frozen=True, slots=True)
class DispatchClaim:
    schema_version: int
    claim_id: str
    dispatch_id: str
    dispatch_digest: DigestString
    worker_id: str
    lease_revision: int
    claimed_at: datetime
    expires_at: datetime

class ProactiveScheduler(Protocol):
    async def materialize_due(
        self, *, now: datetime, call: ServiceCallContext
    ) -> tuple[ScheduleOccurrence, ...]: ...

class ProactiveDeliveryOrchestrator(Protocol):
    async def run(
        self, request: InitiatedRunRequest, *, call: ServiceCallContext
    ) -> ProactiveRunReceipt: ...

class ProactivePreviewPort(Protocol):
    async def preview(
        self, request: ProactivePreviewRequest, *, call: ServiceCallContext
    ) -> ProactivePreviewResult: ...
```

公开 receipt 不含来源正文、群号、用户 ID、最终消息文本、预览正文、订阅 Owner 或 MCP 原始错误。

## 6. 组件所有权

| 组件 | 负责 | 不负责 |
| --- | --- | --- |
| Durable Scheduler | 计算 occurrence、时区/DST、misfire、CAS claim | 决定内容、权限或发送 |
| Opportunity Detector | 产生有界公共话题候选 | 选择个人、读私聊/Memory 或发送 |
| ProactiveInitiationPolicy | allowlist、模式、quiet hours、冷却、频控、授权和预算 | 调 MCP、生成正文或路由模型 |
| Capability Runtime | 执行固定的公开只读能力 | 订阅、调度、目标和消息发送 |
| Unified MCP Client | 连接、Schema、timeout、retry、熔断和结果标准化 | 业务权限、内容排序、Composer 和投递 |
| Source Normalizer | provenance、新鲜度、净化、游标和条目去重 | 授权发送或改变来源事实 |
| Composer/Persona | 形成事实稳定摘要并按 ResponsePlan 表达 | 添加来源没有的事实或改变目标 |
| Proactive Preview Port | 向已授权操作者返回受控预览 | 创建 occurrence、dispatch、发送授权或投递回执 |
| Proactive Dispatch Store | prepared command、claim、幂等和状态 | 充当通用 DomainEventOutbox |
| Output Adapter | 平台投递与受控回执 | 推断 `UNKNOWN` 为成功或决定重试策略 |

现有 `DomainEventOutbox` 只发布 Runtime 领域事件，不能调用工具或发送消息。主动投递使用独立、
明确副作用语义的 `ProactiveDispatchStore`；两者不得通过复用名称混淆。

## 7. 权限与安全

### 7.1 独立动作

新增权限动作 `message.send.proactive`。它与响应式 `message.respond`、普通投递
`message.send` 分开，至少绑定：

```text
subscription grant + active target-policy ref
operator grant + group-policy grant bound by target-policy digest
exact platform + bot + conversation scope
trigger kind
subscription/target policy revision
content and item-set digest
scheduled occurrence or opportunity digest
quiet-hour and rate-limit lease
expiration
```

`ServiceCallContext` 只证明后台服务身份，不能替代创建订阅或启用群策略的 Actor 授权。每次
发送前必须重新解析 TargetPolicy Ref、Owner/管理员权限并重新决策；旧 grant、已撤销角色、
Scope/revision/digest 不一致或配置漂移均拒绝。

### 7.2 Fail-closed 条件

以下任一情况均产生零发送：

- 配置缺失、Schema 无效、revision/digest 不匹配；
- 目标不在 allowlist，或 allowlist 为空；
- 订阅暂停/撤销/过期，Owner 不可解析或权限失效；
- quiet hours、群/全局预算不足、Limiter/Audit/Authorization 不可用；
- kill switch 开启、rollout mode 不是 canary、Output 不健康；
- occurrence/opportunity 过期、claim 丢失、并发 ownership 冲突；
- 来源不够新、无可靠引用、全失败或内容验证失败；
- 准备后发生订阅/群策略/目标/内容/revision 漂移；
- Persona/Profile/Content Safety/Delivery 约束未通过。

## 8. 调度、时区和恢复

- 时区使用 IANA 名称；可配置默认 `Asia/Shanghai`，缺失或非法值拒绝订阅；
- 每个订阅的本地日期最多物化一个 occurrence；UTC instant 与 local date 同时保存；
- Scheduler 使用可注入 Clock，DST 跳跃、重复小时、系统时钟回拨都有确定性测试；
- occurrence claim 使用持久 CAS/lease，两个 Worker 或重复 tick 只能有一个 Owner；
- `misfire_grace` 之外的 occurrence 标记 `SKIPPED_EXPIRED`，不补发；
- 启动时恢复的 recent occurrence 仍需重新检查订阅、授权、quiet hours 和目标；
- Scheduler 不使用每任务一个无限期 `asyncio.sleep` 作为持久语义；
- 暂停或撤销后，未发送 occurrence 和 prepared dispatch 都失效；
- 下一次 schedule 计算失败时保留 last-known-good 配置并告警，不猜测默认时间。

## 9. 去重与游标

必须区分三类状态：

1. **来源游标**：每个 Source Provider 已观察到哪里；
2. **条目账本**：某订阅已采用/投递过哪些来源项；
3. **投递账本**：某 occurrence/target/content 是否已尝试和得到何种回执。

来源项优先使用 `source_id + external_id` 去重；缺少稳定 ID 时使用规范 URL、发布时间和内容
digest。文章修订需要明确 Provider 规则，不能仅因摘要文本变化无限重复推送。

```text
occurrence idempotency
  = digest(subscription_id, subscription_revision, local_date, scheduled_for)

delivery idempotency
  = digest(trigger kind, occurrence_digest/opportunity_snapshot_digest, exact target scope,
           item_set_digest-or-none, validated_response_digest)
```

业务幂等键不得包含 worker/claim、attempt、delivery ID、时间戳或 Adapter/binding revision；同一
业务 occurrence 在部署、重启或 Output Adapter 升级前后必须得到同一个键。`NegotiatedBindingReceipt`
仍要随 `PreparedDispatch/DeliveryRequest` 保存并在调用和回执时单独校验，binding 漂移使当前尝试
失败或重新协商，但不能制造一个可绕过既有投递账本的新业务键。

公式中的 occurrence/opportunity digest 来自已持久化、已 claim 的 canonical 记录；重启恢复必须
读取并复用该记录，不能重新计算日程或重新运行 Opportunity Detector 来替换它。新 Snapshot 是
新的显式 opportunity，仍受未完成投递、长冷却和频控约束，不能作为旧 Trigger 的重试。

同一 Trigger 一旦已有 `PreparedDispatch`、发送 attempt 或 `UNKNOWN` ledger，恢复时必须复用原
PreparedDispatch 和原业务幂等键，不能重跑模型并用新的 `validated_response_digest` 派生第二个键。
若来源或内容策略变化使原内容失效，只能终止该 Trigger；需要新内容时显式物化新的 occurrence/
opportunity，不能把“重新合成”伪装成重试。

`PARTIAL` 只协调未确认分片；`UNKNOWN` 进入 reconciliation window，不自动重发完整消息。
确认成功的 part 永不倒退。窗口结束仍未知时告警并等待人工判断。

## 10. MCP 来源与信息质量

首版按固定顺序接入：

| Capability | 数据范围 | 最低要求 |
| --- | --- | --- |
| `campus.list_public_notices.v1` | 学校/院系公开通知 | 官方 allowlist、发布时间、原文 URL、缓存/抓取状态 |
| `research.list_recent_arxiv.v1` | 明确分类或关键词的近期 arXiv 条目 | arXiv ID、版本、作者、submitted/updated、abs URL |
| `industry.list_allowlisted_updates.v1` | 预审行业来源 | 固定域名/Feed、发布时间、规范 URL、来源许可/robots 记录 |

Provider 输出统一 `SourceBatch`。禁止提供 `fetch_any_url` 给 Planner；新增来源需要独立
Source Policy、Schema、fixture、allowlist、超时/熔断、新鲜度和许可证/服务条款记录。

来源排序的确定性 baseline 至少考虑：

- 是否在订阅时间窗内首次出现；
- 来源权威性与明确类别匹配；
- 发布时间和观察时间；
- 同一事件/论文的规范去重；
- 已推送账本；
- 每来源配额，避免单一来源淹没摘要。

LLM 只能在已验证候选中做有界摘要，不得生成新 URL、来源、日期或标题。原文不足以支持摘要
时保留标题和链接，不能编造内容。

## 11. 回答档位与内容合成

- Conversation Probe 固定 `SHORT`，一个中心问题或一个有用信息点；
- Scheduled Digest 默认 `MEDIUM`，先给摘要，再给有限条目和来源；
- 自动出站默认不使用 `LONG`。未来只有订阅 Owner 显式配置、平台/群策略允许且本地 Eval
  证明不过度打扰时，才可开放；
- Answer Profile 不决定 Model Tier。复杂但需要一句话的探测可是高 Tier + SHORT，简单但条目
  较多的日报可是低/中 Tier + MEDIUM；
- Composer 必须保留 `SourceItem` 的 title/date/citation Fact Anchor；
- Persona 可以改变表达，不能删除引用、失败范围、新鲜度警告或退订语义；
- 分片优先按条目边界；不能把安全提示或引用截断到未发送 part。

## 12. 错误与降级

| 场景 | 行为 |
| --- | --- |
| 无新内容 | 静默，记录 `NO_NEW_ITEMS` |
| 所有来源失败 | 不向群发送失败消息；记录健康告警 |
| 部分来源失败 | 只有剩余内容满足最小数量/新鲜度才发送，并标注来源缺失 |
| MCP Schema 漂移 | 整个对应来源失败，不从未知字段猜测 |
| Model/Composer 不可用 | 使用经过验证的确定性模板；无法保真则静默 |
| Authorization/Limiter/Audit 不可用 | fail closed，零发送 |
| Output `FAILED` | 按回执结束；只在明确未发送且策略允许时重试 |
| Output `UNKNOWN` | 不盲重发，进入 reconciliation |
| 退订发生于准备后 | prepared dispatch 失效，零发送 |
| Probe 无人回应 | 长冷却，不自动追问 |

## 13. Rollout 与可观测性

Digest 和 Probe 使用独立 mode、allowlist、预算、kill switch 和指标：

```text
off
  -> collect/log-only（只物化 trigger/occurrence）
  -> shadow（可读真实公开源并生成摘要，但无 OutputAdapter）
  -> manual preview（操作者显式查看，不自动发送）
  -> authorized single-scope canary
  -> bounded layered rollout
```

低基数指标至少包括 trigger kind、mode、policy/source/profile revision、occurrence disposition、
source success/failure count、item count、freshness bucket、dedup disposition、quiet-hour/limit deny、
composition result、delivery status、latency 和 cost。禁止记录消息正文、标题全文、URL query、群号、
用户 ID、订阅 Owner、Prompt、MCP 原始错误或 Provider body。

## 14. 测试与 Eval

### 14.1 契约与负向测试

- 默认配置、字段缺失、损坏配置、空 allowlist：零 trigger、零 MCP、零发送；
- 两个 Worker、重复 tick、进程重启、时钟回拨、DST、misfire：同一 occurrence 只 claim 一次；
- pause/unsubscribe、授权撤销、群策略/target/revision 漂移能阻止已抓取未发送任务；
- quiet hours、全局/群频控、探测长冷却和 no-response 分支；
- MCP timeout/cancel/retry/circuit、Schema 漂移、过期/部分结果和恶意 Prompt Injection；
- 重叠抓取窗口、重复 URL/source ID、文章更新和跨重启条目去重；
- `PARTIAL/UNKNOWN` reconciliation、确认分片不倒退、无整消息盲重发；
- Shadow 构造图不存在 OutputAdapter、Memory writer、事件停止和外部写能力；
- Preview 不产生 occurrence、PreparedDispatch、DeliveryRequest/Receipt，预览正文不进入普通
  Trace、Audit receipt 或 ProactiveRunReceipt；
- TargetPolicy Ref 在 Snapshot/Trigger/Run（日报为 Subscription/Trigger/Run）之间必须完全一致，
  grant 撤销及 Scope/revision/digest 替换全部 fail closed；
- Adapter 升级前后同一业务 occurrence 的 delivery idempotency key 保持稳定，binding 单独校验；
- 已 prepared/attempted/UNKNOWN 的 Trigger 在重启后复用原内容和键；multipart 已确认 part 不倒退，
  跨 Adapter revision 也不重跑模型或整消息重发；
- 错误目标、未授权发送、重复发送、静默时段发送、过期/无引用内容、敏感 Trace 均为 0。

### 14.2 科学性与产品 Eval

- 使用 fake clock 运行至少 30 个模拟日，覆盖工作日/周末、重启、无内容、来源波动和熔断；
- Digest 指标：新内容覆盖率、重复率、来源多样性、新鲜度、引用完整率、事实一致率、长度、
  P50/P95、Token/成本和打扰投诉；
- Probe 指标：eligible rate、实际发送率、错误目标率、无响应率、明确参与率、冷却遵守率和
  人工相关性/打扰度；
- Digest/Probe 使用独立数据集和发布门禁，不共享一个总 reward；
- 人工盲评至少比较 no-send、确定性 baseline 和候选 Composer；按 group/topic/date 聚类，报告
  paired bootstrap 95% CI；
- 群聊沉默是删失反馈，不按负奖励填 0；安全违规不能被参与率抵消。

## 15. 单人实施顺序

### S15A：契约与默认拒绝

- 冻结 TargetPolicy/Ref、Trigger、Subscription、Schedule、Preview、Source、Policy、Dispatch 和
  Receipt Schema；
- 新增 `message.send.proactive` 权限动作、配置、Fake Clock/Store/Output；
- 默认 `off`，空 allowlist 拒绝，完成 canonical digest 和负向 Contract Test。

退出条件：没有网络、模型和真实发送时，所有授权、Scope、revision、quiet-hour、限流和幂等
fixture 可重复通过。

### S15B：持久 Scheduler 与订阅生命周期

- 实现 occurrence、CAS claim、IANA 时区、DST、misfire、pause/unsubscribe 和 dispatch store；
- 只产生结构化 trigger，不联网、不生成内容、不发送。

退出条件：fake-clock 并发/重启长期测试无重复 occurrence、过期补发和撤销后任务。

### S15C：公开来源 Capability/MCP

- 先接一个校园官方公开源，再接 arXiv，最后接行业 allowlist 来源；
- 实现 SourceBatch、provenance、freshness、净化、来源游标和条目账本；
- 只读、固定 Capability Plan，不向通用 Planner 暴露任意抓取。

退出条件：固定 fixture、真实 Adapter Contract、断网/超时/熔断/Schema/注入测试通过。

### S15D：日报合成与 Shadow

- 接入 ResponsePlan、Composer、Persona、引用/事实/长度 Validator；
- 完成 collect、真实公开源 shadow 和独立 `PREVIEW` Port；
- Shadow composition 无 OutputAdapter。

退出条件：30 日模拟、来源/内容/投递仿真和回滚通过，无真实发送。

### S15E：主动探测 Shadow

- 实现有界 Opportunity Detector、Proactive Policy 和 no-response 长冷却；
- 探测固定 SHORT，不读个人 Memory，不做 Bandit，不自动追问；
- 与日报使用独立配置、kill switch 和 Eval。

退出条件：长期 no-send 仿真中误目标、重复、静默时段、频控和敏感内容违规为 0。

主动出站后的主线顺序固定为：

```text
S15E -> S16 -> S17 -> S18 -> S19 -> S22 -> S23
```

S20 是可选且独立的在线优化阶段，不是主动出站或 S23 的前置。S23 最终真实场景依次验证既有
显式回复、手动触发日报、定时日报，最后才是低频探测；四者分别授权、分别停止、分别复盘。

## 16. Tree 与实现状态

本文是实现前设计。当前状态：

| 能力 | 状态 |
| --- | --- |
| S08-S11 入站显式回复、Shadow/Canary 边界 | 已完成本地范围 |
| Answer Profile / ResponsePlan | S15 离线机械契约已完成；真实中文体验与模型预算校准未完成 |
| Unified MCP/Capability 公共来源 | S12/S13 传输与能力框架、S15C SourceProvider/固定 fixture 已离线完成；真实来源 Adapter 未实现 |
| 主动 Trigger/Policy/Orchestrator | S15A 默认拒绝契约、S15D no-send 日报和 S15E no-send Probe Orchestrator 已完成；生产组合/发送未实现 |
| Subscription/Scheduler/Source ledger | S15B 持久 Scheduler 和 S15C 原子参考 Source state 已完成；生产来源 persistence 未实现 |
| Digest/Probe Shadow 与真实 Canary | S15D fixture Digest 与 S15E synthetic group Probe Shadow 已完成；真实来源/群 Projection、持久 Probe state 和 Canary 未实现 |

TreeWork 已按该顺序进入实施；最终真实群验证仍依赖全部本地分支和审计。设计状态只按对应
Verification 更新，不把 fixture/no-send 证据解释成生产能力。
