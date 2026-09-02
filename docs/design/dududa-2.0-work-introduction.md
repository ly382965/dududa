# 嘟嘟哒 2.0 作品简介

## 一句话定位

嘟嘟哒 2.0 是运行在 QQ 群聊中的受治理群体情境适应 Agent：她能理解自然语言，判断何时
应该回应，按任务难度选择模型，调用校园公开服务，组织带来源的事实，并以稳定而自然的人格
表达；同时把身份、权限、记忆 Scope、预算和消息投递交给可审计的确定性 Runtime。

## 作品背景与要解决的问题

校园群聊中的信息分散在评课社区、二课活动、教务通知、培养方案页面和校车时刻表中。传统
机器人通常只能执行固定命令，或者把所有消息交给一个大模型：前者不懂口语和群聊语境，后者
容易在不该回复时插话、编造事实、调用不合适的工具，甚至把一个群的记忆带到另一个群。

嘟嘟哒 2.0 从“功能插件集合”升级为“受治理的 Agent Runtime”。它解决四个核心问题：

1. 把 QQ/AstrBot 平台事件转换为可测试的通用消息契约；
2. 把语义理解、社交决策、模型选择、工具执行、事实组织和人格表达分开；
3. 把校园服务统一为可发现、可授权、可校验的 Capability，而不是让模型自由调用函数；
4. 在追求自然交流的同时，保持跨群隔离、可回滚、可复盘和可观测。

## 核心功能

### 1. 自然语言群聊入口

NapCat 通过 OneBot v11 将 QQ 消息送入 AstrBot，`AstrBotInputConnector` 生成
`MessageEnvelope`、`Actor` 和 `ConversationScope`。当前运行版本处理群内明确 `@Bot` 的纯文本、
无附件消息；Runtime 会识别空消息、自身消息、未 @ 普通群消息和不支持的附件，并选择回复、
澄清、延期或静默。

### 2. 校园查询助手

系统已接入以下只读能力：

| 场景 | 能力 |
| --- | --- |
| 评课社区 | 搜索课程/教师、查看课程详情和评论、读取公开统计 |
| 二课 | 搜索活动、查看活动详情、读取筛选项和连接状态 |
| 教务公开信息 | 学期、开课、考试和教学日历查询 |
| 培养方案研究 | 按年级/专业查询公开研究快照，支持横向比较 |
| 校车 | 按校区、起终点、日期和时间查询本地版本化时刻表 |
| 校园通知 | 搜索通知、查看详情、日历、截止提醒、来源/分类/统计 |

查询结果经过 Schema 和业务 Validator，带有来源、观察时间、截断和不确定性信息。培养方案
使用公开研究快照，不代替实时毕业审核；二课不提供报名、取消报名或个人学时等写入/个人记录
操作；校园通知只读取公开资料，不保存通知正文。

PR #10 选择性整合还交付五个外围 MCP Server：本地推荐、专业设置、学校主页通知、学院通知和
图书馆开放时间。它们各自只暴露一个读取本地缓存的 `public_query` 工具，已进入 Server Registry
但默认关闭；本轮没有创建 Capability mapping，因此 Planner 和当前生产 Runtime 看不到这些工具。
抓取、缓存刷新和推荐数据维护只存在于运维 CLI，不属于 Agent 自动工具面。

### 3. 有性格但不越权的回答

`dududa` Persona 定义中文语气、句式、技术问题的认真程度、群聊节奏和适量表情。Persona
只负责表达，不负责权限、工具和事实。回答先形成含 Fact Anchor、Citation、Refusal 和
Uncertainty 的 `DraftResponse`，再由 Renderer 生成最终文本并校验。这样嘟嘟哒可以可爱、轻松、
聪明，却不会为了“像一个角色”改动课程分数、删除来源或弱化拒绝。

### 4. 多档模型与回答长度

逻辑模型档位与回答长度独立：

- Luna / Haiku：快速感知、低复杂度任务；
- Terra / Sonnet：普通直接回答和工具结果组织；
- Sol / Opus：复杂论证、比较和复核。

