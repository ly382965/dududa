# Dududa 2.0 核心模块技术与设计哲学研究报告

- 状态：开发前架构研究，不代表 S12 以后功能已经实现
- 基线：`codex/s08-s11@14f05c3`
- 日期：2026-08-09

## 1. 核心结论

Dududa 2.0 最适合成为一个**受治理的 Agent Runtime**，而不是一个不断给大模型增加 Prompt、工具和
记忆的聊天机器人。

两种路线的差别不在于“是否使用大模型”，而在于谁拥有最终权威：

```text
普通 Agent 框架：模型理解 -> 模型规划 -> 模型选工具 -> 模型决定是否行动

Dududa：可信事实 -> 确定性边界 -> 模型提出候选 -> 确定性验证 -> 有界行动
```

研究表明，现有 S01-S11 的方向是成立的。真正需要继续建设的是纵向接线、生命周期、真实证据和
评测，而不是重新设计 Core。Static Router、Scope-first Memory、Capability-before-Tool、
ResponsePlan 与 Persona 分离、独立 initiated-run、受限 Bandit，这些看似分散的设计实际上遵循
同一个原则：

> 智能可以扩展，但权限、边界和事实不能随模型能力一起漂移。

## 2. 研究所采用的设计立场

### 2.1 确定性代码是“宪法”，模型是“提案者”

模型适合处理模糊语言、开放式内容和难以穷举的排序问题，但不适合成为身份、权限、Scope、预算、
发送目标和数据生命周期的最终裁判。

因此 Dududa 的模型输出应被理解为 proposal：

- Perception 模型提出 Intent、Entity、Reference 候选；
- Planner 提出 Capability 调用计划；
- 内容模型提出 Draft；
- Persona 模型提出表达方式；
- Bandit 提出合法 Endpoint 的排序。

每个 proposal 都必须落入一个由确定性代码定义的合法空间。模型不能通过“更聪明”获得更大的
权限，也不能因为更贵、更长或更自信而越过安全边界。

### 2.2 分离“理解、决策、执行、表达”

许多 Agent 系统把这四件事放进一个 Prompt，短期开发很快，长期却无法回答：错误发生在哪一步、
谁授权了动作、为什么换了模型、事实在哪里被改写。

Dududa 应把它们分开：

```text
Perception      理解发生了什么
Social Policy   决定系统是否应该回应
Tier Policy     决定需要哪一类模型能力
Capability      决定允许使用什么外部能力
Runtime         控制预算、状态和副作用
Composer        固定事实、引用和拒绝
Persona         决定如何表达
Delivery        决定是否以及如何真正发送
```

这种分离不是为了增加层数，而是为了让每一种错误都有唯一责任边界和可回滚入口。

### 2.3 先决定“是否有资格”，再优化“哪个更好”

这一原则同时适用于 Router、Memory、Capability、主动消息和 Bandit：

- Router 先过滤隐私、能力、预算和 health，再比较 Endpoint；
- Memory 先做精确 Scope/TTL/visibility，再做语义排名；
- Planner 先看到合法 Top-K Capability，而不是看到全部 Tool；
- Probe 先通过授权、quiet hours、冷却和打扰预算，再讨论相关性；
- Bandit 只在已经合法的 action set 内学习。

质量分数永远不能补偿权限违规。一个“回答更好”的 Provider 不能因此处理不允许外发的数据；一个
“更相关”的记忆不能因此跨群返回；一个“可能有帮助”的 Probe 不能因此绕过 quiet hours。

### 2.4 复杂度必须靠证据挣得

Dududa 不应预先采用最复杂的方案，而应建立逐级可比较的基线：

```text
规则 -> 模型补充
静态路由 -> 离线学习对照 -> 受控 Bandit
recency -> CJK BM25 -> embedding -> hybrid -> graph
固定 Tool Plan -> 有界 Planner
no-send -> deterministic Probe -> 授权 canary
```

