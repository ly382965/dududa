# Findings

Branch: real-group-validation

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- 频率滑块部署后的空下拉不是 Runtime 失效，而是部署前已加载的旧 SPA 继续读取
  新 Catalog：旧 JS 依赖 `proactiveFrequencies`，新接口只返回
  `proactiveTalkLimits`。带哈希静态资源和 `index.html no-cache` 均工作正常，不能
  替换浏览器内存中已运行的 JS。Catalog 因此暂时 additive 保留旧三档别名；新
  数值契约仍是唯一 canonical 写入，普通刷新进入新滑块界面。
- 自动搭话频率不能复用 `replyIntensity`。前者控制真实抽样、冷却和每小时上限，
  后者仍是单次 Run 的参与偏好；把两者合并会让管理员无法区分“更积极地表达”与
  “更频繁地发送”。目标群因此使用独立 `proactiveTalk` 数值策略；概率、冷却和
  每小时上限由管理员分别拖动，旧 `low/normal/high` 只在读取边界迁移。
- 主动控制器原有独立的 60 秒尝试间隔会让 5 秒冷却永远无法生效。尝试间隔现取
  `min(60s, cooldownSeconds)`：普通配置仍不会因每条入站消息密集重试，最快配置
  则可在 5 秒后再次尝试；每小时上限继续只统计成功发送。
- 主动群聊不能通过伪造 `@Bot` 复用普通入口。NapCat 历史被投影为群级上下文后，
  Runtime 保留 `explicit_interaction=false`，Social Decision 使用无个人 target 的
  ACTIVE 群级路径；Tool、Memory 和个人 `@` 均关闭，最终仍复用 Canary、Output
  Adapter 和 Delivery Receipt。
- AstrBot 插件热重载只更新插件目录，不会更新镜像内已安装的 `dududa-agent`。
  当本轮同时扩展 Core admission/context 签名，单独热重载会被 Bridge 的外部边界
  捕获并静默退回 legacy。部署必须同时更新 Python package；本次用本地 wheel
  离线增量镜像完成，只重建 AstrBot/Web，NapCat 保持运行并自动重连。
- `astrbot_plugin_reread` 仍是独立 AstrBot handler，尚未读取 Agent Scope Policy。
  `social.reread.auto=off` 当前不能按群关闭它；自动搭话已与其使用不同插件 ID 和
  频率状态，但不能声称 Web 已拥有复读的群级执行控制。
- 培养方案中的两位年级是领域实体，不是自由文本查询词。Planner 应先归一化
  `25级 -> 2025` 并保留横向比较的两个专业；MCP 边界仍要拒绝两位数字对子串代码
  的模糊命中，避免一次感知漏项演变成表面合理的无关事实。普通主修跨专业比较与
  同专业特殊方案对照是两种语义，不能继续共用“取任意首条普通方案”的回退。
- `requiredOnly/electiveOnly/mixed` 是研究快照中的课程号池分类，不是学生实际需修
  门数或分项学分。最终 Observation 必须同时给出准确总学分、池计数的口径，以及
  当前公开快照未发布分项学分这一边界；不能让 DirectChat 从 53/393 反推毕业要求。
- 校车是仅供 Dududa 使用、无需认证/缓存/独立发布周期的静态确定性查询；MCP 会增加
  不必要的进程、Session 和网络抓取路径。它因此改为 owned 插件实现的 `BUILTIN`
  Capability Provider，继续复用同一个 Registry/Retrieval/Planner/Executor/Validator
  控制面。插件不注册消息 handler，不能绕过 Dududa 2.0 Runtime。
- 教务开课和考试 Tool 的官方上游仍要求整数 semester ID，但用户输入通常是
  “2026 秋/本学期”。为保持一个 Agent Tool Step，Academic MCP Adapter 在该次
  只读调用内查询官方学期列表并解析 ID；Planner 只投影学期表达和公开过滤词，
  不硬编码 semester ID，也不引入第二个控制面。
- Provider health freshness and Endpoint load freshness are independent Router
  inputs. Re-publishing fresh health with the original load timestamp makes a
  long-lived Runtime fail after `runtime_model_load_max_age_seconds`, even when
  every health probe succeeds. The existing production load value is the local
  assumption of zero external-to-admission-controller traffic, so each bounded
  health cycle now republishes that assumption with the same observation time;
  local RPM/TPM and concurrency remain owned by the Admission Controller.
