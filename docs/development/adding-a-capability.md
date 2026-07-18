# 添加一个 Capability

## 1. 适用范围

本文说明在目标架构中新增一个可被 Runtime 检索和执行的能力。Phase 1 尚未实现这些目录和接口；本文是实现阶段的开发契约，不是当前可直接运行的命令。

Capability 是稳定的业务能力，不等于 Python 函数、AstrBot 命令或 MCP Tool。新增能力前先确定它是否真的需要进入 Planner：

| 需求 | 推荐实现 |
| --- | --- |
| 确定性、纯本地、无外部协议 | Built-in Capability Provider |
| 独立外部服务或跨语言能力 | MCP Server + MCP Capability Provider |
| 管理、迁移、批量导出、凭据操作 | 运维/管理员命令，不进入 Planner |
| 仅改变 QQ 消息格式 | Output Adapter，不是 Capability |
| 决定是否回复 | Social Decision，不是 Capability |

不要为了“可被模型调用”把 shell、任意 HTTP、任意文件读写或自由 SQL 包装成通用能力。

## 2. 开发前信息

PR 开始前写清：

- 业务目标和不调用该能力时的降级行为；
- 输入、输出和来源；
- 是否联网、持久化、发送消息或修改外部状态；
- 允许 private/group/channel 中哪些场景；
- 所需权限、风险等级和隐私等级；
- 是否幂等，超时后能否安全重试；
- 成本、典型延迟和全局 deadline；
- 数据保留、审计和敏感字段；
- 回滚时是否需要数据迁移。

信息不完整时先保留为显式命令，不要进入 Planner。

## 3. 定义 Capability

目标配置位于 `configs/capabilities/`。示例：

```yaml
schema_version: 1
capability_id: icourse.search_courses.v1
name: 搜索公开评课缓存
description: 按课程、教师或院系搜索评课社区公开缓存；不用于教务成绩或个人课表。
category: campus.course_review
provider:
  provider_id: mcp.icourse
  operation: search_courses
input_schema:
  type: object
  additionalProperties: false
  properties:
    query:
      type: string
      minLength: 1
      maxLength: 100
    teacher:
      type: [string, "null"]
      maxLength: 50
    dept:
      type: [string, "null"]
      maxLength: 80
    limit:
      type: integer
      minimum: 1
      maximum: 20
  required: [query]
output_schema:
  type: object
  additionalProperties: false
  required: [items, total, source]
  properties:
    items: {type: array, maxItems: 20}
    total: {type: integer, minimum: 0}
    source: {const: icourse.club}
risk_level: low
privacy_level: public
allowed_contexts: [private, group]
required_permissions: [capability.icourse.read]
cost_hint: low
latency_hint: fast
idempotency: read_only
side_effects: []
tags: [课程, 教师, 评课, icourse, 公开缓存]
enabled: true
```

要求：

1. `capability_id` 使用 `<namespace>.<verb_or_noun>.vN`，发布后保持稳定。
2. `description` 同时写“何时使用”和“不能用于什么”，避免与相近能力混淆。
3. `additionalProperties` 默认为 `false`，字符串、数组和结果大小必须有上限。
4. output schema 描述 Provider 标准化后的结果，不直接复制不稳定的第三方 payload。
5. `required_permissions` 使用稳定权限码，不写管理员 QQ、群号或实现类名。
6. 风险、隐私和 side effect 要按最坏情况声明，不能依赖 Prompt 补救。
7. 破坏性 Schema 变化发布新版本 ID；旧版本在迁移窗口内保留。

## 4. 实现 Provider

Provider 实现 Domain Protocol，不让 Runtime import 具体 SDK：

```python
class CourseReviewProvider:
    provider_id = "mcp.icourse"

    async def invoke(
        self,
        capability_id: str,
        arguments: JsonObject,
        context: ExecutionContext,
    ) -> ProviderResult:
        ...
```

Provider 负责：

- 将稳定 Capability 参数映射到具体实现或 MCP Tool；
- 将具体结果和错误转换为 Domain 类型；
- 限制结果数量、文本长度和可返回字段；
- 标记来源、缓存状态、观察时间和 sensitivity；
- 把第三方文本视为不可信数据；
- 保持取消、deadline 和幂等语义。

Provider 不负责：

- 自行判断 actor 是不是管理员；
- 绕过 Executor 直接重试；
- 修改 ConversationScope；
- 将 Server 异常、HTML 或模型输出原样作为用户回复；
- 获取 Persona 或调用 AstrBot Event API。

Built-in Provider 也必须走相同 Executor 和 AuditSink。MCP Provider 只能通过 Unified MCP Client 调用，不自行创建新的 `ClientSession` 或子进程。

## 5. 配置检索信息

Capability Retrieval 在确定性过滤后执行 Top-K 排序。为提高可检索性：

- description 使用清楚、互不重叠的业务语言；
- tags 同时包含规范分类和用户常用词，但不堆叠无关关键词；
- input 字段名表达业务概念，不暴露 Server 内部参数；
- 为相近能力添加互斥边界，例如“公开评课”与“个人教务成绩”；
- 增加正例、困难负例和权限过滤 Eval。

默认 Top-K 为 8。不要通过提高 K 掩盖描述含混；K 的全局硬上限是 20。

至少提供以下 Eval：

```yaml
- input: "张老师的数据结构评价怎么样"
  expected_in_top_k: [icourse.search_courses.v1]
  forbidden: [academic.get_grades.v1]

- input: "查一下我这学期的成绩"
  expected_in_top_k: [academic.get_grades.v1]
  forbidden: [icourse.search_courses.v1]
  context: private

- input: "在群里把我的成绩发出来"
  expected_action: defer
  forbidden_exposure: [academic.get_grades.v1]
```

