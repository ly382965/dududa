# Dududa 2.0 实施计划

状态：S01–S20 的既定本地/离线工程步骤已完成；S22 已完成基于消费者和回滚证据的兼容清理。
S21A Foundation、S21B Group Onboarding、S21C Governed Operations 与 S21 Completion Audit
均已完成离线实现和验证；S23A–S23E 私有历史语料离线 Demo 已完成，但 S23 整体仍为
paused/partial，实时 Shadow/Canary 尚未开始。真实 Provider、Source、Projection、Output 的
环境适配/Conformance 和外部授权输入均未闭合。S23 分支已补齐配置驱动的入站生产 Runtime
最短纵切，并完成固定 AstrBot 4.26.2 候选镜像的受控参数透传和隔离候选启动；Runtime 契约
仍只由 Fake AstrBot Provider 证明。Luna/Terra/Sol 已各完成一次真实 Provider-level no-send，
WebUI 的历史语料内测第一版也已作为既有 Bot Control Plane 中的 no-send Evaluation Adapter
完成；实时 Agent Console 的动态 Catalog、Scope Policy、六项正交配置、插件四态和有效选择解释
纵切也已闭合。六项配置分别是模型档位、推理强度、回答长度、回复强度、上下文长度（运行预算）
和群聊风格。实时 Console 是正式 Bot 超级工作台，不应与历史评测面混为一谈。上述结果都不是
Runtime Shadow、AstrBot Conformance、真实群证据或正式上线。旧 AstrBot Handler 在 `off/shadow`
模式下仍是权威入口；白名单 Canary 只在持久 claim 后取得单一发送所有权。真实群聊场景测试
所需的本地模块、既定 WebUI 测试和集成审计已经完成，但 S23 仍须先闭合环境适配和外部授权；
独立可选 S20 不属于该发布前置。

2026-08-09 Alignment 新增的短/中/长回答、低频 Conversation Probe 和公开来源订阅日报，
现已完成 S15/S15A-S15E 的离线契约与 no-send Shadow 范围；真实来源、人工质量和真实发送仍
未实现，也不扩大 S08-S11 的历史完成范围。

同日完成的开发环境预检、重点 Topic 调研、外部输入门禁和下一轮建议 Tree 汇总见
`../research/recommendation-matrix.md`。这些结论用于开工排序，不构成 S12-S20 实现证据。
截至 2026-08-10 的阶段快照和可立即准备的产品输入分别见
`checkpoint-report-2026-08-10.md` 与 `external-input-checklist.md`。2026-08-14 完成的
[受治理自适应 Agent Runtime 长程研究](../research/deepseek-harness-inspired-dududa-evolution.md)
已经形成并由用户确认长期设计方向；Web 的目标是 Bot Control Plane，其首个用例是管理员在 Bot
入群后选择初始 `GroupServiceProfile`。Tree revision 4 已据此加入 S21；Foundation、Onboarding、
Governed Operations 和 Completion Audit 均已有实现与聚焦验证。其他长期新增能力仍没有
实现证据。完整证据见 [S21 Bot Control Plane 离线完成审计](s21-control-plane-completion-audit.md)。
控制后台的产品边界、入群状态机、Profile/Assignment、命令面和完成定义见
[Bot Control Plane 与群服务初始化设计](../design/bot-control-plane.md)。

2026-08-14 已完成本机 NapCat 私有开发回放和历史游标核验，详见
[NapCat 本机开发语料回放报告](napcat-development-replay-2026-08-14.md)。本机只允许使用当前
嘟嘟哒账号数据；旧账号已排除，精确账号映射只在运行时提供。2026-08-15 提供的外部长期
静态导出已在 S23 私有目录完成筛选、Silver 标注、Student 评测和 no-send Demo；它不是当前
Dududa Bot 实时流量。完整结果见
[S23 私有历史群聊离线 Demo 报告](s23-private-corpus-demo-2026-08-15.md)。

同一 S23 分支已实现配置驱动的入站生产装配：可按实际配置接入 Haiku/Sonnet/Opus 的任意
1–3 个档位，每个 Endpoint 由独立 AstrBot Provider Adapter 接入既有 Static Router；API Key
继续由 AstrBot Provider 管理。首版采用 rule-only Perception，`off` 零 Provider 调用，
`shadow` 每条消息至多进行一次候选回答调用且不 claim、不发送；配置关闭、无效或 Provider
无法解析时回退 legacy。后续 Adapter/Composition 修复的 34 项聚焦测试在 0.719 秒内通过，
此前 27 项 Runtime/rollout 抽样仍有效。以上仅证明 repository production shape，不证明真实 Endpoint、运行容器、实时群或
QQ 发送已经就绪。

2026-08-15 已对 `gpt-5.6-luna`、`gpt-5.6-terra`、`gpt-5.6-sol` 分别完成 Responses API
和 AstrBot 实际使用的 Chat Completions 最小真实请求抽样；两种协议均成功返回、模型 ID 匹配
并包含 usage。此后又通过独立、无 QQ Connector/Output 的 Provider-level runner 对三模型各调用
一次，三次均成功且 `output_calls=0`；该 receipt 只保存模型、档位、延迟和 usage，不保存回答。
这些证据都不是 AstrBot Conformance、Runtime Shadow 或真实群 Shadow。候选镜像已显式透传
请求级输出上限和配置声明的固定 Endpoint 思考深度，提供默认关闭、无凭据的
Luna/Haiku、Terra/Sonnet、Sol/Opus 样板，并已在固定 AstrBot 4.26.2 隔离候选中完成启动验证；
运行中的 AstrBot 仍未切换或正式注册三模型。Builder 必须解析真实 Provider Evidence，Endpoint
初始健康为 `UNKNOWN`。默认关闭的主动健康刷新器现已实现成功、超时失败、`UNKNOWN`、TTL
到期和 `terminate()` 取消的聚焦路径，但尚未在运行中部署启用，也不能替代正式 Conformance。
当前不是同一 Endpoint 按请求动态切换思考深度。

2026-08-16，WebUI 历史语料内测第一版已完成：即使没有 NapCat 账号也可进入 `#/internal-test`，浏览和
筛选 300 个既有脱敏窗口，查看 Silver、Student、AnswerProfile、Static Tier 与
Luna/Terra/Sol 映射。一次由操作员显式触发的 Terra `no_send` 候选耗时 3059 ms，记录为
`providerCalls=1`、`outputCalls=0`、`memoryWrites=0`、`toolCalls=0`；人工评价追加到仓库外
权限 `0600` 的 JSONL，且不保存候选正文、Provider Key 或 Base URL。该历史面板属于控制后台的
no-send Evaluation Adapter，不是第二套 Runtime，也不构成 AstrBot Runtime Shadow、Provider
Conformance、真实群验证或正式上线证据。实时 Agent Console 的产品定位不同：它是正式 Bot
Control Plane/超级工作台，负责管理员初值、合法范围和显式锁定，但不替代 Core Runtime。

2026-08-17 已完成 Agent Console 的自适应配置纵切。配置按
`accountId + conversationId` 持久化到服务端仓库外数据根；模型档位、推理强度、回答长度、
回复强度、上下文长度（运行预算）和群聊风格六项设置保持正交。管理员为每项设置初值、
`allowed[]` 和 mode；`adaptive` 与 `preferred` 均允许 Agent 每轮按任务信号在合法范围内改选，
只有显式 `locked` 才固定。回复强度只是一项候选决策输入，不能解释为真实自动发送概率；
Luna/Terra/Sol 也只能作为默认偏好，不能固化为 SHORT/MEDIUM/LONG 的一一映射。

