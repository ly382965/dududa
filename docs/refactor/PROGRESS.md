# Dududa 2.0 重构进度

更新时间：2026-08-15
历史基线：`main@2767cc9768d4bce63d4b4ee811add951ebce6870`

## 当前结论

- Phase 0–1 的审计、目标设计和迁移计划已完成。
- S01–S22 的既定本地/离线范围均已完成并验证；S19 已闭合本地候选总审计，S22 已按
  消费者与回滚证据清理兼容面，S20 只完成离线 Bandit 契约。S23A–S23E 私有历史语料
  离线 Demo 已完成；S23 整体仍为暂停/部分完成，实时验证尚未开始，分支也未合并。
- 旧 AstrBot Handler 在 `off/shadow` 下仍是权威入口；Canary 只对允许群的结构化显式 @
  取得持久单一所有权。本地发布模块、既定 QQ Web 测试、S21 群服务初始化和总审计已经完成；
  真实 QQ 群运行仍须闭合 S23 环境适配并取得逐行为授权。
- S23 分支已经补齐配置驱动的入站生产 Runtime 最短纵切：实际声明的 1–3 个模型档位经
  AstrBot Provider Adapter、既有 Static Router 和 DirectChat 链装配；默认关闭，`off` 不调用
  Provider，`shadow` 只做一次候选回答调用且不取得事件或发送所有权。当前证据只来自 Fake
  Provider：27 项最终聚焦契约在 1.005 秒内通过，此前 6 项冒烟在 0.196 秒内通过；这不等于
  真实 Endpoint Conformance、部署或上线。
- 2026-08-15 已对 `gpt-5.6-luna`、`gpt-5.6-terra`、`gpt-5.6-sol` 完成 Responses 与
  AstrBot 所用 Chat Completions 的最小真实请求抽样，均返回 HTTP 200、模型 ID 匹配和 usage；
  这只证明协议可达。三个模型尚未注册到当前 AstrBot，现有 Provider 路径也不能透传请求级
  输出上限和动态思考深度，因此 S23 仍无真实 AstrBot Conformance 或持续健康证据。
- 已有 600 条 Terra Silver、137,026 条 Student 预测和私有 Demo 不重跑。若进行新一轮多模型
  校准，采用五小时硬时间盒：20--24 条先测吞吐，Luna 主样本默认 250/最多 350，Terra 复核
  最多 50，Sol 抽查最多 15，T+3.5 小时停止新请求，并按群隔离 train/dev/test。
- 独立可选 S20 不属于主动出站、群服务 Profile 或 S23 的发布前置。
- S04、S06、S07、S14 新路径默认关闭；未迁移、改写或读取生产 Memory。
- 2026-08-09 新增的短/中/长回答已完成 S15 离线机械范围，主动出站已完成 S15A 契约、
  S15B 持久调度、S15C 来源框架/合成 fixture、S15D fixture 日报和 S15E synthetic group
  Probe Shadow；真实来源/群 Projection、持久 Probe state、模型与发送继续作为外部门禁。
- S17 三批 path-only 迁移与旧 lock marker 兼容已经 protected completion 并合入控制分支。
  S18 已实现统一 Eval/Trace/CI，S19 已完成 18/18 本地候选审计；S22 已删除十个路径别名和
  插件专用 iCourse Client，并保留七个仍有消费者的兼容面。Manifest v2 继续因 hash、依赖锁
  和许可证证据不足延期。S20 离线 Bandit 基础已经实现，真实学习/探索未开始。S21A-S21C 与
  Completion Audit 已在 Tree revision 4 完成离线实现和验证。S23 已完成 manifest-only
  readiness、模板、中文 Runbook，以及 S23A–S23E 历史语料 intake/window、Terra Silver、
  本地 Student 和私有 no-send Demo；实时单群阶梯仍未开始。
- 本文是当前实施状态的权威台账；`docs/design/` 保存冻结 Spec，历史基线文档不随实现结果
  改写。完整阶段快照见 [2026-08-10 阶段完成报告](checkpoint-report-2026-08-10.md)，
  待准备输入见 [外部输入清单](external-input-checklist.md)。
- 2026-08-14 形成的
  [受治理自适应 Agent Runtime 长程研究](../research/deepseek-harness-inspired-dududa-evolution.md)
  已被用户确认为长期设计方向，并补充 Web Bot Control Plane 的首要用例：Bot 入群后由管理员
  选择初始 `GroupServiceProfile`。Requirements/Project Spec 已更新，S21 已离线完成。Plugin
  Runtime、Group Context/关系证据/Skill 演化仍未实现，不是现有能力。

“步骤完成”表示该步骤约定的代码、负向测试和退出门禁已通过，不表示产品模块满足统一完成
定义。模块只有具备真实 Adapter、端到端故障/取消/超时证据、生产 feature flag、shadow、
选择性切流和可执行回滚后，才能标记为完成。

