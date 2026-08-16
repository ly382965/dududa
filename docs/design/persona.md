# Persona 与 OC Renderer 设计

## 1. 文档状态与原则

- 阶段：S15 已完成 typed `dududa`/`neutral` 资产、Catalog generation/LKG/回放、
  ResponsePlan 绑定和确定性 Renderer/Validator；模型 Renderer、持久用户偏好、多 Persona
  产品资产和人工风格 Eval 尚未实现。
- 目标代码：`packages/dududa-agent/src/dududa/persona/`。
- 当前资产：`configs/personas/dududa.json`、`dududa.md` 及幂等 Persona seed 流程。

Persona 定义“嘟嘟哒如何表达”，不定义“事实是什么、用户能做什么、是否调用工具、记忆能否读取”。确定性代码负责流程、权限、隐私和事实约束；模型负责受限的语言表达；Persona 不是控制权威，不能绕过安全策略。

Persona 是稳定身份、价值观和表达倾向；群聊风格是系统对当前群体情境的语气、用词、长度和
节奏适应。当前 DirectChat 在一次模型生成中共同消费 Persona resolution、channel rule 与
ResponsePlan，让人格通过措辞、回应节奏、关注点和信息取舍自然出现，而不是在生成后追加固定
话术、概率表情或另一轮“人格润色”。表达可以适应，事实、权限、人格身份和任务要求不变。

Bot 管理员可在群入驻时通过 `GroupServiceProfile` 选择初始 Persona 引用。该引用只确定身份与
表达基线；Group Context、用户偏好、模型和 Bandit 不能替换 Persona identity，也不能借风格
适应改变服务、Capability、Memory、主动行为或发送权限。

## 2. 职责边界

Persona 子系统负责：

- 按 `persona_id` 和版本加载人格定义；
- 将角色语气、称呼和表达习惯组织为 `PersonaDefinition` 与 `RenderContext`，但不覆盖 Social Decision 产生的 `ResponseConstraints`；
- 在事实稳定的 `DraftResponse` 上执行 OC Renderer；
- 验证渲染前后事实锚点、引用、拒绝和目标用户不变；
- 在模型渲染失败时用确定性 Finalizer 生成候选输出，并经过相同 Validator/Safety 链；
- 支持多 Persona、版本升级、回滚和 Eval。

Persona 子系统不负责：

- Social Decision 或主动回复概率；
- 角色权限、管理员关系或能力授权；
- Memory Scope、检索和写入；
- Tool 选择、参数、执行或结果校验；
- Provider 凭据与 Model Route；
- 事实核验和安全策略最终裁决；
- AstrBot `Plain`、`At`、`Image`、`Nodes` 组件构造。

## 3. 流水线位置

```text
Context + Tool Observations
          |
          v
Response Composer
          |
          v
DraftResponse  -- facts/sources/refusals/constraints locked
          |
          v
Persona Renderer
          |
          v
Render Validator
          |
          v
FinalResponse
          |
          v
Platform Output Adapter / legacy ReplyPolish
```

Persona 只看到渲染所需的 Draft、Persona 定义和最小偏好，不接收原始记忆、管理员配置、工具凭据或完整 MCP 输出。

## 4. PersonaDefinition

### 4.1 数据契约

```python
@dataclass(frozen=True, slots=True)
class PersonaDefinition:
    schema_version: int
    persona_id: str
    version: str
    display_name: str
    default_locale: str
    character_profile: CharacterProfile
    voice: VoiceRules
    relationship_lore: tuple[RelationshipRule, ...]
    channel_rules: Mapping[str, ChannelStyle]
    safety_notes: tuple[str, ...]
    renderer: RendererPolicy
    source_digest: DigestString
```

关键辅助类型：

```python
@dataclass(frozen=True, slots=True)
class VoiceRules:
    tone_tags: tuple[str, ...]
    sentence_length: Literal["short", "balanced", "long"]
    preferred_language: str
    emoji_budget: int
    avoid_patterns: tuple[str, ...]
    technical_style: str
    uncertainty_style: str

@dataclass(frozen=True, slots=True)
class RendererPolicy:
    mode: Literal["deterministic", "model", "hybrid"]
    model_role: ModelRole | None
    max_expansion_ratio: float
    preserve_line_breaks: bool
    validator_version: str
```