- 运行切换后的 Agent 所有权只有一份：`dududa-astrbot-1` 中的 Dududa 2.0 Core。Canary 是
  2.0 内部的持久 claim/Delivery 模式，不是与 1.0 并行；不受支持的私聊、附件和未 @ 群消息
  静默结束，不能再回退旧 Agent。
- Sub2API v0.6.4 与 Reread v2.0.0 是明确保留的 2.0 AstrBot 宿主能力。它们可以与 Core
  共用一个宿主，但“插件已加载”仍不等于“Agent 获得 Capability/Planner 权限”，也不构成
  旧 1.0 服务继续运行。
- Web readiness 必须同时读取 Core 配置和 `runtime-status.json`：当前
  `actualEnabled=true / canary / deliveryEnabled=true / killSwitch=false` 与 Core `ready=true`
  一致。QQ 连接健康来自独立的 1/1 NapCat 在线状态；NapCat 在本次切换中未重启。
- Web Policy 已成为生产 Runtime 输入，但当前只消费精确 Scope 的 Agent 开关和
  MCP Capability 类别资格。不能据此宣称模型档位、推理深度、AnswerProfile、
  回复强度、上下文长度和群聊风格六项都已驱动生产 Runtime。
- Capability 的 `on/locked` 表示“保留在合法候选集”，不是“每轮必须调用”。
  Perception、有限 Planner、全局 Tool 开关、授权、预算和健康过滤继续共同决定
  是否发生实际 MCP 调用。
- AstrBot/OpenAI Provider 的输入 usage 含宿主与上游固定 Prompt 开销，不能继续
  用 64 Token 作为通用 wrapping 估算。实测差值会让成功响应在 Admission settle
  时变成 `provider_usage_receipt_invalid`。该值现在是 Endpoint 配置，默认 4,608；
  预算只按这项实测开销调整，没有改变模型档位或路由规则。
- Web no-send 预览必须复用已安装的 `AgentRuntime`，并以内存 Delivery Receipt
  完成 `READY_TO_EMIT -> COMPLETED`；直接在 Node 中再写一套模型/MCP 编排会形成
  第二套 Runtime。预览可调用只读 Capability，但不能 claim QQ Event 或调用 Output。
- 模型健康探测不需要 45 秒高频请求。当前 900 秒间隔配合 1800 秒 Evidence TTL，仍允许一次
  漏刷后保持有界健康窗口，同时显著降低三模型持续探测消耗。
- MCP 链的用户价值由现有 `DIRECT_CHAT` 模型完成，不由 URL formatter 完成。
  Observation 是证据，不是回复；最终回答必须先归纳原文内容，链接只作次要引用。
  这复用 Perception 后既有的第二次模型调用，不再增加一次总结调用或另一条发送路径。
- Complex iCourse questions still consume one Runtime Tool step. The selected
  high-level `icourse.public-query.v2` operation may perform a bounded sequence
  of public-site GETs and in-memory projection inside the read-only Server, but
  the Agent does not build an N+1 Tool plan or retry Tool selection. Capability
  and MCP governance remain outside the model; SQLite joins/rankings belong only
  to historical evaluation and legacy management.
- iCourse review full-text hits do not establish author identity. In particular,
  the five `Wanglulu` search hits only mention that name; the exact public user is
  `/user/12918`, whose review page reports 54. The ranking page may help discover
  a user ID, but its 56/84 counters differ from the authoritative user-page totals
  54/83 for Wanglulu and 萌萌哒mmd. Exact-user answers therefore use the user
  review page and never substitute keyword counts or SQLite rows.
- Anonymous iCourse reviews remain eligible public evidence; anonymity affects
  displayed identity, not public-read eligibility. Site timestamps use both ISO
  and `MM/DD/YYYY`, so year filters must handle both forms in historical assets.
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
  上游账号、缓存与错误处理；本轮不重新设计这些逻辑。由于 ReplyPolish 已退出 2.0
  运行面，显式管理员命令 `overview` 在自身输出边界直接构造
  四节点合并转发，避免依赖普通回答风格链。
- 旧 Compose 项目名不能直接等同于 Dududa 1.0：旧 AstrBot 容器已经不存在，
  但同一项目名下的 NapCat 正被 Dududa 2.0 复用为唯一 QQ Connector。版本切换
  只关闭明确识别出的 legacy AstrBot；不得对旧项目执行整体 `down/stop`。
