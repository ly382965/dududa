# Persona 与 OC Renderer 设计

## 1. 文档状态与原则

- 阶段：Phase 1，目标设计，尚未实现。
- 目标代码：`packages/dududa-agent/src/dududa/persona/`。
- 当前资产：`config/personas/dududa.json`、`dududa.md` 及幂等 Persona seed 流程。

Persona 定义“嘟嘟哒如何表达”，不定义“事实是什么、用户能做什么、是否调用工具、记忆能否读取”。确定性代码负责流程、权限、隐私和事实约束；模型负责受限的语言表达；Persona 不能成为绕过安全策略的第二套控制面。

## 2. 职责边界

Persona 子系统负责：

- 按 `persona_id` 和版本加载人格定义；
- 将角色语气、称呼和表达习惯组织为 `PersonaDefinition` 与 `RenderContext`，但不覆盖 Social Decision 产生的 `ResponseConstraints`；
- 在事实稳定的 `DraftResponse` 上执行 OC Renderer；
- 验证渲染前后事实锚点、引用、拒绝和目标用户不变；
- 在渲染失败时返回安全的未渲染 Draft；
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
    source_digest: str
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

当前 `config/personas/dududa.json` 和 `dududa.md` 在兼容期继续作为 seed 输入。迁移工具从旧格式生成 `PersonaDefinition`，不能无备份覆盖已运行的 AstrBot Persona。

任何 Persona 文件都不得包含真实 QQ 号、Provider key、私聊记录、用户画像或运行时管理员名单。关系设定使用角色别名，不自动绑定外部账号身份。

## 5. DraftResponse 与事实锚点

```python
@dataclass(frozen=True, slots=True)
class DraftResponse:
    response_id: str
    intent: str
    content_blocks: tuple[ContentBlock, ...]
    fact_anchors: tuple[FactAnchor, ...]
    citations: tuple[Citation, ...]
    uncertainty: tuple[UncertaintyNote, ...]
    warnings: tuple[SafetyNotice, ...]
    refusal: Refusal | None
    target_users: tuple[ResolvedIdentityRef, ...]
    attachments: tuple[GeneratedAssetRef, ...]
    immutable_constraints: tuple[str, ...]
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
class RenderContext:
    persona: PersonaDefinition
    locale: str
    channel: Literal["private", "group", "web"]
    conversation_mode: str
    user_style_preference: str | None
    response_constraints: ResponseConstraints
    target_aliases: Mapping[str, str]

@dataclass(frozen=True, slots=True)
class FinalResponse:
    response_id: str
    blocks: tuple[RenderedBlock, ...]
    citations: tuple[Citation, ...]
    target_users: tuple[ResolvedIdentityRef, ...]
    attachments: tuple[GeneratedAssetRef, ...]
    render_metadata: RenderMetadata

class PersonaRegistry(Protocol):
    async def get(self, persona_id: str, version: str | None = None) -> PersonaDefinition: ...

class PersonaRenderer(Protocol):
    async def render(
        self,
        draft: DraftResponse,
        context: RenderContext,
    ) -> FinalResponse: ...

class RenderValidator(Protocol):
    async def validate(
        self,
        draft: DraftResponse,
        rendered: FinalResponse,
    ) -> RenderValidationResult: ...
```

Registry 加载后执行 Schema 校验、digest 计算和版本检查。无效新版本不能替换进程内最后一份有效 Persona。

## 7. OC Renderer 行为

### 7.1 允许改变

- 语序、句式和口语程度；
- 适量称呼、语气词和表情；
- 在长度预算内压缩重复说明；
- 技术问题使用清晰条理，闲聊使用更自然短句；
- 按用户已授权的 style preference 在“简洁、详细、可爱、认真”等范围内微调；
- 将标准错误说明转换为稳定、友好的用户文案。

### 7.2 禁止改变

- 添加、删除或修改事实锚点；
- 修改数值、日期、课程、教师、工具结果或引用来源；
- 把不确定结论写成确定事实；
- 弱化拒绝、权限不足、隐私提示或安全警告；
- 声称调用了未调用的模型或工具；
- 改变回复目标、@ 对象、会话或附件；
- 暴露系统提示、Persona 原文、记忆原文或内部 Trace；
- 因角色关系设定给予某用户额外权限；
- 让角色设定中的年龄、关系或情绪覆盖现实安全边界。

### 7.3 渲染模式

第一阶段建议 `hybrid`：