“上下文长度（运行预算）”只限制本轮送入模型的近期群聊历史，不是模型厂商声明的最大
Context Window。`compact`、`standard`、`extended` 分别限制为 12 条/6,000 字符、
30 条/18,000 字符、60 条/36,000 字符；每次 Run 的 `contextUsage` 返回
`messageLimit`、`characterLimit`、`messagesRead` 和 `charactersRead`，同时解释预算上限和实际
读取量。Run 还返回六项管理员初值、合法范围、实际选择、改选原因和实际调用插件；回答长度按钮
只作为一次性 Run Hint，不写回长期模型策略。

插件使用 `off/auto/on/locked`，但任何模式都不能越过 Core 的 Capability 资格、权限、预算和
副作用控制。Catalog 由服务端动态提供并准确标记安装/可用状态：iCourse 是唯一真实 MCP，
但当前 Console Runtime 不可调用；`gpt-image-2` 当前同样不可调用。自动复读只登记为 Dududa 1.0
历史资产，保持关闭且不可用，不恢复旧概率复读执行链；`/sub2api 自动查询` 是仅超级管理员可用的
确定性只读命令，不受普通会话 Policy 管理，当前 Console 执行链尚未接通。校园资讯、arXiv、
行业资讯、网络搜索等未接能力均显示 `unavailable + reason`，不得用 fixture 或预留接口冒充
真实服务。

Console 同时区分管理员期望与实际 Runtime 状态：被动自动回复保持 `rollout_mode=off`、
delivery disabled、kill switch active；主动参与仅为 S15E Probe Shadow，并明确标记 `NO SEND`。
该纵切的 12 项 Workspace、5 项服务端聚焦测试、TypeScript 类型检查和 Web production build
已通过；候选继续保持 `outputCalls=0`、`memoryWrites=0`、`toolCalls=0`。这些结果不改变 S23
整体 `paused/partial` 状态。

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
- P2：Phase 8–10 加单独批准的 S20/S21，完成部署/兼容清理、离线学习基础和 Bot Control Plane。

原 4 人并行估算只保留为历史参考。当前按 **1 人、WIP=1** 执行：任何时刻只实现一个
可独立验证和回滚的步骤，完成退出门禁后再进入下一步。不要把原工期机械乘除；Memory 数据
质量、外部服务稳定性和真实群测试窗口会主导实际周期，时间不能替代退出门禁。

### S23 多模型结构化抽样的五小时预算

已有 S23A--S23E 的 600 条 Terra Silver、137,026 条 Student 预测和私有 Demo 直接复用，不因
新增 Luna/Sol Endpoint 而重跑。只有需要新的多模型校准样本时，才执行下表；总预算按单人
4--5 小时设计，第五小时为硬停止：

| 累计时间 | 任务 | 调用/规模上限 |
| --- | --- | ---: |
| 0--60 分钟 | 复用并校验现有索引；仅处理新增或失效文件的过滤、去重和窗口 | 不调用 LLM |
| 60--85 分钟 | 20--24 个分层窗口吞吐实测 | 最多 24 次 |
| 85--210 分钟 | Luna 主样本结构化 | 默认 250，最多 350 |
| 与主样本并行 | Terra 低置信度/Schema 复核；Sol 高歧义抽查 | Terra <= 50；Sol <= 15 |
| 210--255 分钟 | 按群隔离训练/评估 | 固定已得样本 |
| 255--285 分钟 | Demo 与指标 | 固定已得样本 |
| 285--300 分钟 | 文档与缓冲 | 不再发请求 |

首批 P95 < 15 秒时 Luna 上限为 350，P95 为 15--30 秒时固定 250，P95 > 30 秒时降为
120--150。T+3.5 小时停止发起新请求，每个窗口最多重试一次；单群样本占比不超过 5%--8%，
train/dev/test 必须按群隔离。五小时内无法完成的样本进入 Review，不延长任务、不把全量
410 MB 文本提交给模型，也不以减少 Demo/指标收尾时间换取更多调用。

### 当前模块完成度

下表按 2026-08-16 的 TreeWork 分支现实和 Dududa 2.0 统一完成定义判断。S08-S13 已补齐静态
路由、语义/难度判断、离线 Runtime、Shadow、受控 Canary 与回滚边界；真实 Provider 效果、
Memory、附件和生产 Tool Rollout 仍按各模块独立门禁判断。授权群放量不再穿插在模块开发中，
只在最终阶段执行。