`safety_notes` 是给 Renderer 的表达提示，不是唯一安全实现。未成年人性化、隐私泄漏、危险操作等硬限制仍由独立 Security Policy 执行。

`VoiceRules.sentence_length` 只描述句式节奏，不是回答档位。`SHORT | MEDIUM | LONG` 由上游
`ResponseProfilePolicy` 生成的 `ResponsePlan` 决定；Persona 不能因为“可爱”“认真”或用户 style
偏好自行扩大输出预算、升级 Model Tier 或把短回答改成长回答。

### 4.2 可提交配置

目标配置建议拆为机器可校验元数据和版本化内容：

```text
configs/personas/
└── dududa/
    ├── persona.yaml
    ├── voice.md
    ├── lore.md
    └── examples.yaml
```

当前 `configs/personas/dududa.json` 和 `dududa.md` 继续作为 seed 输入。迁移工具从旧格式生成 `PersonaDefinition`，不能无备份覆盖已运行的 AstrBot Persona。

任何 Persona 文件都不得包含真实 QQ 号、Provider key、私聊记录、用户画像或运行时管理员名单。关系设定使用角色别名，不自动绑定外部账号身份。

## 5. DraftResponse 与事实锚点

```python
@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    source_ref: str
    label: str
    safe_url: str | None

@dataclass(frozen=True, slots=True)
class UncertaintyNote:
    code: str
    text: str

@dataclass(frozen=True, slots=True)
class SafetyNotice:
    code: str
    text: str
    required: bool

@dataclass(frozen=True, slots=True)
class Refusal:
    code: str
    text: str
    policy_revision: str

@dataclass(frozen=True, slots=True)
class GeneratedAssetRef:
    asset_id: str
    content_ref: str
    media_type: str
    source_digest: DigestString

@dataclass(frozen=True, slots=True)
class DraftResponse:
    schema_version: int
    response_id: str
    producer: ComponentRevision
    response_plan_digest: DigestString
    intent: str
    content_blocks: tuple[ContentBlock, ...]
    fact_anchors: tuple[FactAnchor, ...]
    citations: tuple[Citation, ...]
    uncertainty: tuple[UncertaintyNote, ...]
    warnings: tuple[SafetyNotice, ...]
    refusal: Refusal | None
    target_users: tuple[ResolvedIdentityRef, ...]
    attachments: tuple[GeneratedAssetRef, ...]
    immutable_constraints: ResponseConstraints
```

`FactAnchor` 为渲染校验提供稳定依据：

```python
@dataclass(frozen=True, slots=True)
class FactAnchor:
    anchor_id: str
    value: JsonValue
    source_ids: tuple[str, ...]
    exact: bool
```

课程名、教师、评分、日期、工具状态、权限拒绝和来源链接等应成为锚点。Persona Renderer 可以把“查询失败”说得自然，但不能改成“查询成功”；可以缩短课程说明，但不能改分数或移除必要来源。

## 6. Render 输入输出与 Protocol

