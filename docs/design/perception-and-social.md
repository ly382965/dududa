# 感知与社交决策设计

## 1. 文档状态与边界

- 阶段：Phase 1，目标设计，尚未实现。
- 目标代码：`packages/dududa-agent/src/dududa/runtime/perception.py`、`social_decision.py` 及对应 Domain 类型。
- 兼容来源：`astrbot_plugin_target_talk` 的现有目标匹配、概率、关键词和冷却规则。

Perception 和 Social Decision 是两个不同阶段：

- Perception 说明“消息表达了什么、指向谁、可能需要什么”；
- Social Decision 说明“嘟嘟哒现在是否以及如何介入”。

两者都不能被 Persona 控制。Persona 只能在动作和事实已经确定后改变表达风格。

## 2. 处理关系

```text
ContextSnapshot
      |
      v
PerceptionEngine -> PerceptionResult
      |
      v
SocialDecisionEngine
  + AuthorizationPolicy
  + GroupPolicy
  + RateLimiter
  + LegacyTargetTalkPolicy
      |
      v
SocialDecision
  IGNORE | REACT | DIRECT_REPLY | USE_TOOLS | ASK_CLARIFICATION | DEFER
```

Perception 可以使用规则和模型；Social Decision 必须由确定性硬约束包围模型判断。模型不能自行授予权限、取消冷却或扩大记忆 Scope。

## 3. 输入契约

### 3.1 ContextSnapshot

该对象由 Context Builder 创建，是 Perception 唯一的会话输入：

```python
@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    schema_version: int
    message: MessageEnvelope
    scope: ConversationScope
    recent_messages: tuple[ContextMessage, ...]
    reply_chain: tuple[ContextMessage, ...]
    attachment_summaries: tuple[AttachmentSummary, ...]
    active_topics: tuple[str, ...]
    scoped_memories: tuple[ContextMemoryEvidence, ...]
    memory_conflicts: tuple[MemoryConflictGroup, ...]
    degraded_components: tuple[str, ...]
    group_policy: GroupPolicyView
    user_preferences: UserPreferenceView
    persona: PersonaRef
    available_capability_categories: tuple[str, ...]
```

`available_capability_categories` 只用于判断是否可能需要工具，不暴露完整工具 Schema。具体 Top-K 能力在 Social Decision 输出 `USE_TOOLS` 后检索。

### 3.2 外部信号

Social Decision 还使用不发送给模型的确定性信号：

```python
@dataclass(frozen=True, slots=True)
class AuthorizationView:
    can_respond: bool
    can_react: bool
    can_use_tools: bool
    deny_flags: frozenset[DenyFlag]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class DecisionSignals:
    authorization: AuthorizationView
    bot_was_mentioned: bool
    message_replies_to_bot: bool
    explicit_command: bool
    group_mode: Literal["quiet", "normal", "active"]
    interaction_lease: InteractionLease
    duplicate_or_self_message: bool
    legacy_target_talk: LegacyTargetTalkSignal | None
```

权限、群策略和限流结果以只读值传入，Perception 模型不接收管理员名单、真实权限配置、
Actor roles 或完整限流键。`AuthorizationView` 由统一 `AuthorizationPolicy` 根据完整
`Actor` 和 `ConversationScope` 生成；不得把多角色和 deny overlay 压缩成一个可歧义的
角色字符串。

## 4. PerceptionResult

### 4.1 Schema

```python
@dataclass(frozen=True, slots=True)
class PerceptionResult:
    schema_version: int
    pipeline_revision: ComponentRevision
    component_revisions: tuple[ComponentRevision, ...]
    should_consider_response: bool
    target_users: tuple[ResolvedIdentityRef, ...]
    speech_acts: tuple[SpeechAct, ...]
    topics: tuple[str, ...]
    entities: tuple[Entity, ...]
    references: tuple[Reference, ...]
    resolved_references: tuple[ResolvedReference, ...]
    possible_intents: tuple[IntentCandidate, ...]
    need_tools: bool
    confidence: float
    ambiguities: tuple[Ambiguity, ...]
```

辅助类型至少包含：

```python
class SpeechAct(StrEnum):
    QUESTION = "question"
    REQUEST = "request"
    STATEMENT = "statement"
    CORRECTION = "correction"
    GREETING = "greeting"
    EMOTION = "emotion"
    COMMAND_LIKE = "command_like"

@dataclass(frozen=True, slots=True)
class IntentCandidate:
    intent_id: str
    confidence: float
    slots: Mapping[str, JsonValue]

@dataclass(frozen=True, slots=True)
class Ambiguity:
    code: str
    description: str
    clarification_question: str | None
```