## S01–S07 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S01 核心 Package | 已完成 | 可安装 `dududa-agent`、不可变领域 DTO、Runtime State、错误和严格配置；Python 3.10+ | Orchestrator、State Store、生产 Event 接入 |
| S02 契约与 Port | 已完成 | canonical codec/golden vectors、N/N-1 reader、Port binding、Protocol、Fake 和 Contract harness | 冻结仅由 Fake 证明的后续接口 |
| S03 安全基础 | 已完成 | Actor/Scope、默认拒绝 Authorization、Confirmation、Limiter/Budget、Content Safety、Redaction、Audit、幂等和 typed config | 替换旧插件权限入口或改变中文错误文案 |
| S04 Connector/Output | 已完成 | AstrBot Input Connector、Output Adapter、Attachment Repository、Delivery Receipt、引用/@/附件和去重 fixture | 第二平台、真实 Attachment Source、跨 Runtime 原子去重、模型调用 |
| S05 插件拆分 | 已完成 | Core 薄入口、命令/生命周期拆分、TargetTalk/ReplyPolish 纯逻辑；插件 ID、命令、Decorator 和 priority 保持 | 删除旧 Handler、目录迁移、Runtime 切流 |
| S06 Memory 安全边界 | 已完成 | MemoryScope/Selector/Record/Repository、显式 Write Gate、内存/JSON 参考 Adapter、隔离矩阵 | embedding、Graph、Reranker、自动摘要或自动写入 |
| S07 Iris/迁移边界 | 已完成 | fail-closed Iris Protocol Adapter、缺 metadata 隔离区、backup/dry-run/receipt/rollback CLI | 真实 Iris SDK Backend、生产数据迁移、语义检索、Runtime 接入 |

## S08–S11 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S08 静态 Model Router | 已完成 | Haiku/Sonnet/Opus 契约、Registry、硬过滤、流量 admission、容量、fallback、Fake 与兼容 Adapter | Bandit、随机路由、真实多 Provider 效果声明 |
| S09 Perception 与 Tiering | 已完成 | Rule/Model/Merger/Validator、Social Decision、Complexity、TierPolicy、320 条合成/固定 Eval | 人工标签确认、真实群数据校准、多轮与附件语义 |
| S10 Offline Runtime | 已完成 | Connector 到 Delivery receipt 的显式 @ 直聊闭环、两次模型预算、CAS/single-flight、Composition、reconciliation 与 Shadow；S23 分支另补配置驱动的入站生产装配形状 | Tool、Memory、Attachment、真实 Endpoint Conformance/部署和主动群聊 |
| S11 Controlled Rollout | 已完成（本地） | typed mode、白名单、SQLite claim/tombstone、priority-100 AstrBot Bridge、发送前熔断、脱敏指标和回滚 CLI | 未经授权的真实 QQ 群发送、广泛生产切流 |

## S12–S15E 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S12 Unified MCP | 已完成（离线） | framework-neutral DTO/Port、严格 Registry、长生命周期 Client、隔离 v2 worker、iCourse facade 和 Fake/iCourse 同 Contract；S22 已删除专用直连回滚 | 新真实 Server、实时来源、凭据和生产 Tool enablement |
| S13 Capability Runtime | 已完成（离线） | 分离的 Capability Catalog、Retrieval、有限 Planner、逐步授权 Executor、Observation Validator、iCourse 只读映射和配置式 Fake 扩展 | 真实 Planning Endpoint、高风险/写能力、人工语言质量和生产 Tools Rollout |
| S14 Memory Lifecycle/Retrieval | 已完成（离线） | generation-bound 读取、CAS 删除/tombstone、scoped export、archive/restore、JSON v2 crash replay、正式 Retrieval Port、M0/M1/M2、纯 Python CJK BM25 与固定合成 Eval | Runtime/旧命令消费者迁移、真实 Iris、授权数据/人工质量、Embedding/Hybrid、自动写入和生产切流 |
| S15 Response Profile/Persona | 已完成（离线） | SHORT/MEDIUM/LONG Plan、动态预算、Plan/Persona generation checkpoint、typed assets、Catalog CAS/LKG、最终机械 Validator 与 17-case 3x3 Eval | 真实 Provider tokenizer、人工中文/Profile/Persona 质量、最终预算校准和真实 QQ 体验 |
| S15A Proactive Contracts | 已完成（离线） | initiated-run/Target/Grant/Trigger/Subscription/Preview/Dispatch/Receipt v1 契约、当前 Actor 解析、默认拒绝策略、global/Scope quota、metadata-only Preview、稳定幂等、crash recovery、双 Python 590 项全仓测试 | 持久 Scheduler、真实来源、模型合成、生产 Registry/Output、QQ 发送和真实群证据 |
| S15B Durable Scheduler | 已完成（离线） | framework-neutral Scheduler Ports、typed JSON、SQLite Subscription/slot authority、IANA/DST、misfire、CAS/lease/reclaim/ack、暂停/撤销失效、重启/篡改与 30 日 fake-clock 仿真 | 生产 Scheduler 组合、Source、模型、Output、真实订阅与 QQ 发送 |
| S15C Governed Sources | 已完成（离线） | source-neutral policy/provenance/cursor/identity/fetch 契约、原子 cursor/dedup state、严格规范化、三类 manifest-bound 合成 fixture 和第四 Fake Source 配置式扩展 | 真实 Source Adapter/网络、真实许可/时效/内容质量、生产 source database、Composer 与发送 |
| S15D Digest Shadow | 已完成（离线） | digest policy/metadata、确定性 Composer/Builder、LONG -> MEDIUM Plan、no-send COLLECT/SHADOW、隔离 PREVIEW、来源/引用/Persona/长度验证和第 1/2/30 天抽样 | 生产 Scheduler 组合、真实 Source/模型、生产 metadata persistence、Output/Dispatch/QQ 发送和真实内容质量 |
| S15E Probe Shadow | 已完成（离线） | sanitized group projection、deterministic hard gates、短 TTL Opportunity/Trigger/Run、原子 namespaced claim/cooldown、attribution window、no-response 长冷却、固定 SHORT Persona/Validator 和 metadata-only no-send Runtime | 真实 Projection Adapter/聊天、持久 Probe state、人工相关性/打扰度、模型/Tool/Memory/Output、自动追问和 QQ 发送 |

