# 嘟嘟哒 P0/P1/P2 开发计划（历史恢复稿）

## 来源与适用范围

本文件恢复自 Codex 历史任务“制定嘟嘟哒P0P1P2开发计划”，用于在 API 切换后保留原始规划上下文。

- 会话 ID：`019fc136-387a-75a0-960f-47ff2803641e`
- 原始会话：Codex 本地历史会话（按会话 ID 检索）
- 原始计划时间：2026-08-02 14:55（Asia/Shanghai）
- 会话索引：Codex 本地会话索引

这是历史计划的可读归档，不替代当前实现状态。当前完成度和后续边界以
[`implementation-plan.md`](implementation-plan.md)、[`.TreeWork/progress.md`](../../.TreeWork/progress.md)
及对应 Spec/Verification 为准。

## 总体分层

原计划沿用以下映射：

- **P0：最小可信内核**（Phase 2–5）——公共契约、安全边界、兼容层、可重复 Eval 基线。
- **P1：可用纵向闭环**（Phase 6–7）——端到端 Runtime、工具闭环、受控主动出站。
- **P2：产品化与规模化**（Phase 8–10）——质量优化、WebUI/控制面、部署、兼容清理和真实群验证。

关键原则：

1. 不按横向模块各自重写，而按可验证的纵向切片推进。
2. Eval、Trace、feature flag、shadow 和 rollback 从 P0 就建立。
3. Memory 先证明 Scope 隔离和写入治理，再追求召回效果。
4. 模型只能提出结构化候选，不能授予权限、绕过策略或直接调用工具。
5. MCP 的发现不等于 Capability 授权；执行时必须重新做权限、预算和副作用检查。
6. 真实大群测试是末端 canary，不承担首次发现跨群泄漏、重复回复或越权调用的职责。

原始多人估算仅作历史参考：P0 约 3–4 周，P1 约 4–6 周，P2 约 4–8 周。

## P0：最小可信内核

### P0.1 公共 Core 契约

创建框架无关的 `packages/dududa-agent`，把下列概念固化为不可变类型、Schema 和 `v1alpha`
协议：

- `MessageEnvelope`、`Actor`、`ConversationScope`、`MemoryScope`；
- `DraftResponse`、`ValidatedFinalResponse`、`RuntimeResult`；
- `RuntimeState`、`RuntimeBudget`、deadline、错误/Reason Code；
- `TraceEvent`、`DeliveryRequest`、`DeliveryReceipt` 和幂等键。

首个 PR 只证明 Core 可独立导入、序列化和测试，不接生产 Event、Provider、MCP 或 Iris。

### P0.2 安全和测试底座

- 权限、隐私等级、Redaction、typed config、审计和确认接口；
- forbidden-import、Schema、幂等、错误映射、权限负向和提示注入测试；
- 固定 fixture、数据版本、指标和最小 Trace；
- 所有新能力有 feature flag，默认不产生外部副作用。

### P0.3 Connector 与插件兼容层

- 将 AstrBot Event 转换为平台无关 Envelope/Actor/Scope；
- 建立 AstrBot fixture 和 Connector conformance suite，覆盖引用、@、附件引用、取消和投递；
- 保持现有插件 ID、命令、路径、优先级、`send/yield/stop_event` 行为不变；
- 先做兼容适配，再拆分旧 `main.py`，不以重命名文件冒充迁移完成。

### P0.4 四路骨架

| 模块 | P0 交付 |
| --- | --- |
| 模型路由器 | `ModelRequest/Response`、Role、Endpoint Descriptor、静态 Policy、Fake Provider；先只证明 `PERCEPTION`。 |
| Memory | `MemoryScope`、Selector、Record/Candidate/Repository、内存/JSON Adapter；禁止自动写入和向量检索。 |
| MCP | 冻结 iCourse 10 个 Tool 的 discovery/input/output/error fixture；最小 Registry、Unified Client、allowlist 和生命周期。 |
| 语义理解 | intent/entity/reference/evidence 标注规范、`RulePerception`、Validator、确定性 Social Policy 和首版 Eval。 |

### P0.5 Memory 安全边界（5A）

建立跨平台、Bot、群、私聊、用户、Persona、TTL、过期和缺 metadata 的隔离矩阵；凭据等敏感
候选 100% 拒绝。旧数据只做 inventory、dry-run、quarantine，不自动迁移。

### P0 退出门槛

- Core 不依赖 AstrBot、MCP、Iris 或 Provider SDK；
- 现有插件行为保持兼容；
- Memory 越界/泄漏率为 0，缺 Scope 时 fail closed；
- 新 Runtime 默认不接生产、不发消息、不写 Memory；
- Shell、Python 编译、契约/单元测试、Compose 解析、仓库扫描和 `git diff --check` 通过。

## P1：可用纵向闭环

### P1.1 首条 Runtime 链路

先实现一条低风险、只读、可回滚的链路：

```text
明确 @ 的 Bot 消息
  -> Connector/Envelope
  -> Context（先允许空 Memory）
  -> Perception
  -> Social Decision
  -> Composer/OC
  -> Output Adapter
  -> Delivery Receipt
```

先 shadow，再对白名单逐群启用；任何失败都回退为无副作用结果。

### P1.2 Router 与模型 Provider