### 4.2 校验规则

- `schema_version` 必须被当前 Runtime 支持；
- `pipeline_revision` 标识组合管线；`component_revisions` 分别记录 Rule、Model、Merger
  和 Validator 的实现/配置 revision，供 Eval 重放；不得记录模型隐藏推理；
- 所有置信度限制在 `[0, 1]`；
- `target_users` 只能引用 Context Builder 已知的匿名身份引用；
- `resolved_references` 必须指出依据消息 ID，不能只给模型自由文本结论；
- `need_tools=True` 不代表允许调用工具；权限和 Capability Retrieval 在后续执行；
- 未知 intent 保留为 namespaced ID，例如 `legacy.course_review_search`，不得映射成任意代码调用；
- Schema 校验失败时整个模型结果无效，不采用“能解析多少算多少”的宽松策略。

`confidence` 只用于质量评估、澄清和软决策排序，不是权限分数。Eval 必须按场景报告
校准误差，并使用按完整 conversation 切分的 held-out 数据，避免相邻消息泄漏到训练
与测试两侧。

## 5. PerceptionEngine Protocol

```python
class PerceptionEngine(Protocol):
    async def perceive(
        self,
        context: ContextSnapshot,
        *,
        call: PortCallContext,
    ) -> PerceptionResult: ...
```

推荐实现为组合器：

1. `RulePerception` 提取 @、回复链、显式问句、命令和已知能力关键词；
2. `ModelPerception` 补充主题、实体、指代和意图；
3. `PerceptionMerger` 按固定规则合并，确定性事实优先；
4. `PerceptionValidator` 校验 Schema 和引用依据。

第一阶段不训练新模型。ModelPerception 通过 Model Router 的 `PERCEPTION` 角色请求 Structured Output；模型不可用时仅使用规则结果。

## 6. SocialDecision

### 6.1 动作与结果

```python
class SocialAction(StrEnum):
    IGNORE = "ignore"
    REACT = "react"
    DIRECT_REPLY = "direct_reply"
    USE_TOOLS = "use_tools"
    ASK_CLARIFICATION = "ask_clarification"
    DEFER = "defer"

class ResponseConstraintCode(StrEnum):
    PRESERVE_FACTS = "preserve_facts"
    PRESERVE_CITATIONS = "preserve_citations"
    PRESERVE_REFUSAL = "preserve_refusal"
    PRESERVE_TARGETS = "preserve_targets"
    CONTENT_SAFETY = "content_safety"
    MAX_LENGTH = "max_length"

@dataclass(frozen=True, slots=True)
class ResponseConstraint:
    schema_version: int
    constraint_id: str
    code: ResponseConstraintCode
    parameters: JsonObject

@dataclass(frozen=True, slots=True)
class ResponseConstraints:
    schema_version: int
    constraints: tuple[ResponseConstraint, ...]

@dataclass(frozen=True, slots=True)
class SocialDecision:
    schema_version: int
    policy_revision: str
    component_revisions: tuple[ComponentRevision, ...]
    action: SocialAction
    confidence: float
    reason_codes: tuple[str, ...]
    target_users: tuple[ResolvedIdentityRef, ...]
    reaction: Reaction | None
    clarification: str | None
    response_constraints: ResponseConstraints
    capability_query: CapabilityQuery | None
    interaction_lease_id: str | None
```

语义：

| 动作 | 含义 |
| --- | --- |
| `IGNORE` | 正常静默，不产生用户可见错误 |
| `REACT` | 只做平台支持的轻量反应，不生成正文 |
| `DIRECT_REPLY` | 不需要外部能力，进入直接回答与合成 |
| `USE_TOOLS` | 生成受限 Capability Query，进入能力检索和工具循环 |
| `ASK_CLARIFICATION` | 信息不足且澄清有价值，只问一个最小问题 |
| `DEFER` | 当前不能安全或可靠处理，给出边界或稍后处理说明 |

`reason_codes` 使用稳定机器码，例如 `direct_mention`、`muted_actor`、`low_value_interruption`、`tool_required`、`ambiguous_reference`、`rate_limited`。日志和 Eval 断言 reason code，而不是依赖自然语言解释。

`policy_revision` 标识确定性 Policy Chain 的配置与规则版本。相同 Context、Perception、
DecisionSignals 和 policy revision 在不启用模型软候选时必须产生相同结果；启用概率模型
时，`component_revisions` 和 Trace 还需记录对应模型、合并器与 Validator revision。

