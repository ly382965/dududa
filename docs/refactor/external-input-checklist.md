# Dududa 2.0 外部输入准备清单

## 1. 先说结论

S17–S19 与 S22 已完成；S20 离线基础仍不依赖外部输入。现在最有价值的是准备
产品策略与公开证据，而不是提供 API Key、QQ 登录态或整库群聊原文。

建议立即准备的顺序：

1. 来源与调度策略；
2. SHORT/MEDIUM/LONG 理想样例；
3. Intent/实体/风险 taxonomy；
4. Provider/Endpoint 公开能力证据；
5. Memory 产品策略；
6. 群聊数据治理规则和标注人员。

## 2. 近期工程输入

| 范围 | 是否需要用户输入 | 可选输入 | 作用 |
| --- | --- | --- | --- |
| S17–S19 | 已完成 | Iris 对当前固定 commit 的明确许可，或“保持阻断/升级/替换”的决定 | 只影响 Manifest v2，不影响已完成的 v1 路径 |
| S22 Cleanup | 已完成 | 无 | 已使用消费者扫描、迁移 receipt 和上一 Release 恢复证据 |
| S20 离线 Bandit | 不需要 | 奖励维度和安全 floor 的产品定义 | 合成 propensity/OPE golden；不训练、不在线探索 |

源码 tree hash、patch hash、依赖 lock 和 SBOM 应由工程工具生成，不需要人工填写。

## 3. 建议现在提供的低敏输入

### 3.1 Provider/Endpoint 目录（不要包含 Key）

每个物理 Endpoint 至少提供：

```yaml
provider_id: example
endpoint_id: example-sonnet
model_id: provider-native-model-id
role: chat
tier: sonnet
base_url_public: https://example.invalid/v1
context_tokens: 0
max_input_tokens: 0
max_output_tokens: 0
reasoning_profiles: [low, medium, high]
supports:
  structured_output: true
  streaming: true
  cancellation: true
  tool_calling: false
  usage_reporting: true
pricing:
  currency: USD
  input_per_million: 0
  output_per_million: 0
limits:
  requests_per_minute: 0
  tokens_per_minute: 0
privacy:
  retention: unknown
  residency: unknown
evidence:
  official_url: https://example.invalid/docs
  checked_at: 2026-08-10
```

Bandit 的后续真实阶段至少需要两个“同 Role、同 Tier、同安全资格”的 Endpoint。不同 Tier
之间不做 Bandit 探索。

### 3.2 Intent、实体和风险 taxonomy

建议使用版本化 YAML/Markdown，至少包含：

- Intent ID、定义、正例、反例和 OOS 条件；
- Entity/slot 名称、span 规则、可缺失性和冲突处理；
- reference/uncertainty/clarification 规则；
- unsupported capability；
- action 风险等级、所需权限和是否允许群聊执行。

### 3.3 AnswerProfile 与 OC 样例

SHORT/MEDIUM/LONG 每档先提供 5-10 个理想回答和反例。每例包含：输入、目标回答、必须保留
事实、允许省略内容、期望字符数/消息分片，以及 Persona 允许和禁止的表达。可以全部使用合成
问题，不需要真实群聊。

还需确认 QQ 体验约束：单条最大字符、普通分片/合并转发策略、代码块和引用方式、日常聊天
可接受长度，以及深度问题是否允许多条发送。

### 3.4 来源和调度策略

每个来源至少提供：

- `source_id`、官方 URL、发布者、许可证/使用条款证据；
- 校园栏目、行业 publisher、arXiv category/关键词 allowlist；
- 允许保存 metadata、有限摘要还是全文；
- freshness、revision、每日条数、去重和撤稿/修订策略；
- IANA timezone、发送时刻、quiet hours、misfire、每群日上限；
- 暂停、退订、管理员同意和 kill switch 负责人。

当前不能把这些来源写成已经存在的 MCP。只有实际 Server 出现时，才补充 `server_id`、transport、
Tool Schema/allowlist、SecretRef、timeout、rate limit、health 和许可证信息。

### 3.5 Memory 产品策略

