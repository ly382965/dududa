# Dududa 2.0 实施计划

状态：S01–S11 的本地增量实施步骤已完成。旧 AstrBot Handler 在 `off/shadow`
模式下仍是权威入口；白名单 Canary 只在持久 claim 后取得单一发送所有权。真实群聊场景测试
统一延期到所有当前发布必需模块、既定 WebUI 测试工作和本地集成审计完成之后；独立可选 S20
不属于该发布前置。

2026-08-09 Alignment 新增规划：短/中/长三档回答、低频 Conversation Probe，以及基于公开
Capability/MCP 来源的校园/行业/arXiv 订阅日报。三项均**尚未实现**，不扩大 S08-S11 的历史
完成范围，也不授权真实发送。

## 交付规则

每个 PR 必须说明：

- 目标和所属 Phase；
- 新增、移动或修改的文件；
- 保持不变的用户可见行为；
- 风险和明确的非目标；
- 验证命令与证据；
- 回滚方法；
- 兼容代码及其移除门槛。

每个 Phase 边界都必须执行 Shell 语法检查、Python 编译、全部单元测试和契约测试、
Compose 解析、仓库扫描以及 `git diff --check`。一旦对应范围发生变化，应立即扩展
Docker、插件导入、MCP、Memory 隔离、集成、Eval 和 smoke 测试门禁。

## 模块开发优先级与单人策略

本节中的 P0/P1/P2 表示开发优先级，不是上文的 Phase 编号。对应关系为：

- P0：Phase 2–5，建立公共契约、安全边界、兼容层和可重复 Eval 基线；
- P1：Phase 6–7，形成可选择性切换的端到端 Runtime、工具闭环与受控主动出站闭环；
- P2：Phase 8–10，完成规模化质量优化、Control Plane、部署和兼容清理。

原 4 人并行估算只保留为历史参考。当前按 **1 人、WIP=1** 执行：任何时刻只实现一个
可独立验证和回滚的步骤，完成退出门禁后再进入下一步。不要把原工期机械乘除；Memory 数据
质量、外部服务稳定性和真实群测试窗口会主导实际周期，时间不能替代退出门禁。

### 当前模块完成度

下表按 2026-08-04 的 `716e227` 和 Dududa 2.0 统一完成定义判断。S08-S11 已补齐静态
路由、语义/难度判断、离线 Runtime、Shadow、受控 Canary 与回滚边界；真实 Provider 效果、
Memory/Tool 和附件仍按各模块独立门禁判断。授权群放量不再穿插在模块开发中，只在最终阶段执行。

| 模块或工作流 | 状态 | 已有证据 | 达到完成仍缺少 |
| --- | --- | --- | --- |
| Phase 0 审计、`v1alpha` 接口与迁移计划 | 已完成 | 当前状态、依赖、设计、ADR、迁移和实施文档已形成，并通过文档门禁 | 不包含 Runtime 代码；进入 S01 后按实现证据重新判断 |
| 核心 Package 与 Agent Runtime | 部分完成 | Orchestrator、CAS State Store、完整直聊、Delivery acknowledgement/reconciliation、无副作用 Shadow 和受控 Bridge 已实现 | 真实 Provider composition、Memory/Tool/Attachment Runtime 与授权生产证据 |
| 输入 Connector 与 Output Adapter | 部分完成 | AstrBot Connector/Output、结构化 @、Delivery、持久 rollout claim/tombstone、发送前控制复核和 Bridge 已实现 | 真实 Attachment Source、第二平台与授权真实群 delivery 证据 |
| 模型路由器 | 已完成（S08 静态范围） | 三 Tier 契约、逐 Endpoint descriptor、Registry、隐私/预算/健康/流量过滤、容量 admission、fallback、Fake 与兼容 Adapter | 真实多 Provider 质量/延迟/成本证据；动态优化和 Bandit 不在 S08 范围 |
| Memory | 部分完成 | Memory v2 Scope/Selector/Repository/Write Gate、内存/JSON 参考 Adapter、fail-closed Iris Protocol Adapter、隔离矩阵和可逆迁移工具已实现 | 真实 Iris SDK Backend、Context Builder 接入、删除/导出闭环、效果 Eval、shadow 和生产切流 |
| MCP 集成 | 部分完成 | iCourse stdio Server、SQLite、AstrBot 配置和 10 个 Tool 已存在 | Unified Client、Server Registry、Schema cache、allowlist、错误/健康/熔断和单 Client 切换 |
| Capability 与 Tool Runtime | 部分完成 | 课程命令已有固定手工调用流程 | Registry、Retrieval、有限 Planner、逐步授权 Executor、Validator 和副作用/预算门禁 |
| 语义理解与 Social Decision | 部分完成 | 通用 Intent/Entity/Reference/Evidence、Rule/Model/Merger/Validator、Social Policy、Complexity、TierPolicy 和 320 条合成 Eval 已实现 | 真实脱敏数据、人工标签确认、校准和多轮/附件语义 |
| 回答档位与动态输出预算 | 未完成 | 现有 `max_output_tokens`、`MAX_LENGTH` 和静态字数上限可作为原语 | 缺少独立 `ResponsePlan(SHORT/MEDIUM/LONG)`、显式详略证据、动态预算、Router 正交性和最终长度/完整性 Validator |
| OC 与 Persona | 部分完成 | 最小 Composer、确定性单 Persona Renderer、Fact/target/constraint 保持与 Render Validator 已进入 S10 | 完整 OC 资产、多 Persona、版本发布和人工风格 Eval |
| 主动消息与订阅推送 | 未完成（S15A-S15E） | Legacy TargetTalk、Delivery/rollout、iCourse MCP 和 Scheduler 需求可提供局部场景 | 缺少 initiated-run、主动授权、Subscription/Scheduler/Source ledger、公开来源、Digest/Probe Shadow 和回滚闭环 |
| 在线学习 / Bandit | 未完成（S20） | S08-S11 决策 receipt、脱敏聚合和受控 rollout 可供未来独立设计 | 当前无实现、配置或执行 hook；仍需 propensity/support、OPE 与单独安全评审；禁止学习主动发送和 Answer Profile |
| Trace、Eval 与 CI | 部分完成 | 350 项双版本测试、S09 版本化 Eval、Runtime Trace、S11 低基数指标、镜像 registry smoke 和 CI 门禁 | 真实 SLO、长期趋势、线上故障注入与人工 Eval 确认 |
| WebUI / Control Plane | 未完成 | 只有规划条目；当前文档站不是产品 Control Plane | ADR、只读 API、权限/脱敏/审计、Trace/Eval Viewer，之后才考虑写操作 |
| 大规模真实群测试与 Debug | 最终阶段（未开始） | 白名单/显式 @/并发/重启/TargetTalk/kill switch/UNKNOWN 已完成本地仿真 | 等所有当前发布必需模块、既定 WebUI 测试和本地总审计完成后，再执行授权单群 shadow/canary、分层放量、冻结 SLO 和复盘；可选 S20 不阻塞 |

### 实施步骤完成度