## S16 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S16 Operations Hardening | 已完成（离线） | 标准库 Release Manifest/State/Stage Receipt、只读 Health、SQLite Backup API、校验与确定性 Restore Plan、Upgrade/单次失败回滚、根命令转发、实际 Compose mount/network Contract；共享 Source await 已受 cancellation/deadline 约束 | 真实 Compose/HTTP/MCP Driver、生产备份范围和加密、原地 Restore、真实容器升级/回滚观察、无人值守生产声明 |

## S17–S23 实施状态

| 步骤 | 状态 | 当前证据 | 下一边界 |
| --- | --- | --- | --- |
| S17 Layout Migration | **已完成、已验证、已合并** | Spec `e2cc296`；三批迁移 `8597d70`/`92fd28c`/`6b4ee09`；旧 marker 兼容 `43fe543`；双 Python/canonical/compatibility/Compose/聚焦 Contract 已通过 | 路径别名已由 S22 删除；Manifest v2 继续延期 |
| S18 Evaluation/CI | **已完成、已验证、已合并（离线）** | `daf3111`/`5be566a`/`7e7cbab`/`4cd9ddc`；十个固定 runner、十四维且完整摘要绑定的 catalog、低敏 receipt、内部生成 run ID、真实 phase path Trace、双锁 CI；350 个 bundle case、146 项 focused Contract 与 Python 3.10 风险样本通过 | 完整双 Python 全仓、Web/E2E、镜像/容器、完整故障注入和 SLO/回滚候选审计留给 S19 |
| S19 Local Integration Audit | **已完成（离线候选审计）** | 双 Python 各 651 tests/2 skips、worker 各 2、350-case committed Eval、30 日/故障抽样、Web 108+6、双镜像无网 smoke、39 项 package/static、5 项 Compose、824 文件 secret scan 和两类 rollback 均通过；18/18 固定 gate 由低敏 receipt 绑定 | `s23_ready=false`；真实 Provider/source/QQ/人工质量仍是外部门禁；18 项 S22 清单为 10 remove candidate、7 retain live、1 blocked unknown |
| S22 Legacy Cleanup | **已完成、已验证、已合并** | `88ec307` 删除十个别名并切换 canonical 消费者；`9f0ae9a` 删除专用 iCourse Client；`715ce5d` 完成控制分支合并；Python 3.12 651/2 skips、Python 3.10 风险样本 32/2 skips、无网镜像/Compose/package/secret 通过 | Manifest v2 和明确 retain surface 不在本阶段 |
| S20 Offline Bandit | **已完成（离线）** | Framework-neutral DTO/digest、Router-planned baseline、完整动态 action support、执行/反馈绑定、propensity fail-closed、Decimal IPS/SNIPS/DR/ESS、4 样本固定 bundle 和 16 项双 Python聚焦测试通过 | 无训练、生产 Worker、Router/Runtime hook、Shadow/live exploration 或真实质量声明 |
| S21 Bot Control Plane | **已完成、已验证（离线）** | operator session/RBAC、Profile/Assignment、pending/managed、Desired/Effective、完整生命周期、SQLite LKG/重启恢复、不可变 Runtime snapshot、六面运维投影、统一 command ID、写锁后 deadline 重验和 Python→Node→Vue 查询链均有证据；Agent 占位不发送或伪成功 | 生产 HTTP/身份、真实健康、Provider/Source/Projection/Output、人工质量和真实 QQ 留在 S23 外部门禁 |
| S23 Real Group Validation | **暂停、部分完成；离线 S23A–S23E 与入站 production shape 已完成** | 1,402 个文件、155,567 条唯一群消息、137,026 个窗口；600 条 Terra 抽样得到 592 草稿/8 Review，464 条编译 Silver；群隔离 Student 完成全量预测和 localhost no-send Demo；配置驱动 Builder 已用 Fake Provider 聚焦验证 `off/shadow/fallback`；Luna/Terra/Sol 两种协议最小探测均成功 | 优先补 150–300 条类别均衡人工 Gold；在 AstrBot 注册三模型、修复动态参数透传并完成 Provider Contract/健康观测；真实部署、实时单群 Shadow/Canary、来源和发送仍保持关闭 |

## 产品模块完成度

