# 嘟嘟哒 2.0 设计文档

**文档性质：**作品技术设计报告
**版本：**2.0 设计基线（2026-09-02）
**项目：**Dududa 2.0 受治理的群体情境适应 Agent Runtime

## 摘要

嘟嘟哒 2.0 不是把一个大模型接到 QQ 上的问答脚本，而是一套面向群聊场景的 Agent
Runtime。它把“理解消息”“决定是否介入”“选择模型”“调用能力”“组织事实”“以人格表达”
和“投递消息”拆成可观察、可测试、可替换的阶段；把身份、会话 Scope、权限、预算和副作用
交给确定性代码，把模型限制在语义候选和语言表达范围内。

系统保留一个不可卸载的治理内核，在外围组合校园查询、校车、资讯、人格、主动消息和学习等
能力资产。所有能力都以版本化契约出现，所有外部结果都带来源和可信度边界。AstrBot、NapCat、
MCP Server、模型 Provider、Memory 后端和 Web 控制台都是外围适配器，互不把平台类型带入核心。

当前仓库已经形成框架无关的 Core 契约、Runtime 状态机、静态模型路由、感知与社交决策、统一
MCP 基础设施、能力执行闭环、Memory v2 离线实现、Persona/ResponsePlan、主动消息 Shadow、
Bot Control Plane 和可复现评测。iCourse、二课、教务、培养方案研究四类校园查询以及本地校车
已经进入 2.0 能力组合；PR #9 新增的 NotifAI 公开通知 MCP 已合并到主分支，并完成七项能力
的 Registry、Schema、映射和 Web 目录集成。PR #10 中不重复的社交规则已整理为独立、默认关闭、
只响应显式命令的策略插件；本地推荐、专业设置、学校通知、学院通知和图书馆开放时间已整理为
五个 Registry-only、cache-only 的可选 MCP Server。它们已打包但没有 Capability mapping，不进入
Planner 或生产 Provider health。真实 QQ 入站目前覆盖群内明确 @Bot 的纯文本、无
附件消息，运行实例使用 Luna/Terra/Sol 三档模型；Memory 生产读写、实时主动发送、在线 Bandit
和部分多轮/附件能力仍按各自状态边界运行。

本文是面向评审、部署和后续维护者的统一设计说明。冻结的细粒度接口仍以同目录下的专项设计
文档和源码类型为准：