| 步骤 | 状态 | 当前证据 | 下一边界 |
| --- | --- | --- | --- |
| S00 | 已完成 | Phase 0–1 基线、冻结 Spec、迁移与回滚计划 | 历史基线保留，不作为当前产品完成证明 |
| S01 | 已完成 | `dududa-agent` wheel、55 个子模块独立导入、Python 3.10/3.12、`py.typed` 和 forbidden-import | Package 继续保持无第三方 SDK 依赖 |
| S02 | 已完成 | canonical golden vectors、N/N-1 reader、Port binding、Protocol/Fake conformance | 只由 Fake 证明的后续 DTO 继续标记 `provisional` |
| S03 | 已完成 | Actor/Scope、默认拒绝授权、同角色约束绑定、Confirmation、Limiter/Budget、Redaction、Audit、幂等和严格配置负向测试 | Runtime 全链路接入与生产策略切换留待 S10–S11 |
| S04 | 已完成 | AstrBot Connector/Output/Attachment Adapter 及引用、@、附件、Delivery、取消、重复发送契约测试 | 真实 Attachment Source 与跨 Runtime 原子去重留待 Runtime State Store |
| S05 | 已完成 | Core 薄入口、命令/生命周期拆分、TargetTalk/ReplyPolish 纯逻辑；镜像内 `42/1/1` registry、priority 8 和一次性数据启动通过 | 旧 Handler 保持权威，不删除兼容入口 |
| S06 | 已完成 | Memory Scope/Selector/Record/Repository、显式 Write Gate、内存/JSON Adapter 与完整隔离矩阵 | 自动写入和生产 Memory v2 均保持关闭 |
| S07 | 已完成 | fail-closed Iris Protocol Adapter、缺 metadata 隔离、dry-run/backup/receipt/rollback 迁移工具 | 真实 Iris SDK Backend、生产数据迁移和 Runtime 接入未做 |
| S08 | 已完成 | 三 Tier 静态 Model Router、Registry、流量 admission、fallback、Fake/Adapter conformance | 真实 Provider 效果证据不作为静态路由逻辑的完成声明 |
| S09 | 已完成 | Rule/Model Perception、Merger/Validator、Social、Complexity、TierPolicy 和 320 条固定 Eval | 人工标签与真实数据校准保留为效果门禁 |
| S10 | 已完成 | 显式 @ 直聊离线闭环、两次模型预算、CAS/single-flight、Composition、Delivery/reconciliation 与 Shadow | 生产 Provider 与 Memory/Tool/Attachment 不在 S10 范围 |
| S11 | 已完成（本地） | typed rollout、SQLite claim/tombstone、AstrBot Bridge、发送前熔断、指标和可执行回滚 | 授权真实 QQ 群证据延期到最终 S23 |
| S12–S19、S22–S23 | 未开始/进行中 | 发布主线与既定 WebUI 测试按 WIP=1 推进；主动出站和回答档位只有设计 | 先完成所有发布必需模块与本地总审计，最后才进入 S23 真实群验证 |
| S20、S21 | 独立可选/未开始 | S20 只有设计；S21 不包含既定 WebUI 测试 | 单独 ADR/Spec 获批后排期，不阻塞 S23 |

### 公共开工门禁

项目负责人同时担任接口 Owner，负责公共契约与输入 Connector；后续模块变更通过
Spec/ADR 提议扩展。各步骤依次编码前，接口 Owner 先冻结最小 `v1alpha` 公共契约：

- `JsonValue`、`MessageEnvelope`、`Actor`、`ConversationScope`；
- 统一 `DududaError`、reason code、deadline、`RuntimeBudget` 和 `TraceEvent`；
- `RuntimeStartRequest`、`DraftResponse`、`ValidatedFinalResponse`、`RuntimeResult`、
  `DeliveryRequest` 和 `DeliveryReceipt`；
- Schema 版本规则、向后兼容规则和禁止依赖导入规则。

冻结只覆盖跨模块不变量，不要求一次性设计完所有字段。只由 Fake 证明的 Protocol 标记为
`provisional`；Fake 与至少一个真实或现有兼容 Adapter 通过同一 Contract Test 后才能冻结为
`v1alpha`。未经接口 Owner 评审，模块分支不得自行修改共享契约。

### 模块计划表

| 模块 | 难度 | 单人执行策略 | P0：可信骨架 | P1：可用闭环 | P2：扩展与优化 |
| --- | --- | --- | --- | --- | --- |
| 模型路由器 | ⭐⭐⭐ | 先做单 Provider 静态 Router，只启用 `PERCEPTION`/`DIRECT_CHAT`；Bandit 后置 | 定义 `ModelRole`、逐 Endpoint Descriptor、`ModelRequest/Response`、隐私处理 receipt、错误、静态 Route Policy 和 Fake Provider；先证明 `PERCEPTION` 一个角色 | 接入 AstrBot/OpenAI-compatible Adapter；为 Perception、Direct Chat、Tool Planning、Response Composition 分别配置 Structured Output、deadline、预算和 fallback | 多 Provider 健康检查、熔断、数据等级/驻留/retention 过滤、成本/延迟路由、热更新；可在硬过滤后接保守 Contextual Bandit，完成回滚后清理旧模型路径 |
| 在线学习 / Bandit | ⭐⭐⭐⭐ | 最后实现；先把可评估日志做好，不与 Router 首版并行 | 定义 eligible action、最小 Feature、behavior/candidate propensity、before-action Log、延迟 Feedback、Reward Policy 和静态 baseline；用合成已知策略验证 OPE estimator，不做 live exploration | 先对 Model Route 做 shadow，只验证候选、日志、fallback、策略一致率和延迟；确定性 baseline 对未执行动作没有 support，不能声称效果提升 | 对安全 Endpoint 做极小 conservative canary；只用具有 propensity/support 的日志报告 IPS/SNIPS/DR、有效样本量和群级 bootstrap，通过后才扩展到等价 Capability、预审 Prompt、低风险 Search 和 style；高风险/敏感探索恒为 0，任一安全 Gate 违规立即回滚 |
| Memory | ⭐⭐⭐⭐⭐ | 拆成“安全边界、兼容 Adapter、效果优化”三次完成；禁止一次做完 | 完成问题定义、论文/开源调研、`MemoryScope`、Selector、Record、Candidate、Repository、Write Gate、内存/JSON Adapter 和完整隔离矩阵；禁止自动写入 | 在授权集合内 shadow 比较 recency、BM25、embedding 和 hybrid；接 Context Builder、fail-closed Iris Adapter、TTL、冲突和显式 Memory 选择性切换 | 只有 Eval 证明必要时才引入 Reranker、Episodic/Temporal Graph；完成更新、删除、导出、Delivery Receipt 依赖和在线质量回归 |
| MCP 集成 | ⭐⭐⭐⭐ | 等直聊闭环稳定后，只切只读 `/course search`，再通用化 | 固定 iCourse 10 个 Tool 的 Discovery/Input/Output/Error fixture；定义 `McpServerRegistry`、`UnifiedMcpClient`、allowlist、错误和 Fake Client | 先让只读 `/course search` 通过固定安全 Plan、Executor、Validator 和持久 stdio Session；加入 timeout、有限 retry、熔断、审计和 feature flag | 扩展多 Server、Streamable HTTP、Schema cache、热更新、并发与指标；验证唯一 Client 后删除每次调用新建进程的旧路径 |
| 输入 Connector | ⭐⭐⭐ | 首批实现；只支持 AstrBot，接口稳定后才考虑第二平台 | 实现 AstrBot Event 到 `MessageEnvelope` 与 `Actor` 的转换、真实 conversation ID、引用/@/附件引用、幂等键和 conformance fixture；不做意图判断 | 接入附件 Preprocessor、Context 来源、Output Adapter 和 `DeliveryReceipt`；在 shadow Runtime 中验证不重复发送 | 提炼 Connector SDK，支持新平台能力协商、背压、顺序和版本兼容；新增平台不修改 Core Runtime |
| 语义理解（意图/实体） | ⭐⭐⭐⭐ | 规则 baseline 先行，模型只补规则无法覆盖的结构化结果 | 定义 `PerceptionResult`、Intent/Entity/Reference/Evidence Schema、标注规范和 200–500 条脱敏/合成基线集；实现 RulePerception、Validator 和确定性 Social Policy | 经 Model Router 接入 ModelPerception，固定 Rule -> Model -> Merger -> Validator；实现实体、指代、歧义和工具需求，shadow 对比 TargetTalk | 扩展多轮、多意图、QQ 口语、附件摘要和置信度校准；基于真实错误做 Active Learning，只有 Eval 支持时才微调模型 |
| 回答档位 / Response Plan | ⭐⭐⭐ | 作为 S15 首个子步骤；不重做 S08/S09，不把长度映射为 Tier | 定义 `AnswerProfile`、`ResponsePlan`、显式详略 hint、可见 Token/字符/分片和必要内容契约；固定 SHORT/MEDIUM/LONG policy | Runtime 将 Plan digest/动态预算交给 TierPolicy/Router/Composer/Renderer/Final Validator；覆盖 HIGH+SHORT、LOW+LONG | 多语言/平台预算与用户偏好；只有离线证据支持时优化 Profile policy，Bandit 不选择 Profile |
| OC 撰写与 Persona | ⭐ | 先复用一个版本化 Persona 和确定性 Renderer；多 Persona/A-B 后置 | 整理角色背景、Voice Rules、禁用表达、技术/闲聊示例和版本化 Persona 资产；不在 Persona 中写权限或事实规则 | 接入 `DraftResponse -> PersonaRenderer -> RenderValidator`；事实锚点、引用、拒绝、目标和附件不可改变，失败时确定性 fallback | 多 Persona、版本回滚、受限用户偏好、Golden/Eval 和 A/B；新增 Persona 不修改 Social Decision、Memory 或 Tool Policy |
| 主动消息与订阅推送 | ⭐⭐⭐⭐⭐ | S15A-S15E 串行；先契约/时钟/持久性，再来源，再 Shadow；默认 off | 独立 initiated-run、`message.send.proactive`、Subscription/Schedule/Occurrence/Source/Dispatch 契约、Fake Clock/Store/Output、空 allowlist 拒绝 | 持久 Scheduler、CAS claim、订阅/退订、校园/arXiv/行业公开只读 MCP、来源净化/去重、Digest/Probe no-send Shadow | S23 分别授权日报与 Probe canary；不使用 Bandit 选择发送/目标/时间/频率，不读个人 Memory，不自动追问 |

