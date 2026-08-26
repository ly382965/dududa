# Findings

Branch: real-group-validation

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- MCP 链的用户价值由现有 `DIRECT_CHAT` 模型完成，不由 URL formatter 完成。
  Observation 是证据，不是回复；最终回答必须先归纳原文内容，链接只作次要引用。
  这复用 Perception 后既有的第二次模型调用，不再增加一次总结调用或另一条发送路径。
- Complex iCourse questions still consume one Runtime Tool step. The selected
  high-level `icourse.public-query.v2` operation may perform bounded local
  joins/aggregation inside the read-only Server, but the Agent does not build
  an N+1 Tool plan or retry Tool selection. Capability and MCP governance remain
  outside the model.
- Anonymous iCourse reviews are public records and must remain visible to
  public full-text search and local ranking. Excluding `is_anonymous=1` would
  systematically bias results; anonymity affects displayed identity, not
  public-read eligibility. Site timestamps use both ISO and `MM/DD/YYYY`, so
  year filters must handle both forms.
- Luna Review's boolean fields and some numeric scores were inconsistent in the
  75-answer run. The durable report therefore uses grounded/completeness/
  process/call-economy/profile booleans, issue lists and revised answers; it
  does not present the numeric score as calibrated quality evidence.
- AstrBot “已安装/已加载插件”与 Dududa “已授权 Capability”是两个独立事实。
  Web 安装成功只更改 AstrBot Runtime，不写入会话 Policy、不创建 Capability
  mapping，也不授予 Agent 调用权。浏览器不接触 AstrBot Key；当前写入信任
  仍来自本机回环 + same-origin 的超级工作台，不可外推为已完成远程管理员认证。
- AstrBot 4.26.2 的版本不兼容警告发生在 ZIP 解压之后，直接重试会因目录已存在失败。
  Web 在首次安装前后只比较 AstrBot failed-plugin ID；仅当本次唯一新增失败项
  可确定时回滚该目录并允许显式忽略版本检查重试，结果不唯一时不删除任何插件。
- `/sub2api overview` 的功能基线是本机可核验的原插件 v0.6.2，而不是仓库中较旧
  的 v0.5.1 Git 基线。原版已经拥有当前计费轮快照、精确起点分页聚合、历史排名、
  上游账号、缓存与错误处理；本轮不重新设计这些逻辑。由于 2.0 ReplyPolish 默认
  关闭且只处理合法 LONG 回答，显式管理员命令 `overview` 在自身输出边界直接构造
  四节点合并转发，避免依赖普通回答风格链。
- 旧 Compose 项目名不能直接等同于 Dududa 1.0：旧 AstrBot 容器已经不存在，
  但同一项目名下的 NapCat 正被 Dududa 2.0 复用为唯一 QQ Connector。版本切换
  只关闭明确识别出的 legacy AstrBot；不得对旧项目执行整体 `down/stop`。
- S23 completion is the bounded single-group ladder plus closeout. Expansion to
  3–5 groups is a later authorization decision, not an inherited grant.
- iCourse、二课、教务和校车都是查询型 MCP Capability，不能据此声称日报 Source
  已接入。校园资讯、arXiv 与行业信息仍没有 live Source Provider。
- 本机所谓“已登录工具”实际是 `0600` 的 CAS 凭据存储加临时会话导出器，不是
  持久登录 daemon。直接只读挂载该 TOML，并由现有 SecretRef Resolver 在子进程
  边界解析，比复制到 `.env` 或另建 Token 刷新服务更符合当前最小实现。
- The five-hour budget is protected by labeling 600 stratified windows
  (0.44% of 137,026 eligible windows) with Terra and running a local Student
  over the full corpus. The remaining eight Teacher failures stay in Review;
  they do not justify another remote pass.
- The completed corpus pipeline is the reusable baseline and will not be
  rerun merely because Luna and Sol are now reachable. A later multi-model
  calibration run uses a 20--24 window throughput probe, adaptive Luna cap of
  120--350, Terra review cap of 50, Sol ambiguity cap of 15, no new calls after
  T+3.5 hours and a hard stop at five hours.
- WebUI 内测页属于现有 Bot Control Plane 的 Evaluation Adapter：它消费既有
  脱敏、browser-safe Demo projection，为人工浏览、候选生成和评价提供入口，
  不拥有 Router、权限、Output、Memory、Tool 或 Bandit 决策，因此不是第二套
  Runtime 控制面。