| 模块或工作流 | 状态 | 已有证据 | 达到完成仍缺少 |
| --- | --- | --- | --- |
| 开发环境与研究基线 | 已完成（本地） | TreeWork 0.1.7、根 uv lock、Python 3.10/3.12、Node 22、Playwright、干净构建及十份研究报告已形成 | 生产环境仍未就绪；真实 Provider/来源/数据/标注和授权按各模块门禁补充 |
| Phase 0 审计、`v1alpha` 接口与迁移计划 | 已完成 | 当前状态、依赖、设计、ADR、迁移和实施文档已形成，并通过文档门禁 | 不包含 Runtime 代码；进入 S01 后按实现证据重新判断 |
| 核心 Package 与 Agent Runtime | 部分完成 | Orchestrator、CAS State Store、完整直聊、默认关闭的有界 Tool 链、Delivery acknowledgement/reconciliation、无副作用 Shadow、受控 Bridge 与配置驱动入站 production shape 已实现 | 真实 Endpoint Conformance/部署、Memory/Attachment Runtime 与授权生产证据 |
| 输入 Connector 与 Output Adapter | 部分完成 | AstrBot Connector/Output、结构化 @、Delivery、持久 rollout claim/tombstone、发送前控制复核和 Bridge 已实现；S23 Builder 可从 AstrBot Provider 装配模型 Adapter | 真实 Attachment Source、第二平台、真实 Endpoint 绑定与授权真实群 delivery 证据 |
| 模型路由器 | 已完成（S08 静态范围） | 三 Tier 契约、逐 Endpoint descriptor、Registry、隐私/预算/健康/流量过滤、容量 admission、fallback、Fake 与兼容 Adapter | 真实多 Provider 质量/延迟/成本证据；动态优化和 Bandit 不在 S08 范围 |
| Memory | 部分完成 | S14 已闭合 generation-bound 读取、CAS 删除/tombstone、scoped export、archive/restore、JSON v2 重启证据、M0/M1/M2、纯 Python CJK BM25 和固定合成 Eval；Scope/Write Gate 与 fail-closed Iris 边界保持不变 | 旧命令与 Context Builder 消费者迁移、真实 Iris SDK Backend、授权数据/人工质量评测、Embedding/Hybrid 证据、shadow 和生产切流 |
| MCP 集成 | 已完成（S12/S22 离线范围） | Core MCP DTO/Port、严格 JSON Registry、长生命周期 Unified Client、隔离 MCP v2 worker、Fake/iCourse 共享 Contract；S22 已删除插件专用直连 Client，缺失时 fail closed | 真实新 Server、凭据和在线来源仍是外部门禁 |
| Capability 与 Tool Runtime | 已完成（S13 离线范围） | 原子 Catalog/Health、授权感知 Retrieval、确定性有限 Planner、逐步重验 Executor、single-flight Ledger、Observation Validator、通用 MCP Provider、四个 iCourse 公开缓存映射、配置式 Fake 扩展及默认关闭的 Offline Runtime 工具链均有测试 | 无真实 Tool Planning Endpoint、真实语言质量、生产 Tools Rollout、高风险/写能力或新真实 Server 证据 |
| 语义理解与 Social Decision | 部分完成 | 通用 Intent/Entity/Reference/Evidence、Rule/Model/Merger/Validator、Social Policy、Complexity、TierPolicy 和 320 条合成 Eval 已实现；S23 又对 600 条分层历史窗口生成 Terra Silver，并以 464 条编译样本训练群隔离 Student | Silver 类别严重不均衡；仍缺人工 Gold、阈值校准、当前 Bot 实时流量和多轮/附件语义质量证据 |
| 回答档位与动态输出预算 | 已完成（S15 离线范围） | 独立 `ResponsePlan(SHORT/MEDIUM/LONG)`、显式详略证据、动态预算、Router/Tier/Reasoning 正交性、最终长度/完整性 Validator 和固定 3x3 Eval 已通过 | 真实 Provider tokenizer、人工回答质量、QQ 分片体验和最终预算校准仍是外部门禁 |
| OC 与 Persona | 部分完成 | S15 已增加 typed `dududa`/`neutral` 资产、Catalog CAS/LKG/旧 generation 回放、确定性 Renderer 和 Persona/Plan 最终绑定 | 模型 Renderer、多 Persona 产品资产、用户偏好存储和人工风格 Eval |
| 主动消息与订阅推送 | 部分完成（S15A-S15E 离线链完成） | S15A-S15D 契约/调度/来源/日报之上，S15E 已实现脱敏群投影、确定性 hard gates、短 TTL Opportunity、原子 Shadow cooldown、attribution-bound no-response 长冷却、固定 SHORT 候选和 digest-only no-send 记录；S16-S22 本地发布闭环已完成 | 生产 Projection Adapter、持久 Probe ledger、真实来源/模型/发送和人工相关性/打扰度仍是 S23 的环境集成与外部门禁 |
| 在线学习 / Bandit | 离线基础已完成（S20） | Framework-neutral decision/execution/feedback DTO、Router-planned baseline、完整 action support、propensity validator、Decimal IPS/SNIPS/DR/ESS 和固定合成 bundle 已通过；生产路径无 Bandit import/hook | 真实同档 Endpoint、before-action 日志、可归因反馈、Shadow/在线训练和探索仍未开始；禁止学习主动发送和 Answer Profile |
| 可组合插件 Runtime | 设计方向已确认、工程未开始 | 已确认“不可卸载治理内核 + 可逆、分 Realm 的能力插件”方向，并给出 Descriptor/Lifecycle/Generation/Disposer 边界 | 尚无 Sxx 分支、Plugin Runtime、迁移或故障恢复证据；不得据此宣称已有插件生态 |
| Group Context / 关系证据 / Skill 演化 | 设计方向已确认、工程未开始 | 已确认群级弱先验、Memory、关系证据、候选 Skill/Prompt/Style 资产和 Bandit 分权 | 尚无 DTO、Projection、候选流水线、授权数据或 Eval；不得自动发布 Skill 或推断真实人物关系 |
| Trace、Eval 与 CI | 部分完成 | 版本化 Python 测试、S09/S13 合成 Eval、Runtime Trace、S11 低基数指标、镜像 registry smoke 和 CI 门禁 | 真实 SLO、长期趋势、线上故障注入与人工 Eval 确认 |
| WebUI / Bot Control Plane | S21 已完成（离线）；历史语料内测与 Agent Console 自适应超级工作台纵切均已完成 | 已实现 operator session/RBAC、Profile/Assignment、pending/managed、Desired/Effective、完整生命周期、SQLite LKG/重启恢复、六面运维投影和 Python→Node→Vue 查询链；历史语料面板支持 300 个脱敏窗口浏览/筛选、显式 `no_send` 候选和仓库外人工反馈；实时 Console 已实现动态 Catalog、`accountId + conversationId` 服务端 Policy，以及模型档位、推理强度、回答长度、回复强度、上下文长度（运行预算）、群聊风格六项正交配置。管理员设置初值、`allowed[]` 和 mode，只有 `locked` 固定；上下文三档预算为 12/6,000、30/18,000、60/36,000 条消息/字符，并返回预算和实际读取量 | 被动自动回复仍为 `rollout_mode=off`、delivery disabled、kill switch active；主动参与仅 S15E Probe Shadow/`NO SEND`。iCourse、`gpt-image-2`、自动复读和 `/sub2api 自动查询` 均未接入当前 Console 执行链；生产 HTTP/身份绑定、真实运行健康、Provider/Source/Projection/Output 和授权真实 QQ 仍是 S23 外部门禁。历史面板是 Evaluation Adapter；实时 Console 是 Control Plane，但两者都不替代 Core 权限、预算或发送权 |
| 大规模真实群测试与 Debug | S23 暂停、部分完成（离线 Demo、Web 人工内测与候选模型接入工程完成，实时未开始） | 1,402 个静态文件形成 155,567 条唯一群消息和 137,026 个 past-only 窗口；600 条 Terra Silver 抽样、464 条编译样本、全量 Student 预测及私有 localhost Demo 已完成；Web 内测页完成 300 窗口浏览/筛选及一次 Terra 人工触发候选，调用计数为 `providerCalls/outputCalls/memoryWrites/toolCalls=1/0/0/0`；固定 AstrBot 4.26.2 隔离候选启动、三模型 Provider-level no-send 和默认关闭健康刷新器聚焦证据均已通过 | 150–300 条类别均衡人工 Gold 是推荐的质量校准分支，不阻塞 no-send Shadow；先在隔离候选中正式注册三模型并完成真实 Endpoint Conformance，再启用运行中的候选 Runtime 与持续健康刷新。Projection/Connector 是 Shadow 前置，Output 是 Inbound Canary 前置，真实 Source 是 Manual Digest 前置；随后才按授权分层放量、冻结 SLO 并复盘 |

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
| S12A | 已完成 | MCP v2 native/legacy、生命周期和版本隔离 Spike 已形成 ADOPT ADR | 保持主环境 MCP 1.29、worker MCP 2.0 的隔离结论 |
| S12 | 已完成 | Unified MCP、严格 Registry、独立 worker、iCourse facade/rollback、扩展 fixture、双 Python、故障注入、派生镜像、secret、Web、Ruff 和 TreeWork Verification 均已通过 | 真实新 Server、真实 HTTP Endpoint 和在线来源保持外部门禁 |
| S13 | 已完成（离线） | Capability Catalog/Retrieval/Planner/Executor/Validator、iCourse/Fake Provider Contract、合成 Eval、Tool State/预算/授权/模型不可信证据投影和 no-send 集成测试通过 | 生产 Rollout 保持 Tools 关闭；真实 Planner Endpoint、人工质量和真实新 Server 不在本阶段 |
| S14 | 已完成（离线） | 生命周期、删除/tombstone、scoped export、archive/restore、M0 no-memory、M1 recency、M2 CJK BM25、固定合成 Eval 与双 Python/构建/Web/安全综合证据均通过 | 不启用 Runtime Memory；真实 Iris、授权数据、人工质量和 Embedding/Hybrid 继续作为外部门禁 |
| S15 | 已完成（离线） | Profile/Persona 契约、Runtime/Delivery 绑定、17-case 3x3 Eval、双 Python/构建/Web 综合证据均通过 | 不声明真实中文体验、Persona 风格、Provider tokenizer 或最终预算已校准 |
| S15A | 已完成（离线） | 主动 DTO/Port、Target/Grant Registry、Actor 解析、默认拒绝 Policy、quota、Preview metadata、Dispatch CAS/recovery、Fake 与 590 项双 Python 全仓证据 | 不含 Scheduler、来源、模型、真实 Output 或 QQ 发送；生产保持无入口且默认 off |
| S15B | 已完成（离线） | 持久 Scheduler、typed JSON/SQLite authority、DST/misfire、双实例 claim/reclaim/ack、重启/篡改和 30 日仿真通过 | 不含生产组合、来源、模型、Output 或真实发送 |
| S15C | 已完成（离线） | Source-neutral DTO/Port、Capability/Source digest 分权、可信 receive-time freshness、原子 cursor/dedup commit、revision hold/emit、三类合成 fixture 与第四 Fake Source 配置式扩展通过 | 不含真实 Adapter/网络、真实时效/许可/内容质量、生产 source database、Composer 或发送 |
| S15D | 已完成（离线） | Digest policy/metadata、确定性 Composer/Builder、no-send Shadow Runtime、隔离 Preview、Trigger 过期重验和第 1/2/30 天代表样本通过；普通记录不含正文；S16 已为共享 Source Reader/Store/lock 增加中途取消与期限约束 | 不含生产 Scheduler 组合、真实 Source/模型/持久 metadata、Output/Dispatch/QQ 发送 |
| S15E | 已完成（离线） | Sanitized group window、Probe policy/detection/state/feedback/metadata、原子并发 claim、TTL/hard gates、普通/无人回应长冷却、SHORT Persona/Validator、no-send Runtime 和第 1/2/30 天抽样通过 | 不含原始/真实聊天 Projection Adapter、持久 ledger、人工质量、Output/Dispatch、自动追问、模型或 QQ 发送 |
| S16 | 已完成（离线） | 标准库 Release Manifest/State/Receipt、只读 Health、SQLite 一致性 Backup、确定性 Restore Plan、Upgrade/单次失败回滚、根命令转发和 Compose mount/network Contract 已通过临时数据抽样 | 真实 Compose/HTTP/MCP Health Driver、生产备份范围/加密、原地 Restore、真实升级演练和容器观测留待 S19/S23 授权环境 |
| S17 | **已完成、已验证、已合并** | 三批路径迁移与旧 marker 兼容均已提交；canonical 路径、根 symlink、Compose 和双 Python聚焦 Contract 通过 | 路径别名已由 S22 删除；Manifest v2 因许可证/hash/lock 证据不足延期 |
| S18 | **已完成、已验证、已合并（离线）** | `daf3111` 冻结 Spec；`5be566a` 实现十个固定 runner/十四维 catalog、原子低敏 receipt、append-only Runtime Trace、双锁 CI 与 Node 22；`7e7cbab`/`4cd9ddc` 绑定完整 catalog 并移除外部 run-ID 注入；四套 350-case bundle、146 项 focused Contract、Python 3.10 受影响样本和构建/Compose/secret 门禁通过 | 完整双 Python 全仓、Web/E2E、镜像/容器、完整故障与 SLO/回滚候选证据统一留给 S19；不声明真实质量 |
| S19、S22 | **均已完成并验证（离线）** | S19 18/18 gate 通过；S22 删除十个路径别名和专用 iCourse Client，保留七个 live surface，并冻结精确 S19 归档 | Manifest v2、真实 Provider/source/QQ 和人工质量继续作为独立门禁 |
| S20 | **已完成（离线）** | Decision/execution/feedback 绑定、完整 behavior/evaluation action support、Router planned baseline、严格 propensity、Decimal IPS/SNIPS/DR/ESS 和四样本可重放 Golden 已通过 | 不训练、不接生产 Worker、不做 Shadow/live exploration，且不阻塞 S23 |
| S21 | **已完成、已验证（离线）** | Foundation、Group Onboarding、Governed Operations 与 Completion Audit 均通过；管理员可用 Fake join/service 选择初始 Profile，Runtime 读取不可变 Assignment，运维页只呈现 Core 投影，Agent 路径不直发 NapCat | 生产 HTTP/身份、真实健康、真实 Provider/Source/Projection/Output、人工质量和真实 QQ 操作仍属于 S23 外部门禁 |
| S23 | **暂停、部分完成；离线 Demo、Web 人工内测、Agent 超级工作台与候选模型接入工程已完成** | manifest-only readiness、历史语料 Demo、配置驱动 Builder、固定 AstrBot 4.26.2 隔离候选启动、Luna/Terra/Sol 各一次真实 Provider-level no-send、默认关闭健康刷新器、无 NapCat 的 `#/internal-test` 300 样本人工评价，以及动态 Catalog/Scope Policy/六项正交配置纵切均已完成；历史 Web 候选的一次 Terra 调用为 `providerCalls/outputCalls/memoryWrites/toolCalls=1/0/0/0`，Console 候选保持 `outputCalls/memoryWrites/toolCalls=0/0/0` | 分支尚未合并；被动自动回复实际关闭，主动仅有 S15E Probe Shadow/`NO SEND`，两个 Web 面均不构成 Runtime Shadow、Conformance 或真实群证据；iCourse、`gpt-image-2`、自动复读和 `/sub2api 自动查询` 当前均不可由 Console 执行，运行中 AstrBot 尚未正式注册三模型，候选部署、真实单群 no-send Shadow、实时 Canary、真实来源、发送、环境 Adapter 和逐行为授权继续关闭 |

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
| Memory | ⭐⭐⭐⭐⭐ | 按“安全边界 -> 生命周期/词法基线 -> 授权数据效果门禁”串行；自动写入始终另行授权 | 已完成 `MemoryScope`、Selector、Repository、Write Gate、内存/JSON 与 fail-closed Iris 边界；S14 又闭合删除/tombstone、导出、恢复和冲突 | 已完成同一授权候选集上的 M0 no-memory、M1 recency、M2 CJK BM25 与固定合成 Eval；Runtime/旧命令仍关闭，不把 fixture 指标外推为真实质量 | 取得授权数据和人工判断后才比较 Embedding/Hybrid，并仅在稳定增益时进入 shadow；Graph/Temporal、生产 Iris 和自动写入继续后置 |
| MCP 集成 | ⭐⭐⭐⭐ | S12 只完成传输与生命周期，S13 才授予业务 Capability | Core 定义 MCP DTO/Port；严格 JSON `McpServerRegistry`、长生命周期 `UnifiedMcpClient`、Schema/timeout/retry/circuit、Fake 和独立 v2 worker | iCourse 作为唯一真实兼容 Adapter 经 facade 转发；原生 v2 Fake 与 iCourse v1 通过同一 Contract，Streamable HTTP 只做禁网 Fake Contract | 新 Server 只增加配置、Adapter 和 Capability mapping；Legacy iCourse 仅在 S22 有完整迁移与上一 Release 恢复证据后删除 |
| 输入 Connector | ⭐⭐⭐ | 首批实现；只支持 AstrBot，接口稳定后才考虑第二平台 | 实现 AstrBot Event 到 `MessageEnvelope` 与 `Actor` 的转换、真实 conversation ID、引用/@/附件引用、幂等键和 conformance fixture；不做意图判断 | 接入附件 Preprocessor、Context 来源、Output Adapter 和 `DeliveryReceipt`；在 shadow Runtime 中验证不重复发送 | 提炼 Connector SDK，支持新平台能力协商、背压、顺序和版本兼容；新增平台不修改 Core Runtime |
| 语义理解（意图/实体） | ⭐⭐⭐⭐ | 规则 baseline 先行，模型只补规则无法覆盖的结构化结果 | 定义 `PerceptionResult`、Intent/Entity/Reference/Evidence Schema、标注规范和 200–500 条脱敏/合成基线集；实现 RulePerception、Validator 和确定性 Social Policy | 经 Model Router 接入 ModelPerception，固定 Rule -> Model -> Merger -> Validator；实现实体、指代、歧义和工具需求，shadow 对比 TargetTalk | 扩展多轮、多意图、QQ 口语、附件摘要和置信度校准；基于真实错误做 Active Learning，只有 Eval 支持时才微调模型 |
| 回答档位 / Response Plan | ⭐⭐⭐ | 作为 S15 首个子步骤；不重做 S08/S09，不把长度映射为 Tier | 定义 `AnswerProfile`、`ResponsePlan`、显式详略 hint、可见 Token/字符/分片和必要内容契约；固定 SHORT/MEDIUM/LONG policy | Runtime 将 Plan digest/动态预算交给 TierPolicy/Router/Composer/Renderer/Final Validator；覆盖 HIGH+SHORT、LOW+LONG | 多语言/平台预算与用户偏好；只有离线证据支持时优化 Profile policy，Bandit 不选择 Profile |
| OC 撰写与 Persona | ⭐ | 先复用一个版本化 Persona 和确定性 Renderer；多 Persona/A-B 后置 | 整理角色背景、Voice Rules、禁用表达、技术/闲聊示例和版本化 Persona 资产；不在 Persona 中写权限或事实规则 | 接入 `DraftResponse -> PersonaRenderer -> RenderValidator`；事实锚点、引用、拒绝、目标和附件不可改变，失败时确定性 fallback | 多 Persona、版本回滚、受限用户偏好、Golden/Eval 和 A/B；新增 Persona 不修改 Social Decision、Memory 或 Tool Policy |
| 主动消息与订阅推送 | ⭐⭐⭐⭐⭐ | S15A-S15E 串行；先契约/时钟/持久性，再来源，再 Shadow；默认 off | 独立 initiated-run、`message.send.proactive`、Subscription/Schedule/Occurrence/Source/Dispatch 契约、Fake Clock/Store/Output、空 allowlist 拒绝 | 持久 Scheduler、CAS claim、Source-neutral Contract、Fake Capability Provider、本地固定校园/arXiv/行业 fixture 与 Digest/Probe no-send Shadow | 真实 Source Adapter/MCP 和实时内容保持外部门禁；S23 分别授权日报与 Probe canary，不使用 Bandit 选择发送/目标/时间/频率 |

