# Task Plan

Branch: real-group-validation
Parent: agent-expansion
Title: S23 Authorized Real-Group Validation

## Scope

- Complete S23A--S23E as an offline historical-corpus pipeline: deterministic
  intake, Conversation Windows, real Semantic v2 Silver labeling, local Student
  training/evaluation and a private no-send HTML Demo.
- Deliver a localhost Web internal-test surface that reuses the de-identified
  S23E projection for sample browsing, explicit no-send candidate generation
  and repository-external human feedback.
- Keep that historical-corpus surface a no-send Evaluation Adapter while making
  the live Agent Console in the same application the formal Bot Control Plane
  and administrator super-workbench.
- Let an administrator set per-account/conversation initial preferences, legal
  ranges and explicit locks while the Runtime adapts each Run inside those
  ranges without surrendering Core authority.
- Treat the WebUI operator as `super_admin` for configuration and the Bot
  Runtime as `admin` for execution. Keep `installed`, configured/Compose-ready,
  AstrBot online and actually selected/called as four distinct states.
- Expose six orthogonal settings in that Scope: model Tier, reasoning depth,
  answer length, reply intensity, context length as a per-Run history budget,
  and group-chat style. Keep desired Policy distinct from actual reply or
  proactive-delivery state.
- Keep the internal-test live workspace usable under reconnect and initial-load
  races, and expose Persona-aware SHORT/MEDIUM/LONG candidate generation for
  bounded human evaluation.
- Freeze and validate one low-sensitivity S23 readiness manifest and operator
  runbook without resolving credentials or touching live systems.
- The configuration-driven inbound Runtime production shape is now closed
  without real credentials. After explicit inputs arrive, add only real
  Endpoint Conformance/evidence resolution and the Source, Projection and
  Output environment Adapters required by the authorized stage.
- Execute the single authorized group ladder from no-send Shadow through
  inbound, manual/scheduled digest and low-frequency Probe canaries.
- Reconcile delivery, SLO, incident, rollback and deletion evidence.

## Acceptance

- [x] S23A classifies all 1,402 files and reports authoritative JSONL/ZIP/HTML,
  duplicate, supplement, conflict, excluded-private and unique-message counts.
- [x] S23B produces valid 3--12 message past-only `PerceptionContext` windows,
  including at least 50 real windows and a stratified time-boxed target chosen
  from 240/360/480/600 after measuring real Teacher throughput.
- [x] S23C obtains real Semantic v2 Silver labels for the selected target from
  Terra as the fixed Teacher, routes invalid, low-confidence or ambiguous
  results into a review queue without storing raw requests in Git, and records
  the measured throughput and reason for the selected sample size.
- [x] S23D trains and evaluates `need_tools`, `semantic_complexity` and
  `answer_profile` Students on a group-isolated split, reports Silver agreement
  and generates offline predictions for every eligible window.
- [x] S23E produces a private, reusable localhost HTML Demo that visibly states
  PRIVATE DEVELOPMENT DATA, SILVER NOT GOLD, NO SEND, NO MEMORY WRITE, NO TOOL
  CALL, NO BANDIT and NOT CURRENT DUDUDA BOT TRAFFIC.
- [x] A canonical readiness manifest binds exact release/rollback/SLO,
  Endpoint/source evidence, private SecretRefs, data policy and separate
  behavior grants; placeholder or incomplete manifests fail closed offline.
- [x] A configuration-driven inbound production Runtime parses the actually
  configured 1--3 model tiers and assembles the Static Router and DirectChat
  chain; `off` performs zero Provider calls/sends, `shadow` does not claim or
  send. This records the pre-cutover acceptance behavior; the current 2.0-only
  Runtime fails closed when a Provider is disabled or unresolved and does not
  return ownership to Dududa 1.0.
- [x] Production Builder 优先使用 AstrBot Context 的 Evidence resolver；
  resolver 缺失或返回 `None` 时，从 `runtime_provider_evidence_path`
  指向的仓库外私有 JSON 解析 Provider binding evidence。Provider/model
  不匹配时拒绝装配；初始健康为 `UNKNOWN`，有效且未过期的
  `ModelHealthEvidence` 可使 Router/Admission 看到 `HEALTHY`，TTL 到期后
  自动恢复 `UNKNOWN` 并停止调用 Provider。