### 横向交付计划

| 任务 | P0 | P1 | P2 | 退出证据 |
| --- | --- | --- | --- | --- |
| Trace、Eval 与测试框架 | 建立版本化 fixture、Fake、Contract Test、run/trace ID 和隐私安全记录格式 | 将 Runtime、Router、ResponsePlan、Memory、Capability、MCP、OC 和 Proactive 指标接入同一回放/Eval 入口 | 纳入完整 CI、fake-clock 长期仿真、趋势对比、故障注入和发布门禁 | 同一版本数据与配置可重复运行；安全门禁不可设为非阻塞 |
| WebUI / Control Plane | 先提交 ADR，再定义权限、脱敏、审计、配置版本和只读查询 API；不抢先制作第二套业务逻辑 | 提供只读 Trace Viewer、Agent Playground、Eval 结果和 Model/MCP Health | 增加 RBAC、Memory Explorer、Persona/Model/Capability 配置、成本性能和告警 | UI 不绕过 Runtime Policy 或 Repository；所有写操作有审计、确认和回滚 |
| 集成与真实群聊测试 | 使用合成 Event、fake clock、公开来源 fixture、离线回放和跨 Scope 负向数据，不读取生产聊天 | 完成跨模块离线集成、30 日调度仿真、故障注入和 no-send/no-write 仿真，不连接真实测试群 | 冻结全仓回归、SLO、各行为授权清单和回滚包；真实群执行仍留到最终 S23 | S23 依次通过入站 Shadow/明确 @ Canary、手动日报、定时日报、低频 Probe，再决定分层放量；所有错误目标、重复/静默时段/撤销后发送、未授权 Tool、跨 Scope Memory 和敏感 Trace 为 0 |

### 依赖与单人执行原则

1. 公共契约、权限/隐私、预算、幂等和最小 Trace 是所有模块的共同前置门禁。
2. 全程保持 `WIP=1`：一个 Git 分支只完成下表一个步骤；不得同时打开 Memory、MCP、
   Router 和 WebUI 四条实现线。
3. 每一步固定执行 `确认 Spec/非目标 -> 实现 -> Unit/Contract/负向测试 -> 集成或 smoke ->
   更新 PROGRESS/迁移证据 -> 可回滚提交`，门禁失败就停在本步。
4. 首个纵向闭环是“明确 @ Bot、无工具、Memory 关闭的直接回复”；第二个闭环才是只读
   `/course search`。这两个闭环稳定前不实现通用 Planner。
5. Memory 的 Scope/隔离契约必须先完成，但效果研究不阻塞空 Memory Runtime；Memory 只有
   通过隔离门禁后才能进入 Context Builder。
6. Response Plan 作为 S15 首个子步骤完成；Answer Profile、Tier、Reasoning Profile 正交，
   Router 只消费计划 digest 和动态输出预算，不负责推断回答长短。
7. S15A-S15E 依次完成主动契约、持久 Scheduler、公开来源、日报 Shadow 和 Probe Shadow；
   MCP 只取数，Scheduler 不直调 Tool，定时器不伪造 Connector 消息，主动链不读个人 Memory。
8. 真实群验证是最终阶段：所有当前发布必需模块、既定 WebUI 测试和本地总审计完成后，才允许
   准备白名单 canary；此前只做离线/仿真。独立可选 S20 不属于该发布前置。进入最终阶段前
   必须具备 kill switch、上一版本镜像、无副作用 shadow 证据和明确回滚命令，不能把真实群聊
   当集成测试环境。
9. Bandit 依赖稳定 Router、before-action 日志、延迟反馈和足够流量；WebUI 依赖稳定只读 API、
   权限和脱敏。Bandit 永不选择主动 send/skip、目标、订阅、日程、频率、Answer Profile 或
   follow-up；二者都不在首个主动闭环关键路径上。

### 单人完整开发流程

以下是唯一推荐主线。编号表示严格先后顺序，不表示可并行任务；同一步内也应先完成最小
纵向结果，再增加可选能力。