- [Runtime](runtime.md)
- [感知与社交决策](perception-and-social.md)
- [模型路由](model-routing.md)
- [能力与 MCP](capability-and-mcp.md)
- [Memory](memory.md)
- [Persona](persona.md)
- [主动消息](proactive-messaging.md)
- [Bot Control Plane](bot-control-plane.md)
- [在线学习](online-learning.md)
- [安全与隐私](security.md)
- [PR #10 选择性插件与 MCP 整合](../integrations/pr10-selective-integration.md)

## 1. 背景与要解决的问题

### 1.1 产品背景

嘟嘟哒运行在 AstrBot + NapCat + OneBot v11 的 QQ 生态中，服务对象是校园群聊、私聊和管理
工作台。产品期望同时具备三种看似矛盾的特征：

1. **自然。** 能读懂口语、省略、指代和群聊节奏，不把每条消息都当成命令。
2. **有用。** 能查评课社区、二课活动、教务公开信息、培养方案研究资料和校车时刻表，并给出
   可追溯的结果。
3. **可靠。** 不因模型幻觉、插件异常或群聊上下文而越权、串群、重复发送或泄露个人数据。

早期插件各自监听消息、各自调用模型或 MCP、各自维护配置和发送逻辑，功能增长很快，但形成
了多套权限入口、模型入口和状态来源。一个“查课程”的请求可能同时经过旧命令、自然语言
Handler、Web Search 或插件专用 Client；一个群聊回复也可能被多个监听器竞争。2.0 的核心工作
是把这些隐含行为改造成一条单一、可审阅的执行链。

### 1.2 传统方案的结构性问题

| 问题 | 直接后果 | 2.0 的解决方向 |
| --- | --- | --- |
| 平台事件直接进入业务代码 | 核心逻辑绑定 AstrBot，难以离线复现 | Connector 先转换为平台无关 Envelope |
| 模型同时决定意图、权限和工具 | 提示注入可改变边界，越权难审计 | 模型只产出候选，确定性 Policy 决定资格 |
| 每个插件拥有自己的模型/Client | 重复连接、错误语义不一致、难以回滚 | Model Router 与 Unified MCP Client 统一收口 |
| 记忆查询以可选字段作过滤 | 缺字段会变成全局搜索，发生跨群泄露 | MemoryScope 先精确过滤，再做检索 |
| 人格 Prompt 兼任安全规则 | 改写语气时可能改事实或弱化拒绝 | Draft、Fact Anchor、Validator 与 Persona 分离 |
| 定时任务伪造成用户消息 | 缺少真实 Actor、目标和投递授权 | 主动消息使用独立 Initiated Run |
| WebUI 直接写浏览器状态或发 QQ | 配置看似成功但 Runtime 不消费 | Web 只做 Control Plane，写入 Core Command |

### 1.3 目标与非目标

目标是提供一条从 QQ 消息到可验证投递回执的完整链路，并为校园能力、长期记忆、主动消息和
群体情境适应留下可替换端口。非目标包括：让模型拥有权限、让 MCP 直接发送消息、把所有历史
聊天自动变成长时记忆、用在线学习自动打开新服务，以及用一个“万能 Agent 循环”替代业务策略。

## 2. 设计理念

### 2.1 治理内核 + 可逆能力资产

核心包 `packages/dududa-agent` 拥有身份、Scope、Runtime 状态、授权、预算、错误、Trace、
投递和契约版本。校园查询、Persona、天气、B50 渲染和未来资讯源是可独立启停的能力资产。
能力资产必须声明 Provider、输入输出 Schema、风险、隐私级别、上下文类型、成本和副作用，
由 Registry 组合，而不是把业务判断散落在插件入口。

这种拆分让一个能力可以在离线 Fake、Web 预览、Shadow、单群 Canary 和真实投递之间逐级移动；
能力故障只影响该能力的结果，不会改变 Runtime 的身份和授权模型。

### 2.2 Scope-first Memory

会话、用户、群、Bot、平台和 Persona 构成记忆边界。查询先由确定性策略生成带授权证明的
`ScopeSelector`，Repository 在这个精确集合内做 TTL、可见性和类型过滤，最后才允许 recency、
BM25 或未来 embedding 排序。相似度永远不能扩大 Scope；“全局群知识”必须成为另一个经过治理
的知识资产，而不能由缺少 group_id 的查询隐式产生。

### 2.3 Perception 与 Social Decision 分离

感知回答“这条消息表达了什么、涉及哪些实体、可能需要哪类能力”；社交决策回答“此刻是否
介入、以什么方式介入”。前者可以使用规则和 Haiku 模型，后者由确定性硬规则包围，综合
明确 @、回复关系、群模式、冷却、授权、重复消息和任务价值。Persona 只影响已经决定的表达。

### 2.4 先过滤资格，再优化质量

Model Router 只能在合法的 Tier/Endpoint 中选模型，Capability Retrieval 只能向 Planner 展示
通过权限、隐私、风险、健康和预算过滤的候选，Bandit 只能在安全等价候选中排序。任何质量分、
延迟分或用户偏好都不能恢复一个已经被硬策略排除的能力。

### 2.5 事实、表达和副作用各有所有者

- **事实所有者：**工具 Observation、来源引用和 Fact Anchor。
- **表达所有者：**Response Composer、Persona Renderer 和 Answer Profile。
- **副作用所有者：**Authorization、Budget、Output Adapter、Delivery Reconciliation。
- **配置所有者：**Bot Control Plane Core Command 和版本化 Snapshot。
- **消息入口所有者：**Connector；定时主动行为拥有独立 Orchestrator。

模块之间通过不可变 DTO、Schema Ref、组件 revision 和低敏 Receipt 传递信息，避免一个模块
通过“顺手改字段”获得另一模块的控制权。

### 2.6 兼容优先、逐步切换

旧命令、插件 ID、OneBot 入口和 Compose 入口在新链路通过测试前继续保留为兼容或回滚材料。
迁移按纵向切片推进：先建立 Core 契约，再接 Connector、模型、能力、Persona 和 Output，最后
切换生产组合。旧 Target Talk、ReplyPolish、专用 iCourse Client 等已按消费者证据退出 2.0
默认运行面，但历史源码和数据不会被无依据地抹除。

## 3. 总体技术架构

### 3.1 逻辑架构

```text
                  ┌──────────────────────────────────────────┐
                  │                外部交互层                  │
                  │ QQ / NapCat / OneBot · Web Console       │
                  └───────────────────┬──────────────────────┘
                                      │ Adapter / Connector
                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         Dududa 2.0 Core                                  │
│ Envelope · Scope · Authorization · Budget · Runtime State · Trace        │
│                                                                        │
│ Context Builder → Perception → Social Decision → Response Profile       │
│       │                    │                    │                       │
│       ▼                    ▼                    ▼                       │
│   Memory Port       Model Router          Capability Retrieval            │
│                                                │                           │
│                                  Planner → Executor → Validator            │
│                                                │                           │
│                       Response Composer → Persona → Final Validator      │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ Ports
          ┌─────────────────────┼─────────────────────────┐
          ▼                     ▼                         ▼
   AstrBot Model Adapter   Unified MCP Client       Output / Delivery
          │                     │                         │
   Luna/Terra/Sol       Registry + Sessions        OneBot send + Receipt
                                │
             ┌──────────────────┼────────────────────┐
             ▼                  ▼                    ▼
          iCourse            USTC Campus           NotifAI
       (评课社区)       (二课/教务/培养方案)       (校园通知)
```

### 3.2 依赖方向

```text
AstrBot / Web adapters
          ↓
Runtime / Application
          ↓
Domain DTO + Protocol Ports
          ↑
Infrastructure: Model · MCP · Memory · Builtin Provider · Output
```

`dududa-agent` 不导入 AstrBot、NapCat、OneBot、具体 MCP Server 包或供应商 SDK。服务实现通过
构造函数注入；MCP Server 自己拥有抓取、解析和缓存细节，Core 只看到统一结果。该方向让同一
Runtime 可以由 Fake、离线 CLI、AstrBot 和 Web 预览共同驱动。

### 3.3 部署拓扑

```text
浏览器
  │ HTTPS
  ▼
Cloudflare ──► Caddy（公网 IPv6 源站，443/8443）
                    │ exact host route
                    ├─► Authentik forward-auth ──► Authentik + PostgreSQL
                    └─► dududa-web-api:8000 ──► Vue/Node Web Console

NapCat ── OneBot v11 WebSocket ──► AstrBot Connector ──► Dududa Core
                                      │
                                      ├─► AstrBot OpenAI-compatible Provider
                                      └─► Unified MCP worker（stdio sessions）
```

仓库内的 Dududa Compose 栈包含 AstrBot、Web、MCP Console 和插件；公网 Caddy、Cloudflare、
Authentik、NapCat 登录态和 Provider 凭据属于运行环境。控制台当前可通过
`https://console.mmdustc.top:8443/` 访问，Caddy 对控制台站点启用 Authentik forward-auth，
仅 `Dududa console access` 组成员通过。Cloudflare 现有 Origin Rule 把该主机名回源到 8443，
因此显式端口是当前稳定入口；标准 443 地址需在 Cloudflare 侧把该主机加入同一精确 Origin Rule
后再切换回调地址，Caddy 已同时监听 443 和 8443。

## 4. 核心契约与一次运行的生命周期

### 4.1 MessageEnvelope、Actor 与 ConversationScope

Connector 把 AstrBot Event 转成 `MessageEnvelope`，其中包含平台、Bot、会话类型、会话 ID、
群 ID、用户 ID、时间、纯文本、引用、Mention 和受限 metadata。附件只以有界的 opaque
`AttachmentRef` 跨边界，原始字节留在 Attachment Repository。

`Actor` 是已经由适配器解析的授权主体，携带平台/Bot/用户、角色和 deny flags；
`ConversationScope` 描述当前会话和 Persona。Runtime 校验 Envelope、Actor、Scope 三者的
平台、Bot、会话和群身份一致。缺少必需身份时，运行在进入模型和工具前结束。

### 4.2 PortCallContext 与版本化证据

每次 Port 调用共享 `run_id`、`trace_id`、deadline、取消令牌、预算和 policy snapshot。核心
DTO 使用 `schema_version`；配置、Schema、Provider、Capability、Persona 和策略都带 revision。
规范化编码用于生成域区分的 digest，Receipt 只保留低敏摘要，不把正文、思维链、凭据或原始
Provider 错误写入仓库。

### 4.3 Runtime 状态机

```text
RECEIVED
  → PREPROCESSED
  → CONTEXT_BUILT
  → PERCEIVED
  → SOCIALLY_DECIDED
      ├─ IGNORE / DEFER → COMPLETED
      ├─ DIRECT_REPLY → MODEL_SELECTED → DRAFTED
      └─ USE_TOOLS → CAPABILITY_RETRIEVED → PLANNED
                      → AUTHORIZED → EXECUTING → OBSERVED
                      → VALIDATED ──┐
                                     ├─ FINISH → COMPOSED → RENDERED
                                     ├─ CONTINUE → PLANNED
                                     ├─ CLARIFY / DEGRADE → COMPOSED
                                     └─ ABORT → COMPLETED
  → FINAL_VALIDATED
  → DELIVERY_PREPARED
  → OUTPUT_SENT
  → DELIVERY_ACKNOWLEDGED / RECONCILED
  → MEMORY_CANDIDATE_EVALUATED
  → COMPLETED
```

Runtime 通过 State Store 的 CAS/single-flight 取得一次消息的执行所有权。重复消息返回已有
结果或等待原执行；不会启动第二条工具链。每次状态转换写入阶段、revision、reason code 和
资源使用摘要，便于离线重放和故障定位。

### 4.4 入站数据流

```text
OneBot Event
  → Connector/身份一致性
  → Preprocess（明确 @、附件、重复、群策略）
  → Context Builder（近期上下文 + 可用能力类别）
  → Rule Perception
  → Luna/Haiku Structured Perception（需要时）
  → Merger + Validator
  → Social Decision
  → Complexity + Tier Policy
  → Model Router
  → Direct Chat 或 Capability Loop
  → ResponsePlan
  → Composer（事实/引用/不确定性）
  → Persona Renderer
  → Final Validator + Content Safety
  → Output Adapter
  → DeliveryReceipt / Reconciliation
```

定时日报和主动探测不伪造上述入站 Event，而从 `InitiatedRunRequest` 进入
`ProactiveDeliveryOrchestrator`；它们复用能力、模型、Composer 和 Output 端口，但使用独立的
Target、Grant、订阅、幂等键和发送前检查。

## 5. 消息接入、运行时与投递模块

### 5.1 AstrBot Connector

`astrbot_plugin_dududa_core` 是 2.0 唯一 Agent Runtime 的 AstrBot 适配器。它负责：

- 将 `AstrMessageEvent` 转换为 Core Envelope/Actor/Scope；
- 识别 OneBot 的文本、引用、@、合并转发和附件引用；
- 读取由 Control Plane 发布的 rollout/运行策略；GroupServiceAssignment 的离线投影已完成，
  完整 live Assignment 投影仍在接入中；
- 将 Runtime 的平台无关结果交给 Output Adapter；
- 注册命令、生命周期、健康状态和兼容入口。

Connector 不决定人格、模型或工具。当前真实入站范围是群内明确 `@Bot`、纯文本、无附件；私聊、
附件和未 @ 普通群消息保持静默，不回退到 1.0 Handler。

### 5.2 Context Builder

Context Builder 的目标契约把当前消息、已校验 Scope、近期消息、回复链、群策略、用户偏好视图、
Persona 引用和能力类别组装成 `ContextSnapshot`。近期上下文属于 Conversation Context，不会
自动变成长期 Memory。当前生产实现只投影当前消息，尚未接入真实近期历史、Memory 或完整
Assignment live projection；离线 Port 已为这些数据保留位置。未来接入 Memory 时，Builder 只
接收已通过精确 Selector 的 `ContextMemoryEvidence`，并把冲突、过期和降级状态保留下来。

### 5.3 Runtime Orchestrator

`OfflineRuntimeOrchestrator` 目前承担可离线验证的完整执行骨架，生产装配通过
`AstrBotRolloutBridge` 注入真实 Connector、Provider、Capability 和 Output。Orchestrator 负责
总 deadline、模型/工具步数预算、取消、CAS 状态、幂等、错误降级和最终 Receipt，不负责解析
AstrBot Event 或直接发送 QQ。

### 5.4 Output Adapter 与 LONG 合并转发

Output Adapter 将 `ValidatedFinalResponse` 转成 AstrBot 的 `Plain`、`At`、`Image` 或 `Nodes`。
SHORT/MEDIUM 始终以普通 QQ 消息发送；LONG 单段也是普通消息，只有群聊中确实产生至少两个
纯文本 part 且无附件时才使用合并转发。LONG 的分片优先在自然标点和 UTF-8 字符边界断开，
目标用户语义保留在 Runtime，合并转发不额外制造一个 @。

发送开始前再次检查 target、授权、限流、kill switch 和 delivery binding。OneBot 返回的
`DeliveryReceipt` 与 Runtime run 绑定；超时或连接断开但结果不明时进入 reconciliation，
不把未知结果当成“肯定失败”而盲目重发。

### 5.5 插件兼容面

| 组件 | 2.0 归属与当前状态 |
| --- | --- |
| `astrbot_plugin_dududa_core` | 唯一 Agent Runtime 宿主，负责组合、命令和投递 |
| `astrbot_plugin_ustc_shuttle` | 本地版本化校车 Builtin Provider，进入能力闭环 |
| `astrbot_plugin_sub2api_readonly` | 超级管理员只读命令，独立于 Agent 自动工具路由 |
| `astrbot_plugin_reread` | 独立、默认关闭、按 Scope 配置的兼容插件 |
| `astrbot_plugin_proactive_chatter` | Core 消费的无副作用策略扩展，不监听、不调用模型、不发送 |
| `astrbot_plugin_reply_review` | 保守审校资产，等待 secondary-review Port，当前不拦截线上结果 |
| `astrbot_plugin_weather` | Source/Provider 资产，默认关闭，未进入生产组合 |
| `astrbot_plugin_arc_proxy` / B50 | 受治理的本地渲染/Provider 资产，默认关闭 |
| `astrbot_plugin_dududa_social` | PR #10 非重复社交规则；仅 `/dududa-social` 显式命令，总开关、feature 和群 allowlist 默认关闭，不注册普通消息 Handler |
| `reply_polish` | 1.0 LONG-only 兼容层，默认关闭；2.0 Output 不依赖它 |
| `target_talk` | 已退出 2.0 默认入站路径，保留迁移/回滚材料 |

Sub2API、Reread 和其他宿主插件不因安装在同一容器就获得 Agent Capability 权限。

## 6. 感知、社交决策与回答档位

### 6.1 Perception：从自然语言到结构化证据

Perception 输入是经过 Context Builder 限定的 `ContextSnapshot`，输出包含 intent、entity、
reference、topic、ambiguity、complexity signal、是否需要工具、能力类别和 evidence refs。
流水线为：

```text
Rule Perception
    + Model Perception（固定 Haiku/Luna，严格 JSON Schema）
    → Perception Merger
    → Schema / semantic Validator
    → PerceptionResult
```

规则层负责明确 @、回复关系、命令、站点 marker 和不支持范围；模型层只补充语义候选。以校园
查询为例，“评课社区” marker 可确定地映射到 `campus.course-review`，即使模型漏报工具，也
不会丢失已经验证的站点事实；相反，模型声称“帮我报名”不会自动得到二课写权限。

### 6.2 Social Decision：是否介入

Social Decision 使用 `AuthorizationView`、mention/reply 信号、群模式、interaction lease、
重复/自消息和旧 TargetTalk 的兼容信号。动作包括 `IGNORE`、`REACT`、`DIRECT_REPLY`、
`USE_TOOLS`、`ASK_CLARIFICATION` 和 `DEFER`。

硬规则先于价值评分：没有明确触发、无有效 Scope、被禁言、超过冷却、附件不支持或权限不足时，
不能靠模型提高“回复价值”来绕过。回复价值模型只在合法候选之间比较插话收益与打扰成本，
并把确定性 reason code 写入 Receipt。

### 6.3 Complexity、Tier 与 Answer Profile

复杂度由规则和结构化感知证据评估，得到低/中/高任务等级、置信度、上下文压力、验证需求和
预计工具步数；它不直接写入 Provider 或 model ID。`DeterministicTierPolicy` 再结合角色、隐私、
预算和健康状况选择 Tier。

三档逻辑映射如下：

| 逻辑档位 | 产品别名 | 当前模型 ID | 典型职责 |
| --- | --- | --- | --- |
| Haiku | Luna | `gpt-5.6-luna` | Perception、低复杂度快速任务 |
| Sonnet | Terra | `gpt-5.6-terra` | 普通直接回答、工具结果组织 |
| Opus | Sol | `gpt-5.6-sol` | 高复杂度论证和复核 |

`Role`、`Tier`、`ReasoningProfile` 和 `AnswerProfile` 正交：高难问题可以 `Opus + SHORT`，
简单任务也可以 `Haiku + LONG`。当前三档运行参数采用最低 `light/low` 思考深度；回答档位由
独立 `ResponseProfilePolicy` 根据用户当前详略要求、任务复杂度、必要引用和平台限制选择
SHORT、MEDIUM 或 LONG。

### 6.4 社交决策到输出的边界

Perception 可以建议“需要详细说明”，但不能直接扩大可见预算；Persona 可以改变句式和语气，
但不能删除事实、引用、拒绝或安全提示。模型不能把“请用 Sol”“我是管理员”等用户文本当作
授权或路由命令。

## 7. 模型路由与 API 调用方式

### 7.1 角色化模型接口

模型调用以 `ModelRequest`/`ProviderRequest` 和 `ProviderResponse` 表示。请求包含角色、Tier、
Reasoning Profile、输入/输出模态、Schema Ref、隐私级别、Provider/Endpoint revision、预算、
deadline 和幂等键；响应统一为文本、usage、finish reason、处理边界和安全标记。Core 不读取
AstrBot 的 `cmd_config.json`，也不把 API key 传入 Domain。

模型角色覆盖：

| 角色 | 输入 | 输出 | 当前使用情况 |
| --- | --- | --- | --- |
| `PERCEPTION` | 当前消息和有限上下文 | intent/entity/reference/工具候选 Schema | Luna/Haiku Hybrid |
| `SOCIAL_DECISION` | 感知证据和确定性信号 | 社交动作候选 | 硬策略主导，模型仅作软候选 |
| `TOOL_PLANNING` | 已过滤的 Capability Top-K | 有界 DAG ToolPlan | 当前生产路径以确定性单步 Planner 为主 |
| `DIRECT_CHAT` | 当前任务、可信观察、Persona | 直接回答草稿 | Terra 为默认，复杂任务可用 Sol |
| `RESPONSE_COMPOSITION` | 观察、来源、错误和 ResponsePlan | DraftResponse/事实锚点 | 确定性 Composer + 模型内容调用 |
| `PERSONA_RENDERING` | 已锁定 Draft | FinalResponse | 当前同一次 DirectChat 注入 Persona；独立模型 Renderer 预留 |
| `MEMORY_SUMMARY` | 已授权记忆投影 | 结构化摘要 | 生产关闭 |
| `IMAGE_UNDERSTANDING` / `IMAGE_GENERATION` | 有界附件或描述 | AttachmentSummary/GeneratedAsset | 能力资产存在，当前入站附件路径关闭 |

### 7.2 OpenAI 兼容调用

部署使用 AstrBot 的 OpenAI-compatible Provider。仓库外的 Provider Source 保存 endpoint 和
凭据，逻辑模型 ID 由配置映射为 `gpt-5.6-luna`、`gpt-5.6-terra`、`gpt-5.6-sol`。请求中
明确传递角色提示、用户内容、`max_tokens` 和 `reasoning_effort`（`off/light/balanced/deep`
映射为供应商支持的 `None/low/medium/high` 等值）；生产适配器通过 AstrBot `text_chat` 端口
接收结果，不把供应商 SDK 类型泄漏到 Core。

仓库的 Endpoint 抽样工具也支持直接验证 OpenAI Responses API：

```http
POST {OPENAI_COMPATIBLE_BASE}/v1/responses
Authorization: Bearer <运行环境注入的密钥>
Content-Type: application/json

{
  "model": "gpt-5.6-luna",
  "instructions": "Return one short acknowledgement.",
  "input": "Synthetic no-send check.",
  "max_output_tokens": 32
}
```

Responses 的 `output_text`/`output[].content[].text` 和 `usage` 被压缩为低敏 Provider Evidence；
该探测不连接 QQ、不调用 Tool、不写 Memory。AstrBot 生产链则使用同一 OpenAI-compatible Source
背后的 Chat Completions 适配，经过 `text_chat(prompt, system_prompt, model, max_tokens,
reasoning_effort)` 调用。两种协议都只属于 Provider 传输层，Runtime 依赖统一的 Provider Port。

结构化任务优先使用 Provider 原生 JSON Schema；不支持时由 Adapter 注入受限 JSON 指令并用
`JsonSchemaDocumentRegistry` 校验。第一次 Schema 失败最多进行一次受控修复，仍失败就生成
`OUTPUT_INVALID` 终态，不把任意文本中的“看起来像 JSON”当成有效结果。生产配置把
`store=false` 作为候选 Provider 的默认附加参数，运行凭据和真实 URL 不进入 Git。

### 7.3 静态路由和 Admission

路由步骤是：

1. 根据复杂度和角色得到允许 Tier；
2. 从不可变 Routing Snapshot 读取 Endpoint；
3. 过滤模态、Schema、隐私/驻留、Provider 健康、deadline 和预算；
4. 在共享 RPM/TPM/cost pool 中原子预留；
5. 按静态 priority 和稳定 endpoint ID 选择；
6. 只按显式 DAG 执行同 Tier 重试或跨 Tier fallback。

认证失败、非法请求、安全拒绝、取消和第二次 Schema 失败直接终止；429、不可用和超时只有在
角色策略、幂等和总 deadline 允许时才切换。健康刷新器以 900 秒间隔、15 秒超时和 1800 秒
Evidence TTL 运行，过期后 Provider 回到 `UNKNOWN`，不会在路由热路径盲目探活。

### 7.4 运行时三模型证据

Luna/Terra/Sol 已在当前 AstrBot 宿主完成各一次真实 Chat Provider 调用，Responses 与
Chat Completions 均有最小 HTTP 200 抽样；这证明模型绑定和调用通道可用，不等同于长期质量
指标。75 条 iCourse 真实感知/本地 MCP/Fake Delivery 纵切中，Luna 感知、Terra/Sol 直接回答
和 Luna Review 均使用 `low` 推理深度；其余质量结论以评测章节为准。

## 8. Capability、Planner、Executor 与统一 MCP

### 8.1 Capability Registry

Capability 是可规划的业务原子能力，不等同于一个原始函数。定义至少包含稳定 ID、名称、输入
输出 Schema、Provider、风险级别、隐私级别、允许会话类型、所需权限、成本/延迟提示、幂等性
和副作用集合。当前主分支有 22 个定义文件、21 个 MCP mapping，以及 1 个没有 MCP mapping
的本地校车 Builtin Provider。Server Registry 另登记五个 PR #10 可选 Server，但它们保持
`enabled=false` 且没有 Capability definition/mapping，因此不计入上述 21/22 统计。

发现和授权是两件事：MCP Discovery 只告诉系统“Server 提供了什么”；只有显式 mapping、
Schema digest、健康快照、当前群策略和 Actor 授权全部通过，能力才进入 Planner 候选。Web
控制台只接受批准的 Capability ID 和输入 Schema，不提供任意 `server/tool` 透传。

### 8.2 Retrieval 与 Planner

Social Decision 产生业务目标和意图，不直接指定工具名。Retriever 按以下顺序生成 Top-K：

```text
enabled / revision
  → Provider health
  → conversation type
  → Actor + group policy
  → privacy / risk / side effect
  → input availability / deadline / budget
  → semantic + intent + entity/schema score
  → stable capability_id tie-break
```

默认 K 为 8，全局上限为 20。Planner 只看到候选摘要，生成带 definition digest 的有向无环
`ToolPlan`。参数模板只能引用字面量和已由 Validator 接受的 Observation JSON Pointer，不能
读取任意文件、未来步骤或 Provider 对象。

### 8.3 Executor 与 Observation Validator

Executor 在每个实际调用前重新解析定义、mapping、Provider、Actor、Scope、限流和预算，生成
稳定幂等键，然后调用 Builtin Provider 或 Unified MCP。返回值被转换成 `ToolObservation`，
含状态、数据、来源、Schema/revision、延迟、敏感度和截断标记。

Validator 检查输出 Schema、业务错误、来源、空结果、跨步骤一致性、敏感度和完成条件，输出
`FINISH`、`CONTINUE`、`RETRY`、`CLARIFY`、`ABORT` 或 `DEGRADE`。当前生产组合将工具尝试数
收窄为 1；离线通用 Runtime 仍支持有限多步循环（默认 4、全局 8），并把重试计入步数。超时
后无法确认副作用的结果是 `UNKNOWN`，非幂等操作不自动重放。

### 8.4 Unified MCP Client

`McpServerRegistry` 从严格 JSON 文件加载 Server 定义；`UnifiedMcpClient` 负责长生命周期
stdio session、初始化和 discovery、Schema TTL、并发、超时、取消、有限重试、熔断、健康和
错误标准化。配置只含命令 allowlist、环境变量 allowlist、工具 allow/deny 列表和 SecretRef，
不含实际密钥。

一次 Runtime 使用同一个 Registry/Mapping snapshot。若 Server、Tool Schema 或 mapping revision
漂移，执行被拒绝或重新检索，而不是静默调用新接口。MCP Client 不负责自然语言理解、权限定义、
目标选择、订阅调度或 QQ 发送；这些职责分别属于 Perception、Authorization、Proactive 和
Output 模块。

### 8.5 当前服务矩阵

| 服务/Provider | 统一能力 | 数据与调用方式 | 当前边界 |
| --- | --- | --- | --- |
| iCourse / 评课社区 | 课程搜索、课程详情、评论、统计、公开查询 facade | stdio MCP；匿名访问公开页面/缓存，结果带来源 | 已完成自然语言单步闭环；不开放爬取、导出等管理工具 |
| USTC Young / 二课 | 活动搜索、活动详情、筛选项、连接状态 | stdio MCP；复用 `pyustc`，账号由 SecretRef 注入子进程 | 只读公开活动事实；报名、取消、申请人和个人记录不作为能力 |
| USTC Academic / 教务 | 学期列表、开课搜索、考试搜索、教学日历 | stdio MCP；公开目录和校历源 | 查询学期/开课/考试；不执行教务写操作 |
| USTC Curriculum / 培养方案 | `curriculum_public_query` | stdio MCP；读取 `docs.mmdustc.top/curriculum` 研究快照 | 2015–2026 范围的公开研究资料；不是实时 SIS 或毕业审核 |
| NotifAI | 通知搜索、通知详情、月/周日历、截止提醒、来源、分类、统计 | stdio MCP；调用 `https://notifai-api.enthusjast.cc/api` 公开 API | PR #9 新增并已合入主分支；只读，不保存正文，不接受任意 URL/写操作 |
| USTC Shuttle | `ustc.shuttle.public-query.v1` | 本地 JSON 版本化时刻表 Builtin，不联网 | 解析校区、起终点、日期和时间；数据更新需发布新快照 |

PR #10 选择性整合另提供以下外围 Server 资产。它们与上表使用相同的 strict Server Registry 和
stdio 传输形态，但当前只有 Server 配置，没有 Capability mapping；“可发现”不等于 Runtime
“可调用”。每个 Server 的 MCP 面只有一个查询工具，抓取和写入只属于运维 CLI。

| 可选 Server | 唯一 MCP Tool | 数据边界 | 当前状态 |
| --- | --- | --- | --- |
| Local Recommendations | `local_recommendations_public_query` | 仓库种子与本地运维缓存；查询不更新计数，不调用地图 | Registry-only、cache-only、默认关闭 |
| Training Plan | `training_programs_public_query` | 教务处公开本科专业/院系年度一览缓存，不是毕业审核 | Registry-only、cache-only、默认关闭 |
| Campus Events | `campus_events_public_query` | 中国科大主页通知公告缓存，来源与 NotifAI 不同 | Registry-only、cache-only、默认关闭 |
| College Notice | `college_notices_public_query` | 已配置数学、计算机、物理学院 HTTPS 官网通知缓存 | Registry-only、cache-only、默认关闭 |
| Library | `library_hours_public_query` | 图书馆各校区公开开放时间缓存 | Registry-only、cache-only、默认关闭 |

这五个 Server 没有加入 `configs/astrbot/mcp_server.json`。当前生产 Capability 组合会为已映射
Provider 建立 health；在可选 Provider 加载语义完善前，不以一个表面上的 disabled mapping 把
外围资产带入生产启动和健康链。

NotifAI 的七项稳定 capability ID 为：

```text
notifai.notices.search.v1
notifai.notices.get.v1
notifai.notices.calendar.v1
notifai.notices.deadlines.v1
notifai.sources.list.v1
notifai.categories.list.v1
notifai.stats.read.v1
```

NotifAI Client 使用 `httpx`，关闭环境代理继承，限制 URL scheme/host、字段长度、列表数量、
附件和总 payload 大小；HTTPX/httpcore 日志不记录查询参数。Server 统一返回
`schema_version/ok/data/error/source/observed_at/warnings` envelope，并把通知标题、摘要、
正文和官网链接标为外部不可信资料。`search_notices(light=False)` 才保留清洗正文，轻量模式
明确省略正文并返回 warning。配置和 Web 目录已纳入 NotifAI，但是否进入某一群的 Effective
Service 仍由群策略、健康和 rollout 计算。

### 8.6 典型 iCourse 闭环

```text
“@嘟嘟哒 查询评课社区吴天”
  → marker/意图识别
  → campus.course-review 资格过滤
  → icourse.public-query.v2
  → icourse/icourse_public_query（一次，operation=course/review/teacher/ranking/stats）
  → Observation Schema + 来源验证
  → DirectChat 组织结果
  → Persona/Final Validator
  → 一条最终 Delivery
```

明确“评课社区”的 19 个测试案例均进入正确映射；普通聊天、合理澄清或无足够实体的请求不
调用 MCP。培养方案查询会将“25级”归一化为 2025，避免误命中专业代码；校车查询直接在本地
时刻表上完成，不建立 MCP Session。

## 9. Memory v2：长期记忆与上下文治理

### 9.1 三种状态分离

系统把运行检查点、近期会话上下文和长期语义 Memory 分开：

| 数据 | 所有者 | 是否可作为长期记忆 |
| --- | --- | --- |
| Runtime state/checkpoint | Runtime State Store | 否 |
| recent messages/reply chain | Conversation Context Store | 否，按本轮预算读取 |
| user/group/episodic record | Memory Repository | 需显式 Scope 和 Write Gate |

### 9.2 Scope 与检索

`MemoryScope` 绑定 platform、Bot、conversation、group/user、Persona 和 memory type。Repository
只接受由授权策略签发的 `ScopeSelector`：当前会话、当前群或安全用户画像是三个命名模式，
缺字段、过期证明、错 Actor、错请求或错 policy 都拒绝。

检索流程为：

```text
身份一致性
  → 精确 Scope 过滤
  → TTL / visibility / sensitivity
  → 去重与冲突分组
  → recency / M0-M1-M2 CJK BM25
  → bounded ContextMemoryEvidence
```

S14 已完成 JSON v2 原子状态、版本、tombstone、CAS 删除、归档/恢复、崩溃重放、scoped export、
纯 Python CJK BM25 和固定合成评测。相似度只在已授权集合内排序；过期、Restricted、跨群和
跨用户记录不能通过高相似度进入上下文。

### 9.3 Write Gate

任何自动记忆先生成 `MemoryCandidate`，由 Write Gate 根据来源、Scope、敏感度、置信度、冲突、
确认和投递依赖返回 `REJECT/ALLOW/REQUIRE_CONFIRMATION/DEFER`。密码、Token、Cookie、私钥、
QQ 登录态和推断出的敏感属性直接拒绝；工具结果没有来源和政策证明不能成为用户事实。

当前生产 Runtime 没有挂载 Memory Retrieval/Write Gate，运行状态保持 `memoryWrites=0`，
旧 `/remember` 是独立 JSON CRUD，不被重新命名为 Memory v2。真实 Iris SDK、embedding/hybrid
检索、自动摘要和授权数据人工质量评测属于后续接入工作。

## 10. Persona、Response Composer 与 LONG 合并转发

### 10.1 Persona 的职责

`PersonaDefinition` 由版本、角色档案、VoiceRules、channel rule、安全说明和 Renderer Policy
组成；角色关系等叙事内容保存在版本化 `dududa.md` 源资产中。当前 `dududa` 资产表达“可爱、轻松、聪明、技术问题认真”的基线，
但 Persona 不授予权限、不决定是否调用工具、不改变 Memory Scope，也不拥有事实裁决权。

DirectChat 在一次模型生成中同时注入已解析 Persona、群聊规则和 ResponsePlan，让人格通过
措辞、节奏、关注点和信息取舍自然体现，不靠生成后再追加固定口号、机械卖萌或随机表情。

### 10.2 Draft → Render → Validate

Composer 先把工具结果、来源、错误、不确定性、目标和必要安全提示组织成 `DraftResponse`，并
为课程名、教师、分数、日期、能力状态和拒绝理由建立 `FactAnchor`。Renderer 只能改语序、
句式、口语程度和允许的风格偏好；不能改数字、删引用、改变目标、弱化拒绝或声称调用了不存在
的模型/工具。

最终 `RenderValidator` 比较 Draft/Final 的事实锚点、引用、附件、目标和约束，随后由
Content Safety 产生最终判定。模型 Renderer 不可用时，确定性 Finalizer 走同一校验链。

### 10.3 ResponsePlan 与分片

`ResponseProfilePolicy` 根据当前消息的明确详略要求、复杂度、验证需求、群策略和平台上限选择：

- `SHORT`：结论、问候、轻量探测；
- `MEDIUM`：结论加必要解释，日报默认档位；
- `LONG`：多步论证、比较和完整研究摘要。

Answer Profile 与 Model Tier/Reasoning 独立。LONG 的可见预算、最大字符数、最大分片数和必需
章节写入 ResponsePlan；Reasoning token 另由 Model Router 计费。输出先按自然边界分段，再由
OneBot Adapter 决定普通消息或合并转发，避免 Persona 为满足平台长度而删除事实。

## 11. 主动消息、订阅与来源框架

### 11.1 独立的 Initiated Run

主动行为没有用户入站消息，不能伪造系统用户或 `MessageEnvelope`。它从独立的
`ProactiveDeliveryOrchestrator` 进入：

```text
Durable Scheduler / Topic Projection
  → ScheduleOccurrence 或 ConversationOpportunity
  → ProactiveTrigger
  → 持久 CAS claim / cooldown
  → Target + Grant + Subscription 验证
  → 固定只读 Capability Plan
  → SourceBatch 规范化、去重和新鲜度检查
  → ResponsePlan + Composer + Persona
  → 发送前重新授权、quiet hours、配额、kill switch
  → PreparedDispatch → OutputAdapter → DeliveryReceipt
```

### 11.2 Conversation Probe

Probe 是群级、低频、公共话题相关的短探测。它要求主动 allowlist、`active` 群策略、新鲜的
脱敏话题快照、最小静默时间、长冷却、当日配额和有效发送授权；不针对个人、不读取个人画像、
不连续追问。无明确回应只记为删失观测并进入长冷却，不自动追加消息。

### 11.3 Scheduled Digest

日报订阅绑定精确会话 Scope、创建者授权、来源集合、IANA 时区、发送时间、星期、quiet hours、
misfire 策略、条目/字符/Token 上限、Answer Profile、Persona 和 revision。订阅的预览是独立
`PREVIEW` 入口，只返回授权操作者，不创建 occurrence、Dispatch 或 DeliveryReceipt。

### 11.4 来源治理

来源结果统一包含外部 ID、规范 URL、发布时间、观察时间、来源 revision、内容摘要、引用和
warning。外部网页和通知内容被包在数据边界中，不能修改 system prompt。来源抓取、游标、去重
和许可信息由 Source Registry 管理；MCP 只提供读取能力，不拥有调度和发送。

S15A–S15E 已完成契约、SQLite Scheduler、IANA/DST、misfire、Source fixture、Digest Shadow
和 Probe Shadow 的离线链路。真实 Source Adapter、群 Projection、持久 Probe state、模型
合成、Output 和 QQ 发送尚未接入生产组合；因此当前主动行为仍为 no-send/shadow。

## 12. Bot Control Plane 与群服务初始化

### 12.1 一个逻辑控制面

Web 是管理员的 Bot Control Plane，不是第二套 Agent Runtime。它查询 Runtime、MCP、Plugin、
Memory、Proactive、Model 和 Delivery 的投影；所有写操作都转成 Core Command，由统一授权、
revision CAS、幂等、Audit 和 Receipt 处理。浏览器缓存、UI 标签和本地开关不能成为运行时事实。

### 12.2 GroupServiceProfile 与 Assignment

Bot 检测到新群后先进入 `PENDING_PROFILE`，不自动欢迎、不取得回复或主动发送权。管理员可在
预览页选择版本化 `GroupServiceProfile`，系统计算：

```text
Effective Services
  = Desired Profile
  ∩ Installed + Healthy Definitions
  ∩ Current Capability / Group Grants
  ∩ Rollout + Budget + Kill-Switch Eligibility
```

确认后，Core 原子发布绑定精确 platform/Bot/group Scope、Profile revision、Desired/Effective
服务、授权证据、LKG revision 和 Activation Receipt 的 `GroupServiceAssignment`。更新、暂停、
恢复和回滚均使用 expected revision；并发管理员只有一个 CAS 成功。

Profile 可以指定模型档位、推理强度、回答长度、回复强度、上下文预算、群聊风格和主动行为初值，
但不能自行授予 Capability、扩大记忆、改变权限或开启发送。Group Context 只是带 TTL 的弱先验，
Bandit 只能在已经允许的安全等价候选中排序。

### 12.3 控制台功能面

当前 Vue 3 + Node 网关提供：

- 多账号 QQ 工作区、好友/群目录、历史消息、实时 SSE 事件和会话游标；
- 受限的普通文本、回复、@、表情、图片、语音、视频、文件和合并转发显示/发送；
- Agent Runtime 状态、群服务 Profile/Assignment、Desired/Effective 差异和 LKG；
- MCP Server/Capability Schema、插件目录、健康和安装状态；
- no-send 内测页、Runtime 预览、Trace/Eval/Health 运维投影；
- Sub2API 用量只读概览、插件配置和受治理命令入口。

网关不提供任意 OneBot action 转发；OneBot Token 只用于 NapCat 到服务端的反向 WebSocket，
不会下发浏览器。公网发布时，外层 Caddy/Authentik 负责操作员登录，网关内部仍校验同源和
operator session。

## 13. 安全、隐私与供应链设计

### 13.1 信任边界

QQ 消息、附件、昵称、回复、网页、MCP 结果、模型输出、Provider 错误、Web 表单和插件输出都
是外部输入。只有 Connector 解析的身份、版本化配置、Capability/Model Policy、受控 SecretRef
和经过校验的 Schema 才进入可信边界。Persona 文本不承担认证或授权。

### 13.2 授权、确认、限流和预算

`AuthorizationPolicy` 根据 Actor、精确 ConversationScope、Action、Resource、Capability、
风险和隐私返回 `ALLOW/DENY/REQUIRE_CONFIRMATION`。高风险操作需将确认绑定到 actor、Scope、
动作、payload digest、执行 ID、幂等键和有效期。Interaction Limiter、Budget Ledger 和
Output Circuit 在实际调用/发送前再次检查。

### 13.3 隐私与日志

隐私级别区分 `PUBLIC`、`CONVERSATION`、`PERSONAL`、`SENSITIVE` 和 `RESTRICTED`；Provider、
Capability 和 Memory 各自声明可接受级别。Trace 和指标使用低基数脱敏引用，默认不保存原始
消息、Prompt、completion、思维链、评论正文、附件、Cookie、Token 或 API key。外部 URL 只在
allowlist 和 scheme 校验通过后使用；NotifAI 等服务还限制字段长度、附件数量和总 payload。

### 13.4 容器、网络与第三方

默认服务只在回环或内部 Docker 网络发布；MCP stdio 子进程使用固定工作目录、命令和环境变量
allowlist。Young 的 CAS 凭据以 SecretRef 注入子进程，不写入配置仓库。Iris、Better Reminder、
ChatSummary 等第三方资产保留锁定版本和补丁信息，不能自动成为 2.0 Agent 或第二控制面。

## 14. 运维、部署、备份与回滚

### 14.1 仓库与服务分层

```text
packages/dududa-agent/    Core Domain、Ports、Runtime、Policy、Eval
apps/astrbot-plugins/     AstrBot Adapter、内建 Provider、兼容插件
apps/web/                 Vue/Node Control Plane 与 OneBot Gateway
services/mcp/             iCourse、USTC Campus、NotifAI、Unified Worker
configs/                  无凭据的模型、Persona、MCP、Capability mapping
deploy/                   Compose、镜像、网络和挂载
ops/                      初始化、同步、安装、审计、回滚和评测 CLI
docs/                     设计、研究、Runbook 和证据台账
```

### 14.2 发布流程

发布由 `manage.sh`/`ops/cli` 驱动：检查 Python/Node 依赖和 Schema，构建 AstrBot/Web/MCP 镜像，
原子安装 owned plugins，启动依赖服务，执行 health/status/contract smoke，再开启对应 rollout
行为。运行数据位于仓库外的 AstrBot/NapCat/Web/数据库目录；`.env`、QQ 登录态、数据库、聊天
导出和 Provider evidence 不提交 Git。

### 14.3 备份与恢复

S16 Operations 提供 Release Manifest、状态快照、SQLite Backup API、确定性 Restore Plan、升级
失败单次回滚和 Compose mount/network contract。Authentik 使用独立 PostgreSQL，当前部署已生成
权限为 0600 的数据库备份。应用回滚优先恢复上一份可运行 release；数据恢复使用受控 backup/
restore，不在故障时自动覆盖线上状态。

### 14.4 当前公网控制台交付

本轮在 `mmdustc.top` 外部栈完成了控制台公网接入：

1. Caddy 为 `console.mmdustc.top` 配置独立站点，并反向代理到本地 Web 服务；
2. 控制台站点通过 Authentik forward-auth，应用绑定 `Dududa console access` 组；
3. Web 服务仅绑定宿主机回环地址，由 Caddy 对外提供 HTTPS；
4. 登录成功后可访问工作区和 `/api/workspace`，未登录请求被重定向到 Authentik；
5. 恶意跨源写请求被控制台同源策略拒绝。

当前公开稳定入口是 `https://console.mmdustc.top:8443/`；`auth.mmdustc.top` 是登录入口。标准
无端口 URL 需要 Cloudflare Origin Rule 覆盖 `console.mmdustc.top` 后再启用，应用侧 443 监听
已经就绪。登录账号只在交付给操作员的私密渠道提供，不写入本文或仓库。

## 15. 评测与工程证据

### 15.1 分层证据模型

| 证据层 | 验证对象 | 当前结果 |
| --- | --- | --- |
| Unit/Contract | DTO、Schema、Registry、Policy、CAS、错误映射 | Core 与 MCP/Capability 重点集合持续验证 |
| Offline integration | Runtime、Planner、Memory、Scheduler、Control Plane | S01–S22 离线范围已完成；固定 fixture 可重放 |
| Provider smoke | 三模型调用、模型 ID、usage、deadline | Luna/Terra/Sol 各完成真实 Chat 抽样，Responses 也有抽样 |
| MCP vertical slice | Connector → Tool → Observation → Composer → Delivery | iCourse 75 题 Fake Delivery 75/75；二课/教务/培养方案/校车有单步证据 |
| Host ingress | OneBot JSON → AstrBot Event → Runtime | 合法 75/75 进入宿主，QQ 发送为 0 的 no-send 验证 |
| Human/live | 真实群消息、人工质量、长期 SLO | 真实 QQ 人工端到端仍需一条用户触发消息闭合 |

### 15.2 已有量化结果

- iCourse 75 条自然语言题：75/75 Bridge、75/75 Runtime completed、75/75 Fake Delivery，
  73 次 MCP，显式“评课社区”案例 19/19 正确命中；人工终审 49/75 完整。
- AstrBot 内存 WebSocket：75/75 合法 OneBot JSON 生成 Event 并进入 RequestFactory，发送为 0；
  50 ms 延迟测试暴露过 `1,2,3 → 2,3,1` 的入队乱序，故宿主并发顺序仍是已知待验项。
- NotifAI/MCP/检索相关本轮聚焦测试 18/18 通过；Web 当前类型检查通过，前端/服务端聚焦集合
  20 个文件、77 个前端与 64 个服务端测试通过。
- Memory v2 固定合成评测覆盖 M0 无记忆、M1 recency、M2 CJK BM25，并把跨 Scope、过期、
  tombstone 和 Restricted strata 作为零暴露断言。
- S20 Bandit 已完成 IPS/SNIPS/DR/ESS 的合成 OPE；没有训练 Worker、生产 Router hook 或在线探索。

### 15.3 指标体系

| 模块 | 质量指标 | 运行指标 |
| --- | --- | --- |
| Perception | Intent macro-F1、实体 F1、指代匹配、tool-need recall | 误插话率、Schema 合法率、P50/P95 |
| Model Router | Tier 选择准确率、fallback 成功率 | latency、usage、成本、健康 TTL |
| Capability/MCP | Recall@K、Plan/参数合法率、完成率 | 调用成功率、步数、重试、熔断 |
| Memory | Precision/Recall/MRR、冲突/重复率 | Scope 违规数、候选数、token、P95 |
| Response/Persona | 事实锚点保持、引用完整、风格评分 | 分片数、长度、Validator reject |
| Proactive | 来源新鲜度、内容相关性、退订准确 | occurrence claim、发送率、冷却和删失反馈 |
| Rollout | 任务完成和人工满意度 | 重复回复、未知投递、错误分类、回滚次数 |

指标标签不含真实 user/group ID、原文或凭据；按群/会话聚类分析反馈，避免把同一群消息当作独立
样本。

## 16. 关键技术难点与设计取舍

### 16.1 在不牺牲自然语言体验的情况下保持确定性边界

群聊请求往往省略主语、混用昵称和站点名称。完全依赖规则会漏掉口语，完全依赖模型又会把
“帮我报名”误判为公开查询。2.0 采用 Hybrid Perception：规则锁定身份、@、会话、站点 marker
和硬性不支持范围，Haiku 只补充结构化语义，Merger/Validator 负责合并冲突。这样模型可以
提高召回，却不能修改权限、Scope、预算或工具资格。

### 16.2 多 Provider 的统一边界

不同供应商对 reasoning、structured output、usage 和取消的字段语义并不一致。系统没有把
供应商响应直接向上暴露，而是用 Provider Descriptor、Binding Evidence、Schema Codec 和
Provider-neutral Receipt 统一表示；每个调用再由 Adapter 映射到 AstrBot `text_chat` 或
Responses/Chat Completions。取舍是初期需要编写 conformance 和映射代码，但后续替换模型不需
改 Runtime、Planner 或 Persona。

### 16.3 MCP 的长生命周期与可验证性

短脚本式 MCP Client 会在每次请求重启进程，造成并发、Schema 漂移和超时语义不一致。统一 Client
用 Registry Snapshot 固定 Server 定义，以长生命周期 session 处理 discovery/call/close，
再通过 Capability mapping 把原始 Tool 收敛成业务能力。取舍是新增一个 Registry 层，但换来
Server 隔离、健康、熔断和同一套 Executor/Validator。

### 16.4 记忆质量与隐私的先后关系

embedding 或图检索可以提高召回，却不能修复一个错误的群/用户归属。Memory v2 先实现精确 Scope、
tombstone、冲突和 Write Gate，再比较 recency、BM25、embedding/hybrid；生产默认关闭读写，
不是因为后端无法工作，而是因为质量评测和真实授权数据尚未完成。这一顺序让每种新检索器都
必须在已授权集合内证明收益。

### 16.5 事实回答、人格和平台消息组件的协调

课程评分、校历日期和通知截止日必须保持原值，Persona 又需要自然表达，QQ 还存在消息长度和
合并转发约束。DraftResponse 用 FactAnchor/Citation 固化事实，ResponsePlan 固定可见预算，
Renderer 只改语言，Output Adapter 最后决定 Plain/Nodes。三层各自验证，避免把“风格润色”
误当成事实重写。

### 16.6 状态、重复和未知结果

QQ、MCP 和模型调用都可能在网络断开时返回未知状态。Runtime 用 CAS checkpoint、logical
operation ID、幂等键、DeliveryReceipt 和 reconciliation 区分“未发送”“已发送但回执丢失”
与“明确失败”。对非幂等副作用不自动重放；对只读查询可在策略允许时有限重试。这样恢复逻辑
与业务事实一致，不靠重复发送来猜测结果。

### 16.7 适配旧插件而不复制第二套 Runtime

旧插件包含命令、数据库和用户习惯，直接删除会破坏兼容，原样保留又会形成第二个监听器。2.0
采用薄 Adapter：保留 ID、文案和回滚材料，把行为转换到 Core Port；Target Talk、ReplyPolish、
旧 iCourse Client 在验证完成后退出默认运行面。兼容层只处理历史协议，不拥有新的权限或发送权。

## 17. P0/P1/P2 发展路线与完成定义

历史恢复的完整计划见 [P0/P1/P2 开发计划](../refactor/p0-p1-p2-development-plan-recovered.md)。
它把项目分为三个可验证层级：

| 层级 | 交付重点 | 进入下一层的信号 |
| --- | --- | --- |
| P0：最小可信内核 | Core DTO/Schema、安全、Connector 兼容、Memory Scope、静态 Router、离线 Eval/Trace | 核心不依赖平台；Scope 泄漏、越权、预算越界为 0；插件行为可回滚 |
| P1：可用纵向闭环 | 一条入站 Runtime、Perception/Social、iCourse Tool Loop、Response/Persona、受控 Canary | 可重复的端到端 Trace/Receipt；无重复 Tool/回复；逐群 feature flag 可回退 |
| P2：产品化与规模化 | Memory 效果、更多来源、Web Control Plane、部署/回滚、真实群阶梯、兼容清理 | 真实群人工验收、长期 SLO、来源新鲜度和回滚证据齐全 |

当前 S01–S22 以及 S23A–S23E 的离线既定范围已完成；S23 实时入站处于 Canary。后续工作按照
`offline → shadow → 单群明确 @ → canary → 全量` 推进，主动发送、在线学习和高风险能力不因
模型质量提升而跳过授权阶段。

## 18. 当前实现状态与边界

### 18.1 已实现并可复现

- 框架无关 Core 契约、Domain/Port 分层、Runtime 状态机、CAS 与投递回执；
- Rule + Haiku Schema Perception、确定性 Social Decision、静态 Luna/Terra/Sol 路由；
- Capability Registry/Retrieval/Planner/Executor/Observation Validator；
- 5 个独立 stdio MCP Server（iCourse、NotifAI、USTC Young、USTC Academic、USTC Curriculum），
  21 个映射和 1 个校车 Builtin；
- 5 个独立、默认关闭、只查询缓存的 Registry-only MCP Server（Local Recommendations、
  Training Plan、Campus Events、College Notice、Library），均只有一个 public query Tool，未进入
  Capability Catalog/Planner/生产健康链；
- 独立 `astrbot_plugin_dududa_social` 社交策略插件，只提供 namespaced 显式命令和纯规则 API，
  不监听普通消息、不调用模型/MCP、不自动发送；
- iCourse、二课、教务、培养方案、校车的单步自然语言主链；NotifAI 的服务端、Schema、mapping、
  registry 和 Web 目录；
- Memory v2 生命周期、JSON v2、CJK BM25、删除/导出/恢复和离线评测；
- typed Persona、ResponsePlan、Fact Anchor、LONG 分片/合并转发规则；
- S15A–S15E 主动消息契约、Scheduler、Source fixture、Digest/Probe Shadow；
- S21 Bot Control Plane、GroupServiceProfile、Assignment、LKG、审计和运维投影；
- Caddy + Authentik 保护的公网 Web Console（部署在仓库外的 `mmdustc.top` 栈）。

### 18.2 已实现但默认关闭或仅离线

- Memory 生产读取/写入、Iris SDK Backend、embedding/hybrid 检索；
- 真实主动日报、Probe、来源网络 Adapter 和 QQ 出站；
- Bandit 训练、在线探索、Router/Runtime hook；
- Weather、B50、Reply Review 的生产组合；
- 多 Persona 产品目录、持久用户 `/style` 渲染、多轮 Context、附件语义和 Plugin Runtime；
- 真实 Web 管理员身份系统（公网登录由外部 Authentik 提供，仓库内部网关仍需 operator session）。

### 18.3 当前明确未接入

- 私聊和频道的 2.0 自动回复；
- 附件字节读取、OCR、语音/视频理解；
- iCourse 之外的通用多步复杂计划和任何高风险/写操作；
- 实时校园资讯、arXiv、行业资讯 Server 及生产日报；
- 由真实用户触发并收到 QQ DeliveryReceipt 的完整人工验收；
- 在线群体情境学习、自动 Skill/Prompt/Style 发布。

这些边界是模块状态，而不是产品愿景；新增能力必须在对应模块的 Contract、Scope、Receipt 和
真实入口上有独立证据。

## 19. 参考实现与阅读入口

| 主题 | 入口 |
| --- | --- |
| Core/Runtime | `packages/dududa-agent/src/dududa/runtime/` |
| 感知与社交 | `packages/dududa-agent/src/dududa/perception/` |
| 模型路由 | `packages/dududa-agent/src/dududa/models/`、`apps/astrbot-plugins/astrbot_plugin_dududa_core/adapters/model.py` |
| Capability/MCP | `packages/dududa-agent/src/dududa/capabilities/`、`packages/dududa-agent/src/dududa/mcp/` |
| 校园服务 | `services/mcp/icourse/`、`services/mcp/ustc-campus/`、`services/mcp/notifai/` |
| Memory | `packages/dududa-agent/src/dududa/memory/` |
| Persona/Response | `packages/dududa-agent/src/dududa/persona/`、`packages/dududa-agent/src/dududa/responses/` |
| 主动消息 | `packages/dududa-agent/src/dududa/proactive/` |
| Control Plane | `packages/dududa-agent/src/dududa/control_plane/`、`apps/web/server/control-plane.ts` |
| 运维与证据 | `ops/cli/`、`docs/operations/`、`docs/refactor/PROGRESS.md` |

## 结语

嘟嘟哒 2.0 的核心成果不是某个单独的模型或插件，而是把群聊 Agent 变成一套可解释的系统：
模型带来语言能力，确定性内核守住边界，能力 Registry 连接真实服务，Persona 赋予连续的人格，
Control Plane 让运营者能看见并改变系统，评测和 Receipt 让每次改变都能被复盘。这个结构既能
承载当前校园助手功能，也为未来的群体情境适应留下清晰、可撤销的演化路径。
