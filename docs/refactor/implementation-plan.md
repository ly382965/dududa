# Dududa 2.0 实施计划

状态：S01–S11 的本地增量实施步骤已完成。旧 AstrBot Handler 在 `off/shadow`
模式下仍是权威入口；白名单 Canary 只在持久 claim 后取得单一发送所有权。真实群验证尚未授权。

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
- P1：Phase 6–7，形成可选择性切换的端到端 Runtime 与工具闭环；
- P2：Phase 8–10，完成规模化质量优化、Control Plane、部署和兼容清理。

原 4 人并行估算只保留为历史参考。当前按 **1 人、WIP=1** 执行：任何时刻只实现一个
可独立验证和回滚的步骤，完成退出门禁后再进入下一步。不要把原工期机械乘除；Memory 数据
质量、外部服务稳定性和真实群测试窗口会主导实际周期，时间不能替代退出门禁。

### 当前模块完成度

下表按 2026-08-04 的 `716e227` 和 Dududa 2.0 统一完成定义判断。S08-S11 已补齐静态
路由、语义/难度判断、离线 Runtime、Shadow、受控 Canary 与回滚边界；真实 Provider 效果、
Memory/Tool、附件和授权群放量仍按各模块独立门禁判断。

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
| OC 与 Persona | 部分完成 | 最小 Composer、确定性单 Persona Renderer、Fact/target/constraint 保持与 Render Validator 已进入 S10 | 完整 OC 资产、多 Persona、版本发布和人工风格 Eval |
| 在线学习 / Bandit | 未完成（明确延期） | S08-S11 决策 receipt、脱敏聚合和受控 rollout 可供未来独立设计 | 当前无实现、配置或执行 hook；后续仍需 propensity/support、OPE 与单独安全评审 |
| Trace、Eval 与 CI | 部分完成 | 350 项双版本测试、S09 版本化 Eval、Runtime Trace、S11 低基数指标、镜像 registry smoke 和 CI 门禁 | 真实 SLO、长期趋势、线上故障注入与人工 Eval 确认 |
| WebUI / Control Plane | 未完成 | 只有规划条目；当前文档站不是产品 Control Plane | ADR、只读 API、权限/脱敏/审计、Trace/Eval Viewer，之后才考虑写操作 |
| 大规模真实群测试与 Debug | 未完成 | 白名单/显式 @/并发/重启/TargetTalk/kill switch/UNKNOWN 已完成本地仿真 | 经授权的真实群 shadow/canary、3–5 群分层放量、冻结 SLO 和复盘 |

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
| S11 | 已完成（本地） | typed rollout、SQLite claim/tombstone、AstrBot Bridge、发送前熔断、指标和可执行回滚 | 授权真实 QQ 群证据仍未执行 |
| S12–S22 | 未开始 | 仅保留既有冻结设计与顺序 | 真实 Canary 门禁或负责人重新排序后再逐步进入 |

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
| OC 撰写与 Persona | ⭐ | 先复用一个版本化 Persona 和确定性 Renderer；多 Persona/A-B 后置 | 整理角色背景、Voice Rules、禁用表达、技术/闲聊示例和版本化 Persona 资产；不在 Persona 中写权限或事实规则 | 接入 `DraftResponse -> PersonaRenderer -> RenderValidator`；事实锚点、引用、拒绝、目标和附件不可改变，失败时确定性 fallback | 多 Persona、版本回滚、受限用户偏好、Golden/Eval 和 A/B；新增 Persona 不修改 Social Decision、Memory 或 Tool Policy |

### 横向交付计划

| 任务 | P0 | P1 | P2 | 退出证据 |
| --- | --- | --- | --- | --- |
| Trace、Eval 与测试框架 | 建立版本化 fixture、Fake、Contract Test、run/trace ID 和隐私安全记录格式 | 将 Runtime、Router、Memory、Capability、MCP 和 OC 指标接入同一回放/Eval 入口 | 纳入完整 CI、趋势对比、故障注入和发布门禁 | 同一版本数据与配置可重复运行；安全门禁不可设为非阻塞 |
| WebUI / Control Plane | 先提交 ADR，再定义权限、脱敏、审计、配置版本和只读查询 API；不抢先制作第二套业务逻辑 | 提供只读 Trace Viewer、Agent Playground、Eval 结果和 Model/MCP Health | 增加 RBAC、Memory Explorer、Persona/Model/Capability 配置、成本性能和告警 | UI 不绕过 Runtime Policy 或 Repository；所有写操作有审计、确认和回滚 |
| 集成与真实群聊测试 | 使用合成 Event、离线回放和跨 Scope 负向 fixture，不读取生产聊天 | 白名单测试群依次执行 no-send/no-write shadow、明确 @ canary 和只读 `/course search` canary | 扩展到 3–5 个不同活跃度群，再执行大群并发、重复消息、故障注入和逐步放量 | 重复回复、未授权 Tool、跨 Scope Memory 和敏感 Trace 均为 0；达到模块 SLO，并验证 kill switch |

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
6. 首个白名单 canary 前必须有 kill switch、上一版本镜像、无副作用 shadow 证据和明确回滚
   命令；不能把真实群聊当集成测试环境。
