# 从“一切皆插件”到受治理的群体情境 Agent Runtime

状态：长程研究报告，不代表已经实现或批准生产切流

研究日期：2026-08-14

适用仓库：Dududa 主仓，不包含两个隔离协作仓

DeepSeek Harness 核验版本：`47f943859bef60e4160492346772ded9b24f765a`（仓库版本 `0.1.0-rc.5`）

## 1. 结论

Dududa 不应该把 DeepSeek Harness 的“一切皆插件”照字面搬进 Python，也不应该继续把模型
路由、Memory、MCP、群聊风格、主动消息和 WebUI 当成一组并列功能。更值得追求的核心创新是：

> **受治理的群体情境适应 Runtime**：一个不可卸载的最小治理内核，组合可逆、可观察、
> 分作用域的能力插件；系统把群聊理解为随时间变化且带不确定性的群体情境，在事实、权限、
> 人格和任务要求不变的前提下适应表达；所有自我改进先成为可评测、可撤销的候选资产，
> Bandit 只在安全等价的合法候选之间学习分配预算。

这一定义把四个看似分散的目标统一起来：

1. **可组合**：模型、Memory Retriever、MCP/Capability Provider、群情境分析器、Persona
   Renderer、Source、Bandit Ranker、Observation Projection 和 Web 面板都可以替换或新增，
   不修改 Domain 和治理内核。
2. **会适应**：系统学习群的主题分布、互动节奏和表达习惯，但不复制个人口癖，不把统计相关
   性写成真实人物关系，也不让群默认风格覆盖当前任务。
3. **会优化**：静态 Router 先完成资格过滤、Tier 选择和预算准入，Bandit 只对同 Role、同
   Tier、同安全等级的 Endpoint 或同语义 Variant 排序。
4. **可解释**：QQ 客户端旁的 Agent Observatory 从权威事件和 Receipt 投影运行轨迹，而不是
   再造 Router、权限、Memory、MCP 或发送控制面。

DeepSeek Harness 最有价值的不是包数量，也不是让模型直接生成运行时代码，而是三项方法：

- 用显式依赖表达空间可组合性；
- 用带 disposer 的资源所有权表达时间可组合性；
- 用仅追加事实流派生模型上下文、回放、统计和 UI。

Dududa 可以在此基础上走得更适合社交 Agent：Harness 当前明显偏开发与编码任务，Dududa 应把
`Identity/Scope/Authorization/Budget/WriteGate/Dispatch/Receipt` 固定在不可插件化的治理
内核中，并把群体情境、关系证据、主动行为和在线学习放在更严格的认识论与副作用边界内。

## 2. 研究范围与证据等级

本报告核验了以下一手材料：

- DeepSeek Harness 官方仓库、官方中英文架构文档和插件源码；
- Cordis 论文仓库及其 2026-08-13 草稿；
- Dududa 当前主仓代码、TreeWork 进度、设计文档和测试事实；
- 群聊解缠、语言顺应、长期 Memory、Skill 演化、Contextual Bandit 和 Agent
  Observability 的论文与开源项目；
- OpenTelemetry GenAI Semantic Conventions、OpenInference、Phoenix、Langfuse、pluggy、
  stevedore 和 Python `importlib.metadata` 等工程参考。

用户给出的博客园文章适合作为中文导读，但它是 2026-08-13 发布的第三方二手文章。报告中的
Harness 机制均回查官方仓库。论文证据也按成熟度区分：已正式发表、已接收、普通 arXiv
预印本、2026 年新预印本和仍在修订的 Cordis 草稿不能视为同等强度。

本报告只提出长程方法与下一版工程边界，不实施新架构，不修改运行容器，不恢复 S23，也不把
真实 Provider、群聊质量、在线 Bandit 或真实来源描述为已完成。

## 3. DeepSeek Harness 到底创新在哪里

### 3.1 “一切皆插件”不是“系统没有核心”

官方 README 和架构文档明确声明模型 Adapter、Tool Registry、Session Log、Agent Loop 等
产品能力都是 Cordis 插件，可由配置替换。但“插件”仍运行在不可消失的 Cordis 元内核之上：

- `Context`：服务和事件的共享作用域；
- `Fiber`：插件生命周期、子插件和资源所有权；
- Service Resolver/Registry/Reflect：同一 isolation realm 内同名 Service 的唯一实现、依赖
  响应和运行时检查；
- Event Bus：`emit/parallel/serial/waterfall` 等类型化扩展点；

在这之上还有两层产品机制，而不是 Cordis 必需内核：

- Cordis Loader 和可选 HMR：为配置驱动启动、替换和开发期重载服务；程序也可以直接调用
  `ctx.plugin()`，并不强制启用 HMR；
- DSH Profile、Bundle、Patch、公共 DTO、Session Event、Host API 和浏览器装配协议：组成
  Harness 的产品控制面和兼容边界。

因此更准确的表述是：

> **薄而稳定的组合内核，产品能力全部通过显式接缝装配。**

这与“每个文件都是插件”不同。插件化的对象应是有独立生命周期、替换价值和领域契约的能力，
而不是机械拆分 Python 文件或建立数百个微型 Package。

### 3.2 时间可组合性：注册必须能够撤销

Cordis 插件通过 `ctx.effect()` 登记副作用和 disposer。Service、事件监听、Tool 注册和子插件
可以归属于一个 Fiber；插件卸载时按所有权清理。依赖缺失时插件进入等待，依赖恢复后可以重新
激活。Cordis 提供 Fiber owner、`uid/epoch` 和可逆 Effect，但没有给每项领域注册提供统一的
公开 generation；Dududa 仍需在其上补充领域 generation fencing。核心价值不是“热更新”这个
表象，而是：

- 谁创建资源，谁拥有释放责任；
- 每项通过 Effect API 管理的注册都有 owner、disposer 和明确停止边界；
- 卸载后不能残留监听器、旧 Session、定时任务或重复注册；
- 已登记的 Effect 在失败装配时可以被回收。

但可逆 Effect 有严格边界。它能撤销进程内注册、监听器、连接和后台任务，不能撤回已经发出的
QQ 消息、已经被外部系统接受的 Tool 写操作或已经提交的数据库事实。Dududa 的外部副作用仍需
稳定幂等键、Preview/Commit、Receipt、UNKNOWN 状态和 reconciliation，而不是假定 disposer
可以“回滚一切”。绕过 Effect API 的资源、实现错误或失败的 disposer 也不在绝对保证内。

### 3.3 空间可组合性：依赖变化是生命周期事件

插件通过 `inject` 声明所需 Service，通过 `provide` 声明所提供的 Service。同一隔离 Realm
内的冲突会失败，依赖出现或消失会驱动插件激活和失活。这比一个全局 `plugins: dict` 科学，
因为它把“我依赖谁”和“依赖失效时怎么办”变成运行时事实。

Harness 也证明了 Scope/Realm 很重要：Host 级 Registry、Agent preset 和 Session/Agent
隔离的插件不能混在同一个全局命名空间。对 Dududa 而言：

- Host Realm：Model/MCP Registry、MCP Session、Scheduler、Storage、Observation Sink；
- Bot Realm：Provider/Output Adapter、账号级预算和配置；
- Group Realm：Persona、Group Context、允许能力的只读视图；
- Run Realm：Deadline、Budget、Candidate Set、Trace、临时 Tool Session。

Realm 决定可见性和资源所有权，但**不授予权限**。权限仍由治理内核依据 Actor、Scope、Grant
和当前策略确定。

### 3.4 Profile、Bundle、Patch 与 Agent Preset

Harness 使用 Profile、Bundle 和逐层 Patch 组装应用；随产品交付的主要 Profile 是 `web` 和
`headless`。标准、PTC、Minimal 和 Cordis/创造模式则是四种 **Agent Preset**，用于组装单个
Agent 的能力集合，不是四个 Profile，更不是四套 Runtime。Harness 的 ID Patch 会替换整段
`config`，不是 deep merge。

Harness Profile 本身位于可变的用户目录和 Patch 层，不等于已经认证、digest-bound 且自带
Last Known Good 的发布物。Dududa 应在借鉴组合思想的基础上，进一步把自己的 Profile 提升为
经过验证、摘要绑定且可回滚的组合版本，例如：

- `offline-eval`：全部 Fake、无网络、无 Output；
- `qq-shadow`：真实 Connector，模型可选，零发送；
- `single-group-canary`：固定 Bot/群 Grant、固定模型和预算；
- `digest-preview`：真实只读 Source、人工批准、无定时发送；
- `production`：只装配已批准且具备健康证据的 Provider。