- [x] 固定 AstrBot 4.26.2 候选已在 `--network none`、临时
  `/AstrBot/data`、只读插件挂载、无 NapCat 且无端口的完全隔离环境启动；
  同时完成 Luna/Terra/Sol 各一次隔离 Provider no-send 抽样，每档均为
  `provider_calls=1`、`output_calls=0`。
- [x] 默认关闭的周期模型健康刷新已实现并完成聚焦抽样：默认刷新间隔、
  超时与 Evidence TTL 分别为 45/15/90 秒；固定模型探测使用
  `max_tokens=8`、`request_max_retries=0`，成功发布 `HEALTHY`，失败、超时
  或 TTL 到期保持/恢复 `UNKNOWN`，插件终止时取消刷新任务。脱敏失败样本
  不保存 Key、Base URL、Prompt、回答、QQ 标识或 Provider 错误正文。
- [x] Web 内测页可在没有 NapCat 账号时打开，浏览和筛选既有脱敏窗口，展示
  Student、AnswerProfile、Static Tier 和 Luna/Terra/Sol 映射，并显示人工
  评价进度。
- [x] 操作员可显式触发一次服务端 `no_send` 候选生成并提交人工评价；响应
  明确记录 tier/model/answer profile、延迟和 `output_calls=0`，反馈只写入
  配置的仓库外 JSONL，浏览器与日志均不包含 Provider Secret。
- [x] Workspace SSE 使用单调事件 ID 和最近 4096 条有界内存重放；浏览器重连
  可通过 `Last-Event-ID` 按序补放，ID 无效、过旧或服务重启时回退到
  `workspace.refresh`。前端按 `timestampMs`、无损十进制 sequence、消息 ID
  稳定排序，并重放初始快照期间收到的实时事件。NapCat 历史页以游标边界探测
  判断是否还有更早记录，不再把不足请求条数误判为终页；前端对重复游标/消息停止翻页。
- [x] 历史语料 Evaluation Adapter 的首版候选生成可显式选择 SHORT/MEDIUM/LONG；生成指令复用
  `configs/personas/registry-v1/dududa.json`，按群聊/私聊规则调整表达，同时保持
  NO SEND、NO MEMORY WRITE、NO TOOL CALL、NO BANDIT。该历史候选不等同于当前
  `/agent/respond` 的 2.0 Runtime 预览；后者可调用批准的只读 Capability。首版
  Luna/Terra/Sol 映射只作为历史默认，不再作为永久控制契约。
- [x] Persona 不再依赖 `response_profiles` 开关：关闭回答档位时仍进入同一次
  模型生成；开启时 Persona、群聊情境与 AnswerProfile 在同一请求中自然融合，
  不复述人设、不自我介绍、不套固定口号、不机械追加表情，也不模仿具体群成员。
- [x] SHORT/MEDIUM 始终按普通 QQ 消息投递；LONG 单段同样普通投递。只有
  `profile_validation.valid=true` 的 LONG，且目标为群聊、至少两个纯文本 part、
  无附件时，Output Adapter 才允许合并转发；定向目标保留在 Runtime 契约中，
  转发不另发 `@`。
- [x] Dududa 1.0 的 Meme Manager、PokePro 和 Target Talk 继续退出 2.0 默认
  路径；ReplyPolish 默认关闭且仅作为 LONG-only 兼容层。新群不再生成
  `meme_rate`，管理命令不再写入该字段；显式 `/image` 图片生成能力继续保留。
- [x] 自动复读和现有 `/sub2api 自动查询` 已恢复为独立、默认 `off`、按
  `accountId + conversationId` 配置的 AstrBot 插件。WebUI 配置权限为
  `requiredRole=super_admin`，声明的 Bot 执行身份为 `executionRole=admin`；插件
  源码、动态 Catalog/配置面和 Compose 挂载均已装配。