- S23 completion is the bounded single-group ladder plus closeout. Expansion to
  3–5 groups is a later authorization decision, not an inherited grant.
- iCourse、二课、教务和培养方案研究是查询型 MCP Capability，校车是本地查询
  Capability；不能据此声称日报 Source
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
  12/6,000、30/18,000、100/36,000 条消息/字符双上限，并用
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
- Dududa 1.0 自动社交行为不再整体继承：Meme Manager、PokePro、Target Talk、ReplyPolish
  与旧 Handler 均退出运行面。Reread 作为独立 2.0 宿主能力保留；显式 `/image` 是图片生成
  能力，不是自动表情包。
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
- MCP 控制台可直接调用 14 个映射，不等于自然语言 Planner 已支持全部映射。
  iCourse 现公布 Schema-aware 高层 `icourse.public-query.v2`，二课公布搜索、详情、
  筛选项和连接状态四种公共观察；培养方案研究和教务只公布已有确定性投影的只读操作，
  校车另由本地 Builtin Provider 执行。五类均已进入单步 Planner，公布范围必须与 Planner
  实际投影能力一致；这不等于 14 个映射都支持任意自然语言参数组合。
- 可信 Capability failure 目前在 Canary 已 claim 后 no-delivery；旧 handler 和 Web
  search 不得接管。用户可见失败提示应沿 2.0 Composer、Persona、Final Validator
  与授权 Delivery 的唯一输出路径实现。
- Young 上游必须使用 CAS 会话，但部署 SecretRef 是 Server 连接事实，不是 QQ 用户身份。
  因此 MCP 只保留四个公共只读 Tool，并从 Schema、Capability、权限和 Observation 中移除
  `young_list_my_activities`、个人报名状态、联系方式、报名/取消和申请人数据。
- `off`/`shadow` 始终保留 legacy 所有权；只有既有 Canary 协议完成持久
  claim 后，Runtime 才可能取得发送所有权。
- 仓库外 Evidence 文件是环境 Adapter，不是新的控制面：AstrBot Context
  resolver 保持优先，文件只作为缺失或返回 `None` 时的 fallback。
- 生产装配复用既有 `BoundedModelHealthPublisher`，不新增第二套健康状态机。
  插件内置的周期刷新器已在当前部署启用，运行间隔/超时/TTL 为 900/15/1800 秒；
  固定模型探测使用短输出，成功发布
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
- Scope 查询必须保留 Connector 的命名空间账号 ID，例如 `qq-<self_id>`；只传裸
  QQ 数字会解析到另一个默认 Scope，从而错误显示插件全为 `off`，不能据此判断
  目标群策略未生效。
- `FileScopeAgentPolicyResolver` 在 AstrBot Bridge 内读取同一份仓库外 Policy，
  产生 `scope_agent_enabled` 和 `capability.category.<id>` feature flags；
  `CurrentMessageContextBuilder` 只用这些 flags 缩小既有 Perception 类别。
  Web Catalog 的 `online` 表示对应路径已由 ready 的 2.0 Runtime 消费；当前 iCourse、
  二课、培养方案研究、教务和校车均已接自然语言 Planner。
- Catalog 由服务端动态返回六项正交配置、插件和 MCP Capability 事实，并区分源码
  已安装、配置/Compose 已装配、Runtime online 与本轮实际调用。Web MCP 工作台
  只接受 14 个批准的 MCP Capability ID；校车的 1 个本地 Capability 通过 Agent
  no-send 预览调用。输入控件来自 Capability schema，返回值投影到 Capability output schema，
  不开放任意 MCP Tool。`gpt-image-2` 仍是独立图片能力。自动复读
  和现有 `/sub2api 自动查询` 已恢复为独立 AstrBot 插件，默认 `off`，按
  `accountId + conversationId` 由 Scope Policy 配置。两者要求 WebUI
  `super_admin` 配置，声明 Bot `admin` 执行身份。`/sub2api` 已在 AstrBot 事件
  路径中接入精确 Scope Policy，在线实例已加载它并接收 NapCat OneBot 事件；
  自动复读仍未消费 Web Policy。校园资讯、arXiv、行业和搜索来源继续显示不可用，
  不把查询型校园 MCP、fixture 或接口预留冒充主动资讯插件。