### 横向交付计划

| 任务 | P0 | P1 | P2 | 退出证据 |
| --- | --- | --- | --- | --- |
| Trace、Eval 与测试框架 | 建立版本化 fixture、Fake、Contract Test、run/trace ID 和隐私安全记录格式 | 将 Runtime、Router、ResponsePlan、Memory、Capability、MCP、OC 和 Proactive 指标接入同一回放/Eval 入口 | 纳入完整 CI、fake-clock 长期仿真、趋势对比、故障注入和发布门禁 | 同一版本数据与配置可重复运行；安全门禁不可设为非阻塞 |
| WebUI / Bot Control Plane | 冻结 operator auth、Query/Command、`GroupServiceProfile/Assignment`、群入驻状态机和 Receipt；用 Fake join/service 闭环 | 实现管理员选择初始服务的 Onboarding、Desired/Effective diff、CAS 激活/LKG 回滚，以及 Run/Model/MCP/Plugin 投影 | 只在专用 Core 命令存在后增加订阅、审批、行为级开关、Policy/Plugin 发布和实验回滚 | Web 是控制后台但不是第二套决策权威；所有 mutation 绑定 Actor/Scope、revision、幂等、Audit 和 Receipt，学习不能扩权 |
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
7. S15A-S15E 依次完成主动契约、持久 Scheduler、Source-neutral Contract、fixture 日报 Shadow 和 Probe Shadow；
   MCP 只取数，Scheduler 不直调 Tool，定时器不伪造 Connector 消息，主动链不读个人 Memory。