| 顺序 | 对应 Phase | 本步只实现 | 进入下一步的门禁 | 本步明确不做 |
| --- | --- | --- | --- | --- |
| S00 | 0–1 | 固定基线提交、验证命令、目标契约、feature flag、回滚格式和 `PROGRESS.md`；确认现有生产入口不变 | 基线测试、Compose、镜像/import、MCP handshake、secret scan 和 `git diff --check` 可重复执行 | 任何 Runtime 代码或目录移动 |
| S01 | 2A | 创建可安装的 `dududa-agent`；实现 primitives、Envelope/Actor/Scope、Runtime State、Error、配置模型 | 无 AstrBot 环境可导入；领域/状态/配置单测和 forbidden-import 通过；镜像可安装 | Adapter、Provider、MCP、Memory 后端和命令改动 |
| S02 | 2B | 实现 canonical codec、Schema/Port binding、关键 Protocol、Fake 和 Contract Test harness；`provisional` 接口用 Fake 证明 | golden vectors、N/N-1 reader、Port 协商、Fake conformance 与错误语义通过 | 连接生产 Event 或冻结未经真实 Adapter 验证的接口 |
| S03 | 3 | 实现 Actor 映射、Authorization、Confirmation、Limiter/Budget、Redaction、Audit、幂等和 typed config；旧插件用兼容包装调用 | 默认拒绝、权限矩阵、完整 request digest 绑定、secret/URL/path、损坏配置和审计失败负向测试通过 | 改变用户可见命令、角色顺序或数据路径 |
| S04 | 4A | 实现 AstrBot `InputConnector`、Attachment Repository 边界、`OutputAdapter` 和 Delivery Receipt；先保持旧 Handler 权威 | Event/引用/@/附件/四元去重/重复投递 fixture 通过；同一输入不重复发送 | 第二聊天平台、意图判断或模型调用 |
| S05 | 4B | 将 Core `main.py` 薄化；抽离命令、生命周期、TargetTalk 与 ReplyPolish 纯逻辑，保留插件 ID/路径/优先级 | 派生镜像插件 import/register smoke、命令 Golden、分片 Property、TargetTalk 冷却和干净 bootstrap 通过 | 新 Runtime 切流、目录迁移或删除旧 Handler |
| S06 | 5A | 只建立 Memory 安全边界：`MemoryScope`、Selector、Record、Repository、精确读取、显式 `/remember` Write Gate、内存/JSON Adapter | 跨平台/Bot/群/私聊/用户/Persona 隔离矩阵全部通过；自动写入保持关闭；旧数据不改写 | embedding、Graph、Reranker、自动摘要或自动写入 |
| S07 | 5B | 实现 fail-closed Iris Adapter、缺 metadata 隔离区，以及带 backup/dry-run/receipt/rollback 的迁移工具；功能仍关闭 | JSON 与 Iris 通过同一 Repository contract；缺 metadata 不可读；迁移数量核对和逆向恢复 fixture 通过 | Runtime 接入、语义检索或生产数据原地改写 |
| S08 | 6A | 实现静态 Model Router：一个现有 Provider、`PERCEPTION` 和 `DIRECT_CHAT` 两个角色、逐 Endpoint descriptor、预算/隐私/health/fallback | Structured Output、429/timeout/认证/无合法路由、敏感数据过滤和 Fake/真实兼容 Adapter contract 通过 | 多 Provider 优化、图片角色和 Bandit |
| S09 | 6B | 实现 Rule Perception、严格 Model Perception、Merger/Validator 和确定性 Social Decision；建立首版脱敏/合成 Eval 集 | Intent/Entity/Reference/tool-need 和 should-reply 分层指标已报告；非法 Schema 整体拒绝；误插话/越权 Gate 为 0 | 微调模型、主动学习和复杂群聊价值模型 |
| S10 | 6C | 完成第一个离线纵向闭环：Connector -> Context -> Perception -> Decision -> Router -> Composer -> 单 Persona Renderer -> Output；只处理明确 @、无工具、Memory 关闭 | Runtime 状态/预算、事实锚点、无效模型输出、Delivery、取消和“shadow 绝不发送/写入”测试通过 | 自由插话、Tool、Memory 个性化、多 Persona |
| S11 | 6D | 本地完成 typed off/shadow/canary、持久 claim/tombstone、发送前熔断、指标与回滚演练；旧链路保持权威 | 并发、重启、TargetTalk、kill switch、UNKNOWN 和零副作用仿真通过 | 任何真实群发送；真实场景统一留到 S23 |
| S12 | 7A | 实现 Unified MCP Client/Server Registry，把 iCourse 映射为第一个 Provider；只切只读 `/course search`，使用固定安全 Plan | Discovery/Schema cache、持久 Session、timeout/retry/重启/熔断、export root、抓取上限和 handshake smoke 通过 | 通用多步 Planner、写操作和其他 MCP Server |
| S13 | 7B | 实现 Capability Registry/Retrieval、有限 Planner、逐步授权 Executor、Observation 和 Validator；先覆盖课程只读路径 | 候选资格/Top-K、参数 Schema、最多步数、重复调用、未知结果、Prompt Injection 和预算测试通过；可按 Capability 回滚 | 高风险/不可逆 Tool 和任意动态 Tool 暴露 |
| S14 | 6E | 接入 Memory Retrieval 与 Write Gate：先 exact/recency/BM25 baseline，再 shadow 对比 embedding | Scope 泄漏为 0；显式写入、TTL、冲突、删除/导出、Delivery 依赖和迁移核对通过；复杂检索确有增益 | Graph/Temporal Memory、未确认自动写入 |
| S15 | 6F | 先实现确定性 `ResponsePlan(SHORT/MEDIUM/LONG)` 和动态输出预算，再完成 OC/Persona 产品化：版本化资产、Composer/Renderer 分层、Render/Profile Validator、用户偏好隔离和 Golden/盲评 | 3x3 Complexity/Profile 正交矩阵、明确详略要求、实际长度/分片通过；Fact/Citation/Refusal/Target/Attachment 变化为 0；版本回滚与 fallback 可执行 | 把长度绑定 Tier、多 Persona 市场、在线风格/Profile 探索 |
| S15A | 主动出站 A | 冻结 initiated-run、TargetPolicy/Grant Ref、Trigger、Subscription、Schedule、Preview、Source、Policy、Dispatch、Receipt、`message.send.proactive` 和 `proactive.subscription.preview` 契约；实现 Fake Clock/Store/Output，默认 off | operator/group-policy grant、canonical digest、Scope/授权/revision/quiet-hour/限流/空 allowlist/kill switch、Preview 零投递、恢复复用 PreparedDispatch 和跨 Adapter 版本稳定幂等键的负向 Contract Test 通过 | 网络、模型、真实来源、真实发送 |
| S15B | 主动出站 B | 实现持久 Scheduler、IANA 时区、occurrence、CAS claim、misfire、pause/unsubscribe 和 Dispatch Store；只产生结构化 trigger | 双 Worker、重复 tick、重启、时钟回拨、DST 和 30 日 fake-clock 仿真无重复/过期补发/撤销后任务 | MCP、内容生成、OutputAdapter |
| S15C | 主动出站 C | 依次接一个校园官方公开源、arXiv 和行业 allowlist 来源；固定只读 Capability Plan，经 Unified MCP Client 输出 SourceBatch | provenance/freshness/Schema/URL/大小/来源游标/条目去重，以及断网/超时/取消/熔断/注入 Contract 通过 | 任意 URL、私人校园信息、外部写、MCP 发送 |
| S15D | 主动出站 D | 接入日报 ResponsePlan、Composer、Persona、来源/引用/长度 Validator；运行 collect、真实公开源 Shadow 和独立 `PREVIEW` Port | Shadow/Preview 构造无 OutputAdapter；Preview 不创建 occurrence/dispatch/receipt 且正文不进普通 Trace；30 日来源/摘要/去重/故障仿真和回滚通过 | 自动真实发送、LONG 默认日报 |
| S15E | 主动出站 E | 实现群级 Conversation Opportunity、确定性 Proactive Policy、SHORT Probe 与 no-response 长冷却；独立 Shadow/kill switch | 错误目标、重复、quiet-hour、频控、个人/敏感内容和自动追问违规均为 0 | 主动私聊、@个人、个人 Memory、Bandit send/skip |
| S16 | 8A | 先做运维硬化：health、backup、restore、upgrade receipt、rollback、最小 mount/network 和 Release manifest | 一次性数据完成 bootstrap -> start -> health -> backup -> upgrade -> restore -> rollback | 大规模目录移动或删除兼容入口 |
| S17 | 8B | 用 `git mv` 分批迁移 `apps/`、`packages/`、`services/`、`configs/`、`deploy/ops`、`third_party/`；根入口保持兼容 | 每次路径切换的消费者契约、容器 smoke、根包装层和上一 Release 回滚通过 | 同一 PR 同时移动全部路径或运行数据 |
| S18 | 9 | 汇总 Trace、Eval 与 CI：版本化 fixture、run 关联、模型/ResponsePlan/MCP/Memory/OC/Proactive 指标、fake-clock、故障注入、镜像与容器 smoke | 完整 unit/contract/integration/eval/smoke 矩阵通过；Trace 不含原文/凭据/真实标识；回答档位与主动安全阈值冻结 | 通过删除安全测试恢复绿色状态 |
| S19 | 本地总集成 | 汇总所有当前发布必需模块，执行全仓回归、离线回放、30 日调度/Probe no-send 仿真、故障注入、SLO 预注册和发布候选审计 | 发布必需模块完成定义、本地安全门禁、镜像/配置/插件回滚包与冻结 SLO 全部通过 | 真实群发送或用线上流量补本地测试缺口 |
| S22 | 10 | 按 `migration-map.md` 逐项删除旧 Client、Handler、Import、Mount 和路径；每次只清一个兼容面 | 生产入口和测试只消费新实现；移除清单为 0；迁移/回滚完成并保留可独立恢复 Release | 顺手重构或没有消费者证据的批量删除 |
| S23 | 最终真实场景 | 所有当前发布必需模块、既定 WebUI 测试和本地审计完成后，在同一授权单群依次执行 no-send shadow、明确 @ canary、手动日报、定时日报、低频 Probe；每类独立授权/熔断，再考虑 3–5 群分层放量 | 重复回复/推送、错误目标、quiet-hour/退订后/未授权发送或 Tool、无引用/过期内容、跨 Scope Memory 和敏感 Trace 为 0；冻结分行为 SLO、kill switch、回滚与复盘全部通过 | 提前上线、一次打开全部主动行为、无指标放量，或在任一发布前置模块未完成时进入真实群 |