| 模块 | 状态 | 判断依据 |
| --- | --- | --- |
| 核心 Package | 部分完成 | Package、DTO、Orchestrator、CAS Store、Delivery/reconciliation、Shadow、rollout Ports 与配置驱动入站装配形状已完成；仅有 Fake Provider 聚焦证据，真实 Endpoint/Tool/Memory/Attachment 全能力未完成 |
| 安全组件 | 部分完成 | 授权、预算、内容安全、隐私、持久 claim 和发送前熔断已贯穿 S10/S11；旧命令兼容权限仍保留 |
| Connector / Output / Attachment | 部分完成 | AstrBot Connector/Output、持久 rollout 去重、Bridge 和发送 tombstone 已完成；真实附件读取和第二平台未完成 |
| Memory | 部分完成 | S14 离线生命周期、删除/恢复、词法检索和合成安全/质量回归已完成；生产仍默认关闭；真实 Iris、Context Builder/旧命令迁移、授权数据人工 Eval、Embedding/Hybrid、shadow 与生产读写未完成 |
| 插件拆分 | 部分完成 | 源码拆分、priority-100 rollout handler 和镜像内 43/1/1 registry 已验证；旧 Handler 按回滚设计继续保留 |
| 模型路由、语义理解、OC Runtime | 部分完成 | S08/S09、S10 最小 Composer/Renderer 与 S23 配置驱动 AstrBot Provider→Static Router→DirectChat 纵切已实现；Perception 首版为 rule-only，避免每条 Shadow 消息发生第二次模型调用；Luna/Terra/Sol 直连协议抽样成功，但尚未注册到 AstrBot，动态思考深度/输出上限未透传；真实 Endpoint Conformance、人工质量、完整 OC 资产和多轮能力仍待 Eval |
| 回答档位 / ResponsePlan | 已完成（S15 离线范围） | SHORT/MEDIUM/LONG 与 Tier/Reasoning 正交，动态预算、Runtime/Composer/Persona/Delivery 绑定和 3x3 合成 Eval 已通过；真实体验仍待外部门禁 |
| Unified MCP / Capability Runtime | 已完成（离线） | S12 Unified Client/Registry、独立 worker和 iCourse facade；S22 已删除专用直连 Client，缺失时 fail closed；S13 Catalog/Retrieval/有限 Planner/Executor/Validator 和四个只读映射均有本地证据 | 生产 Tools 仍关闭，真实 Planner Endpoint、新 Server 和在线来源未实现 |
| 主动消息/订阅推送 | 部分完成（S15A-S15E 离线链完成） | initiated-run/默认拒绝、持久 Scheduler、受治理来源、fixture 日报和 synthetic group Probe no-send Shadow 已实现；Preview/Shadow state 隔离，普通 metadata 无正文；S19/S22 本地发布闭环完成 | 生产 Projection/Source/持久 Probe state/模型/Output、人工体验和真实发送仍待 S23 |
| Bandit | 离线基础已完成（S20） | 决策、执行、延迟反馈、完整 support、propensity/OPE 和合成 Golden 已完成；当前仍无配置或生产执行 hook，禁止学习主动 send/skip、目标、日程、频率和 Answer Profile |
| 可组合插件 Runtime | 设计方向已确认、工程未开始 | 已确认“不可卸载治理内核 + 可逆、分 Realm 能力插件”；尚无 Plugin Descriptor/Lifecycle Runtime、迁移或验证证据 |
| Group Context / 关系证据 / Skill 演化 | 设计方向已确认、工程未开始 | 已确认群级弱先验、Memory、关系证据、候选 Skill/Prompt/Style 与 Bandit 分权；尚无 DTO、Projection、候选流水线、授权数据或 Eval |
| Mew/NapCat WebUI / Bot Control Plane | QQ 客户端与 S21 离线范围已完成 | Web 已提供群服务初始化与运行状态视图；Desired/Effective、Assignment、Receipt 和运维健康均来自 Core DTO。Agent 草稿直发 NapCat 已移除，permission/config 占位为无事件只读状态 | 生产 Core HTTP/operator identity、真实 Agent Run/健康数据和授权 QQ 操作仍未完成 |
| 真实群聊放量 | S23 离线历史语料 Demo 与入站 production shape 已完成，实时运行未开始 | 获授权静态快照已完成确定性处理、600 条 Silver 抽样、群隔离 Student、137,026 条预测和私有 no-send Demo；Builder 的 `off/shadow/fallback` 只用 Fake Provider 验证 | 先补 150–300 条均衡人工 Gold；真实 Endpoint、部署、实时授权、发送、来源和 Canary 继续后置 |

## 2026-08-14 长程设计整合状态

| 方向 | 当前状态 | 状态边界 |
| --- | --- | --- |
| 插件组合与生命周期 | 设计方向已确认、实现未开始 | 治理内核不可卸载，能力插件具备 Descriptor、Realm、generation、disposer 和 LKG；未建立 Runtime 或迁移现有 Registry |
| 群服务初始化 | S21A/S21B 已完成（离线） | Bot 入群后进入 pending，管理员选择版本化 `GroupServiceProfile`；Profile/Assignment、命令、SQLite Store、Projector、LKG 与 immutable Runtime snapshot 已实现 |
| 群体情境与社会学习 | 设计方向已确认、实现未开始 | Group Context 只作为带 TTL 的群级弱先验，关系仅保存可撤销证据；不能修改群服务初值；尚无真实群数据、Projection 或效果证据 |
| Skill/Prompt/Style 候选演化 | 设计方向已确认、实现未开始 | 模型只能提出候选资产，不能自动发布或开服务；尚无 lineage、离线 Eval、人工审批和回滚流水线 |
| Bandit 在线学习 | S20 离线基础完成，在线未开始 | 只允许在安全等价合法候选间排序；没有真实 action support、before-action propensity、反馈 join、Shadow 或探索 |
| Bot Control Plane | S21 已完成（离线） | Web 是统一控制后台，查询来自权威投影，写入经过专用 Core Command；Query/Command、operator auth/RBAC、Audit/Receipt、群入驻、六面运维投影和完成审计已实现，未绑定数据源明确 unavailable |