8. 真实群验证是最终阶段：所有当前发布必需模块、既定 WebUI 测试和本地总审计完成后，才允许
   准备白名单 canary；此前只做离线/仿真。独立可选 S20 不属于该发布前置。进入最终阶段前
   必须具备 kill switch、上一版本镜像、无副作用 shadow 证据和明确回滚命令，不能把真实群聊
   当集成测试环境。
9. Bandit 依赖稳定 Router、before-action 日志、延迟反馈和足够流量；Bot Control Plane 依赖
   稳定 Query/Command API、operator auth、Scope、脱敏和 Receipt。Bandit 永不选择主动
   send/skip、目标、订阅、日程、频率、Answer Profile、follow-up 或群服务 Profile。

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
| S12 | 7A | 实现 framework-neutral Unified MCP Client/Server Registry、隔离 v2 worker 和 iCourse facade；discovery 只记录事实、零授权 | 严格配置、Schema cache、持久 Session、timeout/retry/取消/崩溃恢复/熔断、进程树清理、Fake/iCourse 同 Contract 和禁网 HTTP Contract 通过 | Capability Provider/Planner、写操作、真实新 Server；专用 Client 已在 S22 删除 |
| S13 | 7B | 实现 Capability Registry/Retrieval、有限 Planner、逐步授权 Executor、Observation 和 Validator；先覆盖课程只读路径 | 候选资格/Top-K、参数 Schema、最多步数、重复调用、未知结果、Prompt Injection 和预算测试通过；可按 Capability 回滚 | 高风险/不可逆 Tool 和任意动态 Tool 暴露 |
| S14 | 6E | 沿用既有 Scope/Repository/Write Gate，闭合 generation-bound 读取、CAS 删除/tombstone、scoped export、archive/restore，再实现 M0 no-memory、M1 recency 与 M2 CJK BM25 | 生命周期/重启/故障回滚 Contract、Iris unsupported fail-closed、M0 零调用、M1/M2 同 generation、固定合成 Precision/Recall/MRR/nDCG 和五类零暴露门禁通过 | Runtime/旧命令切流、生产 Iris、真实 Memory 数据与人工质量；Embedding/Hybrid、Graph/Temporal 和自动写入均不在 S14 |
| S15 | 6F | 先实现确定性 `ResponsePlan(SHORT/MEDIUM/LONG)` 和动态输出预算，再完成 OC/Persona 产品化：版本化资产、Composer/Renderer 分层、Render/Profile Validator、用户偏好隔离和 Golden/盲评 | 3x3 Complexity/Profile 正交矩阵、明确详略要求、实际长度/分片通过；Fact/Citation/Refusal/Target/Attachment 变化为 0；版本回滚与 fallback 可执行 | 把长度绑定 Tier、多 Persona 市场、在线风格/Profile 探索 |
| S15A | 主动出站 A | 冻结 initiated-run、TargetPolicy/Grant Ref、Trigger、Subscription、Schedule、Preview、Source、Policy、Dispatch、Receipt、`message.send.proactive` 和 `proactive.subscription.preview` 契约；实现 Fake Clock/Store/Output，默认 off | operator/group-policy grant、canonical digest、Scope/授权/revision/quiet-hour/限流/空 allowlist/kill switch、Preview 零投递、恢复复用 PreparedDispatch 和跨 Adapter 版本稳定幂等键的负向 Contract Test 通过 | 网络、模型、真实来源、真实发送 |
| S15B | 主动出站 B | 实现持久 Scheduler、IANA 时区、occurrence、CAS claim、misfire、pause/unsubscribe 和 Schedule Store；只产生结构化 trigger claim | 双 Worker、重复 tick、重启、时钟回拨、DST 和 30 日 fake-clock 仿真无重复/过期补发/撤销后任务 | MCP、内容生成、OutputAdapter |
| S15C | 主动出站 C | 只定义通用 `SourceProvider`、`SourceItem/SourceBatch`、provenance、freshness、revision、citation、allowlist 和去重；用 Fake Capability Provider 与本地固定校园/arXiv/行业 fixture 验证 | Schema/URL/大小/来源游标/条目去重，以及超时/取消/熔断/注入 Contract 通过；准确标记“来源框架完成、真实 Adapter 未完成” | 真实校园/arXiv/行业 MCP/Adapter、实时网络、任意 URL、私人校园信息、外部写、MCP 发送 |
| S15D | 主动出站 D | 接入日报 ResponsePlan、Composer、Persona、来源/引用/长度 Validator；只运行 fixture-backed collect/no-send Shadow 和独立 `PREVIEW` Port | Shadow/Preview 构造无 OutputAdapter；Preview 不创建 occurrence/dispatch/receipt 且正文不进普通 Trace；30 日 fixture 来源/摘要/去重/故障仿真和回滚通过 | 真实来源 Shadow、自动真实发送、LONG 默认日报 |
| S15E | 主动出站 E | 实现群级 Conversation Opportunity、确定性 Proactive Policy、SHORT Probe 与 no-response 长冷却；独立 Shadow/kill switch | 错误目标、重复、quiet-hour、频控、个人/敏感内容和自动追问违规均为 0 | 主动私聊、@个人、个人 Memory、Bandit send/skip |
| S16 | 8A | 先做运维硬化：health、backup、restore、upgrade receipt、rollback、最小 mount/network 和 Release manifest | 一次性数据完成 bootstrap -> start -> health -> backup -> upgrade -> restore -> rollback | 大规模目录移动或删除兼容入口 |
| S17 | 8B | 用 `git mv` 分批迁移 `apps/`、`packages/`、`services/`、`configs/`、`deploy/ops`、`third_party/`；根入口保持兼容 | 每次路径切换的消费者契约、容器 smoke、根包装层和上一 Release 回滚通过 | 同一 PR 同时移动全部路径或运行数据 |
| S18 | 9 | 汇总 Trace、Eval 与 CI：版本化 fixture、固定 runner/catalog、低敏 receipt、模型/ResponsePlan/MCP/Memory/OC/Proactive 维度和可复现 CI 命令 | 双 Python 风险样本、bundle/Contract、Trace 隐私、锁/构建/Compose/secret 门禁通过；完整全仓、Web、镜像/容器和故障矩阵明确交给 S19 | 通过删除安全测试恢复绿色状态，或把合成证据写成真实质量 |
| S19 | 本地总集成 | 汇总所有当前发布必需模块，执行全仓回归、离线回放、30 日调度/Probe no-send 仿真、故障注入、SLO 预注册和发布候选审计 | 发布必需模块完成定义、本地安全门禁、镜像/配置/插件回滚包与冻结 SLO 全部通过 | 真实群发送或用线上流量补本地测试缺口 |
| S22 | 10 | 按 `migration-map.md` 删除十个路径别名和插件专用 iCourse Client；保留仍有消费者的 Handler、Role、Memory、Audit、worker protocol 与根操作入口 | canonical 入口、Unified-only Client、完整 Python 3.12、Python 3.10 抽样、镜像/Compose/package/secret 和精确 S19 归档通过 | 无消费者证据的删除、重设计核心模块或删除明确 retain surface |
| S21 | Bot Control Plane | Tree revision 4 已拆分 S21A Foundation、S21B Group Onboarding、S21C Governed Operations 与 Audit；Bot 入群后管理员选择初始服务 Profile，后续 Console 配置提供初值、合法范围与显式锁定 | 新群 pending 零服务；Profile 不授予 Capability；Desired/Effective 可解释；激活/更新/暂停/回滚具备 auth、Scope、CAS、幂等、Audit、Receipt、LKG 和跨账号/群隔离；Agent 只能在合法范围内自适应 | 浏览器本地权威配置、万能写 API、Agent 直发 NapCat、让模型/Group Context/Plugin/Bandit 开服务或扩权，或把普通管理员偏好误作永久锁定 |
| S23 | 最终真实场景 | S21、本地审计、既定 WebUI 测试和 300 个脱敏窗口的 Web 人工内测纵切完成后，先在隔离环境复用外部长期语料的历史 no-send 结果与人工评测；再在同一授权单群依次执行实时 no-send Shadow、明确 @ Canary、手动日报、定时日报、低频 Probe；每类独立授权/熔断，最后考虑 3–5 群分层放量 | 历史回放无链路异常且质量结论只来自标注样本；Web 候选保持 `providerCalls/outputCalls/memoryWrites/toolCalls=1/0/0/0` 的已测边界且不冒充 Runtime Shadow；重复回复/推送、错误目标、quiet-hour/退订后/未授权发送或 Tool、无引用/过期内容、跨 Scope Memory 和敏感 Trace 为 0；冻结分行为 SLO、kill switch、回滚与复盘全部通过 | 提前上线、把原始历史或 Web 内测反馈直接当质量 Gold/Memory/Bandit reward、一次打开全部主动行为、无指标放量，或在任一发布前置模块未完成时进入真实群 |