```python
@dataclass(frozen=True, slots=True)
class RenderedContent:
    kind: Literal["text", "code", "asset"]
    text: str | None
    asset: GeneratedAssetRef | None

@dataclass(frozen=True, slots=True)
class RenderContext:
    schema_version: int
    persona: PersonaDefinition
    locale: str
    conversation_type: ConversationType
    surface: Literal["chat", "web_preview"]
    conversation_mode: str
    response_plan: ResponsePlan
    user_style_preference: str | None
    response_constraints: ResponseConstraints
    target_aliases: Mapping[str, str]

@dataclass(frozen=True, slots=True)
class RenderedBlock:
    block_id: str
    content: RenderedContent
    fact_anchor_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]
    constraint_ids: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class RenderMetadata:
    persona_id: str
    persona_version: str
    mode: Literal["deterministic", "model", "hybrid"]
    renderer_revision: ComponentRevision
    fallback_used: bool
    latency_ms: int

@dataclass(frozen=True, slots=True)
class FinalResponse:
    schema_version: int
    response_id: str
    producer: ComponentRevision
    blocks: tuple[RenderedBlock, ...]
    fact_anchors: tuple[FactAnchor, ...]
    citations: tuple[Citation, ...]
    uncertainty: tuple[UncertaintyNote, ...]
    warnings: tuple[SafetyNotice, ...]
    refusal: Refusal | None
    immutable_constraints: ResponseConstraints
    target_users: tuple[ResolvedIdentityRef, ...]
    attachments: tuple[GeneratedAssetRef, ...]
    render_metadata: RenderMetadata

@dataclass(frozen=True, slots=True)
class PersonaCatalogSnapshot:
    schema_version: int
    snapshot_id: str
    snapshot_revision: str
    definitions: tuple[PersonaDefinition, ...]
    acquired_at: datetime

class PersonaRegistry(Protocol):
    def acquire_snapshot(self) -> PersonaCatalogSnapshot: ...
    async def get(
        self,
        snapshot: PersonaCatalogSnapshot,
        persona_id: str,
        version: str | None = None,
        *,
        call: PortCallContext,
    ) -> PersonaDefinition: ...

    def list_versions(
        self, snapshot: PersonaCatalogSnapshot, persona_id: str
    ) -> tuple[str, ...]: ...

@dataclass(frozen=True, slots=True)
class PersonaCatalogUpdate:
    schema_version: int
    expected_revision: str
    definitions: tuple[PersonaDefinition, ...]

class PersonaCatalogPublisher(Protocol):
    async def publish(
        self,
        update: PersonaCatalogUpdate,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> str: ...

class PersonaRenderer(Protocol):
    async def render(
        self,
        draft: DraftResponse,
        context: RenderContext,
        *,
        call: PortCallContext,
    ) -> FinalResponse: ...

class DeterministicDraftFinalizer(Protocol):
    async def finalize(
        self,
        draft: DraftResponse,
        context: RenderContext,
        *,
        call: PortCallContext,
    ) -> FinalResponse: ...

@dataclass(frozen=True, slots=True)
class RenderValidationResult:
    schema_version: int
    valid: bool
    draft_digest: DigestString
    rendered_digest: DigestString
    reason_codes: tuple[str, ...]
    changed_anchor_ids: tuple[str, ...]
    validator_revision: ComponentRevision

@dataclass(frozen=True, slots=True)
class ValidatedFinalResponse:
    schema_version: int
    response: FinalResponse
    render_validation: RenderValidationResult
    content_safety: ContentSafetyDecision

class RenderValidator(Protocol):
    async def validate(
        self,
        draft: DraftResponse,
        rendered: FinalResponse,
        *,
        call: PortCallContext,
    ) -> RenderValidationResult: ...
```

Registry 加载后执行 Schema 校验、digest 计算和版本检查。一次 Render 从一个
`PersonaCatalogSnapshot` 解析 definition/version/digest；不能把“最新 Persona”与另一 revision
的规则混用。无效新版本不能替换进程内最后一份有效 Persona。

`PersonaCatalogPublisher` 一次校验并原子发布完整 snapshot，失败保留 last-known-good。
只有 `RenderValidationResult.valid=true`、其中 draft/render digest 与实际对象一致，且
最终 `ContentSafetyDecision.allowed=true`、stage 为最终输出、content digest 等于规范化
`FinalResponse` digest、`required_constraints` 是最终不可变约束的子集时，Runtime 才能
构造 `ValidatedFinalResponse` 并交给 Output Adapter。这样事实/内容门禁不能与另一份文本
拼接，checkpoint 恢复后也不必重新调用概率 Renderer 才能证明校验结果。

## 7. OC Renderer 行为

### 7.1 允许改变

- 语序、句式和口语程度；
- 适量称呼、语气词和表情；
- 结合当前群体情境调整措辞、节奏、关注点和信息取舍；
- 在长度预算内压缩重复说明；
- 技术问题使用清晰条理，闲聊使用更自然短句；
- 按用户已授权的 style preference 在“简洁、详细、可爱、认真”等范围内微调；
- 将标准错误说明转换为稳定、友好的用户文案。

Renderer 只能执行 `ResponsePlan.selected_profile` 和其可见长度/分片预算，不能重新选择 Profile。
自动 Conversation Probe 固定 SHORT，订阅日报默认 MEDIUM；主动出站的 Persona 规则不能删除
来源、新鲜度警告、退订语义或部分来源失败说明。

### 7.2 禁止改变