Profile 只选择实现和配置，不得通过“加载某插件”自动获得 Capability、Memory Scope 或发送
权。否则部署配置会成为第二权限系统。

### 3.5 Session Event 是运行、回放和 UI 的共同事实源

Harness 的 Session 是类型化 append-only Event Log。`dsh-session` Core 本身提供内存 Event
Store，JSONL/SQLite 等持久性由独立插件监听 `session/event` 和 `session/flush` 实现。模型
历史由 Session Event 投影，不另存一份；其原则是“模型可见即已记录”。持久 Session Event、
运行中 Agent Hook、具体 Capability Event 又被清楚分开，但并非所有 Cordis Hook 都会进入
Session Log。

这建立了 Runtime、Telemetry 和 WebUI 可以共同消费的事实源，显著降低三份状态漂移；外部
Sink、异步投影和分页缓存仍可能失败或落后，不能因此宣称强一致。它也让 compaction 只改变
“模型可见表面”，原始轨迹仍可回放。

但 Harness 的 OTel 后端也给出反例：显式上传模式可以携带完整消息、系统 Prompt、Tool 参数/
结果和本机路径，Seam 本身不提供默认脱敏。Dududa 面向 QQ 群聊，不能采用“先完整记录，再由
部署方自行脱敏”的默认。Dududa 应记录足以重放**决策事实**的结构化事件，并让正文仍归属
QQ 会话数据；Observation Projection 默认只含 shape、digest、计数、状态和低基数 reason code。

### 3.6 Harness 当前仍是早期证据，不是稳定底座

本次核验的 GitHub `master` 为 `0.1.0-rc.5`，官方标记 developer preview 并明确预告破坏性
变更；仓库当时没有稳定 tag/Release。npm `latest` 已出现比该 GitHub HEAD 更新的 `rc.6`，
且包元数据不能直接证明对应 Git commit。因此：

- 可学习设计思想，不宜把 Dududa 直接迁到 Harness/Cordis；
- 若实验其代码，必须锁 commit 或 tarball integrity；
- “四种模式”“Trajectory”“创造模式”等可以在源码核验，但性能、Token 节省和生产稳定性
  没有足够比较实验；
- Cordis 论文仍是 2026-08-13 的在修订草稿，自进化 Harness 也仍是未来验证方向；
- Cordis 的语言级依赖控制不能隔离恶意 Host 插件，不可信代码仍需进程或容器沙箱；
- Service 接口的版本和结构兼容仍是论文明确保留的开放问题。
- 根项目采用 MIT 许可证，但第三方义务另由 `THIRD_PARTY_NOTICES.md` 披露；MIT 不代表插件
  生态已经通过供应链审查。

普通第三方插件与创造模式一样属于 Host 代码。Harness 的插件安装路径会调用包管理器，Git
插件的 `prepare` 还可能在 Agent sandbox 之外执行；官方因此要求只采用可信源码并锁定 commit。
Descriptor、签名、许可证和 provenance 只能提供来源证据，不能构成运行隔离或权限。Dududa
对不可信 Adapter 必须使用独立进程或容器，并在 Host 侧只暴露受限 RPC/Port。

### 3.7 MCP 是一个值得保留差异的反例

Harness 当前的 MCP Client 在 discovery 后把每个 MCP Tool 直接注册到 `ctx.tools`，使其进入
模型可见工具集合；它主要桥接 Tools，并不等价桥接 MCP Resources/Prompts。这个选择适合通用
Harness 的快速组合，却不适合直接复制到 Dududa。

Dududa 应借鉴 MCP Session 的生命周期、generation 和 disposer，但保留更严格的分权：

```text
MCP Registry: 怎样连接、Schema 是什么、连接是否健康
        !=
Capability Registry: 哪个 Actor/Scope 可以看到和调用哪项业务能力
```

Discovery 只更新外部事实，必须经过显式 Capability mapping、Schema/语义校验和授权，才可能
成为 Planner 候选。这不是“不够插件化”，而是 Dududa 相对 Harness 有意增加的治理创新。

### 3.8 Web 插件化也依赖稳定 Host 契约

Harness 的 Web 扩展不是任意 HTML 插槽，而是四层：

```text
Host Service / Remote Contract
  -> Client Cordis Plugin
  -> typed Slot declaration
  -> React contribution
```

Slot 注册随 Client Fiber 撤销，适合让 Trajectory、Settings 和 Tool 详情独立扩展。但当前
Plugin Inventory 主要是按需读取的只读快照，并不自动订阅 Loader 变化；外部插件的配置面仍受
Host allowlist 限制。Dududa 应借鉴稳定 Remote DTO、typed slot 和生命周期，不应把“装上插件”
解释成自动获得浏览器管理权限。

## 4. Dududa 已有基础与真实差距

### 4.1 已经具备的正确方向

Dududa 并非需要推倒重写。当前 `dududa.ports` 已包含：

- Model Router/Provider；
- Perception；
- Memory Repository/Retriever；
- Capability；
- Unified MCP；
- Response Plan/Composer；
- Persona Renderer；
- Proactive Trigger/Source/Output；
- Runtime、Context、Attachment 和 Output。

S08-S20/S22 的离线范围还已经建立了很多比普通插件框架更重要的治理契约：

- Haiku/Sonnet/Opus 三 Tier 静态路由、Reasoning/Context/Traffic/Admission；
- 复杂度判断与物理 Endpoint 路由分权；
- Memory 精确 Scope、WriteGate、删除/恢复、CJK BM25；
- MCP Registry 与 Capability Registry 分权；
- SHORT/MEDIUM/LONG 与 Tier/Reasoning 正交；
- 主动出站 Target/Grant/Preview/Dispatch/Receipt、Scheduler 和 no-send Shadow；
- Bandit Decision/Execution/Feedback、完整 support、propensity 和 IPS/SNIPS/DR/ESS；
- 版本化 Trace、Release、Backup/Restore/Rollback 和离线总审计。

这些不是需要被 Cordis 替换的“旧架构”，而是未来插件系统必须服从的 Domain 与治理基础。

### 4.2 缺少的不是 Port，而是组合运行时

当前扩展能力由不同 Registry、composition root 和配置分别管理，缺少统一的插件元数据与运行
投影。关键空白是：

| 空白 | 当前后果 | 目标 |
| --- | --- | --- |
| Plugin Descriptor | 无法统一列出版本、能力、依赖和风险 | 可验证、可查询的插件清单 |
| Lifecycle/Disposer | 各模块自行启动停止 | `load -> start -> quiesce -> stop -> dispose` |
| Realm/Scope | Host、Bot、Group、Run 装配没有统一语言 | 可见性和资源所有权显式化 |
| Dependency contract | 依赖失效时行为分散 | 自动失活，禁止持有陈旧 generation |
| Profile/Bundle | 配置能表达模块参数，但不能表达验证过的组合 | digest-bound 组合与 LKG 回滚 |
| Health/Readiness | 各 Registry 的健康事实不能统一投影 | 插件、Provider、Session 分层健康 |
| Migration/Compatibility | Schema 和 state 迁移按模块实现 | 插件自有 schema revision 与迁移收据 |
| Runtime Event Projection | 当前 Trace 主要是 phase event；丰富事实分散在 checkpoint、Decision、Receipt 和 Audit | 先做 projector，再用重放缺口决定是否新增持久事件账本 |
| Plugin inventory | 管理员看不到实际装配和失活原因 | 只读 inventory、generation、依赖图 |

### 4.3 Web 壳的事实边界

`apps/web` 已是较完整的 QQ 多账号工作台：Vue 通过同源 Node Gateway 连接 OneBot/NapCat，
已有聊天、联系人、群管理、通知、历史、SSE 和受限操作。`AgentConsole.vue` 也已经设计了
Conversation/Run/Settings、Tool、Permission、Reply Draft、Token、Cost 和 Timeline。

但 Agent Runtime 尚未接通。生产后端当前固定返回空的 `sessions`、`agentMessages`、`runs`
和 `configs`；现有 Agent DTO 是早期 UI DTO，缺少当前 Core 的 digest、revision、reason code、
Route Receipt、Capability/MCP 和 Bandit 事实。界面里的模型、Memory、Tool 开关不能直接接成
生产写 API，否则 Web 会变成第二套控制面。

