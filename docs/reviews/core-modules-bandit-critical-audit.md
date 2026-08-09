# 核心模块深度审计与 Contextual Bandit 接入方案

审查日期：2026-08-08

审查基线：`4c6686bab559be1ffe0e66de0860828e44876678`

范围：模型路由器、Memory、MCP、输入 Connector、语义理解、OC/Persona、WebUI，以及新增的
实时学习/Contextual Bandit 技术栈。

相关审查：[`dududa20-prototype / plugin 兼容性审查`](./dududa20-prototype-plugin-review.md)。

## 1. 结论

当前 S01-S11 不是直接照半成品文档生成的空壳。Router、Perception、Memory 安全边界、
Connector/Delivery 和 Rollout 都有独立实现、严格 DTO、失败语义、取消/超时处理和负向测试，
明显超过协作者 prototype 的实现质量。

但“不是 vibe coding”不等于“核心模块已经完成”。当前更准确的问题是：

> **契约和本地测试做得很深，生产装配、真实 Backend、独立数据和效果验证做得很浅。**

主要批评如下：

1. 新 Runtime 没有生产 composition root。`install_rollout_runtime()` 在仓库内没有调用者，
   插件启动后 `rollout_bridge` 仍为 `None`；S08-S11 目前主要存在于 Package 和测试中。
2. 即使现在补上装配，首个 AstrBot Provider 也无法被 Router 正常选择：Runtime 固定发送
   `temperature=0`，Adapter 明确声明不支持 temperature；Adapter health 永远为 `UNKNOWN`，
   Router 又把 `UNKNOWN` 当不可用。
3. Memory v2 的 Scope/WriteGate 做得深，但生产 `/remember` 仍直接写 legacy JSON，完全没有
   经过新 Repository 和 WriteGate。它是“安全边界完成”，不是“Memory 产品完成”。
4. iCourse MCP Server 确实可用，但 Unified MCP Client、Server Registry、Schema cache、
   持久 Session、统一错误/熔断均未实现。当前每次调用仍新建子进程和 Session。
5. S09 的 320 条 Eval 是同源合成策略回归。输入、模型 fixture 和 gold 来自同一模板/生成器，
   不调用真实模型，也没有人工标签；它不能证明真实意图/实体识别质量或 Tier 选择正确性。
6. OC 目前只有一份 43 行人格文本和一个保持内容不变的确定性 Renderer。安全骨架可用，
   但风格产品化、版本资产、盲评和多场景表现尚未完成。
7. Web 的 QQ 多账号工作台已经做深；Agent Console 仍是未连接界面，不是 Trace/Eval/Model/MCP
   测试控制台。不能把两者合并标记为“WebUI 完成”。
8. Bandit 设计文档较深入，但代码实现为 0，且当前没有稳定生产 Router、第二个合法 Endpoint、
   durable before-action log 或可靠质量反馈。现在直接开启探索只会产生不可评估的随机路由。

因此，当前可以称为“本地深度基础设施完成”的是 S01-S11 约定范围；不能称为“全部核心模块
产品完成”，更不能直接进入真实群放量。

## 2. 完成度矩阵