- 实时 Agent Console 是 Bot Control Plane 的管理员超级工作台，而不是只读面板。
  管理员设置的是 Scope 初值、合法候选范围和可选硬锁；`adaptive` 与
  `preferred` 都允许 Agent 依据本轮任务在 `allowed` 内改选，只有显式
  `locked` 阻止改选。服务端仓库外 Policy 是权威，浏览器状态不是权威。
- 模型 Tier、reasoning、AnswerProfile、回复强度、上下文长度和群聊风格必须
  正交。SHORT/MEDIUM/LONG 只描述回答形态，不能永久绑定 Luna/Terra/Sol；
  一次性回答长度 Hint 只影响当前 Run，不写回长期模型偏好。回复强度是当前
  Run 的候选决策输入，不是实际自动发送概率。插件 `off/auto/on/locked` 只影响
  合法候选或偏好，不能授予 Capability，也不意味着每轮必须调用。
- 配置名统一为“上下文长度（运行预算）”。它只限制本轮送入模型的近期群聊历史，
  不是模型最大 Context Window；`compact/standard/extended` 分别应用
  12/6,000、30/18,000、60/36,000 条消息/字符双上限，并用
  `messagesRead/charactersRead` 报告本轮实际读取量。
- Workspace SSE 采用单调 ID 加最近 512 条内存事件的有限补放即可解决本轮
  重连丢失；无需把内测 Web 扩展成持久消息队列。`Last-Event-ID` 可用时按序
  补放，不可用时回到权威 Snapshot/History 的 `workspace.refresh`。
- 客户端消息顺序由 `timestampMs`、无损十进制 sequence 和稳定消息 ID 共同
  决定；sequence 不再转成 JavaScript `Number`，因此大于 `2^53` 的 NapCat
  序号不会因精度丢失而乱序。初始 Snapshot 期间的实时事件必须在合并后重放。
- Persona 与 AnswerProfile 保持正交且在同一次生成中自然融合：Persona 复用
  版本化配置并按群聊/私聊调整措辞、节奏、关注点和信息取舍；AnswerProfile
  约束回答形态，历史评测面的 Luna/Terra/Sol 映射只保留为旧默认，实时 Console
  由独立 Tier Policy 决定模型。`response_profiles` 关闭
  时不得连带关闭 Persona。模型不得复述人设、自我介绍、套固定口号、机械追加
  表情、模仿具体群成员，或改变事实、权限、任务要求和既有安全边界。
- 合并转发是 Output Adapter 的呈现决策，不是 LONG 的默认同义词。SHORT、
  MEDIUM 与单段 LONG 都是普通消息；只有独立校验通过的 LONG，同时满足
  群聊、至少两个纯文本 part、无附件时才可合并转发。定向目标继续保留在
  Runtime 契约中，但合并转发不额外发送 `@` 组件。
- Dududa 1.0 自动社交行为不再整体继承：Meme Manager、PokePro 从默认插件集合
  退出，Target Talk 从默认 Compose 退出，ReplyPolish 仅作为默认关闭的
  LONG-only 兼容层保留。自动复读则恢复为独立、默认关闭、受 Scope Policy
  管理的 AstrBot 插件；显式 `/image` 是图片生成能力，不是自动表情包，应继续
  保留。
- 操作员显式生成一条真实 Provider 候选，只证明 Web Gateway 的 `no_send`
  纵切可用。该请求没有经过 AstrBot Provider、Dududa Runtime、Connector 或
  Rollout Bridge，不能称为 AstrBot Runtime Shadow、Provider Conformance
  或真实群验证。
- A direct HTTP 200 is reachability evidence, not Runtime readiness. Both
  Responses and Chat Completions work for Luna/Terra/Sol. The fixed-version
  candidate image now carries the approved request overrides, but the running
  AstrBot registry still requires deployment binding, Contract/Conformance and
  refreshable health evidence.
- 固定 AstrBot 4.26.2 候选在完全隔离环境启动，只证明镜像、插件加载和
  `DududaCore loaded` 的启动形状成立；它不等于运行中注册、正式部署、
  Provider Conformance 或真实单群 Shadow。
- Luna/Terra/Sol 的新增证据称为“隔离 Provider no-send 抽样”：runner 直接
  调用 Responses API，绕过 AstrBot Provider、Dududa Runtime、Connector 和
  Rollout Bridge，因此不能升级为 AstrBot Runtime Shadow 或生产健康证据。
- Candidate configuration is merged by stable AstrBot IDs into an isolated data
  root instead of replacing `cmd_config.json`; disabled is the default, while
  Shadow rendering still cannot enable delivery or select a group.
- The current Student is an exploration and Demo asset, not a production
  classifier. High accuracy for `need_tools` and `answer_profile` mostly tracks
  majority classes; `semantic_complexity` held-out Silver agreement is 57.0%.