- 添加、删除或修改事实锚点；
- 修改数值、日期、课程、教师、工具结果或引用来源；
- 把不确定结论写成确定事实；
- 弱化拒绝、权限不足、隐私提示或安全警告；
- 声称调用了未调用的模型或工具；
- 改变回复目标、@ 对象、会话或附件；
- 暴露系统提示、Persona 原文、记忆原文或内部 Trace；
- 复述角色档案、无关自我介绍或套用固定口号；
- 每条机械卖萌，或为了证明人格而随机追加表情；
- 模仿某个具体群成员的身份、隐私、口头禅或敏感信息；
- 因角色关系设定给予某用户额外权限；
- 让角色设定中的年龄、关系或情绪覆盖现实安全边界。

### 7.3 渲染模式

当前阶段使用确定性的 Persona resolution/projection，不增加第二次 Persona 模型调用：

1. Runtime 先解析版本化 Persona 与群聊/私聊 channel rule；
2. DirectChat 将可信 Persona style 与 `ResponsePlan` 一起交给同一次回答生成；
3. 模型只负责在预算内自然表达，不得改变事实、权限、工具观察或不可变约束；
4. 确定性 Finalizer、Validator、Content Safety 与 Output Adapter 继续拥有最终边界；
5. `model` 或 `hybrid` Renderer 仅作为未来扩展点，只有真实群聊 Eval 证明第二次改写有净收益时再启用。

不为 Persona 新设一个可访问工具的 Agent。Renderer 的模型调用没有 Tool 权限。

## 8. 当前嘟嘟哒 Persona 的迁移

现有 Persona 已定义：角色身份、数学/计算机兴趣、与“萌萌哒”的角色关系、中文短句风格、技术问题的认真表达、不编造、隐私和未成年人安全边界。

迁移时分类：

| 现有内容 | 目标位置 |
| --- | --- |
| 名字、背景、兴趣、理想 | `CharacterProfile` / lore |
| 可爱、轻松、短句、技术清晰 | `VoiceRules` |
| 与萌萌哒的角色关系 | `RelationshipRule`，只作为表达背景 |
| 不确定时坦诚、不得编造 | Composer/Validator 硬约束 + VoiceRules 表达 |
| 不跨群、不泄露密钥 | Security/Memory 硬策略；Persona 仅保留提示 |
| 未成年人性化禁令 | Security Policy 硬策略 + Persona safety note |
| 图片生成限制 | Image Capability Policy，不由 Renderer 决定 |

目标不是删掉现有 Prompt，而是把其中确定性规则提升为代码策略，让 Prompt 只承载角色和表达。

## 9. 用户偏好与 Persona Scope

`/style` 当前把偏好写入按 QQ 号组织的 JSON，但生成路径未读取。目标通过 `UserPreferenceRepository` 返回 Scope 化偏好：

```python
@dataclass(frozen=True, slots=True)
class PersonaPreferenceScope:
    platform: str
    bot_id: str
    user_id: str
    persona_id: str

@dataclass(frozen=True, slots=True)
class UserPreferenceView:
    schema_version: int
    scope: PersonaPreferenceScope
    style_overrides: Mapping[str, JsonValue]
    revision: int
    updated_at: datetime

@dataclass(frozen=True, slots=True)
class UserPreferenceRequest:
    schema_version: int
    actor: Actor
    conversation_scope: ConversationScope
    persona_id: str

@dataclass(frozen=True, slots=True)
class UserPreferenceCommand:
    schema_version: int
    request: UserPreferenceRequest
    expected_revision: int | None
    style_overrides: Mapping[str, JsonValue]
    authorization: AuthorizationDecision
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class UserPreferenceDeleteCommand:
    schema_version: int
    request: UserPreferenceRequest
    expected_revision: int
    authorization: AuthorizationDecision
    idempotency_key: str

class UserPreferenceRepository(Protocol):
    async def get(
        self,
        request: UserPreferenceRequest,
        *,
        call: PortCallContext,
    ) -> UserPreferenceView | None: ...

    async def put(
        self,
        command: UserPreferenceCommand,
        *,
        call: PortCallContext,
    ) -> UserPreferenceView: ...

    async def delete(
        self,
        command: UserPreferenceDeleteCommand,
        *,
        call: PortCallContext,
    ) -> None: ...
```

- 偏好不是权限，不得启用高风险能力；
- 用户偏好覆盖 `VoiceRules` 的允许部分，不覆盖安全、事实和群级长度上限；
- 群聊中默认不展示偏好原文；
- 偏好可查询、导出、关闭和删除；
- 迁移旧 style 时必须明确旧数据的默认 Scope，不能静默复制到所有 Bot/Persona。