| 模块 | 做深的部分 | 主要缺口 | 当前判定 |
| --- | --- | --- | --- |
| 模型路由器 | 三 Tier、Endpoint Descriptor、硬过滤、预算/容量、retry/fallback、receipt、取消清理 | 生产装配缺失；AstrBot temperature/health 与 Router 不兼容；无真实多 Provider 证据 | **库级深度完成，产品未完成** |
| Memory | Scope/Selector、Repository、WriteGate、JSON、fail-closed Iris Protocol、迁移/回滚 | 真实 Iris SDK、Runtime Context 接入、检索 Eval、删除/导出闭环；生产命令仍绕过新路径 | **安全边界深，产品能力浅** |
| MCP | iCourse Server、SQLite、10 个工具、现有命令可用 | Unified Client/Registry、持久 Session、allowlist、Schema cache、统一超时/熔断、Agent Tool Runtime | **服务可用，统一集成未开始** |
| 输入 Connector/Output | Actor/Scope、@/引用、附件 Repository、Delivery 状态、去重、发送前 guard | 新 Runtime 未装配；真实 Attachment Source 关闭；无第二平台和真实群 Delivery | **契约深，生产接线未闭合** |
| 语义理解 | Rule/Model Schema、整包 Validator、Merger、Complexity、Social Gate、TierPolicy | 同源合成 Eval、无真实模型/人工标注/校准、多轮和附件语义 | **安全与策略深，实证浅** |
| OC/Persona | Fact/Citation/Refusal/Target 保持、Render Validator、内容安全绑定 | 只有单 Persona 和 pass-through Renderer；无风格变换、资产 digest 发布、Golden/盲评 | **最小安全骨架完成** |
| WebUI | Mew/NapCat 多账号 QQ 工作台、消息/联系人/群管理、缓存隔离和大量测试 | Agent Console 未连接；无 Runtime Trace/Eval/Model/MCP/Bandit 只读 API | **QQ 工作台完成，Agent 测试 UI 未完成** |
| Bandit | 决策/反馈/OPE/安全边界设计文档 | 无代码、存储、训练器、策略引擎、反馈入口、artifact、shadow 或 canary | **未实现** |

## 3. 验证证据

本轮只读聚焦验证结果：

| 范围 | 结果 |
| --- | --- |
| Models + Perception + S09 Eval +相关 Port/Codec | `121 passed, 76 subtests passed` |
| Memory Repository/WriteGate/Iris/migration | `17 passed, 6 subtests passed` |
| AstrBot Connector/Output/Attachment + Composition | `22 passed, 10 subtests passed` |
| 历史 S08-S11 双 Python 全仓门禁 | Python 3.10/3.12 各 350 tests，2 个宿主 skip |
| 历史 Web audit | 66 frontend、42 server、6 Playwright、352 repository tests |
| Bandit 实现扫描 | `packages/`、`plugins/`、`services/`、`apps/`、`tests/` 中无 Bandit 实现 |

测试数量不是完成证明。本报告还检查了生产引用关系、实际构造点、Adapter 能力声明、Eval
数据来源和未实现边界。

## 4. 跨模块主要问题

### 4.1 “步骤完成”仍容易被误读为“产品完成”

`docs/refactor/PROGRESS.md` 已明确说明步骤完成不等于产品模块完成，这是正确的。但
`.TreeWork/tree.yaml` 目前只包含 S08-S11 和 Mew/NapCat Web epic，没有 S12-S23；
`.TreeWork/PROJECT.md` 又把真实群 shadow/canary 写成下一项目门禁，而实施计划要求先完成
S12-S22 和 S19 审计。

这会让后续 Agent 或合作者沿 Tree 得出错误顺序。Bandit 现在又成为明确需求，正式编码前应
更新 Tree，把 S12-S23 和 Bandit 的离线/线上两段纳入依赖图；否则文档仍会互相打架。

### 4.2 生产 composition root 缺失

`plugins/astrbot_plugin_dududa_core/composition.py:35-51` 初始化时设置
`plugin.rollout_bridge = None`。`install_rollout_runtime()` 需要外部传入已经组装好的
`AgentRuntime`，但仓库内没有调用点；`StaticModelRouter`、`DeterministicComplexityAssessor`、
`DeterministicModelTierPolicy` 和 `AstrBotModelProviderAdapter` 的构造都只出现在测试中。

因此当前生产插件可以加载命令和 legacy iCourse 路径，但不会自动运行 S10 的完整直聊链。
这不是一个小配置问题，而是产品纵向闭环尚未交付。

### 4.3 首个真实 Adapter 与 Runtime 契约不兼容

两个独立断点会让首个 Provider 在 Router 前就被排除：

- `runtime/perception.py:229` 和 `runtime/direct_chat.py:322` 固定构造 `temperature=0`；
- `adapters/model.py:642-649` 强制 AstrBot Endpoint 声明 `supports_temperature=False`，
  `router.py:1094-1095` 会返回 `temperature_not_supported`；
