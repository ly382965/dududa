# S23 单群真实场景验证 Runbook

## 1. 当前状态

S23 是发布前的真实证据阶段，不是全面上线。Dududa 2.0 已成为唯一运行 Agent，当前以
Canary 接管群内明确 `@Bot` 的纯文本、无附件消息；旧 1.0 Agent 不再回退接管。群
`364894085` 当前策略快照已将评课、二课、培养方案、教务和校车五项查询设为 `on`（不据此
宣称 NotifAI 已在该群启用）。本次 100 题本地 Runner 另以独立 fixture 策略覆盖 NotifAI，
五类目标群输入均完成 no-send 耦合抽样：每次只选择目标 Capability，普通聊天保持零 Tool 调用。

当前校园查询形状为五个已启用的 Unified MCP Server（iCourse、NotifAI、二课、教务处、
培养方案）加一个本地校车 Builtin 插件。教务学期、开课、考试和教学日历均已进入单步
Planner；开课/考试在同一次 MCP 调用内把学期名称解析为官方 semester ID。该证据仍不等于
用户触发的真实 QQ Tool/Delivery Receipt，以下门禁尚未关闭：

- `configs/release/s19-pilot-slo-v1.json` 仍为 `s23_ready=false`；
- 没有校园、arXiv 或行业资讯的 live Source Adapter；
- 没有生产 Probe Projection/Output composition；
- 没有五项校园查询的用户触发 QQ 端到端回执；
- 没有近期多轮群聊 Context、生产 Memory 或在线 Bandit；可信 Capability 失败答复已在
  2.0 Composer/Persona/Final Validator/Delivery 链完成并由 100 题 no-send 案例覆盖。

本 Runbook 的自动验证继续使用 no-send/Fake Output；不要由测试程序向 QQ 群发送消息，也不要
把查询 MCP 误称为资讯日报来源。iCourse 是评课社区 MCP，校车是本地只读插件，两者都不是
校园资讯 Source Provider。

当前入站 production shape 的边界如下：

- 配置默认仍为 `runtime_enabled=false`；当前唯一宿主已显式启用。关闭、配置非法或模型不可用
  时保持 unavailable，不再把事件交给已下线的 1.0 Agent；
- `runtime_models_json` 只声明实际接入的 1–3 个 Haiku/Sonnet/Opus Endpoint，API Key 仍由
  AstrBot Provider 管理；
- Dududa Core 继续拥有 Tier、预算、Runtime 状态和 rollout 所有权；Provider 只实现模型调用 Port；
- 2.0 主链使用 Luna/Haiku Hybrid Perception；规则感知只作降级组件。启用 Tool 时按类别
  执行一次确定性单步 Capability：iCourse、NotifAI、二课、培养方案和教务经 Unified MCP，
  校车经本地 Builtin Provider；随后只执行一次 DIRECT_CHAT。`off` 零 Provider 调用，
  no-send 预览不调用 QQ Output；
- Builder 优先解析 AstrBot Context 提供的 Provider Evidence；resolver 不存在或返回 `None` 时，
  才读取 `runtime_provider_evidence_path` 指向的仓库外私有 JSON。路径为空、文件非法或
  Provider/model 绑定不匹配时，Runtime 保持 unavailable 并回退 legacy；
- 私有 Evidence 文件只保存模型绑定和验证结论，不保存 API Key、Base URL、QQ 标识或聊天正文。
  文件能够被解析不等于已经完成真实 Conformance；
- 初始 operational health 固定为 `UNKNOWN`。只有 descriptor/revision 匹配且未过期的
  `ModelHealthEvidence` 才能转为 `HEALTHY`。当前宿主已启用有界健康刷新，间隔、单次超时和
  TTL 为 900/15/1800 秒；刷新同时续期本地 Endpoint load 观测，插件关闭时取消任务。

### 1.1 真实 Endpoint 最小可达性抽样

2026-08-15 已在私有进程中对三个候选 Endpoint 做一次最小请求；凭据和私有 Base URL 没有写入
仓库、普通日志或本文。

| Endpoint | Responses API | 延迟 | 返回模型匹配 | 文本/usage |
| --- | ---: | ---: | --- | --- |
| `gpt-5.6-luna` | HTTP 200 | 2.212 秒 | 是 | 有 |
| `gpt-5.6-terra` | HTTP 200 | 2.816 秒 | 是 | 有 |
| `gpt-5.6-sol` | HTTP 200 | 2.698 秒 | 是 | 有 |

