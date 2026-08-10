# Branch Spec

Branch: response-persona
Parent: agent-expansion

## Development Design

### 1. 目标与完成边界

S15 在现有 S08-S14 契约上增加一个离线、确定性、可回放的回答规划层：每条可见回复在
Social Decision 之后、任何用户可见模型请求之前生成唯一的 `ResponsePlan`。Plan 选择
`SHORT | MEDIUM | LONG`，投影实际可用的 Token、字符和分片预算，并由 Direct Chat、
Composer、Persona Renderer、最终 Validator 和 Runtime State 共同绑定。

本分支同时把现有单 Persona 的 pass-through Renderer 提升为最小可发布资产闭环：typed
definition、版本和 digest、原子 Catalog snapshot、last-known-good、明确的 neutral fallback
以及可回滚版本。没有真实 Provider、人工风格样本和授权用户偏好数据，因此本阶段只证明
契约、安全不变量和合成回归，不声明中文体验、Persona 风格质量或预算已校准。

### 2. 所有权与依赖方向

新增 `dududa.responses`，拥有 Answer Profile、选择证据、不可变 Plan、Policy、预算投影、
可见 Token 计数和 Profile Validator。新增 `dududa.persona`，拥有 PersonaDefinition、Catalog
和 Registry。两个包只依赖 Domain、canonical contract、Port context 和标准库；不依赖
AstrBot、MCP、Provider SDK、插件目录或运行时配置文件路径。

```text
validated Perception + current-message detail evidence
  -> SocialDecision
  -> ResponseProfilePolicy -> immutable ResponsePlan
  -> projected direct-chat reservation
  -> existing TierPolicy -> existing StaticModelRouter
  -> Composer(plan) -> PersonaRenderer(plan, catalog snapshot)
  -> RenderValidator + ResponseProfileValidator + ContentSafety
```

权限、事实、引用、目标、附件、Memory Scope、Capability 和发送仍由原有确定性模块拥有。
Persona 只拥有表达资产，Answer Profile 只拥有可见详略和输出上限。任何外部框架未来只能
实现 Port，不能建立另一套选择、权限或预算控制面。

### 3. Response Profile 契约

`AnswerProfile` 的枚举语义固定为：

- `SHORT`：直接结论或自然日常回应；
- `MEDIUM`：结论加必要依据、步骤或来源；
- `LONG`：结构化总结、范围/假设、分析、替代/风险和适用来源，不暴露隐藏推理。

具体数字不是枚举语义。`ResponseProfilePolicyConfig` 提供版本化 pilot defaults、会话类型
上限、每个 delivery part 的字符上限和默认档位。初始 profile ceilings 沿用已批准研究：
SHORT 为 128 可见 Token unit、180 Unicode code point、1 part；MEDIUM 为 512/720/2；
LONG 为 1536/2400/5。Runtime 基础 reservation、Social `max_characters` 和平台 part limit
继续是硬上限；不设置最少字数，不奖励注水。

`ResponsePlan` 至少绑定：

- requested、uncapped、selected profile；
- visible token/character、delivery part 和 total generated-token 上限；
- Social Decision、TaskComplexityAssessment、当前消息偏好证据和可选持久偏好的 digest；
- policy revision/digest、reason codes、decided time 和 selection fingerprint。

Plan 通过 canonical `response_plan_digest` 进入 `DraftResponse`、Render metadata、ModelRequest
和 Runtime State。任何阶段错配、替换或恢复后缺失均 fail closed。Router 只通过请求中的
Plan digest、visible-output 上限和 total generated-token reservation 做能力/预算/admission，
不据此选择 Tier。必测反例为 `OPUS + DEEP + SHORT` 和
`HAIKU + SHALLOW + LONG`。

### 4. 确定性选择与偏好隔离

优先级固定为：硬安全/引用/拒绝/平台与预算约束；当前消息明确详略要求；任务和验证需要；
会话/群 policy cap；合法持久偏好；配置默认。首版只识别冻结的、无歧义的中英文表达，
例如“一句话/简短/详细说明/深入展开”和 `one sentence/brief/in detail/deep dive`；普通内容
中偶然出现这些词不构成授权。冲突或模糊证据不猜测，记录 reason code 后走任务/默认规则。

当前消息的明确要求可产生 3x3 Complexity x Profile 的全部组合，包括 HIGH+SHORT 和
LOW+LONG。没有明确要求时，高复杂度或多步验证倾向 LONG，中复杂度倾向 MEDIUM，低复杂度
倾向 SHORT；Clarification 固定 SHORT。会话 cap 可以收窄 `selected_profile`，但不能删除
必要拒绝理由、警告或引用。最低合规内容放不下时拒绝生成或 DEFER，不能静默截断。

本分支定义只读的 `ResponseProfilePreference` evidence contract，不实现 `/style` 迁移或
Preference Repository。Preference 必须绑定 actor digest、exact scope digest、persona ID、
revision、expiry 和来源；当前消息明确要求优先。Runtime 默认不提供持久偏好。跨用户、跨群、
跨 Bot、跨 Persona、过期或 digest 不匹配的 evidence 全部拒绝，不能降级成全局偏好。

### 5. 动态预算与模型请求

Plan 的 generated-token 上限取 profile ceiling 与现有 direct-chat reservation 的最小值；
可见字符上限再与 Social 和 DirectChat absolute limit 取最小值。`project_response_reservation`
只收窄 direct-chat output reservation，保留既有 input、cost、call、retry 约束，不创建预算。
Perception reservation 和 TierPolicy 不修改。