`InteractionLease` 必须在读取限流状态时原子 reserve；Runtime 在最终采用可见动作时
commit，在 `IGNORE`、取消或失败时 release。仅传递一个可过期 snapshot 会让并发消息同时
通过限流，因此不属于正式接口。Lease 的 Scope、action、过期时间和 policy revision 必须
与本次 decision 一致。

### 6.2 SocialDecisionEngine Protocol

```python
class SocialDecisionEngine(Protocol):
    async def decide(
        self,
        context: ContextSnapshot,
        perception: PerceptionResult,
        signals: DecisionSignals,
        *,
        call: PortCallContext,
    ) -> SocialDecision: ...
```

建议实现为明确的 Policy Chain，而不是一个总 Prompt：

```text
Identity/Dedup Gate
 -> Permission Gate
 -> Privacy Gate
 -> Explicit Interaction Rules
 -> Rate Limit/Cooldown Gate
 -> Legacy TargetTalk Signal
 -> Value/Interruption Scoring
 -> Optional Model Decision
 -> Decision Validator
```

## 7. 决策规则

### 7.1 硬规则

以下规则不允许模型覆盖：

- Bot 自己的消息、重复消息和无法确定会话 Scope 的消息不进入主动回复；
- muted 用户不能调用受限能力；数据导出和删除等本人权利需走独立命令策略；
- 权限不足时不得输出 `USE_TOOLS`；
- 群白名单、禁止主动回复和管理员群策略优先于概率模型；
- 冷却或速率限制命中后，默认 `IGNORE`，必要时由命令入口返回限流说明；
- 涉及群聊中的成绩、课表、账号、健康等私密请求，应 `DEFER` 或引导私聊；
- 模型低置信度且澄清成本低时优先 `ASK_CLARIFICATION`；
- 任何工具动作都必须生成 Capability Query，禁止模型直接拼接工具函数名执行。

### 7.2 回复价值与打断成本

软决策至少考虑：

- 是否被明确 @、回复或直接提问；
- 是否与当前活跃话题相关；
- 是否已有群友给出充分回答；
- 是否只是群友之间的对话；
- 回复能否增加事实、帮助或情绪价值；
- 群模式及近期 Bot 发言密度；
- 感知置信度和未解决指代；
- 当前模型/工具可用性，但不因工具昂贵而伪造无需工具的答案。

模型可输出一个候选动作与理由，最终 Validator 必须重新应用硬规则。

## 8. TargetTalk 兼容迁移

当前 TargetTalk 已实现目标 QQ、全局/目标群白名单、概率、关键词、长度、单目标和全局冷却、Provider override、短上下文、@ 回复及可选 `stop_event`。这些行为先封装，不立即重写。

### 8.1 Legacy 信号契约

```python
@dataclass(frozen=True, slots=True)
class LegacyTargetTalkSignal:
    schema_version: int
    matched: bool
    target_ref: ResolvedIdentityRef | None
    probability_passed: bool
    target_cooldown_passed: bool
    global_cooldown_passed: bool
    reply_style_override: str | None
    provider_route_override: str | None
    mention_target: bool
    stop_event: bool
    reason_codes: tuple[str, ...]

class LegacyTargetTalkPolicy(Protocol):
    async def evaluate(
        self,
        context: ContextSnapshot,
        config: LegacyTargetTalkConfig,
        *,
        call: PortCallContext,
    ) -> LegacyTargetTalkSignal: ...
```

第一阶段的 Social Decision 可把通过全部现有条件的信号映射为 `DIRECT_REPLY`，并把字数、提及和风格放入 `response_constraints`。后续再由通用回复价值模型取代特定人逻辑。

### 8.2 必须保留的兼容行为

- 原插件 ID 和 `_conf_schema.json` 键名；
- 目标级配置覆盖全局配置的优先级；
- 最近上下文不重复包含当前消息；
- Provider 失败时现有 fallback 的开关语义；
- `mention_target` 和 `stop_event`；
- 初期保留概率与冷却时机，修正行为必须单独记录 ADR。

### 8.3 需要有意修复的隐私问题

现实现会在白名单和目标判断前记录群消息。迁移后 Context Store 只接收允许范围内、完成 Scope 校验的数据；该修正会改变白名单外群的隐式缓存行为，必须增加回归测试并在发布说明中声明。

## 9. 错误与降级

| 情况 | 行为 |
| --- | --- |
| Perception 模型不可用 | 使用 RulePerception；仅对明确 @、回复、命令等高确定信号回应 |
| Structured Output 无效 | 丢弃整个模型结果，不从自由文本猜字段 |
| Context 不完整 | 降低置信度；必要时澄清，禁止跨 Scope 补数据 |
| Social Decision 模型超时 | 使用确定性 Policy Chain |
| Rate Limiter 不可用 | 主动搭话 fail closed；显式命令按独立保守上限处理 |
| 无可用能力但判断需工具 | `DEFER`，明确当前能力不可用，不让模型编造结果 |
| TargetTalk 配置无效 | 禁用对应条目并记录脱敏配置错误，不扩大到全群 |