- [x] 实时 Agent Console 以 `accountId + conversationId` 为 Scope，从服务端动态
  Catalog 加载模型/Tier、推理档位、modality、AnswerProfile、回复强度、上下文
  长度、群聊风格、插件/Capability、安装状态、可用状态和不可用原因，不在前端
  写死模型或插件。
- [x] 模型/Tier、推理深度、回答长度、回复强度、上下文长度（运行预算）和群聊
  风格六项正交设置统一支持 `adaptive/preferred/locked`；管理员普通修改给出初值
  和 `allowed`，不会永久固定 Agent，只有显式 `locked` 才禁止本轮改选。
- [x] 上下文长度仅控制本轮送入模型的近期群聊历史预算，不表示模型最大 Context
  Window；`compact/standard/extended` 分别限制为 12/6,000、30/18,000、
  100/36,000 条消息/字符，并回传 `messagesRead` 与 `charactersRead`。
- [x] 插件统一支持 `off/auto/on/locked`；状态只改变通过 Core 资格过滤后的候选
  集合或偏好，不授予 Capability，也不要求每轮调用。
- [x] 六项设置保持正交；每次 Run 返回管理员初值、`allowed`、实际选择、上下文
  实际读取量、改选 reason codes 和实际调用插件，且 `preferred` 可改选、
  `locked` 不可被 Agent 覆盖。回复强度只是一项候选决策输入，不能被解释为真实
  自动发送概率。
- [x] Agent Console 配置经专用服务端 API 持久化到仓库外数据根，页面重载后仍按
  同一 Scope 恢复；浏览器 localStorage 只可作为非权威草稿或缓存。
- [x] 旧 Catalog 事实边界准确记录了当时只有 iCourse；该事实由下面的校园 MCP
  增量替代。`gpt-image-2` 是已知图片能力但不属于本次 MCP 工作。自动复读与
  `/sub2api 自动查询` 均由会话 Policy 管理，默认 `off`，并分别显示配置角色、
  执行身份、Runtime target 和 configuration readiness。`installed/configured`
  不得冒充 AstrBot online 或本轮实际执行。校园资讯、arXiv、行业资讯、网络搜索
  及其他未接能力显示 `unavailable + reason`，不得把 fixture 或预留接口伪装成
  真实服务。
- [x] Web Scope Policy 已由唯一 2.0 Runtime 每轮消费：`enabled=false` 在 Canary
  claim 前退出；Capability 为 `off` 时移除映射类别，`auto/on/locked` 只保留
  原本合法的候选资格，不强制调用，也不覆盖全局 Tool、授权、预算或健康判断。
- [x] Web 将候选预览与真实 Runtime 分开显示：iCourse 标记为 Runtime online；
  当时二课、教务和校车标记为已装配。后三者自然语言 Planner 现均已闭环，主动参与仍为
  S15E Probe Shadow/`NO SEND`。
- [x] 将 `/agent/respond` 接到 AstrBot 内已安装的 2.0 Runtime no-send 预览：允许
  已批准的只读 Capability，使用内存 Delivery Receipt 完成状态机，但不 claim/stop
  QQ Event、不写 Memory、不调用 QQ Output；前端显示真实 `runtimePath/toolCalls`。
- [x] 按真实 Luna/Terra usage 修复 AstrBot Provider Token 开销估算：每个 Endpoint
  可配置 `provider_wrapping_tokens`，当前默认 4,608；Perception/总输入预算调整为
  12,000/40,000，避免成功模型响应被容量结算误判为失败。
- [x] `/sub2api 自动查询` 已接通精确 Scope Web Policy Adapter；当前 AstrBot
  已加载插件，NapCat OneBot 反向 WebSocket 已连接，目标群的 Policy 已解析为
  `locked`。方法级真实只读查询已成功，等待用户在重连后重新发送命令
  以闭合 QQ 入站与回复的最终验收。