因此正确结论是：**QQ 工作台的真实 NapCat 数据路径已实现并通过工程测试，但真实账号的外部
操作证据仍有限；Agent Console 是成熟布局原型，Runtime Observation API 和管理员控制面尚未
实现。**

## 5. 核心方法一：受治理的可组合 Runtime

### 5.1 不可插件化的最小治理内核

以下权威必须始终存在，不能作为普通插件卸载或替换：

| 内核权威 | 原因 |
| --- | --- |
| Identity 与 Actor binding | 插件不能定义“自己是谁” |
| Conversation/Memory Scope | 插件不能扩大可见数据范围 |
| Authorization 与 Grant | Discovery 或装配不能自动授权 |
| Budget/Deadline/Cancellation | 插件不能无限消费资源 |
| Runtime State Transition | 模型和插件只能提出合法状态的候选 |
| Memory WriteGate/Delete | Retriever/Backend 不能拥有写入真相 |
| Capability Eligibility | MCP 可连接不等于模型可调用 |
| Output Commit/Receipt | 外部发送必须唯一、可审计、可对账 |
| Audit/Invariant | 插件不能关闭证明自身越权的证据 |
| Plugin Loader Trust Policy | 插件不能自行提升信任级别 |

“不可插件化”不代表写死实现，而是这些规则的**语义权威**不能被普通扩展替代。持久化、
策略数据源或审计 Sink 可以实现 Port，但最终判定仍由内核完成。

### 5.2 三层插件模型

不建议设计一个万能 `Plugin.run(ctx)`。应分成三层：

```text
部署层：Profile / Bundle / Overlay / LKG
        决定装配哪些受信任版本

生命周期层：Descriptor / Dependency / Realm / Fiber / Disposer
        决定何时活跃、谁拥有资源、如何退出

能力层：Port / Provider / Consumer / Policy / Receipt
        决定业务输入输出、资格和证据
```

其中“能力接缝”至少包含三种角色：

1. Service Definition：由 Core 拥有的 Port、DTO、错误和版本；
2. Provider：一个或多个实现，例如 AstrBot Model、iCourse MCP、BM25 Retriever；
3. Consumer：Runtime、Capability Executor、Composer 或 Projection。

只写 Provider 而没有 Consumer Contract，或只写 hook 而没有版本化 DTO，都不构成完整接缝。

### 5.3 建议的 Plugin Descriptor

Descriptor 是静态事实，不包含 Secret 值：

```yaml
plugin_id: dududa.group-context.basic
plugin_version: 1.0.0
contract_version: 1
kind: analyzer
trust_tier: first_party
realms: [group, run]
provides:
  - port: dududa.group_context
    version: 1
requires:
  - port: dududa.runtime_events
    version: 1
permissions:
  network: false
  filesystem: none
  capabilities: []
state:
  schema_revision: group-context-v1
  migration: explicit
health:
  readiness: required
  freshness_seconds: 300
entry_point: dududa.plugins.group_context:plugin
artifact_digest: sha256:...
```

还应记录 provenance、license、source revision、Python/API 约束、配置 Schema digest、失败策略、
quiesce timeout、是否允许 HMR、数据分类和可导出的观测字段。

### 5.4 生命周期状态机

建议最小状态：

```text
DISCOVERED -> VALIDATED -> WAITING_DEPENDENCY -> STARTING -> READY
                                      |             |          |
                                      v             v          v
                                   REJECTED       FAILED    QUIESCING
                                                               |
                                                               v
                                                           STOPPED
                                                               |
                                                               v
                                                           DISPOSED
```

规则：

- 只有 Descriptor、配置、依赖、信任和迁移都通过后才能 `STARTING`；
- 每个 Provider 实例绑定 `plugin_id + version + realm + generation`；
- 依赖 generation 变化时，旧 Consumer 先 quiesce，再释放资源，不能继续调用陈旧对象；
- disposer 必须幂等，启动失败也要回收已注册的部分 Effect；
- stateful 插件默认不做透明 HMR，先完成 drain、checkpoint、migration 和 generation fencing；
- 外部副作用在 `QUIESCING` 时停止领取新任务，已提交任务用 Receipt 对账；
- Last Known Good Profile 是组合级回滚，不是只回滚某个 Python import。

### 5.5 Python 实现选择

不建议引入 Cordis/TypeScript 作为第二 Runtime。Dududa 已有 Python Port 和构造注入，最小实现
可以使用：

- `importlib.metadata.entry_points()`：发现已安装、明确命名空间下的插件；
- Standard Library `Protocol/dataclass/Enum`：延续当前类型和 DTO 风格；
- 小型自有 lifecycle owner：保存 generation、dependency graph、async disposer 和 health；
- 现有各领域 Registry：继续拥有 Model、MCP、Capability、Source 等业务规则；
- 可选 pluggy：只用于需要多参与者的有界 Hook，不作为 Service/Scope/权限容器；
- stevedore：可参考 entry point 的 Driver/Hook/Extension 管理模式，但无必要同时引入两套插件库。

第一版应优先写清 `Descriptor + Lifecycle + Realm + Observation`，而不是先选择插件框架。没有
这些 Domain 语义，换成 pluggy、stevedore 或自研装饰器都只是换一种动态 import。

### 5.6 什么应该和不应该成为插件

| 对象 | 建议 | 理由 |
| --- | --- | --- |
| Model Provider/Endpoint source | Plugin Provider | 实现可替换，资格仍由 Router 决定 |
| Perception Analyzer | Plugin Provider | 输出严格 DTO，Runtime 验证 |
| Group Context Analyzer | Plugin Provider | 可有规则、统计或模型实现 |
| Memory Backend/Retriever/Ranker | Plugin Provider | Scope/WriteGate 不可插件化 |
| MCP Transport/Server Adapter | Plugin Provider | Capability 授权保持分离 |
| Capability Provider | Plugin Provider | 只能发布候选业务能力 |
| Persona/Style Renderer | Plugin Provider | Fact Anchor 和最终 Validator 固定 |
| Source Provider | Plugin Provider | Scheduler/Target/Send 不属于 Source |
| Bandit Ranker | Plugin Provider | 只能返回合法集合内的分布 |
| Observation Projection/Sink/UI Panel | Plugin | 只消费脱敏事实 |
| Authorization/Scope/Dispatch Commit | 非普通插件 | 系统权威不可卸载 |
| 模型生成的任意 Host 代码 | Reject | `node:vm`/同进程 Python 不是安全边界 |

## 6. 核心方法二：群体情境，而不是群标签

### 6.1 四种学习对象必须分开

| 学习对象 | 产物 | 生命周期 | 不能混入 |
| --- | --- | --- | --- |
| 当前消息理解 | `PerceptionResult` | 单 Run | 长期人物关系、权限 |
| 当前会话线程 | `ConversationThreadSnapshot` | 分钟/小时 | 全群永久画像 |
| 群体情境 | `GroupContextSnapshot` | 小时/周，时间衰减 | 可执行 Skill、真实关系断言 |
| 长期事实 | Scoped Memory | 显式 TTL/删除 | 风格统计、Bandit 参数 |
| 策略优化 | Bandit Policy Artifact | 版本化窗口 | 事实、Scope、发送权 |

一句话：**风格状态不是 Skill，关系证据不是事实，Bandit 不是 Memory。**

### 6.2 先做会话解缠，再做主题和关系

群聊不是一条连续对话，同一时间可能有多个线程。ACL 2019 的 Conversation Disentanglement
任务和大规模人工语料明确显示群聊存在交错线程，纯邻接不能可靠恢复线程。若不先识别 reply、
mention、时间邻近和语义延续：

- 主题分布会把两个线程混成一个；
- “谁回应谁”的关系证据会被错误归因；
- Bot 回复后的反馈窗口会关联到无关消息；
- Memory 摘要会形成不存在的因果关系。

因此 `Conversation Disentangler` 应是群情境分析前的只读 Provider。它输出带置信度的线程
候选，不改变 QQ 原始顺序，也不凭低置信度结果获得发送或写 Memory 权限。

### 6.3 内容轴与形式轴正交、多标签、开放集

第一版内容轴可以是：

`闲聊、游戏、学习、校园、技术、时事、组织协调、混合、未知`

第一版形式轴可以是：

`短句连发、长讨论、问答、链接分享、表情/梗回应、协作协调、争论`

但 Snapshot 不应保存两个枚举值，而应保存：