- 接入 AstrBot/OpenAI-compatible Adapter；
- Structured Output 校验、一次受控修复、deadline/budget；
- 对 429、timeout、认证、Schema 和安全错误分别降级；
- 逐角色配置隐私、模型、成本和 fallback；不让模型选择权限或工具资格。

### P1.3 Perception 与 Social Decision

固定流水线：`Rule -> Model -> Merger -> Validator`。意图、实体、指代、歧义和工具需求由
结构化结果表达；权限、隐私、群模式、目标、冷却和是否插话由确定性代码决定。

### P1.4 首个 Tool 闭环

先只做安全的 iCourse 纵切：

```text
/course search
  -> Capability Retrieval
  -> 固定安全 Plan
  -> Unified MCP
  -> Observation Validator
  -> 带来源的最终回答
```

暂不开放通用多步 Planner、高风险写操作或模型自由工具调用。

### P1.5 Memory 可用基线（5B）

在 exact Scope、TTL 和 recency/lexical retrieval 上做 shadow；Write Gate 只记录决策，不自动
写生产。后端故障降级为空 Memory，不影响回复；迁移必须可回滚。

### P1.6 OC 与 WebUI 最小面

- 先用一个版本化 Persona 和确定性透传 Renderer；事实、引用、拒绝、目标和附件不能被风格层改变；
- 在契约稳定后提供只读 Trace/Replay/Eval/Health 页面；WebUI 不复制 Runtime 的权限、Memory、MCP 或 Output 权威。

### P1 退出门槛

- feature flag 可逐群启停并可随时回退；
- 重复回复、重复 Tool、错误 Memory、未授权 Tool 暴露为 0；
- `/course` 兼容文案、权限和数据路径保持不变；
- shadow 无发送、无自动 Memory 写入、无不可逆副作用；
- 端到端 Trace、Receipt、延迟和失败分类可复盘。

## P2：产品化与规模化

### P2.1 Memory 效果与治理

在授权数据集上比较 recency、BM25/lexical、embedding、hybrid、reranker；只有固定 held-out
评测显著优于 baseline 且隔离仍为 0 才进入 shadow/切换。补充摘要、冲突、归档、导出、删除、
Delivery 依赖和受控自动 Candidate；Graph/Temporal 仅在证据足够时引入。

### P2.2 语义和社交扩展

扩展多轮、多意图、指代、口语/错别字、附件摘要和置信度校准；依据真实错误做 active learning，
不把学习结果直接变成权限、主动发送或工具授权。

### P2.3 MCP 与 Capability 规模化

支持多 Server、Schema cache、熔断、并发、HTTP transport、统一指标和故障隔离；Capability
仍须独立 mapping、Scope 和执行时授权，高风险能力不得进入 Planner。

### P2.4 Web Bot Control Plane

提供 RBAC、审计、版本化配置、精确 Scope 的 Memory 查询/删除、Trace/Eval、Health、成本和故障
告警。控制面只能发起经 Core 授权的命令，不能从浏览器直发 QQ 或扩大 Capability。

### P2.5 部署、回滚和兼容清理

- health snapshot、backup/restore、升级失败回滚、CI/Compose/镜像 smoke；
- 旧 Handler、旧 MCP Client、旧模型直连路径按证据逐项清理；
- 每个 PR 记录目标、文件、兼容行为、风险、验证命令、回滚方法和兼容代码移除门槛。

### P2.6 真实群放量阶梯

```text
离线 Eval
  -> no-send Shadow
  -> 单群明确 @
  -> 受控自然参与
  -> 3–5 群 Canary
  -> 全量（需独立授权）
```

### P2 退出门槛

所有扩展能力均有固定数据、指标、Trace、回滚和人工审查证据；真实群测试通过并发、重复、
跨群隔离、故障注入、投递回执和长期 SLO 门禁后，才可删除兼容路径或扩大范围。

## 科学性与评测门禁

| 范围 | 最小指标 |
| --- | --- |
| Memory | 泄漏率（硬门禁 0）、Precision/Recall/MRR、错误归属率、冲突/重复率、token 与 P95。 |
| 语义理解 | Intent macro-F1、Entity span/type F1、Reference exact match、tool-need recall、误插话率、置信度校准。 |
| MCP/Router | 未授权率（硬门禁 0）、Schema-valid rate、成功率、P50/P95、重试/进程数、成本和 fallback 成功率。 |

实验顺序固定为：假设 → 数据/版本 → baseline → 指标 → 受控对比 → 结果与回滚结论。可参考
Mem0、Letta、Zep、LOCOMO、LongMemEval 等研究，但第三方默认 Scope 不能作为安全证明。

## 单人执行映射（后续工作区更新）

历史计划最初按多人并行估算；当前工作区已改为 **1 人、WIP=1**：一次只做一个可独立验证、
可回滚的步骤，完成门禁后再进入下一步。现行文档中的主线为：

1. `S01–S07`：核心契约、安全、Connector、插件拆分、Memory 安全边界；
2. `S08–S11`：静态 Router、语义理解、离线 Runtime、受控 canary；
3. `S12–S13`：Unified MCP 与有限 Capability/Tool 闭环；
4. `S14–S19`：Memory 生命周期/检索、Persona、运维、Eval 与发布候选；
5. `S20–S22`：离线 Bandit、Bot Control Plane、兼容清理；
6. `S23`：另行授权的真实环境和群聊终端验证。

这份恢复稿保存“当时为什么这样排”的上下文；具体状态、证据和未完成项以工作区现行文档为准。