- [x] `/sub2api overview` 完整复用本机原插件 v0.6.2 的命令、权限、缓存、
  Client、错误处理和四段取数逻辑；仅将成功结果包装为四节点 QQ 合并转发，
  节点依次为今日、当前计费轮、2026-07-13 起历史累计和上游账号。错误仍返回
  普通文本。本次只做聚焦验证，不重启、停止或热重载容器。
- [ ] 自动复读仍需单独接通 Web Policy Adapter；不得因 `/sub2api` 已接通而
  声称复读也已由在线 AstrBot 消费会话 Policy。
- [ ] One authorized group's no-send/no-write Shadow proves zero Output, Tool
  write, Memory read/write, wrong-target and sensitive-Trace events.
- [ ] Explicit-mention inbound Canary is limited to approved test users and
  frozen message/run budgets; all delivery outcomes are reconciled.
- [ ] Manual digest then scheduled digest use approved live sources with valid
  provenance, freshness and citations and produce no duplicate, quiet-hour,
  revoked or unsubscribed delivery.
- [ ] A separately authorized low-frequency group Probe produces no personal
  target/mention, Memory access, auto-follow-up or send after no response.
- [x] The authorized `419256533` pilot Scope can enable Dududa 2.0 automatic
  group participation independently of automatic reread. It reads bounded
  NapCat history, uses separately adjustable probability/cooldown/hourly quota
  without changing `replyIntensity`,
  fixes proactive output to SHORT without a personal mention, and keeps LONG
  available only on the explicit `@Bot` entrypoint.
- [ ] Every safety maximum remains zero; frozen latency/cost/quality measures,
  kill-switch and exact rollback evidence are recorded without post-hoc
  threshold changes.
- [ ] All canaries end disabled, retention/deletion actions are recorded, and a
  sanitized S23 report contains no raw message, prompt, answer, real QQ/group/
  user ID, credential or Provider error body.
- [x] The previously completed S23A--S23E and first Web internal-test slices
  synchronized Progress, Findings and Verification and were locally committed
  without push.
- [x] After the adaptive Agent Console slice is implemented and sampled,
  synchronize its Progress, Findings and Verification and create one local
  commit without push.
- [x] iCourse、二课、教务处与培养方案研究作为四个独立 Registry Server 接入现有
  Unified MCP；iCourse 继续匿名复用，二课通过 SecretRef 使用固定 pyustc 版本。
- [x] 校车从 MCP 迁移为本地 owned 插件：版本化时刻表、Builtin Provider、自然语言
  Planner 和 20 题固定测试已闭环，旧 Server/mapping/网页抓取路径已移除。
- [x] 教务学期、开课、考试和教学日历进入自然语言单步 Planner；开课/考试由
  Academic MCP 在同一次调用内把学期名称解析为官方 semester ID。目标群五项
  校园查询已启用并完成 no-send 耦合抽样。
- [x] WebUI 展示四个 MCP 的健康、认证和 Capability 状态，并把校车显示为本地
  `readonly_query` 插件；`super_admin` 可依据
  Capability input schema 直接调用并查看结构化结果、来源与抓取时间；不开放任意
  MCP tool 透传。
- [x] WebUI 新增 Runtime 插件管理区，动态列出 AstrBot 已加载插件，通过服务端
  `plugin` scope API Key 支持 GitHub/ZIP 热安装；安装结果不写入 Scope Policy。
- [x] 发布 `dududa-plugin-development-spec.md` 中文规范并在插件区提供下载链接，
  让人或 AI 生成的插件按同一目录、metadata、配置、权限和测试格式交付。
- [x] Dududa 2.0 的自然语言 iCourse 纵切经 Haiku/Luna `PERCEPTION` 提取实体、
  category 与标准 intent，由确定性单步 Planner 选择 `icourse.public-query.v2`
  并投影 `course/review/teacher/ranking/stats`，通过 Unified MCP 返回 Observation，再由
  `DIRECT_CHAT` 产生唯一最终回答；不得经过 `/course` handler 或 Web search，
  不显示中间计划、Observation 原文或思维过程。最终模型必须归纳 MCP 原始内容并直接
  回答，已有来源链接仅作辅助引用，不得用裸链接、链接列表或原始 JSON 代替正文。