- Agent 状态接口把 Policy 期望与实际行为分开：当前受支持的被动入站为
  `rollout_mode=canary`、delivery enabled、kill switch inactive；主动执行器全局
  online，只有目标 Scope 的 `social.proactive_talk=locked` 使其实际开启。历史评测
  候选继续保持 `outputCalls=0`、`memoryWrites=0` 和 `toolCalls=0`，不能用它覆盖
  实时 Runtime 状态。
- Runtime 的 `DeliveryRequestBuilder` 只为合法、已验证的 LONG 授予
  `allow_forward_bundle`；AstrBot Output Adapter 再独立校验档位有效性、群聊、
  多纯文本 part 和无附件；定向目标保留在 Runtime 契约中，转发呈现不另发 `@`。
- Persona 解析不再受 `response_profiles` feature flag 支配；DirectChat 在
  同一个模型请求中携带可选 `response_plan` 与 `persona_style`，让表达风格与
  回答形态共同生成，而不是由后处理机械拼接人格。
- 当前 Compose/插件运行根只装配 Core、Reread 与 Sub2API，不再接入 ReplyPolish、Meme
  Manager、PokePro 或 Target Talk。新群初始化不再生成 `meme_rate`，管理命令不再写入它；
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
- 插件配置提供 `runtime_health_probe_enabled` 及刷新间隔、探测超时、Evidence TTL 参数。
  当前部署显式启用并使用 900/15/1800 秒；刷新任务随插件生命周期启动/取消，不改变
  Capability、Rollout 或 Output 所有权。

- 对具有明确产品语义的站点 marker，Rule Perception 应确定性提出 Capability
  category，模型继续负责意图和实体；这比要求模型以概率方式重复识别显式事实更
  稳定，也没有把 Tool、权限或发送权交给规则。确定性触发必须只作用于当前
  Context 已公布的 category，并继续经过开关、授权、预算、流量与健康检查。
- “scripted routing contract”“真实模型 Runtime/Fake Delivery”“AstrBot 宿主入口”和
  “真实 NapCat/QQ E2E”是四种不同证据。本轮最终真实模型纵切为 75/75 Runtime、
  73 次 MCP 和 75/75 Fake Delivery；宿主内存入口另为 75/75，但没有形成一条穿过
  真实 NapCat 与 QQ 回执的无中断链。二者都不能自动升级为生产语义完成。
- Luna Review 是 Runtime 结束后的旁路测试：最终合并结果中 65/75 个审校稿与实际
  Delivery 不同，没有重新经过 Composer、Final Validator 或 Output。模型自审在补跑后
  标记 60/75 完整，人工交叉核对只保留 49/75；以后不能用 reviewer 的 grounded/complete
  布尔值替代跨题事实审校。
- 五操作 Planner 仍是单步高层查询。人工未完整项集中在别名规范化、结构化筛选、最新/
  时序、用户/回复联表、分页和多步聚合；增加重试不会补足这些能力，应该扩展查询计划和
  Provider 数据语义。
- 真实 Luna 在三个用户回归中精确抽取 `人工智能`、`萌萌哒mmd`、`线性代数B1`；
  75 条中 category 为 74/75。Case 67 是无站点词、无上文的泛化评分比较，对其
  强制 iCourse 会造成普通聊天误调用，所以不扩张确定性关键词范围。
- Tool 调用不应通过重试堆叠召回率：当前 `maximum_attempts=1` 已足以把显式
  marker 约束为一次有界计划。`USE_TOOLS` 只在用户没有明确详略要求时默认 LONG；
  输出形态仍由实际分片决定，单段结果不为追求形式而包装成单节点转发。
- LONG 合并转发原来按 UTF-8 字节硬切，能把“给分”“基础”等词拆到相邻节点。
  最小修复是保留字节上限、优先选择换行/句末/空格边界；无需引入新的渲染控制面。
- aiocqhttp 对每个 WebSocket 帧创建独立任务，而 AstrBot 的 @ 转换还会异步查询成员；
  延迟第一条查询 50 ms 时，输入 `1,2,3` 稳定入队为 `2,3,1`。顺序执行 Runner 的
  75/75 不能作为生产顺序保证。

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Silver is heavily imbalanced: 447/464 rows say no Tool, only 4/464 are high
  complexity, and no LONG AnswerProfile survived compilation. A balanced human
  Gold set is required before threshold calibration or production integration.
- 2.0 AstrBot 已完成运行替换，NapCat 保持原实例。当前残余风险是宿主并发入队可乱序，且
  缺少用户触发的真实 QQ 端到端回复 Receipt，而不是候选尚未部署。