上述方向已写入根 Requirements/Spec。Tree revision 4 已完成 S21 的离线实现；Plugin Runtime、
Group Context 与 Skill 演化仍没有实现证据。S23A–S23E 离线里程碑已完成，S23 整体仍等待
实时环境适配和逐行为授权。

## 2026-08-15 S23 私有历史语料 Demo

| 项目 | 结果 |
| --- | --- |
| Intake / Window | 1,402 个输入文件，155,567 条唯一群消息，39 个群产生 137,026 个 3–12 条 past-only 窗口 |
| Teacher 抽样 | Terra 固定 Teacher；600 条分层窗口占全量约 0.44%；592 个结构化草稿、8 个请求阶段 Review，P50/P95 为 11.325/22.860 秒 |
| Silver 编译 | 464 条达到 0.65 最低置信度和结构/引用条件；217 条进入编译 Review；Teacher 仍是 Silver，不是人工 Gold |
| Student | 23 群/343 条训练，6 群/121 条测试；指标仅为 held-out Silver agreement，类别偏斜明显，不接生产 Router |
| 全量产物 | 137,026 条本地预测；300 条样本私有 Demo 可由 `http://127.0.0.1:8766/` 查看 |
| 明确未做 | 无 QQ 发送、Tool 调用、Memory 写入、生产路由、在线 Bandit、实时 Shadow/Canary、日报或 Probe |

详细报告见 [S23 私有历史群聊离线 Demo 报告](s23-private-corpus-demo-2026-08-15.md)。

## 2026-08-15 GPT-5.6 Endpoint 抽样与时限

| 项目 | 当前结论 |
| --- | --- |
| Responses API | Luna/Terra/Sol 均 HTTP 200；延迟分别为 2.212/2.816/2.698 秒，模型 ID 匹配且有文本和 usage |
| Chat Completions | 三模型普通请求和 `reasoning_effort=low` 均 HTTP 200，模型 ID 匹配且有 usage，约 2.2--2.3 秒 |
| 证据边界 | 只证明单次协议可达；不等于 AstrBot Provider Contract、Conformance、持续健康、质量或上线 |
| 当前 AstrBot | 只注册 DeepSeek V4 Pro/Flash 与 GPT-5.5；Luna/Terra/Sol 尚未注册 |
| 参数缺口 | 当前 AstrBot payload 组装不透传 Dududa 请求级输出上限或动态思考深度；静态 Provider 初值不能替代动态路由参数 |
| 下一步 | 注册三模型并确认 Provider ID -> 修复参数透传 -> 完成 Contract/Conformance 和健康刷新 -> 配置 Luna/Haiku、Terra/Sonnet、Sol/Opus -> 单群 Shadow |
| 数据预算 | 不重跑现有语料 Demo；新一轮最多五小时，Luna 120--350、Terra <= 50、Sol <= 15，T+3.5 小时停止新请求 |

完整运行边界与时间表见 [S23 单群真实场景验证 Runbook](../operations/s23-real-group-validation.md)。

## 2026-08-11 S23 manifest-only 准备证据

| 门禁 | 当前结果 |
| --- | --- |
| Manifest | 严格 JSON、重复键/未知字段拒绝；release/SLO/Target/SecretRef/Endpoint/Source/Projection/Schedule/Grant 以引用和 digest 绑定 |
| 时间与阶段 | IANA timezone、授权/读取/Grant 时间顺序、七日读取上限、前序 Receipt、Shadow/Inbound/Digest/Probe/Closeout 独立约束 |
| 证据边界 | 输出区分 `manifest_ready` 与真实授权，固定 `validation_scope=manifest_only`、`live_execution_authorized=false`；不解析 Secret 或回显私有引用 |
| 运维文档 | [S23 单群真实场景验证 Runbook](../operations/s23-real-group-validation.md) 固定 Preflight、逐级人工晋级、停止/回滚和 Closeout 顺序 |
| 聚焦验证 | Python 3.10.20/3.12.13 各 8 项通过；Ruff/format、compile、模板 exit `2` 和低敏报告通过 |
| 未声明范围 | 上述证据不等于历史语料 Demo 或实时验证；真实发送、来源和 Canary 均未开始 |

## 2026-08-10 S22 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 路径切换 | 十个 symlink 全部删除；CI、测试、Spike、管理脚本和当前文档只消费 canonical 路径；根 `manage.sh`/`compose.yml` 保留 |
| iCourse Client | 插件内 MCP SDK stdio/逐调用进程、`LegacyICourseClient` 和 `icourse_mcp_mode` 已删除；仅剩 Unified 或稳定 unavailable facade |
| 明确保留 | Rollout `LEGACY` owner、`LegacyRolePolicy`、`JsonMemoryRepository`、worker `protocol_mode=legacy` 和 AstrBot `AuditLog` 均有消费者证据 |
| Python | 3.12 完整仓库 651 tests OK/2 skips；3.10 S22 风险样本 32 tests OK/2 skips；worker 2 tests、根 worker/Capability 11 tests 通过 |
| 镜像与构建 | AstrBot 镜像 `sha256:ca19ef...c5c0a` 在无网/只读模式证明实际 Unified 组合、MCP 1.29/2.0 隔离和 19 项插件测试；wheel/import/pip check 通过 |
| 运维与安全 | 根/canonical Compose 逐字节等价，contract digest `sha256:305745...f0da`；824 文件 secret、双锁、Shell、compile、JSON、import boundary 和 whitespace 通过 |
| 回滚 | 精确 S19 `e303dc8` archive SHA-256 `80500b51...dc77`，mode 0600；完整矩阵见 `s22-removal-matrix.md` |
| 未重复范围 | Web、完整 Eval 和 30 日矩阵沿用 S19 证据；S22 未修改这些表面 |