- [x] iCourse 的高层查询和四个旧兼容读 Capability 均以 `icourse.club` 实时公开页
  为事实源；模型路径不得读取或回退 SQLite。课程/教师、点评/精确用户、排行和统计
  分别走对应公开端点，crawl/export 缓存只保留为管理与历史评测面。

## Local Steps

- [x] S23A: implement and run `inventory`/`extract`; write private normalized
  messages and source-conflict artifacts, then record authoritative counts.
- [x] S23B: implement and run `window`/`sample`; validate 50-window smoke and
  produce stratified 240/360/480/600 candidate samples with per-group caps.
- [x] S23C: implement the private Responses-compatible labeler; run 5, then 50,
  estimate completion from the 50-run throughput, then run the largest target
  that leaves enough of the five-hour budget for training, Demo and handoff.
- [x] Enforce a four-hour target and five-hour hard wall-clock budget: reserve
  at least 75 minutes after annotation, stop launching requests at the
  annotation deadline, reuse successful cached labels and retry a transient
  request no more than once.
- [x] S23D: train three lightweight Students, evaluate with group isolation and
  classify all eligible windows.
- [x] S23E: generate/replay/serve the private no-send Demo, synchronize S23 and
  Chinese development documents, and create no more than three local commits.
- [x] Implement the offline readiness manifest/checker, template and runbook;
  record the current fail-closed external blockers.
- [x] Implement the production Builder, automatic plugin wiring and AnswerProfile
  feature flag; the initial rule-only checkpoint was later superseded by the
  Hybrid Perception and governed iCourse Capability vertical slice below.
- [x] Implement the repository-external Provider Evidence Store and wire the
  existing bounded health publisher through Production Assembly, Router and
  Admission; verify exact binding, `UNKNOWN -> HEALTHY` and TTL expiry with
  focused Fake tests.
- [x] Start the fixed AstrBot 4.26.2 candidate in a fully isolated environment
  and sample Luna/Terra/Sol once each through the isolated Provider no-send
  runner; retain only sanitized operational receipts.
- [x] Implement the default-off periodic model-health refresher and sample its
  success, failure/timeout, Evidence TTL expiry and terminate-time cancellation
  paths without enabling it in the running AstrBot.
- [x] Implement the internal-test Gateway and Vue page over the existing S23E
  projection; run one sample load, one no-send generation and one feedback
  append, then stop Web expansion after focused type/build checks pass.
- [x] Repair the internal-test live message path with bounded SSE reconnect
  replay, stable client ordering, initial-snapshot event replay and stale
  conversation fallback; wire Persona plus SHORT/MEDIUM/LONG selection without
  changing Runtime ownership or enabling side effects.
- [x] Tighten Runtime delivery and generation composition so Persona survives a
  disabled AnswerProfile flag, Persona/Profile share one model request, and
  merged forwarding is independently restricted to eligible validated LONG
  group responses.
- [x] Remove Meme Manager, PokePro and Target Talk from repository defaults,
  stop new `meme_rate` initialization/writes, keep ReplyPolish default-off and
  retain explicit `/image`; do not restore those removed automatic behaviors.
- [x] Restore only automatic reread and the existing `/sub2api 自动查询` as
  independent default-off AstrBot plugins; add their source/Catalog contracts,
  per-Scope Web configuration and Compose mounts while keeping WebUI
  `super_admin` configuration separate from Bot Runtime `admin` execution.
- [x] Split the historical Evaluation Adapter from the live Agent Console in
  product behavior, then add scoped server-side Catalog/config/respond APIs for
  the Console without creating a second Runtime.
- [x] Replace disabled and hard-coded Console controls with dynamic model,
  reasoning, AnswerProfile, reply-intensity, context-budget, group-style and
  plugin settings; save and reload the authoritative `accountId +
  conversationId` configuration from the repository-external data root.
- [x] Resolve every candidate through independent adaptive settings and return
  the effective six-setting selection, context usage, reason codes and actual
  plugin calls; sample `preferred`, `locked`, plugin four-state, persistence and
  no-send behavior with focused tests, one typecheck and one Web build.