```text
GroupContextSnapshot
  group_scope_digest
  content_distribution
  format_distribution
  continuous_features
  topic_candidates
  norm_candidates
  sample_size / unique_speakers
  evidence_window
  posterior_uncertainty / entropy
  change_point / stability
  analyzer_revision
  observed_at / expires_at
```

连续特征至少包括消息长度分位数、发言速率、回复边密度、并发线程数、代码/链接/表情比例、
轮次深度和不同成员覆盖率。BERTopic 可作为离线主题发现参考，但短文本稀疏，生产应对已经
解缠的窗口进行聚合，而不是给每条短消息硬贴主题。

### 6.4 三个时间尺度和覆盖优先级

群长期背景、当前会话模式、当前消息任务必须分开：

- 群长期背景：数周尺度，低频更新、强迟滞；
- 当前会话模式：数十分钟至数小时，快速衰减；
- 当前消息任务：立即生效，拥有最高表达要求优先级。

回答档位与表面风格不是同一条优先级轴。现有 S15 的 AnswerProfile 先选择请求档位，再施加
平台/Runtime cap：

```text
当前消息的显式档位要求（“详细解释”“只说结论”）
  > 当前任务复杂度与验证需要
  > 已授权的持久档位偏好
  > 配置默认值
  -> 平台/Runtime 硬上限
```

安全警告、拒绝、必要引用和必要步骤是不可裁剪的内容门禁，不参与软风格竞争，也不必然升级
AnswerProfile。

未来 Surface Style 另立新契约，建议优先级为：事实/Persona Identity/当前显式要求 > 当前会话
`StyleEnvelope` > 已授权用户 style override > 群级弱先验 > Persona voice default；该顺序仍需
通过 Spec 和真实 Eval 冻结，不能描述成当前实现。因此，即使一个群通常使用短句，群友问
“Transformer 是什么，请详细解释”，也应形成 LONG 的显式请求候选；S15 再在会话、Runtime
与平台硬上限下形成最终可执行档位。群风格只影响段落节奏、术语解释方式、emoji 和正式程度，
不削减必要事实。这与现有 `AnswerProfile`、Tier 和 Reasoning 正交设计一致。

### 6.5 防止群画像僵化和被操纵

- 保存分布和不确定性，支持 `mixed/unknown`，不永久盖章；
- 使用指数衰减、最小样本、迟滞和变化点检测；
- 限制单一成员的贡献，并要求多个不同成员形成群级证据；
- 排除 Bot 自己的输出，防止模型学习自身文本并逐步风格坍缩；
- 不复制连续原句、个人独特口癖、错别字指纹、辱骂或敏感身份暗示；
- 采用 `StyleEnvelope` 和最大 accommodation distance，而非自由 Prompt；
- 最终输出仍经过 Fact、Citation、Refusal、Target 和 Safety Validator。

风格顺应研究说明匹配并非越强越好。2019 年小规模用户研究只在部分会话风格用户中观察到
信任提升；2025 年受控比较发现模型常出现强趋同并可能超过人类反应，2026 年 WildChat 研究
进一步报告八种语言中的显著过度趋同。因此 Dududa 的目标是“有限顺应”，不是“完全融入到
无法区分”。稳定 OC 仍是身份锚点。

### 6.6 “何时说话”和“说什么”是两个问题

Multi-Party Chat 研究把群聊 Agent 的困难明确拆成：决定何时说话，以及生成基于多参与者的
连贯内容。Dududa 应继续保留确定性 Social Gate：

- 群情境分析器可以提出 `NormCandidate` 或 `OpportunityCandidate`；
- Perception/模型可以提供软证据；
- 是否回复、主动插话、目标、频率和 quiet hours 仍由确定性代码决定；
- Bandit 不得在线探索 `SPEAK/SILENT`；
- 主动 Probe 继续从单群、低频、no-follow-up、Memory off 的 S23 独立授权开始。

## 7. 核心方法三：Memory 保存证据，不制造社会事实

### 7.1 群情境、人物关系和事实 Memory 分库分权

不建议把所有学习结果都写进向量库。至少区分：

1. `Conversation Projection`：从 QQ 会话临时派生的线程和节奏；
2. `Group Context Projection`：聚合的主题/形式分布，可重算、有 TTL；
3. `Relationship Evidence Projection`：可审计互动边，不直接进入生成；
4. `Semantic Memory`：仅指经 S14 Scope/WriteGate/生命周期契约批准的长期记录；当前没有从
   群聊自动写入的生产路径，Group/Relationship Projection 不得借此落库；
5. `Experience/Feedback Ledger`：用于离线 Eval、Skill 候选和 Bandit join；
6. `Policy Artifact Store`：只保存经过发布流程的策略版本。

删除 QQ 数据或撤回授权后，原文、可逆特征和派生画像必须立即停止检索、训练和发布；系统按
lineage 删除或重建可撤销 Projection 与候选资产。不可篡改 Audit/Decision/Receipt 和必要的
最小 tombstone 只能保留无正文 digest 与删除证明。已经受相关样本影响的聚合 Policy/模型
Artifact 应进入 impact review、quarantine、重训或撤销流程，不能仅删除引用便声称已经“机器
遗忘”。

### 7.2 第一版只记录可观察互动，声明另走独立契约

允许持久化的互动边只从以下可观察事件开始：

```text
OBSERVED_REPLY
OBSERVED_MENTION
CO_PARTICIPATION
```

每条边必须带群 Scope、受限证据引用（运行时外部 ID 映射）或不可逆 digest、首次/最近观察
时间、计数、
`observation_quality/edge_resolution_confidence`、TTL、有效/撤销状态和 analyzer revision。
这里的质量只衡量 reply/mention/共现归属是否可靠，不衡量亲密度、权力、情感或现实关系。
平台显式 reply edge 与模型推断 edge 必须分开，低置信度的推断边不持久化。它只表示“观察到
某类互动”，不等于好友、敌对、上下级、亲密、喜恶或真实影响力。

`DeclaredRoleAssertion` 另带 issuer、Grant、Scope、expiry 和 revocation，只有发布者对该角色
具有权威时才生效。`PublicStatementCandidate` 可能是玩笑、含糊或过期表达，只保留 provenance
并进入专门验证/确认；默认不形成关系边，也不能绕过 WriteGate 变成事实 Memory。Web 和模型
默认只见 digest，访问原文必须另走当前授权的 QQ 会话查询。

语言顺应可以用于统计潜在互动结构，但相关结构不能直接写成社会事实。敏感关系默认不进入模型
上下文，只用于管理员受限的聚合检查或研究评测。跨群永不 join 同一人的关系与风格画像。

### 7.3 沿用 S14，而不是引入第二套 Memory 控制面

LoCoMo 和 LongMemEval 说明长期记忆的难点不仅是召回，还包括信息抽取、多会话/时间推理、
知识更新和拒答。Dududa 后续 Eval 应按这些能力拆分，而不是只报告 embedding Recall@K。

Mem0、Letta、Graphiti 和 LangMem 可作为 Backend/Index/Ranker Adapter 研究对象。Graphiti 的
时态关系生命周期尤其值得 Spike，但外部框架只能实现 Dududa Port，并继续服从：

- 精确 `MemoryScope`；
- WriteGate、冲突和 provenance；
- TTL、tombstone、导出、撤回和恢复；
- Backend 与 Ranker revision；
- 真实数据上的 BM25/Embedding/Hybrid 对照。

Memory extraction 攻击研究已经证明，长期 Agent Memory 会被诱导泄露。Stylometry-assisted
LLM Agent 的作者归因研究还提示风格特征存在去匿名化风险；其数据不是 QQ 群聊，只能作为风险
机制证据，不能外推为 Dududa 已测得的群聊效果。因此不保存可复原的个人风格向量或独特短语，
真实 QQ ID 不进入模型、Telemetry 或 Bandit 特征。

## 8. 核心方法四：Skill 自进化是候选资产流水线

### 8.1 Skill、Style Profile 和 Plugin 不是同一种东西

- **Skill**：某类任务的可加载指令、流程和契约；
- **Style Profile**：群级表达分布和允许的 Style Envelope，是数据资产；
- **Prompt Variant**：同一语义契约下可评测的实现候选；
- **Plugin**：实现 Port、拥有生命周期的代码或 Adapter；
- **Policy Artifact**：Bandit/规则策略的只读版本。

把群聊文本自动写成 `SKILL.md` 或系统 Prompt，会把不可信用户输入升级成长期控制指令；把
Style Profile 做成可执行 Skill，则会混淆数据、指令和代码三种信任等级。