以下阶段不属于上述严格发布主线，只有单独 ADR/Spec 获批后才排期：

| 可选阶段 | 定位 | 本步只实现 | 完成门禁 | 明确不做 |
| --- | --- | --- | --- | --- |
| S20 | P2 在线优化 | 仅在 Model Route 的同 Role+Tier 合法 Endpoint 中实现 Bandit：先日志与合成 estimator，再 shadow、极小 canary、IPS/SNIPS/DR | 有足够 support/有效样本量；群级 bootstrap、baseline floor、零安全 Gate 违规和自动回滚通过 | 权限、Memory Scope、高风险 Tool、敏感 Provider、Reply/Ignore、主动发送/目标/日程/频率、Answer Profile 探索 |
| S21 | 后续规划 | 在 ADR 批准后实现只读 WebUI：Trace/Eval/Model/MCP Health；稳定后才讨论带审计和回滚的写操作 | API 复用 Runtime 权限/Scope/脱敏；RBAC、审计、CSRF/越权和回滚测试通过 | 既定 WebUI 测试已在发布主线内；不得在 UI 重写第二套业务逻辑或抢先做完整 Control Plane |

达到 S11 算“本地可用直聊版本”，达到 S13 算“本地可用工具闭环”，达到 S15E 算“主动出站
本地 Shadow 完整”，发布主线固定为 `S15E -> S16 -> S17 -> S18 -> S19 -> S22 -> S23`。
达到 S22 且通过 S19 本地总审计后，才允许进入 S23 真实群验证。S20 Bandit 是独立可选阶段，
不是主动出站或 S23 的前置；既定 WebUI 测试仍是前置，但不追加可写控制面。

单人阶段主动暂停以下范围：第二聊天平台、通用高风险 Tool、自动 Memory 写入、Graph Memory、
主动私聊/个人目标、私人校园 Feed、自动 LONG 推送、模型微调、neural bandit、多 Persona 市场
和可写 Control Plane。只有前一里程碑的真实错误证据证明它们必要时，才把其中一项加入新的
Spec 和顺序表。

### 可扩展框架约束

目标依赖方向固定为：

```text
Connector / Output / Provider / Repository Adapter
                    |
                    v
          Application / Agent Runtime
                    |
                    v
          Domain Models + Owned Protocols
```

| 扩展目标 | 稳定扩展点 | 新实现必须提供 | 是否修改 Core Runtime |
| --- | --- | --- | --- |
| 新聊天平台 | `InputConnector`、`OutputAdapter` | Envelope/Actor conformance、幂等、附件与 Delivery 测试 | 否 |
| 新模型供应商 | `ModelProvider` | 能力声明、错误映射、Structured Output、隐私和 fallback 契约 | 否 |
| 新 Memory 后端 | `MemoryRepository`、`SemanticMemoryIndex` | 全隔离矩阵、迁移/回滚、TTL、删除与导出契约 | 否 |
| 新 MCP Server | `McpServerRegistry`、`UnifiedMcpClient` | 连接配置、Tool allowlist、Schema snapshot、健康和错误契约 | 否 |
| 新业务能力 | `CapabilityDefinition`、`CapabilityProvider` | 版本化 Schema、权限/风险、Validator、Eval 和审计 | 否 |
| 新语义实现 | `PerceptionEngine` | 完整结构化输出、Validator、固定 Eval 集和降级实现 | 否 |
| 新回答档位/预算策略 | `ResponseProfilePolicy`、`ResponsePlan` | Profile 语义、动态 Token/字符/分片、正交路由与最终 Validator | 否 |
| 新 Persona | `PersonaRegistry`、`PersonaRenderer` | 版本、Digest、事实保持测试、安全评审和回滚 | 否 |
| 新主动来源 | `CapabilityProvider`、`SourceNormalizer` | 公共只读 Schema、provenance、freshness、allowlist、去重和注入测试 | 否 |
| 新调度实现 | `ProactiveScheduler`、`ProactiveDispatchStore` | IANA 时区、可测试 Clock、CAS claim、misfire、幂等、暂停/撤销和恢复测试 | 否 |

扩展性不等于允许任意模块互相调用。Runtime 只依赖 Core 拥有的 Protocol；具体 SDK、
AstrBot Event、MCP Session、数据库 Client、Credential 和可变配置对象不得进入 Domain。
Registry 只保存版本化定义和 Provider 引用，动态发现的模型或 Tool 不会自动获得权限。

所有扩展接口还必须遵守：