- 入站 production shape 采用配置驱动装配，不建立第二套路由控制面；AstrBot
  Provider 只实现模型调用 Port，Tier、预算、Runtime 状态和 rollout 所有权
  仍由 Dududa Core 决定。
- 2.0 自然语言 Capability 入口使用现有 Hybrid Perception；PERCEPTION 固定由
  Haiku/Luna 执行，DirectChat 仍由 Static Router 决定。旧 rule-only 只保留为
  Hybrid 降级组件，不能继续描述成生产主入口。
- Unified MCP 是 2.0 Production Composition 的一等资源；`ICourseClient` 只是借用
  共享 Client 的兼容消费者。Runtime 不得再从旧 facade 反向取得 MCP 基础设施。
- Production 共享 Client 装配失败时，兼容 facade 必须同步 unavailable；立即重试并
  建立一个仅供旧入口使用的独立 Client 会重新制造第二条 MCP 所有权路径。
- 控制台可直接调用 18 个 Capability，不等于自然语言 Planner 已支持全部 18 个。
  iCourse 现公布一个 Schema-aware 高层 `icourse.public-query.v2`，只投影
  `query/goal/operation/limit`；教务、校车和二课仍只有 Web 直调，公布范围必须
  与 Planner 实际投影能力一致。
- 可信 Capability failure 目前在 Canary 已 claim 后 no-delivery；旧 handler 和 Web
  search 不得接管。用户可见失败提示应沿 2.0 Composer、Persona、Final Validator
  与授权 Delivery 的唯一输出路径实现。
- `off`/`shadow` 始终保留 legacy 所有权；只有既有 Canary 协议完成持久
  claim 后，Runtime 才可能取得发送所有权。
- 仓库外 Evidence 文件是环境 Adapter，不是新的控制面：AstrBot Context
  resolver 保持优先，文件只作为缺失或返回 `None` 时的 fallback。
- 生产装配复用既有 `BoundedModelHealthPublisher`，不新增第二套健康状态机。
  插件现已内置默认关闭的周期刷新器，默认间隔/超时/TTL 为 45/15/90 秒；
  固定模型探测使用 `max_tokens=8`、`request_max_retries=0`，成功发布
  `HEALTHY`，失败、超时或 TTL 到期发布/保持 `UNKNOWN`，terminate 时取消任务。

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `ops/cli/private_corpus_pipeline.py` now provides the private
  inventory/extract/window/sample/label/compile/train/evaluate/predict/demo/
  serve pipeline. All real text, identity maps, labels, predictions, models and
  rendered Demo stay under the repository-external private data root.
- The Demo projects Student `semantic_complexity` and confidence through the
  existing `DeterministicModelTierPolicy`. It does not define a second router
  and labels Haiku/Sonnet/Opus as an offline non-production preview.
- `#/internal-test` 在没有 NapCat 账号时也可打开，只读取既有脱敏 Demo
  projection。候选响应报告 tier、model、AnswerProfile、延迟和零副作用计数；
  人工反馈追加到配置的仓库外 JSONL，且不持久化候选正文。
- `/api/workspace/events` SSE 帧现在携带事件 ID，支持基于
  `Last-Event-ID` 的有界重连补放；缓存无法覆盖请求区间时发出
  `workspace.refresh`，Snapshot/History 仍是完整状态的权威来源。
- Web Agent 请求新增 `conversationType` 和显式 `answerProfile`；控制台提供
  短/中/长一次性 Run Hint，并把 Persona channel rule 交给既有 no-send Gateway
  消费；模型 Tier 和 reasoning 由独立 Policy 选择，不改变 Output、Memory、Tool
  或 Bandit 契约。
- Agent Console 新增 `GET /api/internal-test/agent/catalog`、
  `GET /api/internal-test/agent/config`、`PUT /api/internal-test/agent/config` 和既有
  `POST /api/internal-test/agent/respond` 的 Scope-aware 语义。配置按
  `accountId + conversationId` 保存到仓库外数据根，每次响应返回
  `effectiveSelection`、`reasonCodes` 与 `contextUsage`。