## 2026-08-10 S18 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| Eval catalog | 严格 JSON 只允许十个固定 runner，覆盖十四个维度；任意 callable、Shell、路径和环境值均不可配置 |
| Bundle/Contract | Python 3.12 四套提交 bundle 共 350 个合成 case，加五套 focused Contract 共 146 项通过；所有质量报告保持 `release_ready=false` |
| Python 3.10 | 四套 bundle、30 项受影响 receipt/Trace/Runtime/Delivery/仓库契约通过；独立 MCP worker 2 项禁网测试和根 Contract 11 项通过 |
| Trace/receipt | Runtime 记录 append-only、canonical digest、无正文的 phase event；失败也写 0600 receipt，Schema 禁止命令、绝对路径、环境、凭据和真实标识字段 |
| Catalog/身份绑定 | 完整 catalog canonical digest 固定在代码中，revision/claim/gate/profile 篡改均在执行前拒绝；run ID 仅由 runner 随机生成 |
| 构建/CI | 双 root/worker lock、wheel 干净安装/import/pip check、Node 22 typecheck/build、真实 Compose JSON contract、YAML、Ruff、compile、secret 与 whitespace 通过 |
| 证据边界 | S19 已完成双 Python 各 651 项、Web/E2E、镜像/容器、故障抽样、SLO 与回滚包；真实质量和 S23 行为未据此升级 |

## 2026-08-10 S16 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 发布事务 | Manifest、current/previous State、逐阶段 Receipt 分离且 digest-bound；Health 成功前不提升 target |
| 数据恢复 | 普通文件与 WAL SQLite 一致性 Backup、篡改拒绝、两次一致 Restore Plan、显式空目标恢复通过 |
| 故障回滚 | target Health 失败后只回滚一次；previous pointer 不变，失败 Release、Backup 和 Receipt 保留 |
| 部署边界 | 根 Shell 按需探测 Docker并原样转发退出码；实际 Compose JSON 的 loopback、mount、network Contract 通过 |
| 抽样测试 | Python 3.10/3.12 各 4 个 S16 场景和 1 个阻塞 Reader 样本通过；Python 3.12 受影响 Source 模块 9 项通过；Web/全仓按加速策略留到 S19 |

## 2026-08-10 S15E 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 群级 Detector | 只接受 sanitized group window；PUBLIC、最小静默、最大 topic age、近期 Bot 和八类 interruption blocker 先于候选构造判断 |
| Opportunity/SHORT | Snapshot、Trigger、Run 的 Scope/TargetPolicyRef/TTL 精确绑定；候选固定 SHORT、单 block、无 @/target user/attachment |
| 原子状态与反馈 | 同 Scope 两个并发 claim 仅一个 ACQUIRED；duplicate、普通 cooldown 边界通过；no-response 必须有 attribution digest 且观察窗口结束后才进入更长冷却 |
| no-send 边界 | COLLECT/SHADOW 无 Output/Dispatch/Scheduler/Memory/Tool/Capability/model/follow-up；metadata 无 topic summary、正文、群号和用户 ID 字段 |
| 抽样测试 | Python 3.10.20/3.12.13 各 6 个 S15E 场景通过；Python 3.12 受影响 import suite 13 tests 通过；第 1/2/30 天保持一个候选、零发送 |
| 构建与边界 | 11 个改动文件 Ruff/format、compileall、uv lock、wheel、focused secret 和 whitespace 检查通过；Web/全仓按加速策略跳过 |

## 2026-08-10 S15D 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 日报候选链 | Source Batch -> MEDIUM `ResponsePlan` -> Composer -> Persona Renderer -> 最终 Validator 已闭合；LONG 订阅显式收窄，不改变 Model Tier |
| 无发送边界 | COLLECT 零 Source；SHADOW 无 Output/Dispatch/Scheduler ack/Memory/model/network；普通 metadata 只保存 digest、状态和 reason code |
| Preview 与去重 | 现有 Preview 服务保持授权 Owner；Producer 使用独立 namespace，不消费正式 cursor/dedup，不创建 occurrence、dispatch 或 delivery receipt |
| 时间与重复 | Source 前重验 Trigger；第 1/2/30 天代表样本只在首日产生候选，重复条目均为 no-op |
| 抽样测试 | Python 3.10.20/3.12.13 各 6 个 S15D 场景通过；Python 3.12 受影响套件共 18 tests 通过；未改 Web 和全仓回归按加速策略跳过 |
| 构建与边界 | 11 个改动文件 Ruff/format、compileall、uv lock、wheel、focused secret 和 whitespace 检查通过 |