只有复杂方案在 held-out 数据上稳定优于简单方案，且收益足以覆盖延迟、成本、隐私和维护负担时，
才进入下一阶段。这是单人开发最重要的复杂度控制机制。

### 2.5 可回滚性属于设计，不属于运维补丁

每个模块都需要清晰的旧路径、Shadow、开关、receipt 和移除门禁。回滚不能只依赖“把容器换回去”，
因为插件源码、配置、Schema、Policy 和持久状态也可能已经变化。

推荐演进方式始终是：

```text
旧路径保持权威
  -> 新契约 + Fake
  -> 离线集成
  -> no-side-effect Shadow
  -> 单行为 canary
  -> 冻结证据后切换
  -> 最后删除兼容层
```

### 2.6 可扩展性来自契约演进，而不是接口永远不变

稳定接口不等于冻结所有字段。Dududa 的契约应通过显式版本演进：公共 DTO 不可变且带
`schema_version`，优先 additive change，保留 N/N-1 reader/upcaster；canonical digest 同时绑定
Schema 与用途，不能在字段变化后静默重算旧证据。

只由 Fake 证明的 Port 保持 `provisional`。同一 Contract Test 至少被 Fake 和一个真实或兼容
Adapter 通过后，才冻结为公共契约。删除字段、改变语义或移除旧入口必须先有迁移 receipt、消费者
清单和回滚证据。

这种方式允许系统持续扩展，同时避免“为了兼容永远不改”和“每次升级静默破坏”两个极端。

## 3. 整体架构哲学

### 3.1 入站与主动行为是两种不同的权力来源

入站消息拥有真实 Connector 事实和用户发起的交互上下文：

```text
Platform Event
  -> Connector
  -> Perception / Social Decision
  -> Router or Capability Runtime
  -> Composer / Persona
  -> Delivery
```

主动消息没有用户刚刚发出的 Message，因此不能伪造 Actor、mention 或 MessageEnvelope。它必须从
独立的订阅或群级 Opportunity 开始：

```text
Scheduler / Opportunity Detector
  -> TargetPolicy + Grant
  -> fixed public Capability Plan
  -> Composer / Persona
  -> proactive-send recheck
  -> Delivery
```

这一区分体现了一个重要哲学：**有能力回复，不等于有权打扰。** 主动行为需要比被动回答更强的
授权、更低的默认频率和更严格的停止机制。

### 3.2 系统只允许一个所有者处理一种关键事实

| 关键事实 | 所有者 |
| --- | --- |
| 平台身份、会话、reply/@ | Connector |
| 是否回应 | Social Policy |
| 模型能力档位 | TierPolicy |
| Endpoint 合法性 | Static Router |
| Tool 合法性 | Capability Registry + Authorization |
| Memory Scope 与生命周期 | Memory Core |
| 可见回答长度 | ResponseProfilePolicy |
| 事实、引用、拒绝 | Composer/Validator |
| 语气与角色表达 | Persona Renderer |
| 主动目标与时间 | TargetPolicy + Scheduler |
| 真实发送状态 | OutputAdapter + DeliveryReceipt |

外部框架可以实现这些所有者的 Port，但不能同时成为第二个所有者。否则系统会出现两套路由、两套
记忆权限或两套调度，最终无法解释哪一套决策生效。

### 3.3 本报告中的状态边界

| 状态 | 模块 |
| --- | --- |
| 已有本地实现与测试 | Connector/Output、安全基础、Static Router、Perception/难度、离线 Runtime、受控 rollout |
| 有安全骨架但未成产品闭环 | Memory、iCourse MCP v1、最小 Persona、Capability 固定命令路径 |
| 目标态/研究结论，尚未实现 | semantic v2、Unified MCP、通用 Capability Runtime、AnswerProfile、Scheduler、主动出站、Bandit |

下文章节同时描述现状和目标哲学；出现“应”“推荐”或目标组件名时，不应解读为完成证据。