随后又通过独立 CLI 对三个模型各执行一次固定合成的 Provider-level no-send 请求。该 Runner
不导入 QQ Connector 或 Output Adapter，不保留 Prompt、回答、Base URL、Key 或 Provider 错误
正文；仓库外 Receipt 权限为 `0600`，每项只保存模型、Tier、成功状态、延迟、usage、Provider
调用数和 Output 调用数：

| 模型 | Tier | 结果 | 延迟 | usage（输入/输出/总计） | Provider / Output 调用 |
| --- | --- | --- | ---: | ---: | ---: |
| `gpt-5.6-luna` | Haiku | 成功 | 1.980 秒 | 21 / 7 / 28 | 1 / 0 |
| `gpt-5.6-terra` | Sonnet | 成功 | 1.846 秒 | 21 / 7 / 28 | 1 / 0 |
| `gpt-5.6-sol` | Opus | 成功 | 2.503 秒 | 21 / 7 / 28 | 1 / 0 |

私有 Receipt 位于
`/home/mmdustc/temp/dududa-s23-provider-no-send-shadow.json`。这组结果只证明真实 Provider
能够完成一次合成 Responses 请求，并证明这条隔离路径没有 QQ Output 调用；它绕过了运行中的
AstrBot、Production Runtime 和真实群 Connector，因此不是 AstrBot Conformance、候选部署或
单群 no-send Shadow Receipt。

AstrBot 实际使用的 Chat Completions 路径也完成了普通请求和
`reasoning_effort=low` 各一次抽样：Luna、Terra、Sol 均为 HTTP 200、返回模型 ID 匹配并包含
usage，单次延迟约 2.2--2.3 秒。这只证明两种协议的单次可达、模型绑定和基本输出，不是
Endpoint Conformance、持续健康、质量、成本或生产可用性证据。

以下 Provider 注册情况是本节 2026-08-15 抽样时的历史快照，不代表当前发布；当前版本以
`bot-stable-release.md` 的最新部署记录为准。当时运行中的 AstrBot 只注册了 `deepseek/deepseek-v4-pro`、
`deepseek_1/deepseek-v4-flash` 和 `openai/gpt-5.5`，三个 GPT-5.6 Endpoint 尚未成为 AstrBot
Provider。固定版本候选镜像已用显式 allowlist 透传 `max_tokens` 和 `reasoning_effort`；
隔离 payload 抽样保留了 `max_tokens=321`、`reasoning_effort=high`，且未放行无关插件参数。
固定镜像 `dududa/astrbot:s23-candidate-local` 还曾在 `--network none`、临时
`/AstrBot/data`、无 NapCat、无端口暴露的容器中启动；AstrBot 4.26.2 成功加载 Dududa Core 后，
候选容器即被停止并清理。它证明候选能够启动，不是运行中部署或生产切换。
Runtime 将 OFF/LIGHT/BALANCED/DEEP/MAXIMUM 映射为省略/low/medium/high/xhigh，但远程请求只
抽样验证过 `low`。思考深度当前由每个 Endpoint 固定配置，不是同一 Endpoint 请求级动态切换。
Builder 必须解析真实 Conformance Evidence，初始健康为 `UNKNOWN`。

健康刷新使用 Fake Provider 做了代表性错误抽样：正常结果能够周期刷新 `HEALTHY`；探测超时
会取消请求并发布 `UNKNOWN`；没有运行事件循环时不启动、不调用 Provider；TTL 到期后 Router
重新看到 `UNKNOWN`。这些测试证明默认关闭、刷新、取消和失效语义，不证明真实 Endpoint 的
长期健康、配额、故障率或 AstrBot Conformance。

仓库已提供无凭据、默认关闭的候选样板：Luna -> Haiku/light、Terra -> Sonnet/balanced、
Sol -> Opus/deep。进入真实 Shadow 前的最短顺序为：在部署窗口启动或切换到仍保持 Runtime/rollout
关闭的隔离候选实例；注册三个 AstrBot Provider 并取得实际 Provider ID；在该实际 AstrBot 路径
完成 Contract/Conformance；把验证结论写入仓库外 Evidence 文件并配置
`runtime_provider_evidence_path`；接入能在 TTL 前持续刷新的健康采集源，或在验证配置后显式启用
默认关闭的内置刷新循环。只有 Conformance 与 Preflight 均通过后，才启用运行中的候选 Runtime
进入单群 no-send Shadow。此前始终保持
`runtime_enabled=false`、`rollout_mode=off`。

### 1.2 4--5 小时离线抽样预算