## 2026-08-10 S15B 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 调度与持久状态机 | Subscription create/update/pause/resume/revoke CAS、跨 revision local-date 唯一 slot、READY/CLAIMED/EMITTED/SKIPPED/INVALIDATED、稳定 materialization/claim/ack receipt 均已实现 |
| 时间语义 | New York、Berlin、Lord Howe 的 normal/fold/gap round-trip 测试通过；gap 固定 tombstone，fold 取最早 UTC，未来任务不物化，过期 misfire 不补发 |
| 并发与恢复 | 双 SQLite 实例只有一个 live claim；同 worker 幂等、lease 过期递增 reclaim、旧 claim ack 拒绝、重启 exact ack 与持久行篡改拒绝通过 |
| 30 日 fake-clock | 30 个 occurrence、30 个 emitted、零重复 slot、零过期补发；重复 tick 和时钟回拨不恢复终态 |
| 双 Python | 3.10.20 与 3.12.13 各 `601 tests OK`、2 个既有 AstrBot-only skip；各自 29 项 Proactive/Scheduler `-W error` 聚焦套件全过 |
| 构建与边界 | changed-file Ruff/format、compileall、uv lock、sdist/wheel 安装/import/pip check、782 文件 secret scan、Shell/CLI/Compose/whitespace 全过 |
| unchanged Web | 66 frontend + 42 server tests、typecheck、production build 和 production dependency audit 通过；未扩建 Control Plane，未修改运行中的 NapCat/AstrBot 容器 |

## 2026-08-10 S14 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 生命周期与检索实现 | generation/time-bound read、CAS delete/tombstone、scoped export、archive/checkpoint restore、JSON v1/v2、Iris unsupported、M0/M1/M2 focused suites 已通过 |
| 固定合成 Eval | 8 cases、56 live records、8 tombstones、同一 state revision 9；normal/reverse/fixed-shuffle ranking fingerprint 一致 |
| 安全机会 | 每个策略的 cross-Scope、future-created、expired、tombstoned、Restricted 分母均为 8，暴露事件均为 0，并记录合成机会的一侧 95% 上界 |
| 词法回归 | 预注册 7-case lexical subset 上 M2 binary nDCG@K `1.0`，M1 `0.0`；只作 synthetic regression，不作真实中文质量声明 |
| 双 Python | 3.10.20 与 3.12.13 各 `521 tests OK`、2 个 AstrBot-host-only skip；各自 50 项 Memory/Eval/Iris/import `-W error` 聚焦套件全过、零 skip |
| 构建与边界 | changed-file Ruff/format、compileall、uv lock、sdist/wheel 安装/import/pip check、729 文件 secret scan、Shell/CLI/Compose 和 whitespace 全过 |
| unchanged Web | 66 frontend + 42 server tests、typecheck 和 production build 通过；未扩建 Control Plane，未运行或修改 NapCat/AstrBot 容器 |

## 2026-08-04 S08–S11 验证证据

| 门禁 | 结果 |
| --- | --- |
| Python 3.12 / 3.10 全仓 | 两个版本均 Pass：350 tests，宿主机各有 2 个 AstrBot-only skip |
| Runtime/rollout warnings-as-errors | 两个版本均 Pass：109 tests |
| S09 Eval | 320 条版本化合成/固定数据集通过策略回归；人工确认仍为 false |
| 静态与边界 | Ruff、独立首次导入、Bandit 禁止扫描、WebUI/Sub2API 历史 scope 扫描通过 |
| Python / Shell / Compose | compileall、Shell syntax、两个 CLI `--help`、Compose parse 通过 |
| 仓库安全 | safety scan Pass：372 files；`git diff --check` 通过 |
| 派生 AstrBot 镜像 | `dududa/astrbot@sha256:a72637301a6df1fe2a120a7ed3cb77406999e4c7f69f878ed64887d2d2d1ec09` |
| 镜像插件 smoke | `--network none` 下 19 tests 全通过；Core registry 43 handlers、rollout priority 100 |
| 镜像 Package | `dududa-agent==0.1.0a1`、`dududa.rollout` 可导入、`pip check` 通过 |

完整要求到证据映射见 `s08-s11-completion-audit.md`。

## 2026-08-02 S01–S07 验证证据

| 门禁 | 结果 |
| --- | --- |
| 宿主机完整测试 | Pass：116 tests，2 个仅因宿主机无 AstrBot 跳过 |
| Python 3.10 动态测试 | Pass：同一干净 wheel 安装后 116 tests，2 个 AstrBot-only 跳过 |
| 静态导入与格式 | Pass：Ruff check；80 个 S01–S07 Python 文件无需再次格式化 |
| Python 编译 | Pass：Package、插件、服务、脚本和测试 |
| Shell | Pass：`manage.sh`、`setup_dev.sh`、iCourse setup/start 脚本 |
| Compose | Pass：解析后只有 `astrbot`、`napcat` |
| 仓库安全扫描 | Pass：216 个 tracked/untracked 文件，无凭据或运行数据 |
| 干净 wheel | Pass：`dududa-agent==0.1.0a1`；根包加 55 个子模块可导入；含 `py.typed`，不含 `.pyc`；`pip check` 通过 |
| Memory 迁移入口 | Pass：脚本 mode `100755`、`--help`、4 个 apply/rollback fixture |
| 派生 AstrBot 镜像 | Pass：无缓存重建；镜像 ID `sha256:9a8831c8cbca26d21b797db398a4b8d241d2c324b41c61fc868d968acb036e9d` |
| 镜像 Package | Pass：Python 3.12、`dududa==0.1.0a1`、55 个子模块、`py.typed` 和 `pip check` |
| 镜像 AstrBot 测试 | Pass：6 tests，无 skip；Core / TargetTalk / ReplyPolish registry 为 `42 / 1 / 1`，`natural_course_query` priority 为 8 |
| iCourse MCP | Pass：`--network none` 下发现 10 个工具，空库 `icourse_stats` 成功 |
| 干净启动 | Pass：隔离网络、随机端口和一次性数据目录中启动 AstrBot 4.26.2，并加载四个自研插件；实例和临时网络已清理 |
| 空白检查 | Pass：`git diff --check`；另对未跟踪的 S01–S07 交付范围执行尾随空白扫描 |