Contextual Bandit 只能在 PersonaDefinition、群约束和用户显式偏好共同允许的已评审 style
variant 中排序，正式契约见 `online-learning.md`。Feature 不含原始消息或真实身份；决策在
渲染前记录 propensity。它不能修改 Fact Anchor、引用、拒绝、安全提示、目标、附件或不可变
约束，也不能覆盖用户明确选择；未明确同意的群聊成员不承担 live 风格探索。

Persona 选择纳入 `ConversationScope.persona_id`。Memory Retrieval 和 Write Gate 使用同一 Persona Scope，防止不同 Persona 间把角色关系或称呼混用。

## 10. 与三个兼容插件的关系

### 10.1 `astrbot_plugin_dududa_core`

- 继续注册命令和读取旧 Persona seed 状态；
- `/style` 先双读或迁移到 `UserPreferenceRepository`，保留原命令文案；
- 插件只把 `ValidatedFinalResponse` 转为 AstrBot Result，不自行拼接新人格 Prompt；
- 当前 `/course` 结果的事实字段先变为 Draft 锚点，再允许 Renderer 调整措辞。

### 10.2 `astrbot_plugin_target_talk`

- 已退出默认 Compose 和 Dududa 2.0 入站路径，源码与旧配置只作为迁移、回滚材料保留；
- 主动探测职责由 S15E Governed Probe / 主动 Runtime 接替，默认关闭；
- 旧 `reply_style`、`system_prompt` 和 `prompt_template` 不进入通用 PersonaDefinition；
- 主动参与不能改变 Persona 身份、权限、安全规则、工具结果或群级服务选择。

### 10.3 `astrbot_plugin_reply_polish`

- 它是默认关闭的 Dududa 1.0 LONG-only 输出兼容层，不负责语气或 OC；
- SHORT、MEDIUM 和缺失/未知 Profile 永远不进入合并转发；
- 2.0 Core Delivery 也只让显式 LONG 保留合并资格，且 Output Adapter 仍要求群聊、至少两个纯文本 part、无定向用户和附件；
- LONG 单段继续普通发送；`Plain`、`Nodes` 和 Bot UIN 始终留在 AstrBot 兼容层。

旧插件源码、`@register` ID、配置和持久数据不会因退出默认路径而自动删除；本轮也不修改运行中的 AstrBot/NapCat。

## 11. 错误与降级

| 情况 | 默认行为 |
| --- | --- |
| Persona 不存在 | 使用版本化 `neutral` Persona，不猜测其他 ID |
| Persona Schema 无效 | 拒绝加载新版本，继续最后有效版本 |
| Renderer 模型不可用 | Deterministic Finalizer -> Render Validator -> Content Safety |
| Renderer 超时 | 不阻塞总 deadline；走同一确定性 Finalizer 与验证链 |
| 锚点/引用校验失败 | 丢弃渲染结果，重试一次后回退 |
| 用户 style 无效 | 忽略 override，使用 Persona 默认值 |
| 输出超过平台限制 | 交给 Output Adapter 分段，不让 Persona 删除必要事实 |
| Persona 内容疑似含凭据 | 加载失败并记录脱敏错误，绝不进入模型请求 |

用户可见回复不得暴露模板路径、模型 Prompt、校验细节或内部异常。Trace 记录 Persona ID、版本、渲染模式、耗时和校验结果，不记录 Persona 全文或完整 Draft。

## 12. 隐私与安全

- Renderer 不接收原始 MemoryRecord，只接收 Composer 已采用的最小事实；
- 目标别名来自当前会话的受控映射，不允许 Persona 自行解析真实身份；
- 角色关系不能成为认证依据，“姐姐”等称呼不等于 owner；
- 群聊渲染不得带出私聊偏好或事实；
- Persona 文件和示例必须使用合成身份及内容；
- 外部网页、用户消息、工具结果不能修改 Persona 或 Renderer system instruction；
- 对当前未成年人角色设定，涉及色情、性化和成人关系的硬策略必须在 Renderer 前后各校验一次；
- Persona 不保存用户情绪、健康、成绩等敏感数据，是否保存由 Memory Write Gate 决定；
- 输出不得暗示模型、工具或记忆具有实际不存在的访问权限。