`SHORT`、`MEDIUM`、`LONG` 由 Response Profile Policy 选择，不从模型名称推断。LONG 需要多段
纯文本时由 QQ 合并转发承载；SHORT、MEDIUM 和单段 LONG 使用普通消息。

### 5. 管理员控制台

Vue 3 + Node 网关组成统一 Bot Control Plane，提供 QQ 工作区、账号/群目录、历史消息、实时事件、
Runtime 状态、MCP Schema、插件状态、群服务 Profile、健康、Trace/Eval 和受治理命令。管理员
可以为新群选择版本化 `GroupServiceProfile`，预览 Desired/Effective 服务差异，再激活、暂停或
回滚 Assignment。控制台不是第二套 Agent Runtime，也不能从浏览器直接绕过 Core 发 QQ 或授予
Capability。

## 技术架构

```text
QQ / NapCat / OneBot v11
          ↓
AstrBot Connector
          ↓
MessageEnvelope + Actor + ConversationScope
          ↓
Context Builder
          ↓
Rule Perception + Luna Structured Perception
          ↓
Deterministic Social Decision + Complexity/Tier Policy
          ├──────────────→ Direct Chat（Terra/Sol/Luna）
          ↓
Capability Retrieval → Planner → Executor → Observation Validator
          ↓
Unified MCP Client 或本地 Builtin Provider
          ↓
Response Composer → Persona Renderer → Final Validator
          ↓
AstrBot Output Adapter → OneBot DeliveryReceipt
```

系统分为四层：

1. **交互适配层：**AstrBot、NapCat、OneBot、Web Gateway，处理平台协议和媒体格式；
2. **治理与应用层：**Runtime 状态机、身份/Scope、授权、预算、社交策略、ResponsePlan 和
   Control Plane；
3. **能力与模型层：**Model Router、Capability Registry、Planner/Executor/Validator、
   Unified MCP、Memory 和 Persona Port；
4. **基础设施层：**AstrBot Provider、MCP stdio worker、SQLite/JSON Repository、Output、
   Caddy、Authentik、Compose 和运维 CLI。

核心包不依赖 AstrBot、MCP SDK、NapCat 或供应商 SDK，所有外部实现通过 Port 注入。一次运行
以 CAS checkpoint 获得消息所有权，完成阶段转换，并用 Receipt 记录结果；重复事件返回原结果，
不会启动第二条工具链。

## 模型及 API 调用方式

### Provider 映射

| 产品别名 | Tier | 逻辑 Provider | 模型 ID |
| --- | --- | --- | --- |
| Luna | Haiku | `dududa-luna` / `astrbot-luna` | `gpt-5.6-luna` |
| Terra | Sonnet | `dududa-terra` / `astrbot-terra` | `gpt-5.6-terra` |
| Sol | Opus | `dududa-sol` / `astrbot-sol` | `gpt-5.6-sol` |

逻辑 ID、Provider Endpoint、模型凭据和数据驻留设置由运行环境注入，仓库只保存不含凭据的
候选配置。静态 Router 根据角色、Schema、模态、隐私、健康、预算和 deadline 过滤候选，再按
固定优先级选取；模型不能通过文本自行提升 Tier 或获得工具权限。

### OpenAI-compatible 接口

真实部署使用 OpenAI-compatible Provider。AstrBot 适配器调用统一的 `text_chat` 端口，传入：

```text
prompt
system_prompt
model
max_tokens
request_max_retries
reasoning_effort（按 ReasoningProfile 映射）
```

返回的 `completion_text`、usage、finish reason、处理边界、驻留和 retention 被转换成统一
`ProviderResponse`。结构化感知、工具计划和审校使用版本化 JSON Schema；Schema 不合格时只做
一次受控修复。

仓库还提供 Responses API 的独立连通性抽样，形式为：

```http
POST {兼容接口}/v1/responses
{
  "model": "gpt-5.6-luna",
  "instructions": "Return one short acknowledgement.",
  "input": "Synthetic no-send check.",
  "max_output_tokens": 32
}
```

Responses API 的 `output_text`/`output` 与 usage 只用于 Provider Evidence；它不进入 QQ 输出、
工具调用或 Memory 写入。生产 Chat Completions 适配与 Responses 抽样共享同一逻辑 Provider
契约，因而更换供应商时不需要改 Runtime。