- 跨模块 DTO 使用不可变结构和受限 `JsonValue`，不得携带平台 Event、SDK Client、
  Credential、文件句柄或任意可变 `dict`；
- 公开 DTO、配置和事件包含 `schema_version`；兼容变化只增加可选能力，破坏性变化发布
  新版本，并保留明确的弃用窗口；
- Registry 变更先完成 Schema 与引用校验，再原子切换；无效新版本保留 last-known-good；
- deadline、cancellation、幂等键、隐私等级和 Trace Context 必须贯穿所有异步 Port；
- Model Router 只选择模型，Capability Retrieval/Planner 只选择业务能力，两者不得合并；
- 权限、Scope、风险、预算和最终状态转换由确定性 Runtime 持有，模型只能产生候选结果。
- Scheduler 只物化 occurrence，MCP 只读取公开来源，Proactive Policy 只决定是否允许进入准备，
  Output Adapter 只投递；任何一层都不能吞并其他层的权限。

### 科学性与研究任务

P0 Research Spike 需要限时：Memory 初次调研 5–7 个工作日，语义理解初次调研
3–5 个工作日。交付物不是综述篇幅，而是可复现数据集、Baseline、实验命令、结果表和
架构 ADR。实验开始前预注册主要指标、数据切分和失败条件；P1 canary 前冻结发布阈值，
不得根据上线结果临时替换指标。

| 研究方向 | 必须比较的基线 | 数据与切分 | 指标 | 选型规则 |
| --- | --- | --- | --- | --- |
| Memory 检索 | no-memory、recency、BM25、embedding、hybrid | 脱敏/合成的多群、多用户、私聊、时间和冲突样本；按 conversation 切分 | Scope 泄漏率、Precision@K、Recall@K、MRR/nDCG、错误归属率、P95、Token/成本 | Scope 泄漏必须为 0；复杂方案必须在 held-out 集上稳定优于简单基线，才允许进入 shadow |
| Memory 写入 | 全拒绝、仅显式 `/remember`、规则 Write Gate、模型 Candidate + Gate | 敏感、重复、冲突、过期、未送达和确认样本 | 保存准确率、敏感拒绝率、重复率、冲突发现率、删除完整性 | 自动写入保持关闭，直到负向集全过且人工抽检达到发布阈值 |
| 语义理解 | Rules、LLM Structured Output、Rules + LLM Merger | 首版 200–500 条；按完整会话划分 train/dev/test，部分样本双人标注并仲裁 | 标注一致率/κ、Intent macro-F1、Entity span/type F1、Reference exact match、tool-need recall、误插话率、校准误差 | 硬规则违规必须为 0；模型方案需报告置信区间和分层错误，不以单一总体准确率决定上线 |
| 回答档位 | 固定 MEDIUM、规则 Response Policy、规则+模型 hint | TaskComplexity x AnswerProfile 3x3；按完整会话/任务族切分，包含 HIGH+SHORT、LOW+LONG 和明确用户要求 | Profile macro-F1/混淆矩阵、明确要求满足率、可见字符/Token/分片、完整性、事实/引用保持、冗余度 | 长度与 Tier 正交；跨两档错误、硬上限、引用/警告丢失为发布阻断；质量不能仅按字数判断 |
| Router/MCP | 单 Provider、静态路由、带 fallback 路由；每次新建进程与复用 Session | 固定请求、错误注入和并发场景 | Schema-valid rate、成功率、P50/P95、重试、进程创建数、恢复时间和成本 | 未授权路由/Tool 暴露必须为 0；优化不能降低错误可解释性或回滚能力 |
| 主动日报 | no-send、确定性来源排序/模板、候选 Composer | 30 日 fake-clock，多来源波动/重复/重启/DST/退订/部分失败；真实公开源只用于 Shadow | 新内容覆盖、重复率、来源多样性、新鲜度、引用/事实完整率、打扰度、P95、Token/成本 | 错误目标、重复、quiet-hour、退订后、无引用/过期内容和敏感 Trace 必须为 0；复杂摘要需盲评优于模板 |
| Conversation Probe | 永不发送、固定规则 eligibility、候选软打分 | 按 group/topic/date 聚类的脱敏/合成机会集和长期 no-send 仿真 | eligible/send 建议率、错误目标、无响应、明确参与、相关性、打扰度、冷却遵守 | 首版策略确定性；不因沉默增大发送；零安全违规后才允许独立 Canary，Bandit 禁止 send/skip |

Memory 调研可以覆盖 Iris、Mem0、Letta、Zep/Graphiti，以及 LoCoMo、LongMemEval
等项目或评测方法；结论必须落为带日期、版本、许可、适用边界和可复现实验的研究记录或
ADR。不得把开源项目的默认 Scope、Prompt 或向量检索结果直接当作本项目的安全证明。

### 模块统一完成定义

每个模块只有同时满足以下条件，才能标记为完成：

1. Spec、Scope、非目标、依赖和版本化输入输出已评审；
2. 具备 Fake、至少一个真实 Adapter，以及共享的 Contract Test；
3. Unit、负向、故障、取消、超时和相应 Eval 已通过；
4. 具有稳定 Error/reason code、脱敏 Trace、低基数指标和健康状态；
5. 生产入口受 feature flag 保护，并经过 additive -> shadow -> selective cutover；
6. 数据迁移、兼容代码移除门槛和可执行回滚方法均已记录；
7. 文档说明如何新增下一个 Provider、Backend、Server、Connector 或 Persona。

## Phase 0：审计与基线

状态：已在本次文档变更中完成。

交付物：

- `current-state.md`
- `dependency-map.md`
- `baseline.md`
- 初始版 `PROGRESS.md`

证据包括现有 8 项测试通过、6 个插件的临时安装、Docker 构建以及禁用网络的 MCP
握手。已知失败和测试盲区保留在基线中，不把它们粉饰为正常状态。

回滚：只需回退文档变更。

## Phase 1：目标设计与迁移计划

状态：所有关联的设计、运维、开发、ADR、映射和计划文档通过评审与仓库门禁后，
本 Phase 即告完成。

不改变任何运行时行为、源码路径、插件 ID 或生产状态。

回滚：只需回退文档变更。

## Phase 2：建立核心 Python Package

### 目标

增加一个可安装、框架无关的 Package，其中包含领域模型、Protocol、Runtime State、
类型化配置和错误。现有 Event 暂不经过该 Package 路由。

### 预期文件

```text
packages/dududa-agent/pyproject.toml
packages/dududa-agent/src/dududa/domain/*
packages/dududa-agent/src/dududa/runtime/state.py
packages/dududa-agent/src/dududa/config/*
tests/unit/domain/*
tests/unit/runtime/test_state.py
tests/contracts/test_import_boundaries.py
```

CI 和 Dockerfile 安装该 Package。现有插件文件不移动。

### 不变量

- 现有命令和插件导入保持不变。
- 未安装 AstrBot 时，该 Package 仍可成功导入。
- 领域层不得引入任何具体的文件系统、Provider、MCP 或 Iris 实现。

### 风险

- 在尚无一个 Adapter 证明接口可用前就过度设计接口。
- CI 与镜像中的 Package 安装方式不一致。
- 可变 metadata 或可选 Scope 字段削弱后续不变量保证。

### 验证

- 构建 Package 并执行 editable 安装。
- 对 Envelope、身份、Response、Scope 校验、状态转换、配置解析和类型化错误执行
  单元测试。