- Catalog 由服务端动态返回六项正交配置、插件和 MCP Capability 事实，并区分源码
  已安装、配置/Compose 已装配、Runtime online 与本轮实际调用。Web MCP 工作台
  只接受 18 个批准的 Capability ID：iCourse 5 项、教务 6 项、校车 2 项和二课
  5 项；输入控件来自 Capability schema，返回值投影到 Capability output schema，
  不开放任意 MCP Tool。`gpt-image-2` 仍是独立图片能力。自动复读
  和现有 `/sub2api 自动查询` 已恢复为独立 AstrBot 插件，默认 `off`，按
  `accountId + conversationId` 由 Scope Policy 配置。两者要求 WebUI
  `super_admin` 配置，声明 Bot `admin` 执行身份。`/sub2api` 已在 AstrBot 事件
  路径中接入精确 Scope Policy，在线实例已加载它并接收 NapCat OneBot 事件；
  自动复读仍未消费 Web Policy。校园资讯、arXiv、行业和搜索来源继续显示不可用，
  不把查询型校园 MCP、fixture 或接口预留冒充主动资讯插件。
- Agent 状态接口把 Policy 期望与实际行为分开：被动自动回复为关闭状态，
  `rollout_mode=off`、delivery disabled、kill switch active；主动参与仅为
  `probe_shadow`，并明确 `NO SEND`。候选保持 `outputCalls=0`、
  `memoryWrites=0` 和 `toolCalls=0`。
- Runtime 的 `DeliveryRequestBuilder` 只为合法、已验证的 LONG 授予
  `allow_forward_bundle`；AstrBot Output Adapter 再独立校验档位有效性、群聊、
  多纯文本 part 和无附件；定向目标保留在 Runtime 契约中，转发呈现不另发 `@`。
- Persona 解析不再受 `response_profiles` feature flag 支配；DirectChat 在
  同一个模型请求中携带可选 `response_plan` 与 `persona_style`，让表达风格与
  回答形态共同生成，而不是由后处理机械拼接人格。
- 默认 Compose/插件锁不再接入 Meme Manager、PokePro 或 Target Talk；自动复读
  已重新以只读 Compose mount 装配，并保持全局开关默认关闭。新群初始化不再生成
  `meme_rate`，管理命令不再写入它。ReplyPolish 仍以默认关闭的兼容插件存在，
  `/image` 命令仍由 Core 显式提供。
- The planned readiness artifact contains references/digests only. Real account,
  group and test-user mappings remain in a private local binding store.
- The offline checker intentionally distinguishes structural completeness from
  executable authority. It never upgrades a self-declared digest, `live` flag
  or `status=authorized` into real evidence; live Preflight must resolve those
  artifacts and bind them to the exact candidate and target.
- Deployment authorization and group-data readability are separate windows.
  Both must be valid IANA-timezone intervals, and the initial S23 data window
  is capped at seven days.
- 插件配置新增 Runtime 总开关、模型 Endpoint JSON 和回答档位开关；可只配置
  Haiku/Sonnet/Opus 的实际子集，同一 AstrBot Provider 下的各 Endpoint 仍使用
  独立 Dududa Adapter。
- 配置或 AstrBot Provider 解析失败时，初始化安装 unavailable assembly 并
  回退 legacy；日志只记录固定原因码，不写配置、凭据或 Provider 响应。
- Builder 不再从配置布尔值伪造 Conformance。它优先使用 AstrBot Context
  resolver，并可回退到 `runtime_provider_evidence_path` 指向的仓库外
  Evidence Store。Store 先按 AstrBot Provider ID 与模型 ID 精确解析，
  `AstrBotModelProviderAdapter` 再验证输出上限、residency、retention 和
  全部 conformance flags；缺失或不匹配时拒绝装配。
- `ProductionRuntimeAssembly.publish_model_health()` 将显式健康证据交给
  bounded publisher。Router 和 Admission 读取同一投影视图；初始无证据和
  TTL 过期均表现为 `UNKNOWN`。思考深度当前是 Endpoint 固定 Profile。
- `ops/cli/run_provider_no_send_shadow.py` 对 Luna/Terra/Sol 各执行一次直接
  Responses API 调用，并只持久化模型/档位、成功标志、延迟、usage、
  `provider_calls=1` 与 `output_calls=0`。收据不包含 Key、Base URL、Prompt、
  回答、QQ 标识或 Provider 错误正文；失败样本使用注入故障验证脱敏。
- 插件配置新增默认关闭的 `runtime_health_probe_enabled` 及刷新间隔、探测超时、
  Evidence TTL 参数。刷新任务随插件生命周期启动/取消，不改变 Capability、
  Rollout 或 Output 所有权。

- 对具有明确产品语义的站点 marker，Rule Perception 应确定性提出 Capability
  category，模型继续负责意图和实体；这比要求模型以概率方式重复识别显式事实更
  稳定，也没有把 Tool、权限或发送权交给规则。确定性触发必须只作用于当前
  Context 已公布的 category，并继续经过开关、授权、预算、流量与健康检查。