- [x] Connect the exact-scope Web Policy Adapter for `/sub2api` to the online
  AstrBot plugin runtime and verify policy resolution plus a real read-only
  method smoke; final QQ end-to-end evidence still requires a user-issued
  post-reconnect command.
- [x] Preserve the original Sub2API v0.6.2 implementation and add only the
  four-node merged-forward presentation for `overview`; run the focused
  Sub2API tests and leave the running container lifecycle unchanged.
- [x] Implement the shared `ustc-campus` MCP package and independently register
  `ustc-young`, `ustc-academic` and `ustc-curriculum`; retain the existing
  `icourse` Server and compatibility path.
- [x] Add read-only Capability definitions/mappings, deployment assembly and
  runtime config sync for all four MCP Servers. Add shuttle through the existing
  Builtin Provider Port. A missing CAS SecretRef must degrade only the Young
  Server to an explicit unavailable state.
- [x] Add the internal Capability Console API and schema-driven Agent Console
  panel, then verify one iCourse/public-campus call path without enabling QQ
  output or restarting the current NapCat/AstrBot containers.
- [x] Add the runtime plugin inventory/install proxy and downloadable AI-facing
  plugin specification; prove one Fake install flow and one live list without
  installing an arbitrary production plugin during verification.
- [x] Add the structured Runtime MCP registration form and same-origin proxy for
  stdio/Streamable HTTP Definition v1; persist to a repository-external overlay,
  reload/discover through Unified MCP and return `capabilityGranted=false`.
- [x] Publish `dududa-mcp-development-spec.md` with SecretRef-only authentication,
  Tool semantics, minimum Contract Tests and the separate Capability-mapping step.
- [x] Replace rule-only production Perception with the existing Hybrid Perception
  path, assemble the existing Capability Runtime over the shared Unified MCP
  client, enable one bounded read-only Tool step from Rollout Policy, and prove
  the natural-language iCourse vertical slice with focused Fakes.
- [x] Connect the exact-Scope Web Agent Policy to the production Bridge and
  project its Agent switch plus MCP plugin modes into Perception eligibility;
  expose the four campus MCPs and local shuttle plugin truthfully, then keep
  each Capability unavailable to natural-language planning until its bounded
  argument projection is implemented. All five campus query paths now have
  that projection and report Runtime-online status.
- [x] Make the explicit `评课社区` marker a deterministic 2.0 Capability signal;
  execute all 75 benchmark messages through Runtime/MCP dispatch, add the three
  query-projection regressions, and measure all 75 once with real Luna `low`
  without QQ Output. Keep dispatch evidence separate from strict semantic completion.
- [x] Keep each inbound Tool plan to one MCP attempt; default `USE_TOOLS` to LONG
  only when no explicit AnswerProfile was requested, and package actual multi-part
  group LONG output as one QQ merged-forward while SHORT/MEDIUM remain ordinary.
- [x] Build one public-only iCourse development snapshot, generate answers for all
  75 benchmark questions with Luna/Terra/Sol at `low`, review each batch once with
  Luna, correct the remaining groundedness errors, and publish the Chinese answer
  report without QQ Output or production deployment claims.
- [x] Run all 75 legal OneBot-shaped messages through the real-model 2.0 Runtime
  with Fake Delivery, replace only the four corrected entity-planning cases,
  perform one Luna review plus a cross-case human final audit, and publish every
  final answer. Separately exercise AstrBot's in-memory WebSocket ingress and
  record the observed host-ordering risk without claiming real QQ E2E.
- [x] 将 `icourse.public-query.v2` 和 `stats/search/get_course/get_reviews` 四个兼容读
  工具全部切到实时站点；用禁止 `ICourseStore` 读取的聚焦测试、空 SQLite 真实 Smoke、
  Web Capability 直调和 2.0 no-send 自然语言预览证明不存在缓存旁路，并修复 Core
  热重载未关闭继承式 `terminate()` 所遗留的 MCP Worker。