已有 1,402 文件流水线、600 条 Terra Silver、137,026 条 Student 预测和私有 Demo 不再重跑。
若后续为多模型校准重新发起结构化抽样，使用以下五小时硬时间盒，而不是把约 410 MB 原文全部
提交给 LLM：

| 累计时间 | 工作 | 硬上限 |
| --- | --- | ---: |
| 0--60 分钟 | 复用并校验现有索引；仅处理新增或失效文件的过滤、去重和 past-only 窗口 | 只做本地处理 |
| 60--85 分钟 | 分层抽取窗口测量实际吞吐 | 20--24 次请求 |
| 85--210 分钟 | Luna 生成主结构化样本 | 默认 250，最多 350 |
| 并行复核 | Terra 只处理低置信度和 Schema 边界 | 最多 50 |
| 并行抽查 | Sol 只处理高歧义样本 | 最多 15 |
| 210--255 分钟 | 按群隔离训练/评估 | 不扩大样本 |
| 255--285 分钟 | 固定样本 Demo 与指标 | 不扩大样本 |
| 285--300 分钟 | 文档、结果归档和缓冲 | 五小时硬停止 |

首批吞吐的 P95 小于 15 秒时，Luna 主样本最多扩到 350；P95 为 15--30 秒时固定为 250；
P95 超过 30 秒时降到 120--150。T+3.5 小时停止发起新请求，每个窗口最多重试一次。单群占比
不超过总样本的 5%--8%，train/dev/test 按群隔离，避免同一群表达习惯泄漏。时间不足时保留
已完成样本并明确标记部分完成，不通过压缩 Demo、指标或文档时间来追求全量调用。

### 1.3 Web 人工内测页（非 Live S23）

2026-08-16 已完成 `#/internal-test` 第一版。该页面属于既有 Bot Control Plane 的 Evaluation
Adapter，不建立第二套 Runtime：没有 NapCat 账号也可以进入，浏览和筛选 300 个既有脱敏窗口，
查看 Silver、Student、AnswerProfile、Static Tier 与 Luna/Terra/Sol 映射，并由操作员显式请求
一次服务端 `no_send` 候选和提交人工评价。

已完成的真实浏览器纵切使用 Terra，结果为：

| 样本数 | 模型 | 延迟 | Provider | QQ Output | Memory 写入 | Tool 调用 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 300 | `gpt-5.6-terra` | 3059 ms | 1 | 0 | 0 | 0 |

反馈只追加到配置的仓库外 JSONL，文件权限为 `0600`。服务端不持久化候选回答正文，也不把
Provider Key、Base URL 或 Provider 错误正文写入反馈。启动时必须显式指定脱敏 S23E 投影和
反馈文件；没有数据根时页面显示 unavailable，不回退到固定私有目录：

```bash
cd apps/web
export DUDUDA_INTERNAL_TEST_DATA_ROOT=/absolute/path/to/deidentified-s23e-projection
export DUDUDA_INTERNAL_TEST_FEEDBACK_PATH=/absolute/path/to/internal-test-feedback.jsonl
npm run dev
```

浏览器打开终端输出的 loopback 地址并追加 `/#/internal-test`。如需真实候选生成，可通过以下
环境变量或既有本机 Codex 配置/认证文件提供 Provider 配置；真实值只留在本机，不写入 Git、
Runbook、截图或反馈文件：

```text
DUDUDA_INTERNAL_TEST_BASE_URL
DUDUDA_INTERNAL_TEST_API_KEY
DUDUDA_INTERNAL_TEST_PROVIDER
DUDUDA_INTERNAL_TEST_CODEX_CONFIG
DUDUDA_INTERNAL_TEST_AUTH_FILE
DUDUDA_INTERNAL_TEST_HAIKU_MODEL
DUDUDA_INTERNAL_TEST_SONNET_MODEL
DUDUDA_INTERNAL_TEST_OPUS_MODEL
```

未覆盖模型变量时，默认映射为 Haiku -> `gpt-5.6-luna`、Sonnet -> `gpt-5.6-terra`、Opus ->
`gpt-5.6-sol`。候选生成只在操作员点击后发生；页面没有 QQ 发送、Memory 写入、Tool 调用或
Bandit 学习。上述浏览器证据不构成 AstrBot Runtime Shadow、Provider Conformance、真实群验证
或正式上线，S23 继续保持 `partial/paused`。

## 2. 固定验证阶梯

同一个授权群按下列顺序逐级执行。每一级使用新的 manifest 和 Grant，只有操作员审核上一阶段的
脱敏 Receipt 后才能晋级。