## 4. Connector：翻译平台事实，而不是理解用户

Connector 的设计哲学是 **translation, not cognition**。

它负责把 AstrBot/NapCat Event 转成稳定、不可变、框架无关的消息、Actor 和 Scope；不负责判断
Intent、情绪、难度或是否应该回复。这样未来增加第二平台时，只需要实现同一 Contract，而不需要
复制一份 Agent 逻辑。

重要边界：

- reply、@、发送者和 conversation ID 是平台事实；
- “他”“那个课程”等语言指代是 Perception 结论；
- Attachment 进入 Core 的是 opaque reference 和 digest，不是本地路径或任意 URL；
- UNKNOWN delivery 是一个真实状态，不应被包装成 success 或自动重试。

现有 AstrBot Connector/Output 已形成可信骨架。后续扩展重点不是增加更多启发式判断，而是继续
维护身份一致性、幂等、附件边界和平台 capability 协商。

## 5. 语义理解与智能难度：显式表达不确定性

### 5.1 Perception 不应假装什么都懂

Perception 的任务不是总能给出一个 Intent，而是形成带证据、可拒绝、可澄清的语义状态。推荐的
additive v2 增加 Entity/Reference span，以及 `ACCEPT | CLARIFY | ABSTAIN`，本质上是在接口中
承认不确定性。

这比把所有未知情况映射到一个 `unknown` Intent 更科学，因为系统可以分别评估：

- 是完全超出能力边界；
- 是缺少必要实体；
- 是存在多个同样合理的指代；
- 还是模型置信度不足。

当前 S09 的 320 条 synthetic policy-gold 是很好的回归测试，但不是产品语义证据。没有真实中文
多轮、人工 gold、OOS 和 span 数据前，正确声明是“可重放的语义管线已完成”，不是“语义理解已经
科学校准”。

### 5.2 难度判断不是模型品牌分类

智能难度判断发生在 Router 之前：Perception 提供 reasoning、verification、ambiguity、tool steps
等证据，Complexity Assessor 形成 LOW/MEDIUM/HIGH，TierPolicy 再映射到 Haiku/Sonnet/Opus。

核心哲学是保守：只有明确简单才判 LOW，多个强证据才判 HIGH，其余留在 MEDIUM。长 Context 只是
容量压力，不自动等于高难；用户要求“用 Opus”也不是可信路由指令。

固定 Haiku 负责 bootstrap Perception，解决了“需要先判断难度才能选模型，又需要先选模型才能判断
难度”的递归问题。

## 6. Model Router：规则决定资格，策略决定偏好

Static Router 的价值不只是“按三个档位选模型”，而是把模型选择从 Prompt 技巧变成可审计政策：

```text
Tier authority
  -> privacy/capability/context/budget/health hard filters
  -> stable priority
  -> atomic admission
  -> bounded retry/failover/fallback
```

这里有三个需要长期坚持的区分：

1. **Tier 与 Endpoint 分离。** Haiku/Sonnet/Opus 是逻辑能力档，不是供应商模型名称；模型 ID 只存在
   于配置和 conformance evidence。
2. **Failover 与学习分离。** 同 Endpoint retry、同 Tier failover、跨 Tier fallback 是故障处理；
   Bandit 排序是质量优化，二者不能共享含糊的概率或 reason code。
3. **声明与证据分离。** 配置写“支持 reasoning/stream/context”不等于真实支持；Endpoint 必须通过
   固定 conformance 后才能启用。

RouteLLM、FrugalGPT、RouterBench 和 vLLM Semantic Router 提供了 cost-quality、oracle、signal
等研究方法，但都不适合替换现有 Router。采用它们的方法，不采用它们的控制面，是与 Dududa
哲学最一致的选择。

当前 Router 算法不是主要短板。真正的阻断是 production composition、sampling capability、health
和真实 Provider evidence。放宽 UNKNOWN 或静默丢掉 temperature 只会掩盖集成错误。