`ModelRequest` 以 additive optional fields 承载 `response_plan_digest` 和
`visible_output_tokens_upper_bound`；S15 Runtime 的 DIRECT_CHAT 请求必须提供二者，旧测试/
兼容读取路径可暂时为空。`max_output_tokens` 使用 Plan 的 total generated-token 上限。
Direct Chat 在接收 Provider 结果后、Composer 前校验可见 Token unit 和 Unicode 字符上限，
超限直接失败，不自动截断。可见 Token 使用版本化、纯标准库、确定性 CJK/word/punctuation
counter；它是 Dududa policy unit，不冒充任一 Provider 私有 tokenizer。

### 6. Composer、Persona 与最终校验

Composer 必须显式接收同一 Plan，并把 digest 写入 Draft。它不重新选择档位；Clarification
catalog 和 direct/tool content 都必须在 Plan 内。现有 Fact、Citation、Uncertainty、Warning、
Refusal、Target、Attachment 和 Social constraints 保持不变。

Persona 首版采用 deterministic finalizer，不增加第三次模型调用。`PersonaDefinition` 只包含
版本化表达元数据、voice/channel rules 和 source digest，不包含权限、事实、QQ 身份、凭据、
Memory 或 Tool 指令。`PersonaCatalogSnapshot` 是不可变 generation；Publisher 先完整校验再
原子替换，失败保留 last-known-good。缺失 Persona 只回退到显式配置的版本化 `neutral`，
metadata 记录 fallback，不能猜测其他 ID。当前 `config/personas/dududa.json`/`.md` seed 路径
保持不动；S15 新 typed assets 与 legacy seed 并存，删除留给 S22 证据门禁。

Renderer 显式接收 Plan 与 snapshot 解析出的 definition，只生成 `FinalResponse`，并在 metadata
绑定 Plan、Persona definition 和 Draft digest。首版允许 pass-through/确定性句式选择，但不得
声称已完成模型化风格改写。Render Validator 继续逐字段保持 Fact/Citation/Refusal/Target/
Attachment 等受保护内容。

新增 `ResponseProfileValidationResult`。最终内容 Validator 校验 Draft/Render 的 Plan digest、
实际 visible token、Unicode 字符、Plan selected profile，以及必要的 typed 事实/引用/警告/
拒绝集合。Delivery Builder 之后再用同一 Plan 校验真实 part intents；两次验证和 Content
Safety 都通过后才能获得发送授权。长度合规不能抵消内容漂移；必要内容完整也不能豁免硬上限。

### 7. Runtime 状态与兼容策略

`RuntimeState.response_plan` 是不可变阶段证据。DIRECT_REPLY 和 ASK_CLARIFICATION 在 Social
Decision 后的 DECIDED commit 首次发布；USE_TOOLS 必须等 Observation/Capability validation
完成后，在 VALIDATED commit 首次发布。Tool Retrieval、Planning 和 Execution 不接收 Plan。
IGNORE/DEFER 不创建 Plan；每条可见路径必须且只能有一个 Plan，状态恢复不重新选择。

现有 Domain response 类型采用 additive optional binding 字段保持旧构造和 Output Adapter
rollback 可读；一旦 RuntimeState 含 Plan，state validator 要求所有 S15 binding 和 profile
validation 非空且一致。旧 S10 兼容对象仍可独立解析，但不能混入 S15 checkpoint 冒充完成。
不更改 Static Router、TierPolicy、ReasoningDepth、Social Decision 或既有安全 Gate 的语义。

### 8. 合成 Eval 与声明边界

提交 `evals/response-profile/v1/` 固定 fixture、manifest、gold 和 report。至少覆盖完整 3x3、
明确 override、冲突提示、会话 cap、runtime cap、中文/英文/混写、clarification、tool-backed、
拒绝、警告和引用。自动报告 profile confusion、跨两档错误、明确要求满足、硬 limit、受保护
集合漂移和 ranking/selection fingerprint 确定性。canonical、reverse 和固定 seed shuffle
必须产生同一集合结果。

所有数据为合成内容；manifest 明确 `human_review_complete=false`、
`real_chinese_quality_claimed=false`、`network_allowed=false`、`user_data_record_count=0`。
本分支可以门禁契约正确性、确定性和零内容漂移，不能门禁自然度、群聊打扰度、人工
profile-fit 或真实 Provider Token 行为。人工盲评与预算冻结等待外部样例和评审者。

### 9. 失败与回滚

- 无效/过期偏好、未知 profile、Plan digest 错配、预算为零、超限输出：fail closed；
- 新 Persona Catalog 无效或 revision 冲突：拒绝发布并保留 last-known-good；
- 目标 Persona 缺失：显式 neutral fallback；neutral 也缺失则失败；
- Renderer/Validator 失败：不产生 DeliveryRequest，不将裸 Draft 作为输出；
- 回滚：恢复旧 Runtime composition，typed Persona assets 和 optional response fields 保持可读；
  legacy seed 不在本分支删除。

### 10. 验证范围

Unit/Contract 覆盖契约拒绝、优先级、3x3、Preference Scope、动态预算、Router 正交反例、
Registry publish/LKG/fallback/rollback、Composer/Renderer/Validator binding 和所有受保护字段。
Integration 覆盖 direct、tool-backed、clarification、checkpoint/CAS 恢复和无 Delivery 的失败。
实际 delivery part 门禁复用 `plan_delivery_parts`/`DeliveryRequestBuilder` 产生的 part intents，
并在发送授权前与 Plan 比较；预估字符分片只用于 admission，不能冒充 QQ 分片证据。
版本化 Eval 必须可重算并拒绝篡改。完成前运行 Python 3.10/3.12 全仓、warning-as-error 聚焦、
import boundary、build/compile/secret/lock，以及既定 Web 必要回归；不启动真实 Provider、QQ、
MCP 来源或运行中容器。