- 禁止依赖导入（forbidden-import）契约测试。
- Docker 构建，并执行 `python -c 'import dududa'`。
- 全部 Phase 0 门禁。

### 回滚

移除新增的 Package 和测试，并回退 CI/Docker 安装配置。生产数据和现有导入入口均
不受影响。

## Phase 3：抽取安全与公共逻辑

### 目标

抽取 Actor/权限策略、脱敏、审计契约、类型化配置和公共错误。现有插件模块改为
兼容包装层。

### 保持不变的行为

- 除非某项安全修复被单独隔离并明确批准，否则角色顺序、owner/admin fallback、
  muted 行为、当前审计位置和命令可见错误均保持不变。

### 配置兼容边界

新 `SecurityConfig` 是 Runtime v2 的严格配置，不直接替换旧 AstrBot 插件配置。
`role_constraints` 为必填映射；`role_permissions` 只声明某角色可申请哪些动作，动作还必须
命中**同一角色**的资源、Capability、风险和 metadata 约束才能授权。缺字段、空约束或试图
借用另一角色的约束都默认拒绝。旧 owner/admin/trusted/muted 解析继续由兼容层保持原顺序，
直到 S10–S11 有明确切流证据。

### 主要风险

- 配置缺失时意外授予权限。
- 改变插件配置键或数据路径。
- 脱敏不足，或破坏运维所需的操作者归因。

### 验证

- 权限矩阵、默认拒绝、Actor 转换、嵌套值脱敏、Audit Sink、损坏配置、原子写入和
  兼容导入测试。
- 现有命令契约 fixture。

### 回滚

兼容包装层可以切回旧实现；本 Phase 不移动任何路径。

## Phase 4：拆分 AstrBot 插件

### 目标

将 Core `main.py` 改为组装与注册层。把 Handler 移入 Event Adapter、
basic/admin/memory/course/compatibility 命令、生命周期和 Runtime Bridge 模块。
抽取 ReplyPolish 和 TargetTalk 的纯逻辑，同时保留 3 个可独立加载的插件根目录。

### 文件规模目标

`main.py` 应只包含注册、依赖组装和 Handler 导入，通常控制在 300–400 行以内。
目标是建立职责边界，而不是机械地按行数拆分文件。

### 不变量

- 插件 ID、metadata、Schema 键、容器目标路径、Event 优先级、Decorator、命令名、
  stop/send 行为和状态路径保持稳定。

### 风险

- AstrBot Decorator 发现机制和导入顺序。
- 全局 ReplyPolish 对无关插件的影响。
- TargetTalk 直接发送的时序以及对内部 AIOCQHTTP 的依赖。

### 验证

- 在派生镜像中执行 AstrBot 导入/注册 smoke 测试。
- Event 到命令/结果的契约 fixture。
- 回复分段的 Property/Golden 测试。
- TargetTalk 确定性决策、上下文采集和冷却测试。
- 不含生产数据的干净 Compose bootstrap smoke 测试。

### 回滚

保留一个 Release 镜像，以及用于选择旧 Handler 组装方式的配置开关。本 Phase 不删除
旧模块。

## Phase 5：Memory v2 边界

### 目标

实现 Memory Scope、Record、Repository 契约、精确检索、Write Gate、兼容 JSON
Repository 和 fail-closed Iris Adapter。

### 不变量

- 不自动重写现有 Memory。
- 缺少 metadata 的数据进入隔离区，不得视为共享数据。
- 该功能在生产回复中以禁用或 shadow-only 状态开始运行。

### 风险

- 隐私泄漏、旧数据消失、不可逆迁移，以及 JSON 与 Iris 之间的语义冲突。

### 验证

- 完整的跨群、跨用户、私聊、Bot 和 Persona 负向矩阵。
- 使用 JSON 与 Iris Adapter 验证同一套 Repository 契约。
- Write Gate 的敏感度、TTL、重复、冲突和确认测试。
- 离线迁移 dry-run 与回滚 fixture。

### 回滚

关闭检索/写入开关，恢复使用未修改的旧存储。迁移工具必须要求备份并生成可逆回执。

## Phase 6：Agent Runtime 骨架

### 目标

实现 Context Builder、Perception 接口、Social Decision、Runtime Orchestrator/状态
转换、确定性 ResponsePlan、Response Composer、OC 边界和 Trace。

### 迁移模式

从纯 fixture 开始，然后通过脱敏结果对比进行 shadow 执行。在选定路径获得批准前，
旧链路输出始终是权威输出。

### 风险

- shadow 模式产生重复回复。
- 把模型非确定性误认为状态控制。
- Persona 改变事实或决策。
- Trace 保留原始消息。

### 验证

- 状态转换和预算测试。
- Structured Output 无效及 fallback 测试。
- Social Action 决策表和 Eval fixture。
- Answer Profile 3x3 正交矩阵、明确详略要求、动态输出预算和最终长度/完整性测试。
- Response 的事实/错误/引用保护，以及 OC 一致性测试。
- 证明 shadow 模式绝不发送消息或写入 Memory。

### 回滚

关闭 Runtime Bridge 开关；旧 Adapter 保持完整可用。

## Phase 7：统一 Capability 与 MCP

### 目标

实现 Capability Registry/Retrieval、Planner、Executor、Validator、统一 MCP
Client/Server Registry，以及 iCourse Capability Provider。在选择性切换后消除
iCourse 双 Client 路径；随后为主动日报提供固定、公开、只读、带 provenance/freshness 的
校园、arXiv 和行业来源 Capability。

### 不变量

- 当前课程命令和输出继续可用。
- iCourse 保持为独立的 Service Package。
- Planner 不能看到不符合条件或高风险的工具。
- Scheduler 不直接调用 MCP；后台来源只执行固定只读 Capability Plan，MCP 不拥有订阅或发送。

### 风险

- 无限或重复调用、进程频繁创建、Crawler 过载、Schema 漂移、任意文件导出，以及
  评课文本对模型实施 Prompt Injection。

### 验证

- Capability 资格和 Top-K 测试。
- Planner/Executor/Validator 有界循环集成测试。
- MCP Schema 缓存、超时、错误、重启、重试和熔断测试。
- iCourse Transport 契约和已捕获的 Parser fixture。
- Export Root 和抓取上限负向测试。

### 回滚

按 Capability 设置 feature flag，将课程命令路由回兼容 Client。在单 Client 指标与
smoke 测试通过前，不移除旧 MCP 配置或 Client。

## Phase 7.5：主动消息与订阅推送

### 目标

按 S15A-S15E 串行实现独立 initiated-run、主动授权、持久 Scheduler/Subscription/Dispatch、
公开来源、日报合成和低频 Conversation Probe。完整契约见
`../design/proactive-messaging.md`。

### 不变量

- 默认 off；空 allowlist、缺配置、审计/授权/限流故障全部拒绝；
- 定时器不伪造 `MessageEnvelope` 或用户 Actor，MCP 不调度、不决定目标、不发送；
- Snapshot/Subscription、Trigger 和 initiated-run 使用同一 target-policy Ref；该 Policy 的 digest
  绑定 operator/group-policy grant、精确 Scope 和 revision；