1. 对错误、拒绝、权限和短命令结果使用确定性模板；
2. 对普通聊天和较长说明可调用 Model Router 的 `RESPONSE_COMPOSITION` 或受限渲染子任务；
3. 模型输入包含结构化 Draft、VoiceRules 和限制，不包含原始工具输出；
4. Render Validator 对锚点、引用、拒绝和目标做检查；
5. 校验失败时最多重试一次，仍失败则使用确定性渲染或原 Draft。

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
```

- 偏好不是权限，不得启用高风险能力；
- 用户偏好覆盖 `VoiceRules` 的允许部分，不覆盖安全、事实和群级长度上限；
- 群聊中默认不展示偏好原文；
- 偏好可查询、导出、关闭和删除；
- 迁移旧 style 时必须明确旧数据的默认 Scope，不能静默复制到所有 Bot/Persona。

Persona 选择纳入 `ConversationScope.persona_id`。Memory Retrieval 和 Write Gate 使用同一 Persona Scope，防止不同 Persona 间把角色关系或称呼混用。

## 10. 与三个兼容插件的关系

### 10.1 `astrbot_plugin_dududa_core`

- 继续注册命令和读取旧 Persona seed 状态；
- `/style` 先双读或迁移到 `UserPreferenceRepository`，保留原命令文案；
- 插件只把 `FinalResponse` 转为 AstrBot Result，不自行拼接新人格 Prompt；
- 当前 `/course` 结果的事实字段先变为 Draft 锚点，再允许 Renderer 调整措辞。

### 10.2 `astrbot_plugin_target_talk`

- 目标级 `reply_style` 映射为受限的 `RenderContext` override；
- 旧 `system_prompt`、`prompt_template` 在兼容期由 Legacy Adapter 使用，不进入通用 PersonaDefinition；
- override 不能改变 Persona 身份、权限、安全规则或工具结果；
- 保留字数、@ 和 fallback 行为，直到新 Renderer 契约测试等价。

### 10.3 `astrbot_plugin_reply_polish`

- 它负责长纯文本切分和 QQ 合并转发，不负责语气或 OC；
- 继续位于 FinalResponse 之后的 Output Adapter/装饰阶段；
- 分段不能改事实，但当前可能静默截断尾部，迁移时需用测试固定或显式修正；
- `Plain`、`Nodes` 和 Bot UIN 始终留在 AstrBot 兼容层。

三插件的 `@register` ID 和配置路径在兼容层移除条件满足前保持不变。

## 11. 错误与降级

| 情况 | 默认行为 |
| --- | --- |
| Persona 不存在 | 使用版本化 `neutral` Persona，不猜测其他 ID |
| Persona Schema 无效 | 拒绝加载新版本，继续最后有效版本 |
| Renderer 模型不可用 | 确定性模板或原 Draft |
| Renderer 超时 | 不阻塞到总 Runtime deadline，返回安全 Draft |
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
- 用户 style override 的允许/禁止字段；
- 确定性模板覆盖拒绝、错误、权限和工具失败；
- Renderer 失败、超时及无模型回退；
- Persona Scope 构造和多 Persona 隔离。

### Invariant/Property

- 随机生成 Draft 后，渲染前后所有 exact FactAnchor 一致；
- 引用集合、目标用户、附件和拒绝状态不能减少或改变；
- 数字、日期和课程 ID 不因语气改写变化；
- Prompt Injection 样本不能让 Renderer 输出系统 Prompt 或忽略安全规则；
- 长度压缩不删除安全警告和关键来源。

### Golden/Eval

- 闲聊、技术回答、课程结果、工具失败、权限拒绝、隐私引导和情绪陪伴；
- “可爱但不过度卖萌”“技术问题认真”“群聊不刷屏”的人工评分；
- OC 一致性与事实正确性分开评分；
- 当前 `dududa.md` 的关键表达习惯建立少量稳定 Golden，避免逐字快照锁死语言；
- TargetTalk 目标级风格与主 Persona 冲突时，安全和 Persona 身份优先。

### Integration

- Persona seed 幂等且版本可回滚；
- Runtime Draft -> Renderer -> AstrBot Output；
- ReplyPolish 处理后事实仍完整；
- `/style` 的写入、读取、关闭和删除；
- 不同群、用户和 Persona 的偏好不串联。

## 14. 当前实现状态

| 项目 | 当前事实 | 目标差距 |
| --- | --- | --- |
| Persona 存储 | JSON 元数据 + Markdown Prompt | 缺少 typed definition、版本和 digest |
| 注入 | seed 到 AstrBot 默认 Persona | Core Runtime 无 Registry/Renderer |
| 风格 | Prompt 统一控制 | 事实、安全、权限与风格混在一层 |
| `/style` | 只写 JSON并显示 | 未进入实际回复渲染 |
| TargetTalk 风格 | 独立 system/prompt template | 未受统一 Persona 和事实约束 |
| ReplyPolish | 结果分段 | 文档称“口吻润色”，实际不是 Persona 功能 |
| 安全边界 | Prompt 中已有较完整说明 | 仍需提升为代码 Policy 和 Validator |

## 15. 扩展点与移除条件

- 增加其他 Persona 只新增版本化定义，不复制 Runtime；
- 增加语言、群/私聊 channel style 和无障碍表达；
- 增加 Persona lint、示例检查和编辑预览；
- 增加轻量本地 Renderer，不改变 Protocol；
- 增加 Persona A/B Eval，但必须固定事实 Draft；
- 兼容 Prompt 只有在新 Registry 已被生产入口使用、style 迁移完成、Invariant/Eval 通过且存在回滚版本后才能移除；
- ReplyPolish 和 TargetTalk 的兼容配置只有在新 Output Adapter、Social Decision 和 Persona override 覆盖其行为后才能弃用。