- Adapter 的 `health()` 在 `adapters/model.py:318-335` 永远返回 `UNKNOWN`；
- Router 在 `router.py:1162-1166` 把 `UNKNOWN` 视为 unavailable。

现有共享 Provider fixture 使用 `temperature=None`，因此没有覆盖真实 Runtime 请求形状。
在修复这两个断点并增加 production-shape contract test 前，不能声称“一个兼容 Adapter 已经
接通”。

### 4.4 设计文档状态发生漂移

`docs/design/perception-and-social.md` 仍写“Phase 1，尚未实现”；`model-routing.md` 仍写
“集成前验证阶段”。实现、Progress、Tree 和设计文档的状态语义不一致，容易再次造成协作误判。

## 5. 分模块批评与肯定

### 5.1 模型路由器

值得肯定：

- `ModelRole`、`ModelTier` 和 `ReasoningProfile` 正交，没有从营销模型名猜能力；
- Endpoint 明确声明 structured output、上下文、输入/输出上限、隐私、驻留、retention、
  traffic policy 和共享 quota pool；
- Router 实现了单快照规划、稳定排序、原子 admission、同 Endpoint retry、同 Tier failover、
  显式跨 Tier fallback、一次 Schema repair、调用前后 deadline/cancellation 复核；
- 无合法路由和 Provider 失败不会返回 stub 成功；receipt 和 fingerprint 可审计。

主要批评：

- 没有生产构造和配置发布路径，Catalog/Operational Snapshot 目前主要是测试对象；
- 首个 AstrBot Adapter 存在 temperature 与 health 两个硬断点；
- 没有两个经过同任务、同输出契约评测的真实 Endpoint，无法做质量/成本/延迟比较；
- 真实 Provider 的 reasoning 映射、429/认证/超时行为只有兼容测试，没有长期观测；
- 当前配置层没有完成多 Provider SecretRef、health/load publisher 和热更新闭环。

结论：这部分不是 vibe coding，可靠性工程有深度。但它现在是高质量路由库，不是已经工作的
生产模型路由系统。

### 5.2 Memory

值得肯定：

- Scope 覆盖 platform/bot/conversation/user/persona，Selector、cursor 和 snapshot 均绑定 digest；
- JSON 与内存实现共用 Repository contract，跨 Scope、过期、伪造 selector 默认拒绝；
- WriteGate 拒绝自动写、跨用户、Secret 和未可靠投递内容；
- Iris 缺 metadata 会隔离，不做全局回退；deadline/cancellation 和取消回滚有测试；
- 迁移工具具备 dry-run、backup、receipt、冲突拒绝和 rollback。

主要批评：

- `IrisMemoryRepository` 只接 `IrisBackend` Protocol/Fake，没有真实 Iris SDK Backend；
- S10 Runtime 明确 Memory-off，Context Builder 没有生产 Memory retrieval；
- `plugins/.../commands/memory.py:24-25` 的 `/remember` 仍直接 append legacy JSON，绕过
  `ExplicitMemoryWriteGate`、Memory v2 Scope、digest 和 Delivery 绑定；
- exact/recency/BM25/embedding/hybrid 尚未比较，没有 Precision@K、Recall@K、MRR/nDCG、
  P95 和 token/cost 报告；
- 删除/导出/TTL/冲突在新 Repository 到生产命令之间没有端到端闭环。

结论：Memory 的安全研究做对了，但产品 Memory 仍未开始。不要用“有 10 个 Memory 文件”或
“有 Iris Adapter”来宣称完成。

### 5.3 MCP 集成

值得肯定：

- iCourse MCP Server、SQLite 数据模型、抓取/解析和 10 个 Tool 是真实实现，不是 Mock；
- 现有命令能明确标注来源并限制公开评课内容；
- ADR-0004 已正确识别统一 Client、Registry、持久 Session、allowlist 和逐步授权边界。

主要批评：

- `dududa-agent` 中没有 MCP Package 或 `UnifiedMcpClient` 实现；
- `plugins/.../course.py:24-47` 的每次 `call/list_tools` 都新建 stdio 子进程和 Session；
- `timeout_hint` 没有进入任何 timeout；没有统一 retry、熔断、并发、health 和 close；
- AstrBot MCP 配置和插件自建 Client 形成双连接权威；
- 动态 Tool 还没有 Capability 映射、Top-K、Schema snapshot、执行前重新授权和 Observation
  Validator；