模型错误不能默认变成主动回复。社交判断的安全降级是更少介入，而不是更积极介入。

## 10. 隐私与安全

- Perception 请求使用匿名身份引用，不需要向模型发送 QQ 或群号；
- 最近消息必须已按完整 Conversation Scope 获取；
- 不把管理员列表、muted 列表、Provider ID 或限流内部键写入 Prompt；
- TargetTalk 的目标配置属于私有运行配置，不进入 Git、Trace 或 Eval fixture；
- 用户消息、网页和引用文本均用数据边界包裹并视为 Prompt Injection 来源；
- Perception 只能描述意图，不能把消息中的“忽略权限”等内容变成策略；
- reason codes 可记录，原始推理链不得记录或暴露；
- 主动回复前重新确认目标会话，防止异步模型结果发送到错误群。

## 11. 测试与 Eval

### Unit 表格

| 场景 | 预期动作 |
| --- | --- |
| Bot 自己的消息 | `IGNORE` |
| 群友间普通聊天，未提及 Bot | 默认 `IGNORE` |
| 明确 @ Bot 的事实问题 | `DIRECT_REPLY` 或 `USE_TOOLS` |
| 明确课程查询且能力可用 | `USE_TOOLS` |
| 指代对象不明 | `ASK_CLARIFICATION` |
| muted 用户请求高风险工具 | `DEFER` 或命令层拒绝 |
| active 群模式、Legacy TargetTalk 命中 | `DIRECT_REPLY` |
| quiet 模式且无直接提问 | `IGNORE` |
| 模型超时但直接回复 Bot | 规则降级 `DIRECT_REPLY` |

还需测试：

- Schema 上下界、未知枚举和恶意 Structured Output；
- 硬规则不会被模型候选覆盖；
- 概率边界 0/1、冷却边界和可注入时钟/随机源；
- 同一 `message_id` 不重复回复；
- A 群上下文不影响 B 群决策；
- 私聊内容不会成为群聊 reference；
- TargetTalk 原配置的目标级覆盖和 fallback；
- reason code 稳定性。

Eval 数据使用脱敏 JSONL，至少标注：`should_consider_response`、`target_users`、`speech_acts`、`intent`、`need_tools`、`expected_action`、`allowed_actions`、`reason_codes`。允许多种合理动作时用集合而不是强制单一文案。

Dataset 按完整 conversation、群和时间窗口分层切分，禁止同一回复链跨 train/test。报告
样本量、类别分布、缺失标注、macro/micro F1、target/reference exact match、Brier/ECE、
误插话率与错误目标率。Baseline 与候选在同一 case 上配对比较，使用固定 seeds、多次运行、
paired bootstrap 95% 置信区间和预先冻结的最小效果量；未达到效果量或区间跨零时不能宣称
优于 Baseline。零容忍策略项同时报告违规数、分母和单侧置信上界，不能只写“本次为 0”。

## 12. 当前实现状态

| 项目 | 当前事实 | 目标差距 |
| --- | --- | --- |
| 通用 Perception | 不存在 | 只有 `/course` 的局部意图抽取和文本规则 |
| Structured Output | 手工从模型文本提取 JSON | 缺少统一 Schema、版本和严格校验 |
| Social Decision | TargetTalk 的二元 ignore/reply | 缺少六种动作、权限和回复价值模型 |
| Context | TargetTalk 进程内按群 deque | 缺少 Scope、回复链、附件和受控记忆 |
| 群策略 | core 保存 mode/rate，但未消费 | 需要接入 Policy Chain |
| 限流 | TargetTalk 和课程各自内存冷却 | 缺少统一接口、可测试时钟和持久语义 |
| 权限 | core 单独判断 Event | 未注入 Social Decision，插件间不共享 |

## 13. 扩展点

- 可增加小模型实现 `ModelPerception`，不改变结果 Schema；
- 可注册平台特定的 reaction 能力；
- 可用群级策略插件增加安静时段、Bot 发言预算和话题白名单；
- 可增加“已有群友回答”检测器作为 Decision Signal；
- 可用学习排序替换软打分，但硬规则和 Protocol 不变；
- 可逐步移除 `LegacyTargetTalkPolicy`，移除条件是新决策已覆盖配置语义、Eval 通过并具备回滚开关。