7. Bandit 依赖稳定 Router、before-action 日志、延迟反馈和足够流量；WebUI 依赖稳定只读 API、
   权限和脱敏。二者都不在首个可用版本关键路径上。

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
| S11 | 6D | 在一个白名单测试群依次执行 no-send shadow 和明确 @ canary；旧链路仍可一键恢复 | 无重复回复、错误目标、未授权数据、敏感 Trace；P95/错误率有基线；kill switch、回滚镜像和复盘记录有效 | 扩大群数或接入高风险能力 |
| S12 | 7A | 实现 Unified MCP Client/Server Registry，把 iCourse 映射为第一个 Provider；只切只读 `/course search`，使用固定安全 Plan | Discovery/Schema cache、持久 Session、timeout/retry/重启/熔断、export root、抓取上限和 handshake smoke 通过 | 通用多步 Planner、写操作和其他 MCP Server |
| S13 | 7B | 实现 Capability Registry/Retrieval、有限 Planner、逐步授权 Executor、Observation 和 Validator；先覆盖课程只读路径 | 候选资格/Top-K、参数 Schema、最多步数、重复调用、未知结果、Prompt Injection 和预算测试通过；可按 Capability 回滚 | 高风险/不可逆 Tool 和任意动态 Tool 暴露 |
| S14 | 6E | 接入 Memory Retrieval 与 Write Gate：先 exact/recency/BM25 baseline，再 shadow 对比 embedding | Scope 泄漏为 0；显式写入、TTL、冲突、删除/导出、Delivery 依赖和迁移核对通过；复杂检索确有增益 | Graph/Temporal Memory、未确认自动写入 |
| S15 | 6F | 完成 OC/Persona 产品化：版本化资产、Composer/Renderer 分层、Render Validator、用户偏好隔离和 Golden/盲评 | Fact/Citation/Refusal/Target/Attachment 变化为 0；版本回滚与 fallback 可执行 | 多 Persona 市场、在线风格探索 |
| S16 | 8A | 先做运维硬化：health、backup、restore、upgrade receipt、rollback、最小 mount/network 和 Release manifest | 一次性数据完成 bootstrap -> start -> health -> backup -> upgrade -> restore -> rollback | 大规模目录移动或删除兼容入口 |
| S17 | 8B | 用 `git mv` 分批迁移 `apps/`、`packages/`、`services/`、`configs/`、`deploy/ops`、`third_party/`；根入口保持兼容 | 每次路径切换的消费者契约、容器 smoke、根包装层和上一 Release 回滚通过 | 同一 PR 同时移动全部路径或运行数据 |
| S18 | 9 | 汇总 Trace、Eval 与 CI：版本化 fixture、run 关联、模型/MCP/Memory/OC 指标、故障注入、镜像与容器 smoke | 完整 unit/contract/integration/eval/smoke 矩阵通过；Trace 不含原文/凭据/真实标识；发布阈值冻结 | 通过删除安全测试恢复绿色状态 |
| S19 | 真实场景 | 从 1 个白名单群扩到 3–5 个不同活跃度群，再做大群并发、重复消息、Provider/MCP 故障和长时间运行 | 重复回复、未授权 Tool、跨 Scope Memory、敏感 Trace 为 0；SLO、单侧风险上界、kill switch 和复盘满足门禁 | 无指标的全量放开 |
| S20 | P2 在线优化 | 仅在 Model Route 的合法 Endpoint 中实现 Bandit：先日志与合成 estimator，再 shadow、极小 canary、IPS/SNIPS/DR | 有足够 support/有效样本量；群级 bootstrap、baseline floor、零安全 Gate 违规和自动回滚通过 | 权限、Memory Scope、高风险 Tool、敏感 Provider 或 Reply/Ignore 探索 |
| S21 | 规划项 | 在 ADR 批准后实现只读 WebUI：Trace/Eval/Model/MCP Health；稳定后才讨论带审计和回滚的写操作 | API 复用 Runtime 权限/Scope/脱敏；RBAC、审计、CSRF/越权和回滚测试通过 | 在 UI 重写第二套业务逻辑或抢先做完整 Control Plane |
| S22 | 10 | 按 `migration-map.md` 逐项删除旧 Client、Handler、Import、Mount 和路径；每次只清一个兼容面 | 生产入口和测试只消费新实现；移除清单为 0；迁移/回滚完成并保留可独立恢复 Release | 顺手重构或没有消费者证据的批量删除 |