## 全部模块说明

### Core Domain 与 Runtime

`domain` 定义身份、消息、内容、能力、投递和通用原语；`contracts` 定义 Schema/版本/规范化
编码；`runtime` 管理状态、上下文、模型预算、工具步数、取消、幂等、交付和恢复；`ports` 只
描述可替换的外部接口。Runtime 的关键阶段是：接收、预处理、构造上下文、感知、社交决策、
模型选择、工具执行、验证、合成、人格渲染、最终校验和投递。

### Perception 与 Social Decision

`perception` 包含规则感知、语义 Schema、Merger、Validator、复杂度评估和 Social Policy。
规则确定 @、回复、命令、marker 和不支持范围；Luna 提供 intent/entity/reference 等候选；
确定性策略决定 `IGNORE/REACT/DIRECT_REPLY/USE_TOOLS/ASK_CLARIFICATION/DEFER`。

### Models

`models` 包含 ModelRole、Tier、ReasoningDepth、Endpoint Descriptor、RouteDecision、Admission、
健康 Evidence 和 usage 账本。模型角色包括 Perception、Social Decision、Tool Planning、
Direct Chat、Response Composition、Persona Rendering、Memory Summary 和图像能力。当前运行三档
均采用最低 `light/low` 思考深度，复杂度只影响合法候选选择，不把长答案自动当成高难任务。

### Capability Runtime

`capabilities` 将业务能力与原始 MCP tool 解耦，包含 Catalog、硬过滤 Retrieval、有限 Planner、
Argument Binder、Executor、Observation Validator、Provider health 和 mapping。Planner 看见的
只有通过权限、Scope、风险、隐私、健康和预算过滤的候选摘要。

### MCP 基础设施

`mcp` 包和 `services/mcp/unified-worker` 管理 Server Registry、stdio 生命周期、discovery、
Schema TTL、并发、超时、取消、重试、熔断和错误映射。五个独立 Server（iCourse、NotifAI、
USTC Young、USTC Academic、USTC Curriculum）各有自己的 session 和 revision；MCP 不负责
权限、调度、目标选择或发送。另有五个 PR #10 Registry-only Server 作为默认关闭的可选资产；
Registry discovery 不会自动生成 Capability 或授予 Planner 权限。

### Memory v2

`memory` 包实现 MemoryScope、Selector、Record、Candidate、Repository、Write Gate、删除/归档/
恢复、JSON v2、tombstone、CAS 和 CJK BM25。它把用户画像、群记忆、情节记忆和显式记忆分开，
把短期会话上下文与长期记忆分开。当前生产默认关闭读取和写入，离线实现用于契约和质量评测。

### Persona 与 Response

`persona` 管理版本化 `dududa`/`neutral` 资产和 Catalog LKG；`responses` 管理 SHORT/MEDIUM/LONG、
可见预算、Fact Anchor、Citation、Uncertainty、SafetyNotice、分片和最终校验。两者共同保证
回答既有连续人格，又不会改变事实或安全语义。

### Proactive

`proactive` 提供 initiated-run、Target/Grant/Subscription、持久 Scheduler、时区/DST、来源游标、
Digest Composer 和 Probe Shadow。日报和探测拥有独立授权和幂等状态，不伪造用户消息。当前契约、
Fixture 和 no-send Shadow 已完成，真实来源、群 Projection、Output 和 QQ 发送尚未进入生产。

### Bot Control Plane

`control_plane` 提供操作员会话/RBAC、GroupServiceProfile、Assignment 生命周期、Desired/Effective
差异、命令网关、Audit、Receipt、SQLite LKG 和 Runtime Snapshot。Web 查询投影，Core 执行命令；
管理员能控制服务初值，却不能以 Profile 自授予能力或发送权。

### AstrBot/NapCat/Web 与运维

AstrBot 插件负责适配和组合；NapCat 是 QQ Connector；Web Node 网关提供同源 HTTP/SSE、OneBot
反向 WebSocket 和受限 action；Vue 前端提供工作区和管理视图；Compose 管理容器网络；`ops/cli`
提供安装、同步、Provider conformance、健康、评测、备份和回滚命令。