### 8.2 推荐的演化闭环

```text
Runtime Receipt / 获准的群聊窗口 / 显式反馈
  -> ExperienceCandidate（去标识、来源和用途绑定）
  -> 离线聚类、失败归因或反思
  -> SkillCandidate / PromptVariant / StyleProfileCandidate
  -> 静态检查 + Contract Test + 事实/隐私/安全/质量 Eval
  -> 人工审阅和签名发布
  -> Shadow
  -> 小范围 Canary
  -> Stable / Revoke / Last-Known-Good rollback
```

模型可以生成候选，但不能直接修改活动 Prompt、Plugin Descriptor、Capability mapping、Router
策略或权限配置。每个候选必须记录训练/观察窗口、training-data lineage、consent/retention
revision、生成器版本、父版本、差异、适用 Scope、依赖契约、Eval digest 和到期时间。发布前
还必须执行内容相似度/训练文本外泄检查；原始数据撤回会触发前述 Artifact impact review、
quarantine、重训或撤销流程。

### 8.3 为什么不能照搬 Voyager 或创造模式

Voyager 在 Minecraft 中积累可执行 Skill，环境反馈客观、封闭且代码结果可测试；群聊的“用户
没反对”并不是客观成功。ExpeL 从轨迹提炼自然语言经验，适合作为候选生成参考，但错误反思
会被重复放大。DSPy 可以作为离线 Optimizer Adapter，不应在线改 Runtime。

DeepSeek Harness 的创造模式允许模型生成并运行 Host JavaScript，官方也要求按 Bash 权限
对待；`node:vm` 不是安全边界。Dududa 处理真实社交数据和外部发送，不能允许类似路径进入生产。

近期研究还发现 Skill Library 扩大时可能因选错 Skill 而退化，规模从小集合扩到 202 项时性能
最多下降 21%；这说明“插件/Skill 越多越先进”是错误目标。Dududa 应把 Skill 检索、冲突、
依赖漂移、过期和撤销作为一等问题。

## 9. 核心方法五：路由负责预算，Bandit 负责合法候选内学习

### 9.1 保留现有静态路由的权威顺序

推荐决策链：

```text
当前消息 + Context + Group Context（弱先验）
  -> Perception / TaskComplexityAssessment
  -> Deterministic TierPolicy（Haiku / Sonnet / Opus）
  -> ResponsePlan（SHORT / MEDIUM / LONG，独立）
  -> Static eligibility filter
       Role / Tier / capability / privacy / context / health / freshness
       budget / deadline / traffic / quota
  -> eligible compatibility class
  -> Static priority 或可选 Bandit ranker
  -> atomic admission
  -> Provider attempt / Receipt / settlement
```

智能难度判断仍位于 S09：它输出证据和复杂度，不选择 Provider。TierPolicy 将复杂度映射到档位，
Router 再将 Role+Tier 解析为物理 Endpoint。Group Context 只能作为弱先验；“详细解释”仍由
当前意图和任务复杂度覆盖。

### 9.2 三个维度不能绑定成一个档位

- Model Tier：能力与成本类别；
- Reasoning Profile：供应商支持的思考深度；
- Answer Profile：用户可见的 SHORT/MEDIUM/LONG。

短回答可能需要 Opus 判断后简洁作答，长回答也可能由 Haiku 整理低难度材料。Router 可以消费
已验证的输出预算，但不能根据“LONG”直接授权更高 Tier，也不能用“HAIKU”强制短回答。

### 9.3 Bandit 的正确作用

Bandit 最适合按以下顺序逐步开放：

1. 同 Role、同 Tier、同隐私/能力资格的多个 Endpoint；
2. 经评审且保持同一语义契约的 Prompt Variant；
3. `StyleEnvelope` 内有限的表达 Variant；
4. 更晚才研究安全等价 Capability Provider 的排序。

这里的“同隐私/能力资格”是未来 Router integration 必须生成和证明的 compatibility class。
当前 S20 DTO 只直接强制同 Role、同 Tier；驻留、retention、capability、health 和其他完整等价
条件尚没有由 S20 逐 action 校验，不能据现有离线测试宣称已闭合。

永不进入 action set：

- `REPLY/IGNORE`、`SPEAK/SILENT`；
- SHORT/MEDIUM/LONG；
- 身份、Scope、Memory 可见性或写入；
- Capability/Tool 授权；
- 主动发送目标、频率、日程；
- 安全、事实、引用和拒绝策略。

这延续 Dududa 已实现的“先过滤资格，再优化质量”，也避免 Bandit 为低成本奖励牺牲权限或
事实正确性。

### 9.4 上下文、动作和奖励

Endpoint Bandit 的上下文可以包含：

- Role、固定 Tier、复杂度分量和输入规模桶；
- 工具/结构化输出/上下文需求；
- AnswerProfile 和输出预算；
- 群情境的低敏聚合特征，不含 QQ ID、正文或关系图；
- Endpoint 当前健康、价格 revision 和容量桶。

动作必须是 Router 已发布的完整合法 Endpoint 集合；chosen propensity 在调用前记录，实际
执行动作必须与抽样动作一致。Admission 失败时以 `NOT_EXECUTED` 关闭并记录原 Decision，不归因
reward，默认回到 Router 的确定性降级或失败语义，不能把 fallback 冒充原 Bandit 动作。未来若
允许再次 Bandit 决策，必须创建新的 `decision_id`，基于新 Snapshot 重算完整 action set 和
propensity，单独消耗探索预算并排除刚失败的 Endpoint；无真实证据前，这不是当前 S20 能力。

奖励不应过早压成单一标量，先分别保存：

```text
explicit_satisfaction
independently_verified_task_success
correction_or_reask
latency
token_cost
provider_failure
```

“无人点赞”“下一条消息无关”“群聊暂时沉默”都不是负奖励。它们在反馈采集侧保持 pending；
归因窗口关闭后仍无有效反馈时，才按现有 S20 契约落为 `CENSORED`。缺失结果研究表明，忽略
非随机缺失会产生偏差，甚至线性 regret；密集代理指标也可能与真实目标错位。

### 9.5 从 S20 离线基础到在线学习

Dududa S20 已有 Decision/Execution/Feedback、propensity validator 和 IPS/SNIPS/DR/ESS，
但没有生产 Hook、真实 Endpoint support 或在线探索。合理阶段是：

1. Static baseline 继续生产权威；
2. 两个以上同 compatibility class Endpoint 分别通过 conformance；
3. Bandit 只做 Shadow ranking，验证 action support 和反馈 join；
4. 使用按群/会话聚类的 OPE，检查 ESS、clipping sensitivity 和 reward completeness；
5. 预注册极小 exploration budget、质量 floor、成本上限和自动回滚；
6. 先 Endpoint，最后才考虑 Style Variant；主动发送永不探索。

Vowpal Wabbit 可作为隔离 Policy Worker；Open Bandit Pipeline 可交叉验证离线估计。两者都只
实现 Dududa Port，不拥有 Router eligibility、日志事实或发布控制。

## 10. 核心方法六：QQ 与 Agent Observatory 融合

### 10.1 事件、投影、UI 和外部 Telemetry 分层

推荐形状：

```text
Dududa 现有 phase Trace / checkpoint / Decision / Receipt / Audit
        |
        v
只读、脱敏、版本化 Receipt/Checkpoint Projector
        |
        +-> Observation Projection
        +-> 若重放缺口确实存在，再新增 durable Agent Event Ledger
        |----------------------|
        v                      v
Dududa Query API          可选 Telemetry Mapper
+ /api/agent/events SSE
        |                      |
        v                      v
QQ 内 Agent Observatory  OTel/OTLP -> Phoenix/Langfuse/其他 Sink
```

当前 Runtime Trace 主要记录进入的 phase，而完整 Decision、TTL checkpoint、Receipt 和 Audit
分散在不同存储中；不能把它描述成已经存在的完整持久事件流。第一步应从现有权威事实建立
Projector，并用重放测试识别缺失事实，再决定是否新增 append-only Agent Event Ledger。

Observation Projection 是 Dududa 自有契约。OTel SDK/OTLP 负责采集和传输，OpenInference 是
一套基于 OTel 的 AI 观测语义，Phoenix/Langfuse 等才是后端 Sink。OpenTelemetry GenAI 语义
在核验 commit `8d3e4a0f3c34a46f6edb9c71e8666e02e6bf3958` 已覆盖 inference、retrieval、
memory、tool、agent 和 MCP，但相关规范仍处于 Development，正文属性也是 Opt-In。因此内部
DTO 不能直接绑定其易变字段，应由版本化 Mapper 转换。