## 7. Runtime 与安全：把副作用推迟到最后

Runtime 的核心价值是把一次 Agent 行为变成显式、有限、可恢复的状态演进，而不是隐藏在一次模型
调用里。

```text
input -> context -> perception -> decision -> optional tools
      -> composition -> rendering -> ready-to-emit
      -> delivery acknowledgement -> memory evaluation -> complete
```

只有内容、授权、预算和目标全部确定后才进入 Delivery；只有真实 receipt 返回后才承认发送结果。
对于有可见输出且存在待写候选的路径，Memory commit 位于 delivery acknowledgement 之后；
`NO_REPLY` 等无输出路径不伪造 Delivery，而是经过同一 WriteGate 完成。这样可以避免：发送失败却
写入“已经告诉用户”、Shadow 意外发送、重试造成双回复、模型部分失败后预算被乐观退回。

安全设计强调**结构性缺权**：Shadow 的对象图中没有 OutputAdapter 和 writer，比“提示模型不要发送”
可靠；缺失 policy、Scope、health、audit 或 budget 时 fail closed，比异常后猜测默认值可靠。

本地 Runtime 已有较强的单元、契约和离线集成证据，但运行中的 AstrBot 还没有装配这条纵向链。
生产前四个门禁是 composition root、sampling capability、health 状态和 SQLite 安全版本。

## 8. Memory：记忆首先是一种数据权利

Memory 不只是提升回答相关性的检索组件，它还包含“系统为什么记住、在哪里可见、何时过期、如何
删除、是否能够导出”的数据权利。

因此 Dududa 的首要顺序应是：

```text
Scope -> WriteGate -> lifecycle/delete/export -> retrieval baseline -> semantic optimization
```

而不是：

```text
embedding/graph -> 看起来更聪明 -> 以后再补权限和删除
```

现有 `MemoryScope`、Selector、Repository Snapshot 和显式 WriteGate 是正确核心。语义索引只能在
Repository 已经按 Scope/TTL/visibility 过滤的候选中排名，不能先全库检索后再过滤。

检索也遵循“复杂度靠证据挣得”：no-memory、recency、CJK BM25 是必须保留的基线；本地 embedding、
hybrid、Graph 只有在 held-out 数据上稳定提高检索和回答质量，且没有扩大隐私/维护成本时才采用。

对外部框架的判断：

- Mem0 和 Graphiti 可做隔离实验，但不能替代 Scope/Repository/WriteGate；
- Letta 是完整 Agent Runtime，引入后会产生第二套控制面，因此只借鉴分层思想；
- Zep Cloud 涉及外传和 retention，首版后置；
- Iris 当前固定版本许可证不清晰，保持 blocked；
- LoCoMo/LongMemEval 用于研究评测，不替代中文 QQ 数据。

Memory 完成的真正标志不是“可以搜到”，而是删除后重启、重建索引、恢复备份都不会复活；跨 Scope、
过期返回和未授权外传保持为 0。

## 9. Capability 与 MCP：协议不是权限系统

MCP 解决“如何与外部 Server 通信”，不解决“模型应该看到什么、是否有权调用、结果是否可信”。
因此 Dududa 应坚持 Capability-before-Tool：

```text
raw MCP tools
  -> explicit Capability mapping
  -> permission/risk/privacy/health filters
  -> bounded Top-K summaries
  -> Planner proposal
  -> deterministic validation and execution
```

Unified MCP Client 负责 Session、transport、timeout、取消和错误标准化；Dududa Registry 负责批准的
Server 配置；Capability Registry 负责授权映射；Schema Snapshot 负责 freshness。Discovery 发现了
一个 Tool，不代表模型自动获得调用权。