- “测试集存在”“测试集经过 Runtime”和“公开快照上生成了回答”是三种证据。
  本轮形成 75 次真实本地 Unified MCP dispatch，并另行完成 75 个公开快照回答；
  两者都不能自动升级为生产语义完成。五操作 Planner 仍是单步高层查询，缺失的
  用户/回复/历史数据和 27 个部分结果继续阻止全量完成声明。
- 真实 Luna 在三个用户回归中精确抽取 `人工智能`、`萌萌哒mmd`、`线性代数B1`；
  75 条中 category 为 74/75。Case 67 是无站点词、无上文的泛化评分比较，对其
  强制 iCourse 会造成普通聊天误调用，所以不扩张确定性关键词范围。
- Tool 调用不应通过重试堆叠召回率：当前 `maximum_attempts=1` 已足以把显式
  marker 约束为一次有界计划。`USE_TOOLS` 只在用户没有明确详略要求时默认 LONG；
  输出形态仍由实际分片决定，单段结果不为追求形式而包装成单节点转发。

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Silver is heavily imbalanced: 447/464 rows say no Tool, only 4/464 are high
  complexity, and no LONG AnswerProfile survived compilation. A balanced human
  Gold set is required before threshold calibration or production integration.
- The running AstrBot/NapCat stack is not the S19 derived candidate and has not
  been authorized for replacement. S23 needs an explicit deployment window and
  a rollback owner before mutation.
- 512 条 SSE 重放是断线恢复窗口而非持久日志；服务进程重启或客户端落后超过
  窗口时只能刷新 Snapshot/History。当前修复减少可观察丢失，不构成跨进程
  exactly-once 保证。
- Persona 接线只证明配置、channel rule 和回答档位进入生成链路；真实中文群聊
  的自然度、群体情境适应和长短回答边界仍需人工内测反馈，不能声明已充分校准。
- Agent Console 的动态 Catalog、Policy 持久化和有效选择解释只证明超级工作台
  纵切闭合；六项配置中的回复强度也不能替代真实发送授权。自动复读和
  `/sub2api 自动查询` 的 `triggerMatched` 只表达确定性触发条件适用，当前仍为
  `selectedForRun=false`、`toolCalls=0`；已安装/已配置不等于 Runtime online，
  且 no-send Gateway 不等于生产 AstrBot Runtime 或真实群权限。
- Production `CurrentMessageContextBuilder` 目前仍主要投影当前消息；Web 内测
  上下文与 Prompt 风格接线不能替代生产近期群聊上下文，因此长期群体情境适应
  尚未完成。
- 仓库默认 AstrBot 插件隔离仍只装配 Dududa Core、ReplyPolish、自动复读和
  Sub2API，没有恢复 Meme Manager、PokePro 或 Target Talk。校园 MCP 由独立
  `mcp-console` 运行并已供 Web 超级管理员只读调用；当前 AstrBot/NapCat 未因该
  接入重启，因此不能把 Web 调用证据外推为 Agent 自动 Tool 选择或主动发送。
- Runtime MCP 接入现在能保存连接定义并发现 Tool，但 Discovery 只更新外部事实。
  新 Server 默认有零项 Capability；要让 Agent 使用，仍需主仓独立的 Definition、
  Schema、MCP mapping 和 Scope Policy。当前 Web 信任边界仍是本机回环地址加
  同源管理页面，不能据此声明已经具备远程管理员认证。
- 可解析的 Evidence JSON 只证明工程契约成立，不证明字段来自真实
  Conformance 执行。当前聚焦测试仍使用 Fake AstrBot Provider 和固定
  Evidence fixture；健康刷新实现已经存在，但运行中 AstrBot 未启用，正式
  Conformance、持续生产健康、部署绑定和实际 Shadow 均未证明。
- 默认关闭的刷新器只有在正式部署配置启用后才会周期探测；在此之前没有生产
  健康证据。即使曾发布 `HEALTHY`，TTL 内没有成功刷新时 Router 仍会恢复
  `UNKNOWN`。
- 当前运行中的 AstrBot 只注册 DeepSeek V4 Pro/Flash 和 GPT-5.5，尚未切换到
  已打补丁的候选镜像，也未注册 Luna/Terra/Sol。候选样板的 light/balanced/deep
  是待 Conformance 的 pilot 初值；真实请求只抽样验证过 `low`，不能据此声称
  medium/high/xhigh 或持续观测已经通过。
- 注入的 no-send 失败样本只证明收据脱敏和零 Output 行为，不代表真实 Endpoint
  曾发生故障，也不能替代正式故障注入或生产错误率观测。