PR #10 的非重复社交规则位于独立 `astrbot_plugin_dududa_social`。它只响应
`/dududa-social` 显式命令，总开关、逐功能开关和群 allowlist 默认关闭；不注册普通消息 Handler，
不调用模型/MCP，也不自动发送。生日、睡眠、投票和互动状态使用独立 SQLite，并按平台、Bot 和
会话 Scope 隔离；情绪、夸奖和关键词只作为纯策略信号。

## 创新点

1. **治理内核与能力资产分离。** 能力可以独立升级、Shadow 和回滚，模型不直接拥有系统权限。
2. **Perception/Social Decision 双层决策。** 既保留自然语言理解能力，又把是否插话变成可解释
   的社交策略，而不是一个难以审计的概率。
3. **Model Router 与 Capability Router 分离。** 模型负责语言和候选，工具资格由 Registry、
   Policy 和 Executor 负责，MCP 发现不等于授权。
4. **事实锚点驱动的人格表达。** Composer 先锁定事实、来源、拒绝和目标，Persona 只改表达，
   解决“风格润色导致事实漂移”的常见问题。
5. **主动消息使用独立因果边界。** 日报/Probe 不伪造入站消息，有独立 Target、Grant、订阅、
   冷却和投递回执，为将来的主动能力提供可回放基础。
6. **群服务 Profile 化。** 新群先进入 Pending，管理员以版本化 Profile 激活服务；群体情境和
   学习只能提供弱先验，不能暗中扩大服务范围。
7. **校园服务的统一语义层。** iCourse、二课、教务、培养方案、通知和校车虽然来源、认证和
   数据形态不同，但对 Runtime 都表现为相同的 CapabilityResult/Observation；新增外围 Server
   可以先作为 default-off Registry 资产交付，经过来源与 mapping 审核后再进入 Planner。
8. **从离线证据到真实群的渐进发布。** 固定 fixture、no-send Shadow、单群 Canary 和真实
   Delivery 使用同一契约，质量、权限和运维指标可以沿阶段比较。

## 实现与验证概况

截至 2026-09-02：

- S01–S22 及 S23A–S23E 的既定离线范围已完成；
- iCourse 75 条自然语言题完成 75/75 Runtime 和 Fake Delivery，显式站点 marker 19/19 正确；
- 75 条合法 OneBot JSON 均进入 AstrBot 内存入口的 no-send Runtime；
- Luna/Terra/Sol 均完成 Provider Chat 调用抽样；
- NotifAI PR #9 已合并，七项只读 capability、映射、Schema、Registry 和 Web 目录已纳入；
- PR #10 中五个非重复 MCP 已收敛为单工具、cache-only、Registry-only 的默认关闭资产，独立社交
  插件已加入 owned-plugin 安装流程且默认不接管普通群消息；
- Memory、主动消息和 Bandit 的离线契约/评测已具备，但生产开关仍分别关闭或 shadow-only；
- 当前 2.0 入站为群内明确 @ 的纯文本，真实 QQ 用户触发的人工端到端投递验收仍是下一步。

## 作品价值

嘟嘟哒 2.0 将校园信息服务、群聊社交性和 Agent 工程治理放进同一个可运行系统。用户看到的是
一句自然的回答，系统内部则完成了身份校验、上下文裁剪、模型路由、能力授权、来源验证、事实
组织、人格渲染和投递对账。它既能作为当前的校园群助手，也提供了一条从固定插件走向可组合、
可观察、可回滚 Agent 产品的工程路径。

## 关键词

`QQ Agent`、`AstrBot`、`NapCat`、`OneBot v11`、`OpenAI-compatible API`、`Responses API`、
`Chat Completions`、`MCP`、`Capability Runtime`、`Scope-first Memory`、`Persona Renderer`、
`Bot Control Plane`、`Contextual Bandit`、`校园信息服务`

详细的 PR #10 资产筛选、工具契约、部署接线和回滚方式见
[PR #10 选择性整合报告](../integrations/pr10-selective-integration.md)。