MCP Python SDK v2 值得做迁移 Spike，因为它提供更合适的长生命周期 Client；当前 v1.29 Server
在迁移期同时作为限时 legacy fallback 和固定兼容 fixture。迁移的目标不是追新版本，而是消除
“每次调用新建进程”、Schema 漂移和未知写结果盲重试。

校园、行业和 arXiv 来源同样服从这一边界：只接官方 allowlist，只保存 metadata、有限摘要和规范
链接；robots 不是内容许可证，来源文本也永远不是系统指令。

## 10. AnswerProfile 与 Persona：事实和表达必须分层

SHORT/MEDIUM/LONG 描述用户可见回答的详略和结构；Haiku/Sonnet/Opus 描述模型能力档；Reasoning
描述推理参数。三者相关但不能互相推导。

一个复杂任务可以要求短结论，一个简单任务也可以要求完整枚举。因此系统必须能够表达
`OPUS + DEEP + SHORT` 和 `HAIKU + LIGHT + LONG`。把 LONG 自动映射到 Opus 会混淆质量需求、
成本和用户表达偏好。

Response Composer 固定事实、引用、拒绝、目标和附件；Persona 只改变语气、称呼和句式。OC 不是
权限、事实或产品策略。这个分层让 Persona 可以自由迭代，而不会因为“更有个性”改变课程分数、
漏掉来源或绕过拒绝。

IFEval、AlpacaEval、HELM、OpenAI Evals 和 Chatbot Arena 的价值主要在评测方法：确定性 checker、
随机顺序、长度偏差控制、版本化场景和匿名 pairwise。它们不是需要整体引入的新 Runtime。

## 11. 主动消息：打扰权高于回答权

主动消息的核心问题不是“模型能不能找到话题”，而是“系统何时有权打断群聊”。所以首版应默认
关闭、群级、低频、可撤销，并且先做 no-send Shadow。

Opportunity Detector 只能产生短 TTL 的公共话题候选。relevance、information gap、coherence、
originality 和静默时间只能在已经通过授权、quiet hours、冷却、频率和敏感度 Gate 后用于排序。

这里需要抵抗一种直觉：静默越久，并不代表越应该说话。话题可能已经结束，沉默也不是负反馈。
无人回应应记录为 censored，并触发更长冷却，而不是促使系统自动追问。

相关论文支持复用 timing、boundary respect、relevance 和 disturbance 等评价维度，但小规模、纯 AI
或单机构实验不能证明长期 QQ 群体验。Dududa 不采用持续 hidden inner-thought、个人 Memory 驱动的
插话或 Bandit `SEND/SKIP`。

## 12. Scheduler：时间语义也是业务契约

定时任务不能被理解成简单的 `sleep + send`。订阅 revision、时区、DST、misfire、重启、撤销、
重复 tick 和未知投递都会改变“这是不是同一次业务发送”。

因此 Scheduler 只负责生成稳定 occurrence 和竞争 claim，内容与发送仍由主动 Orchestrator 所有。
APScheduler 可以作为 Trigger/DST 参考，但不应成为双 Worker 的 claim authority；Dududa 自有 SQLite
CAS 才能把业务幂等键、授权 revision 和 Delivery reconciliation 绑定在一起。

时间边界应偏向不打扰：不存在的 DST 时间跳过，过期 misfire 不补发，重启不突发，退订后的准备
任务在发送前失效。吞吐可以降低，错误目标和重复发送不能妥协。

## 13. Bandit：在宪法范围内学习

Bandit 适合 Dududa，但它应该优化已经合法的选择，而不是学习产品权限。

唯一合理的首个动作空间是：Static Router 完成所有 hard filter 后，同 Role、同 Tier、同隐私和
能力语义的 Endpoint 排序。它不能选择 Tier、AnswerProfile、SEND/SKIP、Memory Scope、工具权限、
目标或发送时间。

这一边界同时解决两个问题：

- 安全不会依赖一个需要探索才能学会的策略；
- reward 可以聚焦质量、成本和延迟，而不混入权限与打扰伦理。