请冻结：retention/TTL、备份删除窗口、restore 后 tombstone 规则、允许群聊使用的具名
`SAFE_USER_PROFILE` 字段、`/forget` 交互、导出格式/加密、embedding residency，以及 Iris
“保持阻断、升级或替换”的选择。现在不要提供生产 Memory 文件。

## 4. 群聊记录准备方式

约 100 个群的原始聊天记录现在不要放进 Git、文档或聊天窗口。先完成数据治理清单，再提供
一个小型私有 Pilot：首批 30-50 个脱敏 conversation window；确认流程后扩至 200-500 个。

数据治理清单必须包含：

- 使用同意或其他合法依据、用途和允许访问角色；
- 撤回、删除、保留期限和删除负责人；
- 去标识规则与版本；
- 私有保存位置、加密和审计方式；
- group-level split 规则，避免同一群泄漏到 train/eval 两侧；
- 第二标注者、盲评者和仲裁人。

推荐 JSONL 最小结构：

```json
{"dataset_id":"pilot-v1","window_id":"w-001","conversation_cluster_id":"g-pseudo-01","purpose":["semantic","probe"],"messages":[{"speaker_pid":"u01","time_bucket":"2026-08-10T10:00+08:00","text":"脱敏文本","reply_to":null,"mentions_bot":false}],"consent_revision":"consent-v1","deidentification_revision":"deid-v1","retention_until":"2026-12-31"}
```

真实 QQ/group/member ID、头像 URL、文件 URL、Token、Cookie 和未脱敏附件不得进入数据集。
即使已经去标识，聊天正文仍按高敏感数据管理。

## 5. S20 真实 Bandit 阶段以后需要的输入

S20 当前只做离线契约。以后要进入 Shadow/OPE 或在线学习，还必须有：

- 至少两个同 Role+Tier 且安全等价的真实 Endpoint；
- before-action action set、chosen action 和 propensity；
- executed action、fallback/censor 状态、policy/config digest；
- 可归因的任务成功、人工/显式反馈、延迟、Token 和成本；
- 奖励权重、baseline floor、最小有效样本量、探索预算和自动回滚线。

Provider 故障后的 fallback 不能冒充同一次 Bandit 抽样，也不能复用原动作 propensity。

## 6. S23 前的单独授权

S23 只能在 S17、S18、S19、S22 和既定 Web 回归完成后进入。每类行为分别授权：

| 行为 | 最小授权内容 |
| --- | --- |
| no-send/no-write Shadow | Bot/account 引用、单测试群引用、可读时间窗、数据范围、保存/删除期限 |
| 明确 @ 入站 Canary | 授权群、测试用户、最大请求/回复数、允许 Capability、有效窗口、kill switch |
| 手动日报 | 目标群、批准来源、条目/字数上限、一次性窗口、停止条件 |
| 定时日报 | 手动日报字段加 timezone、时刻、quiet hours、misfire、日上限、退订负责人 |
| Conversation Probe | 独立授权、群级不 @ 个人、最大次数、长 cooldown、无人响应不追问、Memory 禁用 |
| 3-5 群扩展 | 单群全部门禁通过后的新授权，不继承单群 Grant 自动扩展 |

授权记录只引用 `SecretRef`，不保存真实凭据：

```yaml
authorization_id:
revision:
grantor:
bot_account_ref:
target_group_ref:
behavior: shadow
valid_from:
valid_until:
max_runs:
timezone: Asia/Shanghai
quiet_hours:
allowed_capabilities: []
memory_allowed: false
slo_revision:
kill_switch_owner:
rollback_release_digest:
data_retention_until:
```

## 7. 现在不要提供

- Provider API Key、QQ/NapCat/OneBot Token、Cookie 或登录二维码；
- 真实群号、QQ 号和成员映射；
- 原始 100 群聊天库、生产数据库、Memory 文件或备份；
- 运行中容器的 Secret、完整 `.env` 或可写生产挂载；
- 尚未到 S23 时的真实发送授权。

凭据仅在执行真实 conformance/S23 时写入本机私有 Secret Store，仓库只保存 `SecretRef`。