S20 不属于上述严格发布主线，已经单独批准并完成离线范围：

| 可选阶段 | 定位 | 本步只实现 | 完成门禁 | 明确不做 |
| --- | --- | --- | --- | --- |
| S20（已完成，离线） | P2 离线学习基础 | 定义 decision/feedback、同 Role+Tier action support、propensity validator、静态 baseline 和合成 IPS/SNIPS/DR golden | 固定输入的 estimator/validator 结果可重放，非法 support/propensity fail closed，并证明无生产执行 hook | 训练、生产 Worker、Shadow/live exploration；权限、Memory Scope、高风险 Tool、Reply/Ignore、主动发送/目标/日程/频率和 Answer Profile 探索 |

达到 S11 算“本地可用直聊版本”，达到 S13 算“本地可用工具闭环”，达到 S15E 算“主动出站
本地 Shadow 完整”，达到 S16 算“离线发布事务骨架完整”。S17、S18、S19、S22 和 S20 的
既定离线范围与 S21 均已完成。下一步只剩暂停的
`S23`；S23 同时受真实环境集成工程和外部输入阻塞，并非拿到授权即可直接运行。S20 Bandit 不是
主动出站或 S23 的前置；既定 QQ Web 客户端测试和 Bot Control Plane 离线闭环均已通过，但不等于
生产环境适配、真实群质量或真实发送已经就绪。

截至 2026-08-15，S23 又完成了候选模型上线前的一段工程纵切：仓库外私有 Provider Evidence
解析已接入 Production Builder，固定 AstrBot 4.26.2 隔离候选启动通过，Luna/Terra/Sol 各完成
一次真实 Provider-level no-send 且零 Output 调用。既有 `BoundedModelHealthPublisher` 已连接
Router 与 Admission，默认关闭的刷新器已聚焦证明成功、超时失败、`UNKNOWN`、TTL 到期和
`terminate()` 取消。这只闭合了候选启动、Provider 可达性和健康状态传播路径；正式 Provider
注册、AstrBot Conformance、运行中部署启用和真实单群 Shadow 仍未完成，因此 S23 继续保持
暂停、部分完成。

截至 2026-08-16，既有 Bot Control Plane 又完成历史语料 Web 人工内测第一版：无需 NapCat 账号即可
进入 `#/internal-test`，在 300 个既有脱敏窗口上检查 Silver、Student、AnswerProfile、Static
Tier 和 Luna/Terra/Sol 映射，并由操作员显式生成一次 Terra `no_send` 候选和追加一次仓库外
人工评价。该纵切实测 `providerCalls=1`、`outputCalls=0`、`memoryWrites=0`、`toolCalls=0`，
反馈文件权限为 `0600`，不保存候选正文、Key 或 Base URL。历史面板只扩展控制后台的
Evaluation Adapter，不改变 Runtime 权威，也不提升 S23 的 `paused/partial` 状态。实时 Agent
Console 则是控制后台的正式配置与观测面；其配置必须由服务端持久化并由 Runtime 在 Core 边界
内解释，不能退化为浏览器本地状态或前端写死选项。

截至 2026-08-17，Agent Console 的 S23 自适应工程纵切已完成：前端从服务端动态 Catalog
加载模型档位、推理强度、回答长度、回复强度、上下文长度（运行预算）、群聊风格与插件事实，
并按 `accountId + conversationId` 保存和恢复 Scope Policy。六项设置保持正交，管理员为各项
配置初值、`allowed[]` 和 mode；`adaptive`、`preferred` 允许 Agent 每轮在合法范围内改选，
只有显式 `locked` 才固定。上下文 `compact/standard/extended` 三档分别为 12/6,000、
30/18,000、60/36,000 条消息/字符的运行预算，而不是模型最大 Context Window；每次 Run 返回
`contextUsage.messageLimit/characterLimit/messagesRead/charactersRead`、六项有效选择、reason
codes 和实际插件状态。回复强度只影响候选决策，不能替代真实发送授权。