Phoenix 适合本地 Trace/Eval 调试，Langfuse 的 Session、成本、反馈和 Dataset 体验成熟；
它们都不能成为 Dududa 的 Prompt、Router 或权限权威。尤其不能为了“可观测性”默认上传群聊
正文、Memory、Tool 参数、系统 Prompt 或模型 reasoning。

### 10.2 建议的 Observation 内容与来源

| 投影 | 关键字段 | 当前来源状态 |
| --- | --- | --- |
| Run | trigger、shadow/canary、phase、result、组件 revision | 可从现有 phase Trace/checkpoint/Receipt 派生，Projector 待实现 |
| Perception | intent/复杂度/should-reply、置信度、reason code；无 CoT | 可从现有结构化结果派生 |
| Group Context | 内容/形式分布、窗口、熵、有效期、analyzer revision | 新契约与新埋点 |
| ResponsePlan | SHORT/MEDIUM/LONG、预算、选择证据、Validator | 可从现有 Plan/Receipt 派生 |
| Router | Role/Tier、eligible/rejected、拒绝原因、Endpoint、fallback | 可从现有 Route Decision/Receipt 派生 |
| Model Attempt | Provider/Model、TTFT、总耗时、分项 Token、成本状态 | 部分可派生；TTFT 和 settled cost 需要新埋点 |
| Capability | Catalog、候选、计划、授权、预算、Observation/Validator | 可从现有结构化 Contract/Receipt 派生 |
| MCP | Server/Tool、generation、Schema freshness、health、retry/circuit | 可从 Registry/Result 派生，调用投影待实现 |
| Memory | Scope digest、strategy、候选/命中、rank、degraded reason；无正文 | 可从 Retrieval/Receipt 派生 |
| Delivery | Preview/Dispatch/Ack/UNKNOWN、幂等和 Receipt digest；无正文复制 | 现有 Contract/Receipt |
| Bandit | action support、chosen、policy、propensity、feedback join、OPE/ESS | 离线 Contract 已有，生产来源与投影未实现 |
| Plugin | descriptor、realm、generation、依赖、health、LKG、失活原因 | 新契约与新埋点 |
| Eval | evidence mode、provenance、bundle/revision、metric、score/label、失败原因 | 离线 manifest/report 已有，查询投影待实现 |

成本不能只是一个格式化字符串，应拆为币种、定价 revision、input/cache/reasoning/output Token
以及 `estimated/settled/unknown`。

### 10.3 与 QQ 工作台融合的信息架构

保留现有 QQ 主工作区，增加两级入口：

**全局 Agent 运维页**

- Overview：Run 量、错误率、P50/P95、TTFT、Token/成本、Delivery UNKNOWN，以及 rollout、
  digest、probe 等按行为和 Scope 分开的 switch/revision/owner；
- Runs：按账号、群 Scope 引用、触发、模式、Tier、Endpoint、状态筛选；
- Models：Endpoint health/capacity、资格拒绝、fallback 和成本趋势；
- Capabilities/MCP：分栏展示“能连接”与“已授权”，显示 generation/Schema/health；
- Plugins：依赖图、Realm、版本、generation、失活原因和 LKG，只读为先；
- Memory：Scope 拒绝、策略、命中和降级统计，不做全库正文浏览器；
- Group Context：群级聚合主题/形式和变化，不展示个人风格指纹；
- Bandit/Eval：日志完整率、support、feedback join、OPE/ESS、artifact revision，并始终显示
  `fixture/offline/shadow/canary/live` 和 evidence provenance。

**QQ 会话内 Agent 抽屉**

1. `运行`：当前会话关联的 Run；
2. `决策`：Perception -> Social -> AnswerProfile -> Router；
3. `执行`：Model、Capability/MCP、Memory、Composer、Delivery 时间线；
4. `反馈`：对已投递 Bot 消息进行显式评分和归因。

当前 QQ Message DTO 只预留了 `runId` 字段，服务端 mapper 尚不会填充。未来必须由服务端根据
`DeliveryReceipt -> account/conversation/message` 建立可信绑定，不能接受浏览器自报的 `runId`。
建立该绑定后才可以深链到 Run。需要查看正文时从当前获准 QQ 会话读取，不应把正文复制到通用
Trace 表。

### 10.4 Web 不是第二控制面

第一阶段只读。少量写动作只有在各自的专用权威命令实现后才能暴露，并携带 Actor、expected
revision/CAS、授权、幂等键和 Audit Receipt。当前状态需要逐项区分：

- 人工反馈：S20 有离线 Feedback Contract，但生产写命令待实现；
- 取消 Run：已有取消契约不等于管理员 API，专用命令待实现；
- Preview/Permission 审批：部分领域有 Contract，统一 Web 命令待实现；
- switch/pause/unsubscribe：按 rollout、digest、probe 和 Scope 分别实现，不能假装一个全局开关。

禁止 Web 直接强制 Tier/Endpoint、修改 Router/Bandit/Prompt/Persona、动态开放 MCP Tool、读写
Memory、读取 Secret 或绕过 Output 直接发送 QQ。当前 Agent Console 的本地可变开关应替换成
“有效配置只读投影”，而不是简单接上 REST 写接口。

现有 `approveDraft()` 会直接调用 NapCat；当前因 Agent Session 未接通而不可达，但在接通前必须
删除这条直发语义，改为调用权威 Preview/Dispatch/Output 命令并取得 DeliveryReceipt，否则会
绕过 Runtime 的授权、幂等和对账链。

Observatory 还必须先补管理员认证和读权限。当前 loopback Host 与同源写校验不等于 operator
authentication/RBAC；每次查询都要绑定 operator、Bot/account 和 group Scope，并留下只读审计。
在认证、会话安全和非 loopback 部署门禁完成前，不得向外网暴露 Runs、Memory、Group Context
或 Bandit 页面。

## 11. 一个统一的端到端形状

```text
QQ Connector
  -> Conversation Disentangler
  -> Group Context Provider -----------------------------|
  -> Context Builder + scoped Memory                     |
  -> Perception / Complexity                             |
  -> deterministic Social Gate                           |
       IGNORE -------------------------------------------|-> Receipt/Event
       REPLY -> ResponsePlan                             |
              -> Router eligibility -> optional Bandit  |
              -> Model / Capability / MCP               |
              -> Composer (Fact Anchor)                  |
              -> Persona + bounded StyleEnvelope         |
              -> Final Validators                        |
              -> Output Commit / DeliveryReceipt --------|
                                                          v
                                       Observation Projection
                                          -> QQ Observatory
                                          -> optional OTel Sink

获准的 Receipt / Feedback / 群聊窗口
  -> 离线 Group Context 更新
  -> Relationship Evidence Projection
  -> Skill/Prompt/Style Candidate
  -> Eval + 人工批准 + Shadow/Canary + LKG
  -> 可发布 Plugin/Profile/Policy Artifact
```

这个闭环的关键不是每一步都用 LLM，而是每种不确定性都有正确归属：模型负责候选，统计器负责
分布，Memory 负责有来源的长期事实，Bandit 负责合法候选分流，确定性 Runtime 负责权威和
副作用。

## 12. 长程路线

这不是第二套 Sxx 路线。现有 S01-S23 事实保持不变；新方向应在下一次 Tree Alignment 中作为
S23 之后或与外部数据门禁解耦的增量分支映射到既有工程顺序。

### P0：组合与观察基础，不依赖真实群聊

目标：让现有 Port 真正成为可管理能力，同时不改变生产行为。

1. 冻结 `PluginDescriptor`、Realm、Dependency、Lifecycle、Generation 和 Disposer 契约；
2. 选两个无副作用 Provider 做 Spike，例如 Fake Model + Fake Group Analyzer；
3. 为现有 Model/MCP/Capability/Memory/Persona/Source Registry 增加只读插件投影，不合并
   领域 Registry；
4. 先实现 Receipt/Checkpoint Projector 和低敏 `ObservationProjection`，用重放缺口决定是否
   新增 durable Agent Event Ledger，明确正文不进入默认 Trace；
5. 建立 `offline-eval`、`shadow` 等 digest-bound Profile 和组合 LKG；
6. 增加 operator authentication/RBAC、账号/群 Scope 和只读审计，作为所有 Observatory 页面的
   前置；