## 13. 测试与 Eval

### Unit

- Persona Schema、版本、digest 和 last-known-good 加载；
- Persona catalog 原子发布、revision 冲突和回滚；
- 用户 style override 的允许/禁止字段；
- 确定性模板覆盖拒绝、错误、权限和工具失败；
- Renderer 失败、超时及无模型回退；
- Persona Scope 构造和多 Persona 隔离。

### Invariant/Property

- 随机生成 Draft 后，渲染前后所有 exact FactAnchor 一致；
- 引用集合、目标用户、附件和拒绝状态不能减少或改变；
- `ValidatedFinalResponse` 的 draft/render digest 不可替换、错配或在恢复后丢失；
- 数字、日期和课程 ID 不因语气改写变化；
- Prompt Injection 样本不能让 Renderer 输出系统 Prompt 或忽略安全规则；
- 长度压缩不删除安全警告和关键来源。
- SHORT/MEDIUM/LONG 的实际可见长度、结构目标和分片上限通过；Renderer 不改变
  `response_plan_digest`，也不把主动 Probe/Digest 扩展到更长 Profile；

### Golden/Eval

- 闲聊、技术回答、课程结果、工具失败、权限拒绝、隐私引导和情绪陪伴；
- “可爱但不过度卖萌”“技术问题认真”“群聊不刷屏”的人工评分；
- OC 一致性与事实正确性分开评分；
- 人工风格评分使用盲化、随机顺序、至少两名标注者并报告一致性；候选与模板在同一 Draft
  上配对，报告样本量、95% 置信区间和预先冻结的最小效果量；
- Fact/Citation/Refusal/Target/Attachment 改变、跨 Scope 泄漏、内容安全违规和危险 URL
  都是独立零容忍门禁，不能被风格分抵消；
- 当前 `dududa.md` 的关键表达习惯建立少量稳定 Golden，避免逐字快照锁死语言；
- 若显式运行旧 Target Talk 迁移 fixture，其目标级风格不得覆盖 Persona 身份和安全边界。

### Integration

- Persona seed 幂等且版本可回滚；
- Runtime Draft -> Renderer -> AstrBot Output；
- 若操作员显式启用 Dududa 1.0 ReplyPolish 兼容层，处理后事实仍必须完整；
- `/style` 的写入、读取、关闭和删除；
- 不同群、用户和 Persona 的偏好不串联。

## 14. 当前实现状态

| 项目 | 当前事实 | 目标差距 |
| --- | --- | --- |
| Persona 存储 | typed/versioned Registry 与 `dududa` 配置已存在 | 多 Persona 产品资产仍待扩展 |
| 注入 | Persona resolution、channel rule、AnswerProfile 已进入同一次 DirectChat 生成 | 真实中文群聊自然度仍待人工校准 |
| 风格 | 人格通过措辞、节奏、关注点和信息取舍自然融入 | 长期群体情境输入尚未进入生产 Context Builder |
| `/style` | 只写 JSON并显示 | 未进入实际回复渲染 |
| TargetTalk | 已退出默认 Compose 和入站路径 | 旧源码和配置作为迁移、回滚材料保留；是否物理清理是独立决策 |
| ReplyPolish | 默认关闭的 1.0 LONG-only 兼容层 | 正式 2.0 输出不依赖它 |
| 发送形态 | SHORT/MEDIUM 普通发送；LONG 仅实际多段时合并 | 真实 QQ 体验仍待 S23 人工验证 |
| 安全边界 | Policy、Validator 与 Output 边界独立于 Persona | 继续用真实场景验证，不把风格分当安全证据 |

## 15. 扩展点与移除条件

- 增加其他 Persona 只新增版本化定义，不复制 Runtime；
- 增加语言、群/私聊 channel style 和无障碍表达；
- 增加 Persona lint、示例检查和编辑预览；
- 增加轻量本地 Renderer，不改变 Protocol；
- 增加 Persona A/B Eval，但必须固定事实 Draft；
- 兼容 Prompt 只有在新 Registry 已被生产入口使用、style 迁移完成、Invariant/Eval 通过且存在回滚版本后才能移除；
- ReplyPolish 和 TargetTalk 已退出 2.0 默认执行路径；是否物理删除源码、配置和历史数据是独立迁移决策。