旧灰色控件、前端硬编码插件和 SHORT/MEDIUM/LONG 到 Luna/Terra/Sol 的永久映射已移除。
iCourse 是唯一真实 MCP，但与 `gpt-image-2` 均未接入当前 Console Runtime；自动复读只是关闭且
不可用的 Dududa 1.0 历史资产，`/sub2api 自动查询` 仍是仅超级管理员可用、普通会话 Policy
不管理的确定性只读命令，且 Console 执行链未接。被动自动回复实际保持 `rollout_mode=off`、
delivery disabled、kill switch active，主动参与仅 S15E Probe Shadow/`NO SEND`；候选
`outputCalls=0`、`memoryWrites=0`、`toolCalls=0`。校园、arXiv、行业资讯等仍只是预留接口或
fixture，不得描述为真实服务，因此该纵切不改变 S23 整体 `paused/partial` 状态。

单人阶段主动暂停以下范围：第二聊天平台、通用高风险 Tool、自动 Memory 写入、Graph Memory、
主动私聊/个人目标、私人校园 Feed、自动 LONG 推送、模型微调、neural bandit、多 Persona 市场
和任意未治理的 Web 写入口。只有前一里程碑的真实错误证据证明其他暂停项必要时，才把其中一项
加入新的 Spec 和顺序表。

2026-08-14 已确认受治理 Runtime、通用插件生命周期、Group Context、关系证据、Skill 候选演化
和 Bot Control Plane 的长期方向。首个实现范围只取可离线闭环的 S21 控制后台与群服务初始化；
其余能力必须继续拆入后续 Spec，不能塞进 S21 或绕过 S23 门禁。

### S21 Bot Control Plane 建议拆分

| 子步骤 | 本步范围 | 离线退出证据 |
| --- | --- | --- |
| S21A Foundation（已完成） | `GroupServiceProfile/Assignment`、join/pending、Query/Command Envelope、operator auth/RBAC、Projector、Audit/Receipt 和 Fake join/service | 未授权、跨 Bot/account/group、未知 service、stale revision、重复命令和浏览器直写全部 fail closed |
| S21B Group Onboarding（已完成） | pending inbox、Profile Catalog、Desired/Effective diff、Preview/Activate/Update/Pause/Resume/Rollback、immutable Runtime snapshot 和 LKG | 新群缺 Profile 零 Agent 服务；双管理员并发仅一个 revision 生效；失败保持 pending/LKG |
| S21C Governed Operations（已完成） | Run/Model/MCP/Plugin/Memory/Proactive 六面投影；Model 与 MCP/Capability 使用快照，未绑定面明确 unavailable；只发现已有 Group Service Core 命令 | UI 不自行推导权限/状态；Agent Draft/permission/config 无专用命令时不发送、不改状态、不伪成功 |
| S21 Audit（已完成） | 移除 Agent Draft 直发 NapCat、浏览器本地 permission/config 占位；跨账号/群、重启、回滚和构建审计 | 真人 QQ 操作与 Agent Output 分离；Group Context/Plugin/Model/Bandit 无法改变 Assignment 或发送权 |

S21 的实现和验收不依赖聊天正文。Fake join/service/Catalog 是主证据；只有 Connector、历史分页、
Perception 或控制台会话投影发生变化时，才抽样重跑本机 `嘟嘟哒` 私有 replay。外部数百群语料
不得提前进入 S21、Memory 或 Bandit。

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
- Scheduler 只物化 occurrence，未来 MCP Source Adapter 只读取受批准公开来源，Proactive Policy 只决定是否允许进入准备，
  Output Adapter 只投递；任何一层都不能吞并其他层的权限。

### 科学性与研究任务

P0 Research Spike 需要限时：Memory 初次调研 5–7 个工作日，语义理解初次调研
3–5 个工作日。交付物不是综述篇幅，而是可复现数据集、Baseline、实验命令、结果表和
架构 ADR。实验开始前预注册主要指标、数据切分和失败条件；P1 canary 前冻结发布阈值，
不得根据上线结果临时替换指标。

| 研究方向 | 必须比较的基线 | 数据与切分 | 指标 | 选型规则 |
| --- | --- | --- | --- | --- |
| Memory 检索 | S14 先冻结 no-memory、recency、CJK BM25；Embedding/Hybrid 是后续候选 | 当前只用固定合成多平台/Bot/群/私聊/用户/Persona/TTL/tombstone fixture；未来授权集按 conversation/time 切分 | Precision@K、Recall@K、recall-any/all、MRR、binary nDCG、ranking fingerprint 与固定安全机会分母；后续再加 P95/Token/成本 | 合成集五类暴露必须为 0，M2 只在预注册 lexical subset 上证明回归增益；Embedding/Hybrid 必须在授权 held-out 集稳定优于简单基线才允许 shadow |
| Memory 写入 | 全拒绝、仅显式 `/remember`、规则 Write Gate、模型 Candidate + Gate | 敏感、重复、冲突、过期、未送达和确认样本 | 保存准确率、敏感拒绝率、重复率、冲突发现率、删除完整性 | 自动写入保持关闭，直到负向集全过且人工抽检达到发布阈值 |
| 语义理解 | Rules、LLM Structured Output、Rules + LLM Merger | 首版 200–500 条；按完整会话划分 train/dev/test，部分样本双人标注并仲裁 | 标注一致率/κ、Intent macro-F1、Entity span/type F1、Reference exact match、tool-need recall、误插话率、校准误差 | 硬规则违规必须为 0；模型方案需报告置信区间和分层错误，不以单一总体准确率决定上线 |
| 回答档位 | 固定 MEDIUM、规则 Response Policy、规则+模型 hint | TaskComplexity x AnswerProfile 3x3；按完整会话/任务族切分，包含 HIGH+SHORT、LOW+LONG 和明确用户要求 | Profile macro-F1/混淆矩阵、明确要求满足率、可见字符/Token/分片、完整性、事实/引用保持、冗余度 | 长度与 Tier 正交；跨两档错误、硬上限、引用/警告丢失为发布阻断；质量不能仅按字数判断 |
| Router/MCP | 单 Provider、静态路由、带 fallback 路由；每次新建进程与复用 Session | 固定请求、错误注入和并发场景 | Schema-valid rate、成功率、P50/P95、重试、进程创建数、恢复时间和成本 | 未授权路由/Tool 暴露必须为 0；优化不能降低错误可解释性或回滚能力 |
| 主动日报 | no-send、确定性来源排序/模板、候选 Composer | 30 日 fake-clock，本地固定多来源 fixture 的波动/重复/重启/DST/退订/部分失败；不访问真实公开源 | fixture 覆盖、重复率、来源多样性、新鲜度、引用/事实完整率、打扰度、P95、Token/成本 | 错误目标、重复、quiet-hour、退订后、无引用/过期内容和敏感 Trace 必须为 0；真实内容质量等待外部门禁 |
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

S12 已实现统一 MCP Client/Server Registry、隔离 v2 worker 与 iCourse compatibility
facade；S13 已实现 Capability Registry/Retrieval、确定性参考 Planner、Executor、Validator 和
iCourse 公开缓存只读 Provider。Legacy iCourse 路径保留到 S22。主动日报在 S15C 只定义
source-neutral Contract，并使用 Fake Provider 与本地固定 fixture；真实校园、arXiv 和行业
来源 Adapter 不在本轮离线实现中。

### 不变量

- 当前课程命令和输出继续可用。
- iCourse 保持为独立的 Service Package。
- Planner 不能看到不符合条件或高风险的工具。
- Scheduler 不直接调用 MCP；fixture-backed 来源只执行固定只读 Capability Plan，MCP 不拥有订阅或发送。

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

按 Capability 设置 feature flag，并在启动期显式选择 Unified 或 Legacy iCourse。调用失败
不得自动 fallback；只有 S22 证明全部消费者迁移且上一 Release 可独立恢复后，才移除旧
Client/配置兼容面。