7. 接通 Web 只读 Run/Decision/Plugin Query API 与独立 `/api/agent/events` SSE，替换空 Agent
   DTO；现有携带 QQ 消息的 `/api/events` 保持独立数据面；
8. 移除 Agent Reply Draft 的 NapCat 直发路径，在未来专用权威命令完成前保持不可用；
9. 只接本地可选 Phoenix/OTel Sink Spike，默认关闭；
10. 为 Group Context 定义双轴、多标签、时间衰减的 DTO 和固定合成 fixture。

P0 完成只能声明“组合契约和可观察投影完成”，不能声明插件生态、群风格学习或在线自进化完成。

### P1：真实数据上的有限群体适应

依赖用户授权的脱敏群聊 Pilot 和标注流程：

1. 30-50 个窗口验证会话解缠、内容/形式 taxonomy 和数据治理；
2. 扩至 200-500 个窗口，按群整体切分，评估校准、漂移和变化点；
3. 建立 `StyleEnvelope` 候选和“明确要求覆盖群默认”的反例集；
4. 在 no-send Shadow 中盲评内容保持、任务完成、自然度、过度趋同和群体适配；
5. 建立 Relationship Evidence Projection，只记录互动事实、TTL 和撤销；
6. 建立 Skill/Prompt/Style Candidate 离线生成、Contract、人工发布和 LKG；
7. 接通人工反馈 sidecar，但不把沉默自动变成奖励。

P1 不进行自动 Prompt 改写、人物关系断言、跨群画像或主动行为探索。

### P2：保守在线优化与生态扩展

依赖至少两个同 Role+Tier 合法 Endpoint、真实反馈和 SLO：

1. Endpoint Bandit Shadow、OPE 和 ESS/支持检查；
2. 极小、预注册、可立即回滚的同档 Endpoint exploration；
3. 经 Endpoint 阶段证明后，研究同语义 Prompt/Style Variant；
4. 建立签名插件包、兼容矩阵、迁移/回滚、依赖漂移和 quarantine；
5. 只对可信插件开放同进程运行，不可信 Adapter 进入独立 Worker/容器；
6. 将真实 Source/MCP、Memory Backend、可观测 Sink 按同一 Contract 接入；
7. Web 从只读逐步增加经过权威命令的窄写操作。

主动消息的发送/沉默、目标和频率永不进入 Bandit exploration。真实群放量继续遵守 S23 的逐
行为授权，不因插件或 Bandit 完成而自动扩大。

## 13. 评测体系

### 13.1 插件组合

- 加载/失败/卸载/重复卸载后零残留；
- 依赖出现、消失、generation 更新和循环依赖；
- quiesce 超时、后台任务取消、Session 关闭和部分启动回收；
- Profile digest、配置漂移、Schema 迁移、LKG 回滚；
- 新增 Fake Provider 只增加插件/配置，不修改 Core Domain；
- 恶意/未知插件不能通过 Descriptor 自授予权限。

### 13.2 群体情境与风格

- 按群划分的内容/形式多标签校准，而非随机消息切分；
- 时间漂移、少样本、混合/未知、活跃成员支配和 Bot 自反馈；
- 短句群中的“详细解释”、梗图群中的严肃问题等覆盖反例；
- 内容保持、事实、引用、拒绝、Persona Identity 和 accommodation distance；
- 删除/撤回后检索与继续使用为零，并生成 lineage invalidation Receipt；受影响 Artifact 进入
  impact review、quarantine、重建或撤销，不伪称自动机器遗忘。

### 13.3 Memory 与关系证据

- exact/recency/BM25/Embedding/Hybrid 的分项对照；
- LongMemEval 风格的信息抽取、多会话、时间、更新和拒答；
- wrong-group、跨 Bot、跨 Persona、删除后召回目标为零；
- 互动证据与社会关系断言严格区分；
- Prompt Injection/Memory extraction 和风格去匿名化攻击。

### 13.4 Router 与 Bandit

- hard eligibility 违规 action 为零；
- 完整 action support、before-action propensity、实际执行绑定；
- delayed/missing/censored feedback、admission `NOT_EXECUTED`，以及未来若获批准时使用全新
  `decision_id` 的重决策；
- IPS/SNIPS/DR、ESS、最大 weight、clipping sensitivity；
- 质量 floor、成本/延迟上限和 LKG 自动回滚；
- 以 conversation/group cluster 分析，避免把相互影响的消息当独立样本。

### 13.5 Observatory

- 权威 Event 可重放出同一 Run Projection；
- UI 不自行推导权限、模型选择或 Delivery 状态；
- 默认 Trace/metric 和新的 `/api/agent/events` Observation SSE 不含正文、QQ ID、Prompt、Tool
  body、Memory 文本或 CoT；现有 QQ `/api/events` 属于独立数据面并继续按其授权传输会话消息；
- QQ Message -> Run 深链和分页/重连不改变统计；
- OTel Sink 关闭时零导出，开启时 Mapper 版本和脱敏策略可审计。

## 14. 主要失败模式

| 失败模式 | 结果 | 防线 |
| --- | --- | --- |
| 字面“一切皆插件” | 权限和发送也可被卸载/替换 | 固定治理内核 |
| 每个模块拆成独立包 | 单开发者陷入版本与装配成本 | 按能力边界而非文件拆分 |
| 一个万能 Registry | Scope、权限和连接混为一谈 | 领域 Registry + 生命周期层 |
| Discovery 自动开放 Tool | 新 MCP 获得模型权限 | Capability mapping 独立授权 |
| HMR 状态型组件 | 旧 Session/租约/任务残留 | quiesce、generation、migration |
| 群永久硬分类 | 当前任务被默认风格覆盖 | 分布、时间尺度和确定性优先级 |
| 完全模仿群友 | 过度趋同、身份丢失、去匿名化 | StyleEnvelope + Persona Anchor |
| 推断真实人物关系 | 统计相关性变成错误社会事实 | 只存互动 Evidence |
| 聊天记录直接生成 Skill | Prompt Injection 长期固化 | Candidate/Eval/人工发布 |
| Bandit 学发送与权限 | 用探索制造真实副作用 | action set 硬限制 |
| 把沉默当负反馈 | 非随机缺失导致策略偏差 | 采集侧 pending，窗口关闭后 `CENSORED` |
| Web 直接改运行配置 | 第二控制面和状态漂移 | 只读投影 + 权威命令 |
| 全量 Telemetry | 群聊、Memory、Tool 数据泄露 | metadata-first、正文 opt-in |
| 引入外部 Memory/Agent 框架 | 第二套 Scope/写入/权限 | 只能实现 Port |

## 15. Adopt / Spike / Reject

| 方向 | 决策 | 说明 |
| --- | --- | --- |
| 薄组合内核 + 领域插件 | Adopt | 与现有 Port/Registry 兼容 |
| Descriptor/Realm/Lifecycle/Disposer | Adopt | 当前最关键的组合缺口 |
| 持久事实与实时 Hook 分离 | Adopt | Runtime、回放和 UI 共同基础 |
| Profile/Bundle/LKG | Adopt | 先做受验证组合，不做任意脚本 |
| GroupContext 多轴分布 | Adopt | 替代僵硬群分类 |
| StyleEnvelope 有界顺应 | Adopt | 当前任务和事实门禁优先 |
| Relationship Evidence | Adopt | 只表示可观察互动 |
| Skill 候选资产流水线 | Adopt | 模型提案、人审发布、可回滚 |
| 同档 Endpoint Bandit | Adopt/后置 | S20 已有离线基础，仍缺真实 support |
| Python lifecycle owner | Spike | 先用两个 Fake 证明语义 |
| pluggy Hook | Spike | 仅用于有界多参与者 Hook |
| Graphiti/Embedding Memory | Spike | 先由真实数据证明收益 |
| Phoenix/OTel Exporter | Spike | 本地、默认关闭、Mapper 隔离 |
| Cordis 作为 Dududa Runtime | Reject | 会形成第二技术栈和控制面 |
| 任意模型生成 Host 代码 | Reject | 同进程 VM 不是安全边界 |
| 权限/Scope/发送普通插件化 | Reject | 破坏治理权威 |
| 自动写活动 Prompt/Skill | Reject | 数据到控制指令的越权升级 |
| Bandit 决定回复/沉默/长度 | Reject | 非等价动作且有真实社交副作用 |
| 默认上传群聊正文/CoT | Reject | 不符合 QQ 数据边界 |