Vowpal Wabbit 可作为隔离策略 Worker，Open Bandit Pipeline 可复核 IPS/SNIPS/DR；但没有
before-action propensity、action support 和可归因反馈时，任何“模型 B 本来会更好”的结论都是伪
因果。DR 不能创造不存在的 support，群聊沉默也不能被填成 0 奖励。

所以当前应先建设可评估日志和合成 estimator golden，而不是先上线探索。

## 14. 科学性：声明必须与证据等级匹配

Dududa 的“科学性”不来自使用论文术语，而来自可证伪的声明：

- synthetic fixture 证明契约，不证明真实用户质量；
- offline Adapter 证明兼容，不证明生产可靠；
- Shadow 证明无副作用和候选一致性，不证明用户体验提升；
- 人工盲评需要独立标注、cluster split 和预注册门槛；
- online learning 需要 propensity、support、ESS 和可归因反馈；
- 观察到 0 次安全事件仍应报告样本数和置信上界。

所有实验都应绑定代码、数据、Schema、Policy、模型、配置和 seed revision。结果应同时报告质量、
成本、延迟、失败和缺失反馈，而不是只展示一个最有利均值。

最重要的负向门禁始终是：跨 Scope、错误目标、重复发送、未授权 Tool、删除复活、敏感 Trace 和
安全 Gate 违规必须为 0。它们不能与平均质量做加权折中。

## 15. 外部框架的总体取舍

研究得到的共同模式是：**采用方法和词汇，拒绝重叠控制面。**

| 领域 | 候选 | 采用 | 不采用 |
| --- | --- | --- | --- |
| Router | RouteLLM、FrugalGPT、RouterBench、vLLM Semantic Router | cost-quality、oracle、signal 分类 | 替换三 Tier Router、生产 cascade、重叠网关 |
| Memory | Mem0、Letta、Graphiti、Zep | 分层、hybrid、temporal、benchmark | 外部 Scope authority、自动写入、第二 Agent Runtime |
| MCP | MCP Python SDK v2 | 长 Session、transport、cancel | Discovery 自动授权、SDK cache 作为 freshness authority |
| Scheduler | APScheduler | Trigger、DST/misfire 对照 | 双 Worker claim authority |
| Eval | IFEval、AlpacaEval、HELM、Arena | checker、随机盲评、版本化结果 | 整套 Server、许可不清或 NC 数据 |
| Bandit | VW、OBP、MABWiser | ADF Worker、OPE 复核、离线 baseline | 无 support 的效果声明、安全关键探索 |

这不是“拒绝开源框架”，而是避免让一个框架因为功能丰富而同时获得身份、权限、存储、调度和发送
所有权。框架越全能，越需要被放在 Dududa 的 Port 之外。

## 16. 主要架构张力

### 16.1 可适应性与可解释性

静态政策不如在线学习灵活，但它建立了可验证 baseline。合理路线不是永远静态，而是先固定安全
envelope，再让学习器在 envelope 内优化。

### 16.2 记忆收益与被遗忘权

更多记忆通常提高个性化，但也扩大隐私、错误事实和删除成本。因此 Memory 先完成生命周期，再证明
检索收益，而不是把删除作为后续功能。

### 16.3 主动帮助与群聊打扰

更积极不等于更有用。主动行为应该优化 precision 和 boundary respect，而不是消息数或回复率。

### 16.4 模块化与单人开发成本

模块边界会增加 DTO 和测试数量，但 WIP=1、共享 canonical contract 和清晰实施顺序能控制成本。
相反，一个大 Agent 循环在早期文件更少，却会把所有调试都变成 Prompt 调试，长期成本更高。

## 17. 推荐开发顺序

顺序本身体现了设计哲学：先让系统可达和可证，再增加能力，最后增加自主性。