- 512 条 SSE 重放是断线恢复窗口而非持久日志；服务进程重启或客户端落后超过
  窗口时只能刷新 Snapshot/History。当前修复减少可观察丢失，不构成跨进程
  exactly-once 保证。
- Persona 接线只证明配置、channel rule 和回答档位进入生成链路；真实中文群聊
  的自然度、群体情境适应和长短回答边界仍需人工内测反馈，不能声明已充分校准。
- Agent Console 的动态 Catalog、Policy 持久化和有效选择解释不替代 Runtime 证据。当前 Web
  已能从 Core config/status 证明受支持入站实际开启；Reread/Sub2API 的在线加载仍只说明宿主
  能力存在，不能从 `triggerMatched` 或安装状态推导一次实际插件调用。
- iCourse Policy 接线已有运行中容器、精确 Scope 解析和完整 Web -> 2.0 Runtime ->
  MCP -> 总结的 no-send 实测。二课已有 OneBot-shaped Event -> 2.0 Runtime ->
  Unified MCP -> Fake Delivery 的 75 题证据；培养方案、教务和校车也已有 2.0
  no-send Runtime 抽样，但这些都还不是 NapCat/QQ 真端到端 Receipt。
- Production `CurrentMessageContextBuilder` 目前仍主要投影当前消息；Web 内测
  上下文与 Prompt 风格接线不能替代生产近期群聊上下文，因此长期群体情境适应
  尚未完成。
- Production Composition 的注入时钟必须同时交给 Runtime State Store、DirectChat
  和 Content Safety；只让 Router/Orchestrator 使用该时钟会使固定时钟 Run 在真实
  时间推进后被下游误判为过期。现有 75 题固定时间纵切直接复现并覆盖该契约。
- 当前唯一 AstrBot 宿主只加载 Dududa Core、Sub2API v0.6.4、Reread v2.0.0 和 AstrBot
  内建插件；ReplyPolish、Meme Manager、PokePro、Target Talk 与旧 Handler 均已退出运行面。
  校园 MCP 由独立 `mcp-console` 提供，Web 调用证据仍不能外推为 Agent 自动 Tool 选择或主动发送。
- Runtime MCP 接入现在能保存连接定义并发现 Tool，但 Discovery 只更新外部事实。
  新 Server 默认有零项 Capability；要让 Agent 使用，仍需主仓独立的 Definition、
  Schema、MCP mapping 和 Scope Policy。当前 Web 信任边界仍是本机回环地址加
  同源管理页面，不能据此声明已经具备远程管理员认证。
- Luna/Terra/Sol 已在运行 AstrBot 注册并各完成一次真实 Chat 调用，Core status 也为 ready；
  但单次成功仍不证明长期可用性或质量。刷新器按 900 秒运行，TTL 内没有成功刷新时 Router
  仍会恢复 `UNKNOWN`。
- 2026-08-30 的主动搭话失败不是凭据失效：三档模型探测均能成功，但容器内延迟存在明显
  波动，原 15 秒探测超时会把慢成功取消为 `UNKNOWN`；后续一次临时超时还会立即覆盖
  TTL 内的健康证据，导致 Static Router 暂时没有合法候选。Core 现在使用 60 秒探测超时，
  并在新探测仅为 `UNKNOWN` 时沿用尚未过期的最后可用证据；显式 `UNAVAILABLE` 和 TTL
  到期仍会正常撤销资格，没有放宽 Router 的资格过滤。
- 路由恢复后，Rollout Ledger 将失败从毫秒级 `runtime_failed_without_delivery` 推进到模型
  完成后的 `rollout_admission_changed`。初次 Admission 已显式允许群级主动参与，但持久
  Canary Send Guard 复验时遗漏了同一标志，于是把合法的非 `@` 主动回复重新当作普通入站
  拒绝。Guard 现在从已绑定到 `RuntimeStartRequest` 的布尔 Feature Flag 恢复同一语义；
  revision、Canary mode、kill switch、delivery enabled 和 allowlist 复验保持不变。
- 三档当前都固定为最低 `light/low`。没有证据支持 medium/high/xhigh 的运行质量，也没有
  实现同一 Endpoint 的逐请求动态思考深度切换。
- 注入的 no-send 失败样本只证明收据脱敏和零 Output 行为，不代表真实 Endpoint
  曾发生故障，也不能替代正式故障注入或生产错误率观测。