- Probe 固定 SHORT、不 @ 个人、不读个人 Memory、无人回应不追问；日报默认 MEDIUM；
- 订阅、目标、quiet hours、频控、kill switch、内容 digest 在发送前重新校验；
- Preview 使用独立 Port，不创建 occurrence/dispatch/delivery，正文不进普通 Trace/receipt；
- 投递业务幂等键跨 Adapter revision 稳定，binding 单独校验；
- Shadow 没有 OutputAdapter，真实群验证仍只在最终 S23。

### 风险

- 重启/并发/DST 产生重复或集中补发；
- 退订、授权撤销或群策略变化后仍发送；
- MCP 来源提示注入、过期/无引用信息或私人校园数据进入群；
- `UNKNOWN` Delivery 被盲重发；主动探测打扰用户或形成自动追问。

### 验证

- Fake Clock/Store/Output 的 30 日并发、重启、DST、misfire、pause/unsubscribe 仿真；
- TargetPolicy/Grant Ref 替换与撤销、Preview 独立授权/零投递/正文不落普通 Trace，以及
  Adapter revision 变化和 `UNKNOWN` 恢复时复用 PreparedDispatch/业务幂等键；
- 公开来源 Contract、provenance/freshness/URL/Schema/注入/去重和部分失败测试；
- Digest/Probe 独立 no-send Shadow、指标、kill switch 和回滚演练；
- 错误目标、重复、quiet-hour、退订后、未授权、无引用/过期内容和敏感 Trace 为 0。

### 回滚

Digest 和 Probe 使用独立 mode/kill switch。回滚先原子切回 `off`，使未发送 occurrence 和
PreparedDispatch 全部失效，再停 Scheduler/Worker；保留最小 dedup/reconciliation tombstone，
不删除仍在窗口内的 `PARTIAL/UNKNOWN` 投递证据。

## Phase 8：部署与第三方目录布局

### 目标

将权威路径移动到 `apps/astrbot-plugins/`、`deploy/`、`ops/`、
`third_party/`、`configs/` 和 `services/mcp/`；增加运维阶段和 Manifest v2，
同时保留根目录入口。插件宿主机源码只在 Phase 4 完成 Adapter 拆分后进行纯路径移动；
容器目标路径和插件 ID 保持不变。

### 不变量

- `./manage.sh up`、根目录 Compose 用法、插件 ID 和持久化数据根目录保持兼容，
  或输出经过测试的迁移说明。
- 使用 `git mv` 移动文件；绝不隐式移动运行数据。

### 风险

- 遗漏 CI、文档、Compose 或 Docker 中的硬编码路径。
- 变更后的 Manifest 无法基于现有 Receipt 完成升级。
- 未执行备份或健康检查就发生部分升级。
- 收窄 Mount 导致上游 NapCat/AstrBot 假设失效。

### 验证

- 路径消费者契约，以及 Manifest Schema/完整性/许可证测试。
- 使用一次性数据完成干净 bootstrap、prepare、build、start、seed、health、
  upgrade、backup、restore 和 rollback smoke 测试。
- 根目录包装层兼容测试。
- 容器 Mount/网络契约和安全评审。

### 回滚

使用版本化 Release 目录、升级前一致性备份、上一版本镜像 Digest、Manifest Receipt
和根目录兼容包装层。

## Phase 9：Eval、Tracing 与 CI 汇总强化

### 目标

汇总并强化从 Phase 0 起已经存在的版本化 Eval 数据集、Runtime Trace、MCP/模型指标、
ResponsePlan、Memory 隔离回归、Proactive fake-clock/来源/投递指标、导入/分层检查和完整
smoke Job；本阶段不是首次增加 Eval 或 Trace。Bandit estimator 与 OPE 只属于独立可选的 S20，
不在本 Phase 汇总或实现。

### 必需的 Eval 维度

回复决策、目标、意图、指代、Answer Profile、工具选择、参数、隔离、结果校验、fallback、
OC 一致性、调度/订阅/来源新鲜度/去重和主动打扰度。Fixture 只能使用合成 ID 以及公开或
合成文本。

### 验证

CI 执行单元、契约、集成和 Eval 测试，以及镜像构建、插件安装/导入、Persona seed、
MCP 握手、Compose、仓库扫描和选定的一次性容器 smoke 测试。不稳定的模型测试使用
确定性 Gateway，或采用明确的非阻塞 Eval 策略。

### 回滚

Tracing 可以独立关闭。不得为了恢复绿色状态而移除必需的安全与隔离测试。

## Phase 10：兼容清理

### 目标

只有在 `migration-map.md` 中的每一项移除清单都通过后，才能删除旧模块和旧权威路径。

### 必需证据

- 生产入口使用新实现。
- 对应行为测试和文档为最新状态。
- 不再存在旧 Import、Mount、脚本、CI 路径或运维工作流。
- 数据迁移与回滚均已完成。
- 聚焦于移除工作的 PR 具有可独立测试的回滚 Release。

## 下一可审阅实施步骤

标题：**先完成回答档位、主动出站与其本地审计，真实群验证最后执行**

S01–S11 的本地实现已经完成。接下来按 WIP=1 完成 S12-S15、S15A-S15E、既定 WebUI 测试、
S16-S18、S19 本地总集成与 S22 最终兼容审计。回答档位和主动出站目前只有设计，不得跳过
本地门禁。只有全部通过后，才准备 S23：

1. 冻结授权群、测试用户、发送窗口、SLO 和 digest-pinned 回滚包；
2. 单群执行 no-send/no-write Shadow，先检查脱敏指标；
3. 同一授权群仅对结构化明确 @ 执行入站 Canary；
4. 单独授权并验证手动日报，再验证定时日报；
5. 前述门禁通过后，单独授权一次低频 Conversation Probe；
6. 所有单群行为门禁通过后，才考虑 3–5 群和长时间 Debug；
7. 任一重复、错误目标、quiet-hour/退订后发送、越权、无引用内容、敏感 Trace 或熔断异常
   立即关闭对应行为并回滚。

Bandit 不作为主动出站或 S23 的前置，且禁止探索 send/skip、目标、日程、频率和 Answer
Profile；WebUI 只按既定测试范围验证，不追加可写控制面。

## Phase 验收矩阵

| Phase | 新的权威范围 | 退出前必须新增的门禁 |
| --- | --- | --- |
| 2 | 领域契约/Package | Package/导入/分层测试 |
| 3 | 安全/配置基础组件 | 行为测试和安全负向测试 |
| 4 | AstrBot Adapter/命令 | 插件导入和 Event 契约 |
| 5 | Memory 边界 | 完整隔离和迁移回滚 |
| 6 | Runtime 决策/合成 | 状态、Eval、shadow 无副作用测试 |
| 7 | Capability/MCP Runtime | 有界工具循环和 MCP 契约 |
| 7.5 | 主动消息/订阅推送 | 默认拒绝、fake-clock/持久 claim、公开来源、无发送 Shadow 和独立回滚 |
| 8 | 运维/布局/Manifest | 一次性完整生命周期和回滚 |
| 9 | Trace/Eval/CI | 回答档位、主动调度/来源/投递与完整 CI/隐私安全 Fixture |
| 10 | 无兼容依赖 | 无旧消费者，并具备回滚 Release |
| 最终真实场景 | 入站、日报、Probe 分行为授权群 Shadow/Canary | 所有前置模块和本地审计完成；冻结分行为 SLO、kill switch、回滚包和授权窗口 |