```text
1. production-shape gate
   SQLite/image -> sampling capability -> health -> composition root

2. semantic evidence
   additive v2 -> annotation guide -> synthetic/schema pilot

3. controlled capabilities
   MCP v2 Spike -> Unified MCP -> bounded Capability Runtime

4. governed context
   Memory lifecycle -> CJK baseline -> optional semantic retrieval

5. controlled expression
   AnswerProfile -> Composer/Persona Eval

6. controlled initiative
   proactive contracts -> Scheduler -> sources -> Digest Shadow -> Probe Shadow

7. system evidence
   operations -> repository-wide Eval -> local audit -> compatibility audit

8. authorized reality
   S23 single-group validation

9. optional optimization
   S20 same-tier Endpoint Bandit
```

Bandit 不作为 S23 前置，因为真实群验证首先要证明确定性系统本身安全、可用。WebUI 保持测试入口，
不扩张为第二套 Control Plane。

## 18. 当前仍需负责人提供的产品判断

技术研究不能替代以下产品权衡：

- 哪些 Provider/模型属于每个 Tier，以及官方能力、价格、retention/residency 证据；
- 产品 Intent taxonomy、unsupported capability 和高风险 action；
- 中文群聊样本的授权、撤回、去标识和保存期限；
- SHORT/MEDIUM/LONG 的理想回答与 QQ 分片体验；
- 在 private-to-group 默认拒绝前提下，哪些具名 `SAFE_USER_PROFILE` 字段可由策略显式开放，以及
  Memory retention 和 `/forget` 交互；
- 校园栏目、行业来源、arXiv 分类、每日条数和修订策略；
- quiet hours、主动消息日上限、管理员同意和停止流程；
- 第二标注者、盲评者和仲裁机制。

缺少这些输入不阻塞 Contract、Fake、synthetic fixture 和隔离 Spike；它们阻塞真实质量声明、真实
Endpoint enablement 和 S23。

## 19. 设计宪章

后续实现可以用以下十条快速判断是否偏离 Dududa 的开发哲学：

1. 模型提出候选，确定性代码拥有权限和副作用。
2. 先过滤资格，再比较质量。
3. 身份、Scope、事实、发送状态各有唯一所有者。
4. Tier、Reasoning、AnswerProfile 和 Provider 保持正交。
5. 契约通过版本、additive change 和 N/N-1 reader 演进，不静默改变旧语义。
6. Protocol/SDK 不自动成为权限、Schema freshness 或业务所有者。
7. Memory 的删除和导出与检索同等重要。
8. 主动行为的授权高于被动回答。
9. 复杂方案先战胜简单 baseline，并保留 no-side-effect 验证和回滚。
10. 声明的强度不得超过证据等级。

## 20. 专题研究索引

具体版本、commit、许可证、实验矩阵、指标和失败线保留在以下专题报告中：

- [语义感知、Static Router 与 AnswerProfile](perception-routing-response.md)
- [Memory 架构与评测](memory-evaluation.md)
- [Unified MCP、Scheduler 与公开来源](mcp-scheduler-sources.md)
- [Conversation Probe](proactive-messaging.md)
- [Contextual Bandit](contextual-bandit.md)
- [Production Shape 预检](production-shape-preflight.md)
- [环境就绪报告](environment-readiness.md)
- [总推荐矩阵](recommendation-matrix.md)

## 21. 最终判断

Dududa 的核心竞争力不应是“调用了多少框架”或“让模型自主到什么程度”，而应是：在保持安全、
隐私、可解释和可回滚的前提下，逐步扩大模型能够提出有效候选的空间。

当前最优策略是继续完成已有架构，而不是替换它。先闭合 production shape，再建立受控 MCP/
Capability、Memory 生命周期和回答规划；主动消息最后接入，Bandit 最后优化。这样做速度看起来较慢，
但每一步都会留下可以复用的接口、证据和回滚路径，适合长期单人开发，也更接近一个真正可扩展的
Agent 框架。