- 当前测试目录没有 S12 所要求的 Unified Client lifecycle/handshake/restart 合同测试。

结论：MCP Server 可以用，Agent 的 MCP 集成不能用“部分完成”弱化为一个小尾巴。S12 是完整
工程阶段，尚未开始。

### 5.4 输入 Connector、Output 与 Attachment

值得肯定：

- Connector 生成结构化 Actor、ConversationScope、Mention、Reference 和 AttachmentRef；
- Attachment 有大小/MIME/Scope/目的授权、取消回收、tombstone 和 no-follow 约束；
- Output 明确区分 SUCCEEDED/PARTIAL/FAILED/UNKNOWN，发送异常不盲重试；
- 发送前 guard、payload digest、幂等键冲突和中途失败都有负向测试。

主要批评：

- 新 Connector 只通过未调用的 `install_rollout_runtime()` 进入 Bridge；生产消息仍未走完整链；
- 默认 `RejectingAttachmentSource` 会 fail closed，说明真实附件读取没有实现；
- Attachment Repository 的当前 Actor 二次交叉绑定仍不完整；
- 只有 AstrBot/QQ 平台，没有第二 Adapter 来证明 Port 真正通用；
- 真实群、真实发送回执和跨 Runtime 一致性仍没有证据。

结论：接口和失败处理深度合格，生产接线不合格。

### 5.5 语义理解、难度判断与 Social Decision

值得肯定：

- Context 有界且去标识；原始 QQ ID 不进入模型请求；
- Model Projection 使用严格 Schema，未知字段、越界引用和部分结果整包拒绝；
- Merger 保持规则证据权威，模型不能扩大响应目标或制造 Tier/Provider 权威；
- Complexity Assessor 明确区分语义难度和长上下文压力；
- Perception 固定 Haiku，低置信度/冲突默认 Sonnet，Opus 需要多个高复杂度信号和预算；
- Social Gate 在软语义前执行显式提及、隐私和 Tool-off 等硬规则。

主要批评：

- 320 条数据由 32 个模板簇扩展；很多安全 Gate 实际只有 1-3 个适用簇；
- Template 同时定义输入、模型 fixture 和 gold，生成器还调用被测规则生成标签；
- Eval runner 读取固定 fixture，不调用真实 Haiku/Provider；`F1=1.0` 只说明冻结策略自洽；
- 当前 `macro_f1` 是几组异质指标的平均，不是按 Intent 类别计算的标准 macro-F1；
- Entity DTO 没有 span，无法实现计划声称的 entity span F1；
- 没有双人标注/仲裁/κ、真实脱敏会话、独立 Rules/LLM/Hybrid baseline、校准误差和置信区间；
- 多轮、回复链可信历史、附件语义和真实工具需求仍未覆盖。

结论：这部分不是“智能理解已完成”，而是“安全、可重放的语义决策骨架已完成”。真正的
NLP/LLM 效果研究尚未开始。

### 5.6 OC / Persona

值得肯定：

- Persona 不能改变 Fact Anchor、Citation、Refusal、Target、Attachment 和 immutable constraint；
- Renderer 输出绑定 draft digest、persona ID/version 和 component revision；
- Final Validator 重算内容 digest 并再次执行 Content Safety。

主要批评：

- `config/personas/dududa.md` 只有 43 行，内容是首版人物设定，不是经过场景设计的 OC 资产；
- `DeterministicPersonaRenderer` 当前逐块原样复制文本，没有真正实现风格转换；
- `dududa.json` 只记录 prompt 文件名，没有内容 digest、发布状态或兼容版本；
- 没有群聊/技术/情绪/拒绝/危机等场景 Golden，没有盲评、偏好隔离效果或 fallback 质量报告；
- 未成年人 OC 的长期一致性、时间推进和关系设定需要专门内容安全审查。