- [x] 将二课的搜索、详情、动态筛选项和连接状态接入唯一 Dududa 2.0 自然语言
  Planner；不增加 QQ 用户登录、账号绑定、“我的活动”或报名写能力，不经过任何
  1.0 handler、旧命令路由或 Web search。
- [x] 建立 75 条二课自然语言案例，覆盖今日/本周、德智体美劳、报名窗口、余位、
  学时效率、规模比较、系列活动、上下文追问与正确拒绝；全部通过 OneBot-shaped
  原生消息模拟进入 2.0 Bridge，并区分路由完成、事实完成和正确边界回答。
- [x] 使用固定二课活动 fixture 完成 75/75 无 QQ 发送模拟；再以最小真实模型抽样
  检查 Perception、最终总结、过程隐藏和群聊表达，不把旁路 Reviewer 稿冒充
  Runtime 实际输出。
- [ ] Route validated Capability failure through the governed Composer, Persona,
  Final Validator and authorized Delivery path; do not fall back to the legacy
  course handler, Web search or a Bridge-level second send path.
- [ ] Connect automatic reread to the Web Policy separately; a matched Web
  trigger remains distinct from execution evidence.
- [ ] Receive and privately bind the authorization, Endpoint, source, SLO and
  SecretRef packet; do not commit identifiers or credential values.
- [ ] Produce and privately bind real AstrBot Provider Conformance evidence,
  bind it to the formal candidate, then enable and configure the implemented
  health refresher before the Evidence TTL expires. Add live Source, Projection
  and Output composition only for the authorized stage.
- [ ] Execute Preflight and single-group no-send/no-write Shadow; review the
  sanitized receipt before promotion.
- [ ] Execute explicit-mention inbound Canary and reconcile every request and
  delivery before promotion.
- [ ] Execute manual digest, then scheduled digest, with separate promotion and
  receipts.
- [ ] Execute one separately authorized Probe Canary, then disable all canaries.
- [x] Implement and sample the exact-Scope `social.proactive_talk` production
  Adapter, expose its real Runtime state in WebUI, enable only the authorized
  group, and retain the existing Canary/Output path without restoring 1.0
  Target Talk.
- [ ] Run closeout, rollback/kill-switch checks, deletion, report, verification
  and protected completion.

## Out Of Scope

- Calling the historical export current Dududa traffic, reconnecting its source
  account, real QQ sends, production routing, live probes/digests or online
  Bandit learning during S23A--S23E.
- Default-on or broad production launch, private/personal proactive targets,
  arbitrary Tool writes, automatic Memory writes or unbounded group history.
- Bandit selection of send/skip, target, schedule, frequency, AnswerProfile,
  permission, Tool or Memory; S20 is not connected in S23.
- Fabricating arXiv/industry MCP Servers or treating campus query Capabilities
  as an already-governed proactive news Source.
- Redesigning S01–S20 contracts, turning WebUI into a second Runtime, bypassing
  Core permission/budget/side-effect ownership, adding a universal raw config
  write API, or changing running containers before an approved deployment
  window.
- Automatic expansion to 3–5 groups; that requires a new grant after bounded
  single-group completion.

## Dependencies

1. S17–S20, S22, S19 release audit and the Mew/NapCat Web audit are complete.
2. External: behavior-specific group authorization, test-user references,
   data governance, private SecretRefs, frozen SLO and deployment window.
3. External/engineering: at least one conformance-proven real model Endpoint;
   digest stages additionally need approved live Source Adapter evidence;
   Probe needs a real sanitized group Projection Adapter.
4. The current candidate and exact previous release must both remain
   recoverable throughout the ladder.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: S19 pilot SLO/receipt/rollback evidence, S22 exact previous release,
  S11 rollout controls, S15A-S15E proactive contracts, current production-shape
  evidence and the external-input checklist.
- Reuse check: reuse existing authorization, rollout, Scheduler, Source,
  ResponsePlan, Output and operations Ports; add only S23 readiness/evidence and
  environment Adapters proven necessary by supplied facts.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