## 6. Planner 和执行契约

新增能力必须能回答：

- Planner 如何知道完成条件；
- 哪些参数来自 Message/Context，哪些来自上一步 Observation；
- 结果为空、部分成功或过期时怎么办；
- Validator 如何证明结果满足 output schema；
- 是否允许继续规划、重试或澄清。

执行仍受全局循环约束：

- 默认最多 4 个执行步骤，硬上限 8；
- 重试计入步骤，单步骤默认最多 1 次；
- 非幂等能力不自动重试；
- 每次执行和重试都重新校验权限、Scope、限流和 deadline；
- 达到上限后返回可信的部分结果或明确降级，不继续调用。

如果一个“能力”必须通过十几个隐藏步骤才能返回，应把确定性工作流放进 Provider，并给上层一个原子业务契约；不要让 Planner 模拟内部实现。

## 7. 权限、隐私和安全

### 7.1 权限

- 在 CapabilityDefinition 中声明权限；
- 在 Registry 检索前过滤；
- Executor 调用前再次校验；
- Provider 或下游服务仍实施自己的最小权限；
- 拒绝结果使用稳定 `CapabilityDeniedError`，不泄露未授权资源是否存在。

### 7.2 隐私

- 明确数据属于 public、conversation、personal 或 sensitive；
- 个人和敏感能力必须使用完整 ConversationScope；
- 群聊不得默认调用私人能力；
- Provider 只返回完成当前请求所需字段；
- 不把原始账号、Token、Cookie、数据库路径或用户标识交给 Planner；
- Trace 和指标只记录低基数 ID、shape、hash 和 reason code。

### 7.3 输入与输出

- Schema 之外字段一律拒绝；
- 文件路径必须转换为受控资源 ID 或限定目录内相对路径；
- URL 必须经过 scheme、host、redirect 和私网访问策略；
- 第三方 HTML/Markdown/评论不得作为指令；
- 大结果先由确定性代码裁剪，再交给模型；
- Persona 不能改写来源、错误、拒绝和事实约束。

## 8. 错误和降级

能力需要声明可观察错误：

| 情况 | 推荐错误 | 默认处理 |
| --- | --- | --- |
| 参数不合法 | `CapabilitySchemaError` | 不调用 Provider；有限重规划 |
| 权限不足 | `CapabilityDeniedError` | 拒绝或静默 |
| 依赖不可用 | `ProviderUnavailableError` | 使用显式替代或降级 |
| 超时 | `ToolTimeoutError` | 只读/幂等时有限重试 |
| 外部业务拒绝 | `ToolBusinessError` | Validator 选择澄清或解释 |
| 结果不符合 Schema | `ToolResultInvalidError` | 不用于事实回答 |
| 预算耗尽 | `ToolBudgetExceededError` | 停止循环并返回可信部分 |

不要捕获所有异常后返回 `{}` 或自然语言“失败了”。原始异常只进入脱敏诊断。

## 9. 测试要求

### Unit

- Capability 配置 Schema 和 ID 唯一性；
- Provider 参数映射、结果标准化和字段裁剪；
- read-only/idempotent/non-idempotent 重试策略；
- 权限、context、risk 和 privacy 过滤；
- Top-K 正例、负例和稳定排序；
- output schema、结果大小和提示注入处理。

### Contract

- Provider Protocol；
- input/output schema snapshot；
- MCP 映射时的 tool name 和参数；
- 标准 Domain Error；
- AuditSink 中敏感字段不出现。

### Integration/Eval

- Retrieval -> Planner -> Executor -> Validator；
- timeout、取消、依赖中断和熔断；
- 无权限时 Provider 调用次数严格为零；
- 错误工具选择率和目标能力 Recall@K；
- Persona 渲染后事实、来源和拒绝保持不变。

测试 fixture 不得包含真实 QQ、群号、Cookie、Token、成绩、课表或聊天记录。

## 10. 注册与发布

建议发布顺序：

1. 合入 CapabilityDefinition、Provider 和测试，但保持 `enabled=false`；
2. 在测试环境注册，验证 Schema Discovery 和健康状态；
3. 只向管理员或 canary 群启用；
4. 观察调用量、错误、P95 延迟、重试和错误能力选择；
5. 扩大允许上下文；
6. 文档化用户入口和运维边界；
7. 确认回滚只需禁用配置，不需要删除数据。

破坏性能力必须有 dry-run 或确认机制，但不能把“模型说用户确认了”当作确定性确认。

## 11. PR 检查清单

- [ ] ID、描述、输入和输出稳定且原子；
- [ ] 权限、隐私、风险、side effect 和幂等性已声明；
- [ ] Planner 看不到实现路径和密钥；
- [ ] Provider 不直接依赖 AstrBot Event 或具体模型 SDK；
- [ ] 参数、结果大小和外部内容已限制；
- [ ] timeout、取消、错误和降级有测试；
- [ ] Top-K 正负 Eval 已添加；
- [ ] 审计和指标不含敏感正文；
- [ ] 群聊、私聊和无权限场景已覆盖；
- [ ] 发布、禁用和回滚方式已说明；
- [ ] README、设计文档和能力目录已同步。

## 12. 常见反模式

- 用一个 `execute_anything(prompt)` 包办所有业务；
- 将全部 MCP Tool 自动注册给 Planner；
- 在 description 中放密钥、内部 URL 或完整系统 Prompt；
- 把权限检查只写在 Prompt；
- 用 Persona 决定事实、权限或工具参数；
- 遇到失败无限重试或不断扩大 Top-K；
- 用自由文本替代可校验错误码；
- 为目录整齐而复制一份新的 MCP Client；
- 将管理型导出、批量抓取或 shell 包装成普通能力。