结论：安全外壳可以保留，OC 撰写与 Persona 产品化基本仍是待办。

### 5.7 WebUI

值得肯定：

- `apps/web` 已形成真实 NapCat 多账号 QQ 工作台，约 2 万行 Vue/TypeScript；
- 浏览器不直连 NapCat，Gateway 限制 OneBot action，账号/会话缓存键隔离；
- 聊天、联系人、通知、群管理、历史、上传和响应式行为有 Unit/Server/Playwright 证据；
- 不伪造 QQ 未读、置顶、历史或不支持的 NapCat 能力。

主要批评：

- README 明确写 Agent Console “未连接”；
- Agent UI 内的模型、Agent、触发、Memory 和 Tool 选项是界面占位，没有 Runtime API；
- 没有 Trace/Eval/RouteDecision/MCP Health/Bandit experiment 的只读 Schema 和权限边界；
- 浏览器 API 仍只建议 loopback，外部发布前缺操作员认证；
- 当前 Web audit 证明的是 QQ operator client，不是 Agent Control Plane。

结论：WebUI 不能用单一“完成/未完成”描述。QQ 工作台完成，用户要求的测试型 Agent WebUI
未完成；按既定计划只做只读测试界面，不扩展成可写 Control Plane。

## 6. 是否属于半成品文档驱动的 vibe coding

### 否定部分

以下证据说明当前核心不是直接套用旧文档的随意实现：

- DTO 版本、不可变集合、canonical digest 和 revision 贯穿多个模块；
- Router 的 capacity lease、取消清理、未知结果结算和 fallback ceiling 有实质并发测试；
- Connector/Memory/Delivery 大量测试针对越权、伪造、Scope、取消和 UNKNOWN，而不是只测 happy path；
- S09 Data Card 主动声明 synthetic-only、release-ready=false，没有把策略回归包装成真实效果；
- 当前实现与协作者 prototype 的可变 DTO、假成功 Router、默认 Mock MCP 和随机社交决策明显不同。

### 肯定批评

项目仍有一种“Spec 很完整，所以实现也接近完成”的风险：

- 生产构造点、真实 Backend 和真实数据没有随复杂契约同步交付；
- 同源生成的 Eval 容易制造全绿结果；
- 文档状态与代码状态漂移；
- Tree 未覆盖后续模块，却把真实群测试写成下一门禁；
- 测试大量证明内部自洽，较少证明与 AstrBot、Provider、Iris、MCP 和用户反馈的真实兼容。

因此应把当前阶段定义为“深度本地基础设施”，而不是“核心功能全部开发完成”。

## 7. Bandit 当前设计的批评

`docs/design/online-learning.md` 已正确提出 eligible action、behavior/candidate propensity、
before-action log、延迟反馈、IPS/SNIPS/DR、cluster bootstrap 和 baseline 回退。可用部分应保留。

但它现在仍是目标接口，不是技术栈：

- 没有 `dududa.bandit` 契约包或任何实现测试；
- 没有 durable decision/feedback schema、数据库 migration 或幂等 join；
- 没有明确的显式反馈入口；群聊沉默不能当负奖励；
- 没有第二个经过同任务质量门禁的同 Tier Endpoint，action set 常常只有一个动作；
- 没有生产 Router，无法记录真实 eligible/rejected candidate；
- 没有训练器、OPE estimator、artifact 格式、snapshot publisher、drift detector 或 rollback；
- S20 要求极小 canary，但真实群测试又被统一延后到 S23，阶段定义存在冲突。

最重要的原则：

> **实时决策不等于在请求线程里实时修改模型。**

第一版应实时记录决策和反馈，在独立 Worker 中近实时更新候选模型，经 OPE/安全 Gate 后原子
发布 immutable snapshot。在线请求只读一个冻结版本；训练失败继续使用 last-known-good。

## 8. 推荐 Bandit 技术栈

外部项目状态按 2026-08-08 调研：