| 阶段 | 允许行为 | 关键门禁 |
| --- | --- | --- |
| Preflight | 只核对配置、证据和私有引用 | 不读群、不调用 Provider、不发送 |
| Shadow | 读取授权时间窗并运行真实理解/路由链 | Output、Memory、Tool write 均为 0 |
| Inbound Canary | 批准测试用户结构化明确 `@` 后回复 | 固定请求/消息预算，逐条核对投递结果 |
| Manual Digest | 操作员触发一次日报 | live 来源、引用、新鲜度、目标和预算通过 |
| Scheduled Digest | 激活一个有界 occurrence | 手动日报先通过；时区、quiet hours、misfire、退订通过 |
| Probe Canary | 低频群级主动消息 | 不 `@` 个人、不读个人 Memory、不自动追问，冷却不少于 24 小时 |
| Closeout | 关闭全部 Canary 并清理证据 | Receipt 对账、删除/保留、kill switch 和回滚完成 |

3-5 群扩展不属于本轮。单群 Closeout 后必须重新授权，不能继承原 Grant。

## 3. Readiness Manifest

提交模板位于 `configs/release/s23-readiness.template.json`。真实 manifest 建议放在仓库外的私有
运行目录；仓库和 manifest 都只保存 opaque reference 和 digest，不保存真实 QQ/群/用户 ID
或凭据值。

manifest 绑定：

- candidate、上一 release 和回滚 archive 的精确 digest；
- 单独冻结且 `s23_ready=true` 的 SLO policy ID/digest；
- Bot、单群和测试用户的私有引用；
- 部署授权窗和独立的群数据可读窗；
- 用途、保留期限、删除负责人和私有 audit sink；
- OneBot 与 Provider 的 SecretRef；
- Endpoint conformance、健康、路由目录和启用 Role/Tier；
- 当前阶段独立 Grant、预算、quiet hours、kill switch 和停止策略；
- 后续阶段需要的前序 Receipt、Source、Schedule 或 Projection 证据。

模板本身是合法 JSON，但必须 fail closed。离线检查命令：

```bash
PYTHONDONTWRITEBYTECODE=1 \
  uv run --locked python ops/cli/validate_s23_readiness.py \
  --manifest configs/release/s23-readiness.template.json \
  --at 2026-08-11T12:00:00+08:00
```

退出码含义：

| 退出码 | 含义 |
| --- | --- |
| `0` | 当前阶段 manifest 结构完整且处于有效窗口；不代表真实证据已解析或允许执行 |
| `1` | JSON、字段、类型、digest、时间或 IANA timezone 非法 |
| `2` | manifest 合法但仍有 readiness blocker |

报告只包含 manifest identity digest、阶段、时间、digest 和稳定 blocker code。字段
`validation_scope=manifest_only` 且 `live_execution_authorized=false` 始终成立：离线脚本不会把
自声明的证据 digest 升级为真实授权。它不会解析 Secret、读取群聊、连接 Provider/来源、检查
容器或输出私有引用值。

## 4. 外部输入和私有绑定

Preflight 前由操作员提供：

1. 单个 Bot/群和测试用户引用、数据可读窗、有效期不超过 7 天的部署授权窗；
2. 数据用途、保留期限、删除负责人和私有审计位置；
3. 至少一个真实模型 Endpoint 的公开能力目录、实际 AstrBot Provider ID、私有 Provider
   SecretRef、仓库外 Conformance Evidence 文件和持续健康采集配置；
4. OneBot/NapCat 私有连接引用和 SecretRef；
5. 各阶段独立预算、quiet hours、kill-switch 负责人和停止条件；
6. 允许配置/重启当前实例的部署窗口，或一个隔离测试实例。

真实 Secret 值和 QQ 标识映射只进入本机私有部署配置或 Secret Store。不得写入 Git、命令行
参数、普通日志、Receipt 或 readiness 报告。

以下 digest 由工程命令生成，操作员不手工伪造：release/archive、SLO、stop policy、Endpoint
conformance/health/catalog、Source/Projection evidence 和前序阶段 Receipt。

## 5. Preflight

Preflight 在任何真实群读取前完成：

1. 验证 candidate 和上一 release 均可恢复，rollback archive 可读且校验一致；
2. 验证冻结 SLO 的 policy ID/digest，全部安全计数上限为 0；
3. 在私有进程中解析 Bot、群、测试用户和 SecretRef，确认引用均指向同一授权环境；
4. 对实际启用 Endpoint 执行 conformance、健康和 Role/Tier 绑定检查；
5. 检查系统时钟、IANA timezone、授权窗、数据可读窗和保留期限；
6. 检查行为 kill switch 和精确回滚命令，但不执行破坏性 restore；
7. 运行 readiness checker，只有退出码 `0` 才能进入该阶段。