## Phase 7.5：主动消息与订阅推送

### 目标

按 S15A-S15E 串行实现独立 initiated-run、主动授权、持久 Scheduler/Subscription/Dispatch、
受治理来源契约、fixture-backed 日报合成和低频 Conversation Probe。完整契约见
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
- fixture 来源提示注入、过期/无引用信息或私人校园数据进入群；未来真实 Adapter 仍需独立门禁；
- `UNKNOWN` Delivery 被盲重发；主动探测打扰用户或形成自动追问。

### 验证

- Fake Clock/Store/Output 的 30 日并发、重启、DST、misfire、pause/unsubscribe 仿真；
- TargetPolicy/Grant Ref 替换与撤销、Preview 独立授权/零投递/正文不落普通 Trace，以及
  Adapter revision 变化和 `UNKNOWN` 恢复时复用 PreparedDispatch/业务幂等键；
- Source-neutral Contract、provenance/freshness/URL/Schema/注入/去重和部分失败测试；
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
ResponsePlan、Memory 隔离回归、Proactive fake-clock/来源/投递指标和导入/分层检查，并把
完整 release-candidate 命令固化进 CI。S18 运行风险分层样本；完整全仓、Web、镜像/容器和
故障矩阵统一在 S19 执行。本阶段不是首次增加领域 Eval。Bandit estimator 与 OPE 只属于
独立可选的 S20，不在本 Phase 汇总或实现。

### 必需的 Eval 维度

回复决策、目标、意图、指代、Answer Profile、工具选择、参数、隔离、结果校验、fallback、
OC 一致性、调度/订阅/来源新鲜度/去重和主动打扰度。Fixture 只能使用合成 ID 以及公开或
合成文本。

### 验证

CI 定义双 Python 单元/契约/集成/Eval、独立 MCP worker、镜像构建、插件安装/导入、
Persona seed、MCP 握手、Compose、仓库扫描和一次性容器 smoke 命令。S18 本地验证
catalog/receipt/Trace、双锁、聚焦 Contract、package、Node 22 build 和真实 Compose JSON；
S19 才执行完整矩阵与实际镜像/容器 smoke。不稳定的模型测试使用确定性 Gateway，或采用
明确的非阻塞 Eval 策略。

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

## 已完成的 Tree 变更

标题：**S21 Bot Control Plane 已完成，S23 离线 Demo、Web 人工内测、候选模型与 Agent 超级工作台工程纵切已完成**

Tree revision 4 已完成以下 S21 变更；此列表保留为完成记录。S23 的 manifest-only readiness、
模板和 [单群验证 Runbook](../operations/s23-real-group-validation.md) 已完成；获授权静态历史
语料的 S23A-S23E no-send Demo 和控制后台 Web 人工内测第一版也已闭环，但不授权任何实时发送
或 Canary：

1. 在 revision 4 中把 `S21A -> S21B -> S21C -> S21 Audit` 加为 S23 的前置；
2. 用 Fake join、Fake services 和固定 Catalog 完成控制后台离线闭环；
3. 证明新群缺 Profile 时零服务，管理员激活具有 auth/Scope/CAS/幂等/Audit/Receipt/LKG；
4. 证明 Profile 不授予 Capability，Group Context/Plugin/Model/Bandit 不能扩权；
5. 移除 Agent Draft 直发 NapCat 和浏览器本地 permission/config 占位；
6. S21 完成审计后，已在 S23 私有环境处理外部长期记录，完成全量本地预测和 600 条 Teacher
   Silver 抽样；下一步以 150–300 条均衡人工 Gold 复核质量，不把 Silver 当 Gold；
7. 候选模型生产装配现可从 AstrBot Context 或仓库外私有文件解析 Provider Evidence，并复用
   bounded health publisher 向 Router/Admission 发布有 TTL 的健康状态；固定 AstrBot 4.26.2
   隔离候选已启动，三模型各一次 Provider-level no-send 通过，默认关闭的刷新器已有聚焦证据，
   但正式注册、Conformance、运行中启用和真实单群 Shadow 尚未完成；
8. 历史语料 Web 人工内测第一版在既有 Bot Control Plane 内完成：无 NapCat 也可浏览/筛选 300 个脱敏
   窗口，展示 Silver/Student/AnswerProfile/Static Tier/三模型映射，显式 Terra 候选保持
   `providerCalls/outputCalls/memoryWrites/toolCalls=1/0/0/0`，反馈只追加到仓库外 `0600`
   JSONL；该历史面板是 Evaluation Adapter，不是第二套 Runtime 或 Live S23 证据；实时 Agent
   Console 是正式 Control Plane，管理员配置初值、合法范围和锁定，Runtime 决定每轮有效选择；
9. Agent 超级工作台自适应纵切已完成：动态 Catalog、Scope Policy，以及模型档位、推理强度、
   回答长度、回复强度、上下文长度（运行预算）、群聊风格六项正交配置已接入前后端。管理员设置
   初值、`allowed[]` 和 mode，`adaptive/preferred` 允许每轮合法改选，只有 `locked` 固定；
   上下文三档预算为 12/6,000、30/18,000、60/36,000 条消息/字符，并返回预算上限与实际读取量。
   插件 `off/auto/on/locked` 及每轮有效选择解释也已接入；当前被动自动回复关闭，主动仅
   S15E Probe Shadow/`NO SEND`，iCourse、`gpt-image-2`、自动复读和 `/sub2api 自动查询`
   均不可由 Console 执行，候选 `outputCalls/memoryWrites/toolCalls=0/0/0`；
10. 历史 Shadow 通过后，冻结授权群、测试用户、发送窗口、SLO 和回滚包；
11. S23 依次执行单群实时 no-send Shadow、明确 @ Canary、手动日报、定时日报、低频 Probe，最后
   才考虑 3–5 群和长时间 Debug。

Bandit 不作为主动出站、群服务 Profile 或 S23 的前置，且禁止探索 send/skip、目标、日程、频率
和 Answer Profile。Web 可以执行写操作，但只能通过专用服务端配置/命令 API；浏览器不能成为
权威存储，也不能提供绕过 Core 权限、Scope、预算和副作用控制的万能配置写 API。

## Phase 验收矩阵

| Phase | 新的权威范围 | 退出前必须新增的门禁 |
| --- | --- | --- |
| 2 | 领域契约/Package | Package/导入/分层测试 |
| 3 | 安全/配置基础组件 | 行为测试和安全负向测试 |
| 4 | AstrBot Adapter/命令 | 插件导入和 Event 契约 |
| 5 | Memory 边界 | 完整隔离和迁移回滚 |
| 6 | Runtime 决策/合成 | 状态、Eval、shadow 无副作用测试 |
| 7 | Capability/MCP Runtime | 有界工具循环和 MCP 契约 |
| 7.5 | 主动消息/订阅推送 | 默认拒绝、fake-clock/持久 claim、Source fixture Contract、无发送 Shadow 和独立回滚；真实来源 Adapter 不在本轮 |
| 8 | 运维/布局/Manifest | 一次性完整生命周期和回滚 |
| 9 | Trace/Eval/CI | 回答档位、主动调度/来源/投递与完整 CI/隐私安全 Fixture |
| 10 | 无兼容依赖 | 无旧消费者，并具备回滚 Release |
| S21 Control Plane | 群入驻、初始服务 Profile、Query/Command 与 governed operations | operator auth/RBAC、Desired/Effective、CAS/幂等/Audit/Receipt/LKG、跨 Scope 和零浏览器直写 |
| 最终真实场景 | 入站、日报、Probe 分行为授权群 Shadow/Canary | 所有前置模块和本地审计完成；冻结分行为 SLO、kill switch、回滚包和授权窗口 |