| 组件 | 当前状态与优点 | 问题 | 用法建议 |
| --- | --- | --- | --- |
| [Vowpal Wabbit 9.11.2](https://github.com/VowpalWabbit/vowpal_wabbit) | BSD-3-Clause；2026-03 发布；Python 3.10-3.13 wheels；成熟 online CB、ADF、exploration、IPS/DR reduction | C++ 内核和模型格式需要 Adapter；自身不替代本项目审计/反馈/OPE Gate | **推荐生产策略引擎**，放在独立 Bandit Worker/Adapter，不进入 Core |
| [MABWiser 2.7.4](https://github.com/fidelity/mabwiser) | Apache-2.0；LinUCB/LinTS/partial_fit，接口简单 | 最新发布 2024-09；偏研究/模拟，不提供本项目日志、propensity、OPE 和发布治理 | 作为离线 LinUCB/LinTS 对照基线 |
| [Open Bandit Pipeline 0.5.7](https://github.com/st-tech/zr-obp) | Apache-2.0；OPE 方法完整，含 IPS/SNIPS/DR/Switch-DR 和合成数据 | 依赖 Torch 等重栈；主仓维护较慢，不适合生产请求路径 | 独立 research container 中交叉验证 OPE，不作为运行时依赖 |
| [River 0.25.0](https://github.com/online-ml/river) | BSD-3-Clause；活跃在线学习和 drift 组件 | Python >=3.11；其 LinUCB 文档明确称实际使用过慢 | 可研究 drift/在线 baseline，不作首选策略服务 |
| [contextualbandits 0.3.30](https://github.com/david-cortes/contextualbandits) | BSD-2-Clause；算法丰富，源码仍活跃 | 主要假设二元 reward；Cython/OpenMP、`-march=native`、序列化有运维风险 | 只做研究对照，不进入生产镜像 |
| [VW RL Client](https://github.com/VowpalWabbit/reinforcement_learning) | Predict/Log/Learn/Update 集成思路完整 | CMake/vcpkg/C++ 依赖过重 | 单人项目第一版不引入 |

### 8.1 最小生产组合

```text
dududa-agent Core
  - Bandit DTO / Protocol / Validator（仅标准库）
  - Static Router 仍拥有全部 hard eligibility

services/bandit-worker
  - Vowpal Wabbit --cb_explore_adf
  - decision/feedback join
  - nearline learner
  - immutable artifact publisher

runtime/bandit
  - SQLite WAL append-only event store（单实例第一版）
  - Parquet export
  - artifact + manifest + SHA-256 digest

offline evaluation
  - DuckDB/NumPy 计算项目自有 IPS/SNIPS/DR/ESS/bootstrap
  - OBP research container 交叉验证 estimator
```

第一版不引入 Kafka、Feast、Ray、Celery、MLflow 或可写 Web Console。单 Bot/单 Worker 使用
SQLite WAL 足够；出现多个写实例、写锁竞争或数据量证据后再迁 PostgreSQL。

### 8.2 为什么使用 VW ADF

模型 Endpoint 的合法集合会随 Tier、隐私、上下文、健康和容量变化。VW 的
`--cb_explore_adf` 支持每次决策具有不同 action set 和 action-dependent features，适合在
Router 已完成硬过滤后对 Endpoint 重排。

VW 只接收最小化、版本化特征；action line 的顺序必须与 `action_id` 列表一起写入日志，
不能把行号当稳定 Endpoint ID。VW 使用 cost 语义时，Adapter 统一采用版本化转换，例如：

```text
cost = 1 - clipped_reward
```

转换范围、缺失值、归一化和 revision 必须冻结，不能训练后临时调整。

## 9. Bandit 决策边界

第一阶段只优化：

```text
已经由 DeterministicTierPolicy 选定的 Role + Tier
  -> Static Router 完成全部硬过滤
  -> 两个或以上语义兼容的 eligible Endpoint
  -> Bandit 在这些 Endpoint 中选择
```

不允许 Bandit：

- 选择 Haiku/Sonnet/Opus Tier；
- 绕过隐私、驻留、retention、Schema、预算、健康或容量；
- 授权 MCP Tool、Memory Scope、Confirmation 或发送目标；
- 对高风险/不可逆 Tool 做探索；
- 在 live 群聊探索 Reply/Ignore；
- 修改事实、拒绝结论、引用或 Persona 安全边界。

Prompt、Search、Capability 和 Persona Style 的 Bandit 都放在 Model Route 之后，且必须有各自
独立 experiment 和反馈契约，不能共用一套 reward 混训。

## 10. 行为分布与日志

保守 canary 不直接执行候选 Policy 的原始分布。使用 baseline 混合：

```text
p_behavior(a | x)
  = (1 - epsilon) * I[a = baseline]
  + epsilon * p_candidate(a | x)
```

工程默认探索上限建议不超过 1%，最终值必须按 SLO 和风险预算预注册。流量不足时延长实验，
不能通过临时提高 epsilon 追样本。

执行前必须原子持久化：

- decision/experiment ID；
- request、hard-constraint 和 action-set digest；
- 完整 eligible action ID/revision/顺序；
- baseline、candidate 与实际 behavior distribution；
- executed action 和精确 propensity；
- policy/feature/reward/sampler revision；
- sampling value、snapshot digest 和发布时间。

日志失败时只执行确定性 baseline。Shadow 中 candidate 只做推荐，实际 baseline propensity 为 1；
Shadow 没有未执行动作的 support，不能用来声称候选 Policy 会提高奖励。

## 11. Feature、Reward 与反馈

### 11.1 首版 Feature

只使用低基数、可解释且已存在的结构化结果：

- ModelRole、固定 Tier；
- task kind、complexity level/confidence bucket；
- context pressure、文本长度、预计工具步数 bucket；
- 是否要求结构化输出/实时信息；
- group/private 类型；
- budget、deadline、time-of-day bucket；
- Endpoint 的静态成本/延迟 bucket。

禁止原始消息、QQ/群 ID、昵称、敏感实体、附件正文、Prompt、Provider error body 和高基数
组合键。群/会话只使用 experiment-scoped 不可逆 cluster key 进行统计和随机化。

### 11.2 Reward

数据库保存分量，不只保存一个总分：

```text
explicit_satisfaction
task_success
delivery_success
quality_audit_score
latency
token_cost
retry/fallback
```

权限、隐私、事实保持、重复发送和错误目标是硬 Gate，不进入可相互抵消的奖励和。

首版反馈来源按可信度排序：

1. 用户显式 reaction 或 `/rate +1|-1`；
2. 有严格 Schema 的 Tool/任务成功回执；
3. 按冻结 rubric 的盲审抽样；
4. latency、cost 和 delivery 等机器指标。

群聊沉默、下一条无关消息、Bot 自己的“已完成”文字不能充当负面或正面反馈。未观察反馈标记
`PENDING/CENSORED`，不能零填充。

## 12. 训练、OPE 与发布

1. 实时请求只读取 immutable Policy Snapshot。
2. Feedback Worker 幂等 join decision 与 observed outcome。
3. Learner 在影子副本上增量更新 VW；不修改正在服务的 Workspace。
4. 达到预注册的最小 observed feedback/ESS 和固定时间窗后生成候选 artifact。
5. 使用 IPS、SNIPS、DR，同时报告 ESS、最大 importance weight、action coverage 和 paired effect。
6. 按 group/conversation 做 cluster bootstrap；同群消息不能当独立样本。
7. 安全 Gate、效果下界、延迟和 artifact 校验全部通过后原子发布。
8. 发布失败或 drift 超阈值保留 last-known-good；kill switch 立即回 baseline。

OBP 只用于研究交叉验证。本项目仍需实现窄而可审计的 estimator，并用已知 behavior/evaluation
policy 的合成数据验证 bias、coverage 和极端 propensity 行为。

## 13. Bandit 实施顺序

当前 S20 同时包含离线实现和 live canary，与“真实群统一留到 S23”冲突。建议拆分：

### S20A：离线基础设施，可在 S23 前完成

1. 冻结 Bandit ADR、DTO、Feature/Reward Schema 和安全非目标；
2. 实现 append-only decision/feedback store 和 before-action receipt；
3. 实现 StaticBaselinePolicy、synthetic environment 和 IPS/SNIPS/DR golden tests；
4. 接入 VW Adapter，但只跑合成和离线 replay；
5. 在 Runtime 做 log-only，再做 recommendation-only Shadow；
6. 完成 artifact digest、atomic publish、last-known-good 和 rollback 演练。

Shadow 结束时只能证明接口、候选覆盖、日志、延迟和建议可重放，不能证明效果提升。

### S20B：受控在线学习，作为 S23 内部子门禁

1. 先用静态 Router 完成授权单群 baseline/shadow；
2. 冻结 experiment、eligible Endpoint、epsilon、SLO、停止规则和反馈窗口；
3. 对同 Tier 安全 Endpoint 开启不超过预注册上限的 conservative canary；
4. 达到 support/ESS 后做 OPE 和 cluster bootstrap；
5. 只有质量下界、成本/延迟和零安全违规同时通过，才允许 exploit；
6. 任何安全违规、异常 weight、coverage 崩塌或 drift 立即回静态 baseline。

### 后续扩展

Model Route 稳定后，才能分别为等价 MCP Provider、预审 Prompt、低风险 Search 和 Persona
Style 建立新实验。不要同时打开多个 Decision Point，否则无法归因。

## 14. 修正后的单人顺序

```text
先修复 S08-S11 生产装配与 Adapter 断点
  -> S12 Unified MCP
  -> S13 Capability / Tool
  -> S14 Memory 产品接入与检索研究
  -> S15 OC / Persona 产品化
  -> S16-S19 本地硬化与总审计
  -> S20A Bandit 日志 / OPE / Shadow
  -> S21 测试型只读 WebUI（可展示 Bandit 状态，不可在线改策略）
  -> S22 清理旧路径并复审
  -> S23 静态单群验证 + S20B 极小 Bandit canary
  -> 分层放量与长时间 Debug
```

WIP 保持为 1。Bandit 是新增正式范围时，应先更新 Tree，再编码；不允许用 Bandit 绕过
S12-S15，也不允许为了“实时学习”提前拿真实群当训练环境。

## 15. 方法学参考

- Li et al., [A Contextual-Bandit Approach to Personalized News Article Recommendation](https://arxiv.org/abs/1003.0146)：LinUCB 与 replay evaluation 的经典来源；
- Dudik et al., [Doubly Robust Policy Evaluation and Learning](https://arxiv.org/abs/1103.4601)：DR 估计与学习；
- Agarwal et al., [Making Contextual Decisions with Low Technical Debt](https://arxiv.org/abs/1606.03966)：生产 Contextual Bandit 的低技术债架构；
- Saito et al., [Open Bandit Dataset and Pipeline](https://arxiv.org/abs/2008.07146)：OPE 流程与公开 logged bandit 数据。

这些论文和库用于确定算法与评测边界，不替代 Dududa 自己的隐私、权限、投递、反馈和发布
Contract Test。

## 16. 最终判定

| 问题 | 回答 |
| --- | --- |
| 当前实现是不是直接照半成品文档 vibe coding | **不是**。S01-S11 的契约、可靠性和负向测试有实质深度 |
| 核心模块是否全部完成 | **不是**。只有约定的本地基础范围完成，产品装配和后续模块大量未完成 |
| 哪部分最成熟 | Static Router 内核、Perception 安全骨架、Scope/Delivery/取消等基础契约、QQ Web 工作台 |
| 哪部分最容易被高估 | 语义 Eval、Memory、MCP、OC、Agent WebUI，以及未接生产的 S10/S11 |
| Bandit 是否可以应用 | **可以**，但第一阶段只在同 Tier 合法 Endpoint 内选择 |
| Bandit 是否已经接入 | **没有**，目前只有设计文档 |
| 现在是否应实时探索 | **不应**。先闭合生产 Router、反馈日志、OPE 和 S20A，再在 S23 授权场景做极小 canary |

当前最应做的不是继续扩大接口，而是把已经很深的接口接成一个可运行、可观测、可回滚的真实
纵向闭环，再逐项完成 MCP、Memory、Persona 和 Bandit 的独立证据。