实际 Provider ID 和 `runtime_provider_evidence_path` 可以在 `runtime_enabled=false` 时写入私有
部署配置；只有第 4 步的真实 Conformance 和首份未过期健康证据均通过后，才允许为授权 Shadow
打开 Runtime。Fake Contract、历史 HTTP 200、可解析的 Evidence JSON 或手工填写全部 `true` 的
flags 都不能替代真实 Conformance。

Preflight 失败时修正输入并重新生成证据。不得通过删除 blocker、使用 fixture digest 或把
`s23_ready` 直接改为 `true` 绕过。

## 6. Shadow 和入站 Canary

### 6.1 Shadow

Shadow Grant 必须满足：`output_enabled=false`、`max_messages=0`、`memory_allowed=false`、
`allowed_capabilities=[]`。只读取 manifest 绑定的数据窗，运行真实 Connector、Perception、Tiering
和 Router 路径，记录低基数统计与 digest。

退出前核对：

- Output 调用、Capability 调用、Memory 读写均为 0；
- wrong target、cross-scope、sensitive trace 均为 0；
- Router 只选择 manifest 允许的 Endpoint；
- 原始消息、Prompt、回答和 Provider error body 未进入提交证据。

操作员审核 Receipt 后，签发新的 Inbound Grant。

### 6.2 Inbound Canary

只接受同一群内、批准测试用户发送的结构化明确 `@`。Memory 保持关闭，Capability 只能来自
Grant 的只读 allowlist。每个请求和 Delivery Receipt 必须一一对账；超预算、非测试用户、非明确
`@`、过期 Grant 或未知投递结果立即停止该阶段。

## 7. 日报 Canary

Manual Digest 需要至少一个批准的 live Source Adapter。Source evidence 必须绑定官方来源、
许可证/条款、allowlist、provenance、freshness、revision、引用和去重策略；fixture 和 iCourse
不能替代 live 证据。

先执行一次手动 occurrence，核对目标、条目数、字数、引用、新鲜度和 Delivery Receipt。通过后
才签发 Scheduled Digest Grant，并额外绑定 IANA timezone、发送时刻、quiet hours、misfire、
每日上限、暂停/退订负责人和 schedule policy digest。

## 8. Probe Canary

Probe 只能在入站、手动日报和定时日报均通过后开始。它需要真实且脱敏的群级 Projection
Adapter evidence，并满足：

- 目标是群，不是个人；不 `@` 任何成员；
- Memory 关闭，不读取个人画像；
- 冷却不少于 86400 秒；
- 无人回应后不追加消息；
- 每次发送均重新检查 Grant、预算、quiet hours 和 kill switch。

## 9. 停止与回滚

以下任一事件立即关闭当前行为，不晋级其他行为：

- wrong target、重复投递、quiet-hour/撤销后投递；
- 未授权 Capability、跨 Scope Memory、个人 Probe 目标；
- 过期或无引用日报、敏感 Trace、未知 Delivery outcome；
- Endpoint health 为 `UNKNOWN`、缺 Receipt、SLO 超线；
- kill switch 或回滚检查失败。

关闭后保留故障现场的私有证据，执行冻结回滚路径，并按
[升级与回滚设计](upgrade-and-rollback.md)核对上一 release。禁止在未完成对账时自动重试发送。

## 10. Closeout 和证据

Closeout 必须：

1. 关闭所有行为、Subscription、Schedule 和 Output；
2. 对账每个 Decision、Dispatch 和 Delivery Receipt；
3. 执行保留/删除计划并记录删除 Receipt；
4. 验证 kill switch 和精确回滚路径；
5. 输出脱敏 SLO、事故和外部门禁报告。

可提交证据仅包含不可逆 digest、低基数计数、SLO 聚合和稳定 reason code。原始聊天、Prompt、
回答、真实 QQ/群/用户 ID、凭据、完整 `.env`、Provider error body 和私有 audit 内容均不提交。

S23 只有在完整单群阶梯及 Closeout 证据存在后才能标记完成。在此之前应保持 TreeWork 分支
`partial/paused`，不能用离线 checker、S19 Release 或 S20 合成 Bandit 结果替代真实 Receipt。
私有 Evidence 解析、TTL 健康发布和默认关闭的周期刷新工程纵切已经完成；真实运行 AstrBot
Provider 注册、真实 Conformance、实际启用后的持续健康证据、部署切换和单群 Shadow 仍未完成。