镜像构建从 digest-pinned AstrBot 基础镜像开始，但 iCourse 的开放版本依赖仍会在线解析；上表
记录本次产物证据，不把它描述成完整的供应链锁定。

## 已收紧的边界

- 所有 55 个子模块可以作为首次导入，顶层惰性导出不再产生循环依赖。
- 核心 Package 只依赖 Python 标准库和内部模块，不导入 AstrBot、模型、MCP 或 Iris SDK。
- Runtime、canonical/binding、Security、Connector/Output/Attachment 和 Memory 的 digest、
  Scope、权限、幂等、deadline/cancellation 与不可变集合均有负向测试。
- 多角色授权不能把一个角色的 permission 与另一个角色的资源约束拼接；
  `SecurityConfig.role_constraints` 是 v2 严格配置的必填映射，缺失或不匹配默认拒绝。
- Memory 等待会响应 deadline/cancellation；Iris 后端写入被取消时回滚本地 record、
  decision 和 idempotency 状态。
- JSON Memory 临时文件使用独占、no-follow 创建；预置 symlink 不会覆盖其目标。
- Attachment 有界流在 token 或调用任务取消后回收 `__anext__` 子任务。

## 残余边界

1. **真实群验证延期到最终阶段。** S11 已有本地 Bridge/Shadow/Canary/kill switch 证据，S21
   控制后台和群服务初始化离线审计也已完成；现在仍须先闭合 S23 环境适配和逐行为授权。
   独立可选 S20 不属于该发布前置。
2. **Attachment Actor 绑定不完整。** `AttachmentAccessRequest` 没有独立 `Actor` 字段；当前
   只能验证 `AuthorizationDecision.actor_digest`，Repository 没有第二份当前 Actor 做交叉核对。
3. **去重分层。** S10 Runtime Store 证明同进程 CAS/single-flight；S11 SQLite rollout ledger
   证明跨进程 claim 与发送 tombstone。通用多平台持久 RuntimeState 仍未实现。
4. **真实附件读取未实现。** AstrBot 组合层使用 fail-closed `RejectingAttachmentSource`，不会
   静默丢弃或越权读取附件。
5. **真实 Iris 未接入。** 当前只有 `IrisBackend` Protocol、fail-closed Repository 和 Fake
   Backend 契约测试；仓库没有 Iris SDK 实现。
6. **生产 Memory 不变。** 旧 `/remember` 仍写旧 JSON；Memory v2 自动读取/写入均关闭，迁移
   CLI 只允许离线显式执行。S14 的 synthetic M2 `Recall@K=1.0` 只证明固定 lexical fixture，
   不证明真实中文质量或生产可启用性。
7. **Hook 证据分层。** 宿主机两个 AstrBot 测试会 skip；真实 Hook 证据来自本次重建镜像，
   不能把宿主测试与镜像 smoke 合并成同一结果。
8. **三档回答已完成机械契约。** 不得把长回答映射 Opus 或短回答映射 Haiku；当前
   `ResponsePlan` 和 Validator 证据不等于真实中文质量、Persona 风格或最终预算已校准。
9. **主动出站离线链完成到 S15E。** 定时器和 Probe Detector 只产生结构化 Trigger，不伪造
   用户消息；MCP 不拥有订阅、调度或发送。S15D/S15E 只构造 no-send 候选，不能证明真实来源、
   群话题相关性、生产持久化、生产组合或真实群发送已存在。
10. **Bandit 只完成离线数学与证据契约。** S20 没有 Router/Runtime/AstrBot hook，也没有
    真实 Endpoint、propensity 日志、训练、Shadow 或探索；固定四样本只能证明 estimator 和
    support validator 可重放。

## 下一步

S17–S22、S21 和 S23A–S23E 离线范围均已完成。下一步若以质量为先，先建立 150–300 条
类别均衡的人工 Gold，复核 Tool、复杂度和 AnswerProfile；若进入实时阶段，则从单群 no-send
Shadow 开始，并继续等待 Provider/Source/Projection/Output 环境适配和逐行为授权。实时
“入站 Shadow -> 明确 @ Canary -> 手动日报 -> 定时日报 -> 低频 Probe”不得跳级。Bandit
不是主动链路或群服务 Profile 前置，也不得对主动行为开启探索。

后续分支采用风险分层验证：优先运行受影响 Contract、聚焦 warning-as-error 与抽样仓库回归；
只有跨模块高风险变更或 S19/最终总集成才重复双 Python 全仓，避免每个 Sxx 重复执行同一套
600 余项测试。

## 历史基线

2026-07-18 的 Phase 0–1 基线为 8 tests、Compose 两服务、六个锁定第三方插件、派生镜像和
网络禁用 MCP 握手通过。该结果保留在 `baseline.md`，只用于比较，不再代表当前实现状态。