达到 S11 才算“首个可用直聊版本”，达到 S13 才算“首个可用工具闭环”，达到 S19 才进入
“可扩大真实使用”的候选状态。S20 Bandit、S21 WebUI 和 S22 清理都不能反向阻塞前三个里程碑。

单人阶段主动暂停以下范围：第二聊天平台、通用高风险 Tool、自动 Memory 写入、Graph Memory、
模型微调、neural bandit、多 Persona 市场和可写 Control Plane。只有前一里程碑的真实错误证据
证明它们必要时，才把其中一项加入新的 Spec 和顺序表。

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
| 新 Persona | `PersonaRegistry`、`PersonaRenderer` | 版本、Digest、事实保持测试、安全评审和回滚 | 否 |

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
| Router/MCP | 单 Provider、静态路由、带 fallback 路由；每次新建进程与复用 Session | 固定请求、错误注入和并发场景 | Schema-valid rate、成功率、P50/P95、重试、进程创建数、恢复时间和成本 | 未授权路由/Tool 暴露必须为 0；优化不能降低错误可解释性或回滚能力 |

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
转换、Response Composer、OC 边界和 Trace。

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
- Response 的事实/错误/引用保护，以及 OC 一致性测试。
- 证明 shadow 模式绝不发送消息或写入 Memory。

### 回滚

关闭 Runtime Bridge 开关；旧 Adapter 保持完整可用。

## Phase 7：统一 Capability 与 MCP

### 目标

实现 Capability Registry/Retrieval、Planner、Executor、Validator、统一 MCP
Client/Server Registry，以及 iCourse Capability Provider。在选择性切换后消除
iCourse 双 Client 路径。

### 不变量

- 当前课程命令和输出继续可用。
- iCourse 保持为独立的 Service Package。
- Planner 不能看到不符合条件或高风险的工具。

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
Memory 隔离回归、Bandit 反事实评估、导入/分层检查和完整 smoke Job；本阶段不是首次增加
Eval 或 Trace。

### 必需的 Eval 维度

回复决策、目标、意图、指代、工具选择、参数、隔离、结果校验、fallback 和 OC
一致性。Fixture 只能使用合成 ID 以及公开或合成文本。

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

标题：**S08：增加静态模型路由器**

S01–S07 已完成，下一步只进入 S08：

1. 定义一个现有 Provider 的兼容 Adapter，以及 `PERCEPTION`、`DIRECT_CHAT` 两个
   `ModelRole`。
2. 实现逐 Endpoint descriptor、静态 Route Policy、预算/隐私/健康硬过滤和有界 fallback。
3. 使用 Fake 与真实兼容 Adapter 共享 Contract Test，覆盖 Structured Output、429、
   timeout、认证失败、无合法路由和敏感数据拒绝。
4. 保持旧模型调用路径和 AstrBot Handler 权威；不在 S08 接入生产 Event。
5. 不实现多 Provider 优化、图片角色、Bandit、Perception 合并器或 Runtime Orchestrator。

S08 通过后才进入 S09。生产 shadow/canary 仍需等待 S10–S11，不能用 Router 单测替代。

## Phase 验收矩阵

| Phase | 新的权威范围 | 退出前必须新增的门禁 |
| --- | --- | --- |
| 2 | 领域契约/Package | Package/导入/分层测试 |
| 3 | 安全/配置基础组件 | 行为测试和安全负向测试 |
| 4 | AstrBot Adapter/命令 | 插件导入和 Event 契约 |
| 5 | Memory 边界 | 完整隔离和迁移回滚 |
| 6 | Runtime 决策/合成 | 状态、Eval、shadow 无副作用测试 |
| 7 | Capability/MCP Runtime | 有界工具循环和 MCP 契约 |
| 8 | 运维/布局/Manifest | 一次性完整生命周期和回滚 |
| 9 | Trace/Eval/CI | 完整 CI 矩阵和隐私安全 Fixture |
| 10 | 无兼容依赖 | 无旧消费者，并具备回滚 Release |