## 16. 最终设计哲学

Dududa 的方法创新不应被描述为“接入了很多模型、Memory、MCP、Bandit 和 WebUI”。更准确的
五条原则是：

1. **组合而不失权威**：所有实现可替换，身份、Scope、授权、预算和副作用不可被替换。
2. **适应而不伪装**：学习群体情境和表达习惯，但保留稳定 OC、事实密度和任务义务。
3. **记证据而不造事实**：Memory 保存来源、时间、置信度和冲突，关系只保留互动证据。
4. **学习而不越界**：Skill 和 Policy 都从候选开始，Bandit 只在合法等价动作中优化。
5. **可观察而不复制控制面**：同一权威事件派生回放、评测和 UI，Web 与 Telemetry 不拥有业务
   决策，也不默认复制群聊正文。

如果这五点能够形成可执行契约、真实数据 Eval 和逐步放量证据，Dududa 的创新就不再是功能
堆砌，而是一种适用于长期社交 Agent 的系统方法：**在持续变化的人群环境中保持身份与治理
稳定，同时让能力、表达和资源分配可以被安全地组合、学习和撤销。**

## 17. 参考资料

### Dududa 主仓事实入口

- [当前实施进度](../refactor/PROGRESS.md) 与 [目标架构](../refactor/target-architecture.md)；
- [模型路由](../design/model-routing.md)、[Perception/Social Decision](../design/perception-and-social.md)、
  [Memory](../design/memory.md)、[Persona](../design/persona.md) 与
  [在线学习](../design/online-learning.md)；
- [Contextual Bandit 调研](contextual-bandit.md) 与
  [S20 离线完成报告](../refactor/s20-offline-bandit-report.md)；
- [MCP/Capability 设计](../design/capability-and-mcp.md) 与
  [主动消息设计](../design/proactive-messaging.md)；
- [QQ Web 工作台说明](../../apps/web/README.md)、
  [Agent Console](../../apps/web/src/components/AgentConsole.vue) 与
  [现有空 Agent 后端投影](../../apps/web/server/onebot-hub.ts)；
- [Core Ports](../../packages/dududa-agent/src/dududa/ports) 与
  [Runtime phase Trace](../../packages/dududa-agent/src/dududa/runtime/state.py)。

### DeepSeek Harness 与插件架构

1. DeepSeek AI, [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness),
   核验 commit `47f943859bef60e4160492346772ded9b24f765a`, 2026-08-13。
2. DeepSeek Harness,
   [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/architecture.zh.md)。
3. DeepSeek Harness,
   [Capability Seams](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/capability-seams.zh.md)。
4. DeepSeek Harness,
   [Cordis Lifecycle and Effects](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/cordis-tutorial/02-lifecycle-and-effects.zh.md)。
5. DeepSeek Harness,
   [Session Telemetry OTel](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/session/session-telemetry-otel/README.md)、
   [MCP Client](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/mcp/mcp-client/README.md)、
   [Client Runtime](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/client/runtime/README.md)、
   [Plugin Inventory](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/packages/client/ui-settings-plugin-inventory/README.md) 与
   [Git Plugin Publishing](https://github.com/deepseek-ai/deepseek-harness/blob/47f943859bef60e4160492346772ded9b24f765a/docs/user/develop/basic/publish.md#installing-from-github-the-build-script-catch)。
6. Cordis, [A Programming Paradigm for Spatiotemporal Composability](https://github.com/cordiverse/paper),
   核验 commit `948a07b369c62adb3b12e102458be5c18dfb69b9`，2026-08-13 在修订草稿。
7. pluggy, [Official Documentation](https://pluggy.readthedocs.io/en/stable/)。
8. OpenStack, [stevedore Documentation](https://docs.openstack.org/stevedore/latest/)。
9. Python, [`importlib.metadata`](https://docs.python.org/3/library/importlib.metadata.html)。
10. 见路非道，[DeepSeek Harness 2026：一切皆插件](https://www.cnblogs.com/sing1ee/p/22455466)，
    2026-08-13，二手中文导读。

### 群聊、风格与 Memory

11. Kummerfeld et al., [A Large-Scale Corpus for Conversation Disentanglement](https://arxiv.org/abs/1810.11118),
    ACL 2019。
12. Grootendorst, [BERTopic](https://arxiv.org/abs/2203.05794), 2022。
13. Khalid and Srinivasan, [Style Matters!](https://doi.org/10.1609/icwsm.v14i1.7306), ICWSM 2020。
14. Ireland et al., [Language Style Matching Predicts Relationship Initiation and Stability](https://doi.org/10.1177/0956797610392928),
    Psychological Science 2011。
15. Hoegen et al., [An End-to-End Conversational Style Matching Agent](https://arxiv.org/abs/1904.02760),
    IVA 2019。
16. Ananthasubramaniam et al., [Exploring Linguistic Style Matching in Online Communities](https://aclanthology.org/2023.sicon-1.7/),
    ACL SICon 2023。
17. Jin et al., [Deep Learning for Text Style Transfer: A Survey](https://arxiv.org/abs/2011.00416),
    Computational Linguistics 2022。
18. Blevins et al., [Do language models accommodate their users?](https://arxiv.org/abs/2508.03276),
    EACL 2026。
19. Blevins, [Accommodation Goes Both Ways](https://arxiv.org/abs/2605.29278), 2026 预印本。
20. Wei et al., [Multi-Party Chat](https://arxiv.org/abs/2304.13835), 2023。
21. Maharana et al., [LoCoMo](https://arxiv.org/abs/2402.17753), 2024。
22. Wu et al., [LongMemEval](https://arxiv.org/abs/2410.10813), ICLR 2025。
23. Wang et al., [Unveiling Privacy Risks in LLM Agent Memory](https://arxiv.org/abs/2502.13172),
    ACL 2025。
24. Zhang and Zhang, [Assessing Deanonymization Risks with Stylometry-Assisted LLM Agent](https://arxiv.org/abs/2602.23079),
    2026 预印本；其作者归因设置仅用于风险机制参考。
25. [Mem0](https://github.com/mem0ai/mem0), [Letta](https://github.com/letta-ai/letta),
    [Graphiti](https://github.com/getzep/graphiti), [LangMem](https://github.com/langchain-ai/langmem)。

### Skill 演化与 Bandit

26. Wang et al., [Voyager](https://arxiv.org/abs/2305.16291), 2023；
    [代码](https://github.com/MineDojo/Voyager)。
27. Zhao et al., [ExpeL](https://arxiv.org/abs/2308.10144), AAAI 2024。
28. [DSPy](https://github.com/stanfordnlp/dspy)。
29. Song and Wei, [More Skills, Worse Agents?](https://arxiv.org/abs/2605.24050), 2026 预印本。
30. Fan et al., [Skill Drift Is Contract Violation](https://arxiv.org/abs/2605.10990), 2026 预印本。
31. Li et al., [A Contextual-Bandit Approach to Personalized News](https://arxiv.org/abs/1003.0146),
    WWW 2010。
32. Agarwal et al., [Making Contextual Decisions with Low Technical Debt](https://arxiv.org/abs/1606.03966),
    2016。
33. Saito et al., [Open Bandit Dataset and Pipeline](https://arxiv.org/abs/2008.07146),
    NeurIPS Datasets and Benchmarks 2021；[OBP](https://github.com/st-tech/zr-obp)。
34. [Vowpal Wabbit](https://github.com/VowpalWabbit/vowpal_wabbit)。
35. Mahrooghi et al., [Multi-armed Bandits with Missing Outcome](https://arxiv.org/abs/2411.05661),
    UAI 2025。
36. Takehi et al., [Off-Policy Learning with Partially-Observed Reward](https://arxiv.org/abs/2506.14439),
    ICLR 2025。

### Agent 可观测性

37. OpenTelemetry,
    [GenAI Semantic Conventions](https://github.com/open-telemetry/semantic-conventions-genai/tree/8d3e4a0f3c34a46f6edb9c71e8666e02e6bf3958)，
    核验 commit `8d3e4a0f3c34a46f6edb9c71e8666e02e6bf3958`。
38. Arize AI, [OpenInference](https://github.com/Arize-ai/openinference) 与
    [Phoenix](https://github.com/Arize-ai/phoenix)。
39. Langfuse, [Observability](https://langfuse.com/docs/observability/overview) 与
    [开源仓库](https://github.com/langfuse/langfuse)。
