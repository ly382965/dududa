# Verification

Branch: real-group-validation

## Latest Verification

- 2026-08-31 校车无回复修复：20 条既有校车事实/Schema 用例和新增泛查询大小回归
  3/3 通过；Production Composition 校车 2.0 Runtime 聚焦测试通过。热重载校车和
  Core 后，原句“查看明天校车”经 Web -> 已安装 Runtime 返回 Terra `low`、LONG、
  `toolCalls=1`、非空总结、`outputCalls=0 / memoryWrites=0`，耗时 44,417 ms；
  Capability 仅为 `ustc.shuttle.public-query.v1`，原上下文溢出原因码消失。
- 2026-08-31 Web 历史/SSE 修复：Server 37/37、Workspace 13/13、TypeScript
  typecheck 和 production build 通过。600 条事件重放用例证明超过旧 512 窗口仍从
  ID 2 连续补放；不足请求数的中间页、终页探测和重复游标均有聚焦覆盖。部署后目标群
  首页/第二页实际返回 95/93 条，二者 `hasMoreBefore=true` 且游标前进。
- Output Adapter 17/17 与 Ruff E/F/I 通过。发送异常后的精确近期 Bot 消息可协调为
  `SUCCEEDED` 并绑定平台消息 ID；无可读历史仍为 `UNKNOWN`，没有重试发送，合并转发
  行为未改变。本轮未故意触发真实 QQ 外部发送。Core/校车均为插件热重载，Web 单独
  重建；AstrBot 与 NapCat 容器 ID、StartedAt、`RestartCount=0` 保持不变。
- 2026-08-30 WebUI 跨版本空下拉修复：实际 Catalog 同时返回新版三滑块范围和
  旧 `low/normal/high` additive 别名；旧 `high` PUT 迁移测试保持通过。Web Server
  聚焦测试 9/9、TypeScript typecheck 和 build 通过。部署后 Playwright 在目标群
  读取到三个 enabled range，值为 20/180/8；Web、AstrBot、NapCat 均 running，
  后两者未重启。
- 2026-08-30 连续主动频率更新：Python 主动搭话契约 6/6、Web Server 10/10、
  Workspace 12/12、TypeScript typecheck、production build、Ruff 和 whitespace
  检查通过。最大端点测试证明 100% 概率下 4.999 秒仍受冷却限制、5 秒可再次进入，
  扩展档向 NapCat 请求最多 100 条。Core 单插件热重载成功；AstrBot 与 NapCat
  `RestartCount` 均保持 0。Web 单独重建后 Catalog 返回 0-100% / 5-1,800 秒 /
  1-500 次三条滑块范围。目标 Scope 已迁移为 20%/180 秒/8 次每小时并切到
  `extended`；本次未发送 QQ 测试消息。
- 2026-08-30 自动搭话聚焦验证：Admission、Context、Social、Runtime、Rollout、
  历史投影与频率 46/46 通过；Web Workspace 12/12、Server 10/10、TypeScript
  typecheck 和 production build 通过。真实 AstrBot `Plain` 事件投影 smoke 通过，
  Web 经 OneBot `get_group_msg_history` 读取目标群最近 12 条，证明 NapCat 历史能力
  在线；未人为发送测试 QQ 消息。
- 部署证据：本地 wheel 镜像中的 `decide_rollout_admission` 已包含
  `allow_proactive_group`，Context preprocess 已接收 feature flags；唯一
  `dududa-astrbot-1` 与 `dududa-web-1` 单次重建后 Runtime status 为
  `ready=true / proactive_talk_enabled=true`，NapCat 未重启并恢复 OneBot 连接。
  Web Catalog 报告 `social.proactive_talk` online，目标 Scope 返回
  `normal + standard + natural`、主动 SHORT 和明确 `@Bot` LONG 锁定。自然概率
  命中的真实主动 Delivery 尚未观察，因此 S23 总体仍为 `paused/partial`。
- 2026-08-29 培养方案事实回归：USTC campus package 14/14、Planner 4/4、Ruff、
  output Schema 和 whitespace 检查通过。真实公开快照直调对完整单方案问题返回
  `2025级 计算机科学与技术 / 167 学分`；对
  `query=25, goal=对比25级计算机和人工智能` 返回两份 2025 级普通主修，而不是
  `02502` 网络与新媒体。MCP Console 同一路径成功，generation=2。
- Core 经单插件热重载生效，AstrBot 与 NapCat `RestartCount` 保持 0。原 NapCat
  消息 `712374591` 通过 `get_group_msg_history -> aiocqhttp convert_message ->
  Dududa 2.0` no-send 重放，结果为 Terra/low、LONG、一次
  `ustc.curriculum.public-query.v1`、`outputCalls=0`、`memoryWrites=0`；回答正确引用
  2025 级两专业均为 167 学分及专业课程差集。第一条单方案原问题的 Web -> 2.0
  预览同样只调用一次培养方案 Capability，并明确快照无法证明必修/选修分项学分。
- 2026-08-29 目标群 `364894085` no-send 耦合抽样：iCourse、二课、培养方案、
  Academic 和校车均为 `on`；五类自然语言输入各自只选择对应插件并执行一次只读
  Tool，普通聊天为零 Tool。六条 Web -> 已安装 2.0 Runtime 预览均返回
  `runtimePath=dududa_2_preview / outputCalls=0 / memoryWrites=0`，AstrBot 与 NapCat
  `RestartCount=0`，未发送 QQ 消息。
- Academic 实际预览把“教务处查询 2026 秋季学期的开课信息”解析为官方
  `semester_id=461`，返回 2,841 个教学班中的前 10 条；只选择
  `ustc.academic.read`。USTC campus package 11/11、Production Composition 聚焦通过、
  Web server 9/9 和配置生成器 `--check` 通过。
- 2026-08-29 校车插件：`tests/fixtures/ustc_shuttle/questions.v1.json` 的 20/20 问题
  通过静态查询事实断言和 Capability output Schema 校验，覆盖校园三校区、节假日、
  `no_public_bus`、高新即停即走、下一班、太湖路周六特例、周日班次与未知直达线路。
- 3 条原生 `@Bot` 消息抽样通过 Dududa 2.0 Perception -> Planner -> Builtin Provider
  -> Observation -> DirectChat -> Fake Delivery；每条一次本地 Tool、一次最终回答、一次
  Fake Delivery。模型漏报校车 Tool 的样本由显式 marker 补回，MCP Client 未执行校车
  discover/call，QQ Output 为 0。
- 当前聚焦回归通过：校园 Runtime/配置/Registry 18/18，二课 75 题纵切 1/1，
  owned 插件安装与 repository contract 15/15，USTC campus package 11/11，Web
  `internal-test.spec.ts` 9/9，配置生成器 `--check` 通过。S23 仍为 `paused/partial`。
- 固定时钟复跑曾暴露 Production Composition 只把时钟传给 Router/Orchestrator，
  未传给 State Store、DirectChat 和 Content Safety，导致固定时间过去后 75 题在
  不同阶段被误判超时。三处现共用 `effective_clock`；原 75 题测试无需改 fixture 即通过。

- 2026-08-29 二课原生消息形状模拟：75 个手工构造的 OneBot-shaped Event 全部进入
  唯一 Dududa 2.0 Bridge，结果为 75/75 Runtime completed、75/75 Fake Delivery、
  62 次 Unified MCP、13 次正确不调用、150 次脚本 Fake 模型调用和 0 次真实 QQ 发送。
  关键语义断言覆盖日期、报名窗口、余位阈值、填充率排序、容量、学时效率、五育覆盖
  和规模比较。
- 同一路径只调用 `young_search_activities`、`young_get_activity`、
  `young_list_facets` 和 `young_connection_status`；个人活动、报名、取消、申请人、
  Web search、ReplyPolish 和旧命令路由均未执行。Case 54 多实体比较使用宽查询，
  根据公开余位比较当前报名可行性，没有仅按活动规模推断。
- Case 70 的脚本模型故意把“我参加过哪些二课”误判为 Young 公共搜索；2.0 合并前的
  确定性资格过滤移除该 category/intent，最终仍给出诚实边界回答且 MCP 调用为 0。
- 生产 Registry -> Unified Client -> Young MCP 真实只读抽样只发现四个 Tool 并成功
  调用；错误凭据抽样返回 `available=false` / `young_authentication_or_upstream_failed`，
  无凭据或内部异常泄露。这些是只读工程证据，不是提问者登录、真实 QQ 端到端或全量
  中文质量证据。
- Luna Perception + Terra DirectChat 以最低 `low` 对 Case 1/54/71 完成 3/3 最小
  真实模型抽样，旁路 Luna Review 为 3/3 grounded/complete/process-hidden。Review
  未进入 Runtime 生产链，不是已发送回复。
- 聚焦验证通过：75-case 1 项、Young Planner 3 项、Young MCP Contract 4 项、CAS
  Secret resolver 1 项和配置生成器 `--check`。运行中的 AstrBot 未重启或重建，因此
  尚未消费新增的只读 CAS 挂载；75 个 Event 也未经过 NapCat、AstrBot Filter 调度或
  真实 QQ 回执。校车与教务 Planner 已由上方 2026-08-29 证据补齐；通用
  Capability 失败答复仍未完成，S23 保持
  `paused/partial`。

- 2026-08-28 iCourse live-source closeout: all five model-visible Capability
  mappings now read current public pages. A focused test replaces
  `ICourseStore.stats/search_courses/get_course/get_reviews` with immediate
  failures; all high-level and legacy reads still pass. The local fixture runs
  a real MCP stdio subprocess against fixed HTML, so Worker, Capability Provider,
  natural-language Runtime and the 75-case dispatch contract no longer depend on
  an SQLite seed or the public network. The 21-test focused unit/plugin/config
  run passed 19 with two expected AstrBot-host skips; two Worker/Provider tests
  and two Production Composition regressions passed separately.
- Real public-site smoke used an empty temporary SQLite and called
  `icourse_stats`, `search_courses`, `get_course` and `get_reviews`; it observed
  19,194 courses, 49,606 reviews and four `大数据算法` search hits while the
  database remained 0 courses/0 reviews. The Web MCP Console then called the
  compatible `icourse.courses.search.v1 -> search_courses` path and returned the
  same four live hits on generation 3.
- Two installed Dududa 2.0 no-send previews in Scope `364894085` each made one
  MCP call: `查询评课社区wanglulu` reported the user page's 54 reviews and
  `查询评课社区萌萌哒mmd` reported 83. Both used Terra `low`, selected LONG,
  returned `bounded_tool_execution + delivery_ready`, and recorded
  `outputCalls=0` plus `memoryWrites=0`. The active Runtime cache remained 11
  courses/24 reviews; the Console cache remained 0/0.
- AstrBot 4.26.2 only detects lifecycle methods declared on the concrete plugin
  class. The new concrete `terminate()` delegate was installed, and a second
  Core-only hot reload returned HTTP 200 and removed all three prior Runtime MCP
  Worker generations without manual process termination. The next no-send run
  created one current generation per configured Server. AstrBot, NapCat, Web and
  MCP Console containers were not restarted, and no QQ message was sent.
- Evidence boundary: crawler/export/cache-maintenance tools and historical
  SQLite snapshots still exist outside the model Capability surface. This proves
  live iCourse reads and no cache fallback, not real QQ delivery or full S23;
  branch status remains `paused/partial`.

- 2026-08-28 长生命周期 Runtime 故障复现与修复：群 `364894085` 的真实 `@Bot`
  事件正常进入 AstrBot，但 30 分钟后的 Endpoint load 快照被 Router 判为陈旧，
  no-send 同形请求稳定返回 `model_route_not_found`、空正文。假时钟跨越 31 分钟的
  聚焦测试通过；Core 单插件热重载后，原 iCourse 请求恢复为
  `bounded_tool_execution + delivery_ready`、Terra `low`、LONG、`toolCalls=1`
  和非空正文。该复测没有调用 QQ Output。
- 热重载 API 返回 HTTP 200；`dududa-astrbot-1` 的容器 ID、StartedAt 和
  `RestartCount=0` 前后不变，NapCat 未重启。
- 2026-08-28 Web -> 2.0 Runtime no-send 实测：`POST /agent/respond` 返回 HTTP 200、
  `runtimePath=dududa_2_preview`、`toolCalls=1`、`outputCalls=0`、
  `memoryWrites=0`；iCourse 查询经 Terra `low` 生成非空 LONG 回答，Runtime 原因
  为 `bounded_tool_execution + delivery_ready`。该调用没有发送 QQ 消息。
- 同一路径修复前连续复现空回答。脱敏诊断测得 Perception input usage
  6,608/estimate 6,353，Direct Chat 5,525/estimate 4,016，均在 Admission settle
  产生 `provider_usage_receipt_invalid`；配置 wrapping/预算后复测通过。
- Python 相关组合/契约共 54 tests 通过，其中既有 75-case iCourse 分发测试完整执行；
  Ruff F/I 与 `git diff --check` 通过。Web typecheck、聚焦服务端/UI 测试和 production
  build 通过；Playwright 打开 `127.0.0.1:5173` 确认页面显示“2.0 Runtime 在线”
  和“2.0 Runtime 预览”。
- 2026-08-28 Web -> 2.0 Runtime Policy 接线核验：20 项聚焦 Python 测试通过，
  覆盖精确 Scope 解析、`enabled=false` 的 claim 前退出、Capability 类别过滤和
  no-delivery 原因保真；Web 76 项前端测试与 7 项服务端测试、TypeScript
  typecheck 和 production build 均通过。Production 同形测试覆盖自然语言 -> Perception -> Unified
  MCP -> 总结 -> Fake Delivery，未产生真实 QQ 副作用。
- 运行中 Core 状态为 `ready/runtime_ready`，OneBot 已连接；用户选择的目标 Scope
  解析为 Agent enabled、`campus.course-review=true`。Web Catalog 将 iCourse 显示为 Runtime online，
  当时二课、教务和校车显示为已装配、待 Planner 接管；2026-08-29 的二课、
  教务和校车 2.0 证据已取代该项状态。仅替换 AstrBot/Web，NapCat
  容器未重启；本轮没有发送真实 QQ 消息。
- Evidence boundary: the production Runtime currently consumes only the Scope
  switch and Capability eligibility from Web Policy. The six adaptive settings
  are not all production-wired, and no user-triggered QQ Tool/Delivery Receipt
  exists. Later Academic and Shuttle Runtime evidence supersedes the earlier
  Planner gaps.
  Verification remains `partial`; S23 remains `paused`.

- 2026-08-26 最终 75 题 Connector 形状 Runtime 纵切：Bridge 75/75、Runtime
  `completed` 75/75、Fake Delivery 75/75、MCP 73、Runtime/MCP 错误 0、真实 QQ
  输出 0。Case 25 为确定性澄清、Case 67 为合理直接回答；显式“评课社区”19/19
  调用 MCP。149 次 Runtime 模型调用为 75 Luna Perception + 73 Terra DirectChat +
  1 Sol DirectChat；75 次 Luna Review；最终保留记录的 224 次业务链调用全部
  `reasoning_effort=low`。四题定向补跑另发生 12 次业务调用和 3 次健康探测，故全过程为
  236 次业务调用和 6 次健康探测。
- 主跑耗时 2,513,233 ms（41.9 分钟）；Case 4/26/27/39 定向补跑耗时 150,642 ms，
  其余 71 题没有重跑。补跑后输出形态为 49 forward/26 plain，档位为 73 LONG/
  1 SHORT，Case 25 无 DirectChat/Profile。Luna 为 63 revised/12 pass、60 complete/
  15 incomplete；人工交叉终审覆盖 19 条，最终为 49 complete/26 incomplete。
- 65/75 个 `review.final_answer` 与实际 `delivery.text` 不同。Luna Review 在 Runtime
  结束后旁路执行，没有重新进入 Composer、Final Validator 或 Fake Delivery；报告不得把
  审校稿描述为已经发送。逐题报告为
  `docs/refactor/icourse-75-native-message-e2e-review-2026-08-26.md`，私有合并证据为
  `/home/mmdustc/temp/dududa-icourse-75-native-message-e2e-2026-08-26-final-audited.json`
  且 mode 为 `0600`。
- AstrBot 宿主入口契约在固定 AstrBot 4.26.2 / aiocqhttp 1.4.4 镜像、禁网和严格
  Fake OneBot API 下完成：75/75 合法 JSON 经内存 WebSocket、`Event.from_payload`、
  EventBus、AstrBot convert 形成真实 `AiocqhttpMessageEvent` 并进入
  RuntimeRequestFactory，发送 action 为 0。50 ms 延迟首条成员查询时，输入
  `1,2,3` 实际入队 `2,3,1`，证明当前宿主存在并发乱序能力。
- 本轮发现 LONG 分片按 UTF-8 字节硬切会拆开“给分”“基础”等词。实现已改为优先在
  换行、句末标点或空格处分段；新增聚焦回归与原 UTF-8 上限/重组测试均通过。该修复发生
  在主跑后，原 Delivery 记录不倒改为已重新投递。
- 聚焦回归：Runner/Planner、Tool Runtime/Orchestrator/State、Redaction/Safety、
  iCourse/MCP 与 Production Composition 共 97/97；随后新增 Runner 报告与自然边界分片
  聚焦用例也通过。`git diff --check` 通过；changed-file Ruff 无 F 类错误，但仍有 23 个
  E501、6 个 E402、5 个 I001，本轮未把风格清理扩大为主任务。
- 最终干净汇总命令覆盖 Runner、Planner、Tool Runtime、Orchestrator、State、Redaction、
  Authorization、iCourse storage/lifecycle/fetcher/facade、离线三模型模拟与 Production
  Composition，93/93 通过，用时 132.344 秒；命令不含此前误写的不存在模块名。
- 证据边界：宿主入口与顺序执行 Runtime Runner 是互补的两段证据，不是一次穿过真实
  NapCat、网络、生产并发和 QQ 服务端回执的无中断 E2E。S23 保持 `partial`。

- 2026-08-26 运行切换核验：旧 `mmdustc-bot-astrbot-qq` Compose 已无 AstrBot 容器，当前唯一
  Agent 宿主为 `dududa-astrbot-1`。启动日志只加载 Dududa Core、
  `astrbot_plugin_sub2api_readonly v0.6.4`、`astrbot_plugin_reread v2.0.0` 与 AstrBot 内建插件；
  ReplyPolish 和其他 1.0 插件未加载。Sub2API/Reread 是保留的 2.0 宿主能力，不是第二个
  Agent Runtime。
- 运行配置核验：`runtime_enabled=true`、`rollout_mode=canary`、
  `rollout_allowlisted_groups=["*"]`、delivery 开启、kill switch 关闭、Tool 开启、Memory 关闭。
  当前 Handler 只接管群内明确 @Bot、纯文本、无附件消息；私聊、附件与未 @ 消息无 1.0 fallback，
  主动参与仍为 Probe Shadow/NO SEND。
- Readiness 核验：Core `runtime-status.json` 返回 `ready=true/state=ready/reason=runtime_ready`；
  `GET /api/internal-test/agent/status` 返回被动入站
  `actualEnabled=true / rolloutMode=canary / deliveryEnabled=true / killSwitch=false`，并明确显示
  “所有群内明确 @Bot”的接管摘要。`GET /api/health` 返回 connected、1/1 个 QQ 账号在线且
  NapCat 连接正常。
- 容器边界：`dududa-astrbot-1` 在 2026-08-26 切换时重建；现有 NapCat 的 StartedAt 仍为
  2026-08-23，切换中未重启，继续作为唯一 QQ Connector。旧 1.0 AstrBot 私有配置/数据已备份。
- Provider/健康核验：Luna/Terra/Sol 已在运行 AstrBot 注册，旧 GPT-5.5 与 DeepSeek Provider
  禁用；三模型分别完成一次真实 AstrBot Chat Provider 调用，均成功，三档均使用最低
  `light/low`。运行配置的模型探测间隔/超时/TTL 为 `900/15/1800` 秒，取代此前 45/15/90 秒
  的高频候选值。
- 聚焦回归：Provider/Compose 21 项、Repository/候选配置 15 项、AstrBot Model Adapter 19 项、
  Web Server 6 项均通过；Web TypeScript typecheck 与 production build 通过。
- 证据边界：这些结果证明 1.0 已退出、2.0 唯一所有权、真实 Provider 可调用、Core/Web
  readiness 与 NapCat 连接；尚未由用户发送一条明确 @ 消息来证明真实 QQ Delivery、MCP 与
  LONG 合并转发。私聊、附件、未 @ 主动参与、日报/Probe、Memory 与在线 Bandit 均未启用。

- MCP answer synthesis style: the focused Dududa 2.0 natural-language iCourse
  vertical test passed (one test in 5.613 seconds). The trace retained exactly
  two model calls, `PERCEPTION` followed by `DIRECT_CHAT`, and one MCP call. The
  final model request explicitly required a self-contained synthesis instead of
  bare URLs, link lists or raw JSON; the emitted answer contained the course
  summary and no URL. This used a Fake Output with no real QQ side effect; it is
  not a deployed real-model style evaluation. Recorded: 2026-08-26.
- iCourse public-query follow-up: the final combined focused command ran 29
  storage/lifecycle/planner/mapping/MCP/Registry/Provider tests; all passed.
  The generated Capability configuration passed `--check`; changed-file Ruff
  critical checks and `git diff --check` passed.
- Historical predecessor benchmark: the public-only development snapshot contains 19,194 course summaries, 174
  targeted course details and 4,216 public reviews. All 75 benchmark questions
  had reviewed Chinese answers: 43 were complete from the available evidence,
  27 are explicitly partial and five request clarification. Luna reviewed every
  batch once: its predecessor boolean field was true for 59 and false for 16;
  this is not the final protocol's 12 `pass`/63 `revised` verdict. It returned 17
  non-empty revision suggestions. Nineteen final answers differ from their
  generated draft; four groundedness cases received a factual correction.
- The answer run made 48 successful Provider calls and zero QQ Output calls.
  The repository report contains all 75 cases and no API Key, internal chain of
  thought, raw Observation or provider endpoint. This is a public-snapshot
  development benchmark, not human Gold or deployed Runtime evidence.
- `icourse.public-query.v2` now projects `course/review/teacher/ranking/stats`
  into one ToolStep and at most one MCP call. A Fake MCP Server and iCourse use
  the same contracts; all five operations are covered without invoking the
  crawler. S23 remains `partial` because real-group Shadow, QQ delivery,
  production deployment and human quality calibration are still outstanding.
- Recorded: 2026-08-26

- Command: `.venv/bin/python -m unittest tests.unit.responses.test_policy tests.unit.runtime.test_composition tests.contracts.test_astrbot_output tests.contracts.test_production_composition.ProductionCompositionContractTests.test_natural_language_icourse_uses_2_0_runtime_and_unified_mcp`.
  Result: 33 focused tests passed in 4.496 seconds. Evidence: Tool-assisted
  responses default to LONG without overriding an explicit profile; the iCourse
  vertical slice made one MCP call and one `nodes` send after real 512-byte
  splitting; SHORT/MEDIUM, private, attachment and single-part cases retained
  their ordinary delivery behavior.
- Scripted iCourse routing matrix: all 75 benchmark questions plus three user
  regressions entered the AstrBot Canary Bridge, Hybrid Perception, Capability
  Runtime and a real local Managed Unified MCP/iCourse worker. The run recorded
  78 MCP calls and 78 single Fake Deliveries. The 19 benchmark questions with
  an explicit `评课社区` marker plus all three regressions deliberately received
  `need_tools=false` from the scripted model; deterministic Rule/Merger evidence
  still produced 22/22 Tool paths. The three regression arguments were exactly
  `人工智能`, `萌萌哒mmd` and `线性代数B1`.
- Command: `.venv/bin/python -m unittest tests.contracts.test_production_composition.ProductionCompositionContractTests.test_all_icourse_benchmark_messages_reach_2_0_mcp_dispatch`.
  Result: one matrix test passed in 76.299 seconds. Test Endpoint RPM/TPM was
  raised to isolate routing because the default 60 RPM correctly denies the
  31st rapid request after 30 two-model-call runs; production limits are unchanged.
- Real Luna Perception sample: 75/75 benchmark outputs passed the Production
  JSON Schema with `reasoning.effort=low`; 74/75 proposed
  `campus.course-review`, and explicit marker recall was 19/19. Case 67 was the
  sole model-only miss and had neither a site marker nor iCourse context. The
  sanitized per-case result is repository-external at
  `/home/mmdustc/temp/dududa-icourse-perception-benchmark-2026-08-26.json` with
  mode `0600`; the run made no QQ Output.
- Focused follow-up: the two benchmark fixture tests and the original local
  natural-language iCourse vertical slice passed (3 tests in 4.282 seconds).
  `git diff --check` passed. All-rule Ruff reports 14 pre-existing
  `composition.py` style findings; focused E/F/I checks are recorded separately
  and this change does not broaden the cleanup scope.
- Dududa 2.0 natural-language vertical slice: `@嘟嘟哒 查询评课社区吴天` produced
  one Luna/Haiku PERCEPTION call, one deterministic
  `icourse.courses.search.v1 -> icourse/search_courses({"query":"吴天"})` call
  through the local Unified MCP worker, one DIRECT_CHAT call and one final
  Delivery. Both model calls used `reasoning_effort=low`; no `/course`,
  `search_site_courses`, Web search, process narration or second send occurred.
- The scripted Perception deliberately returned both `评课社区` and `吴天` as
  valid entities. The Planner ignored the service term and projected only
  `吴天`. Production Perception advertised only `campus.course-review`; academic,
  shuttle and second-class categories remained outside this Planner slice.
- Commands: focused Production Composition, iCourse facade, Rollout, legacy
  plugin split, iCourse parser/fixture and model-simulation suites ran 42 tests
  with two existing AstrBot host-only skips; all executed tests passed.
  Capability generators passed `--check`, followed by four passing production
  mapping Contract tests.
- First-class MCP ownership: Production Composition now reads
  `plugin.unified_mcp_client`; the iCourse facade borrows it. A disabled iCourse
  definition no longer prevents the Unified Client from being assembled, and
  plugin termination closes the shared Client. If shared composition fails,
  production initialization now leaves the compatibility facade unavailable
  instead of retrying an independent legacy-only Client.
- Real no-send model sample: Luna/Terra/Sol answered one fixed validated iCourse
  Observation with Responses `reasoning.effort=low` in 3292/3346/3531 ms. Luna
  reviewed each candidate once; all three Reviews passed with score 100. The
  sample made six Provider calls and zero QQ Output calls. The full result is a
  `0600` repository-external file and contains no API Key or Base URL.
- Evidence boundary: the scripted matrix proves routing and real Luna Perception
  coverage. The later host-ingress contract now proves in-memory AstrBot JSON
  conversion and RequestFactory handoff, but not real NapCat transport,
  production ordering, QQ delivery or semantic completion. Queries requiring
  aliases, structured filters, user/reply/longitudinal data or multi-step
  aggregation remain partial. S23 remains partial.
- Recorded: 2026-08-26
- Static checks: changed-file Ruff critical/import rules and `git diff --check`
  passed. The broad all-rule Ruff profile was not used as a release gate because
  it reports existing style debt outside this vertical slice.

- Runtime MCP registration: MCP Console unittest 6/6 passed; the structured
  Web Definition is persisted outside the repository, the strict Registry
  reloads it, Discovery sees the Fake Tool, repository Servers cannot be
  replaced, unknown/plaintext Secret fields are rejected and every result keeps
  `capabilityGranted=false`.
- Web registration: the focused Vue case and Node route case each passed;
  `npm run build` completed Vue/Node type checks, the client production build
  and server bundle. The existing large-chunk warning remains unchanged.
- Compose config, Ruff and `git diff --check` passed. The real Unified worker plus
  MCP v2 Fake stdio smoke completed install -> reload -> Discovery and found
  `echo`; it did not create a Capability mapping or raw Tool route.
- Live deployment: only `dududa-web-1` and `dududa-mcp-console-1` were rebuilt
  and recreated. Runtime list returned the four repository Servers with
  Capability counts `4/6/2/5`; Catalog and `DUDUDA-MCP-SPEC 1.0.0` download both
  returned HTTP 200. Desktop 1440x1000 and mobile 390x844 displayed the MCP panel
  and structured dialog without horizontal overflow or visible error state.
- `dududa-astrbot-1` and the active NapCat retained exact container IDs/start
  times and `RestartCount=0`; no QQ message was sent and no runtime Server was
  added during live UI verification.
- Evidence boundary: this proves registration, Discovery and downloadable format
  guidance. It does not prove a new production MCP, Source quality, Agent Tool
  selection or remote administrator authentication. AstrBot and NapCat were not
  restarted. Recorded: 2026-08-24.
- Commands: `npx vitest run --config vitest.server.config.ts server/plugin-manager.spec.ts
  server/plugin-manager-routes.spec.ts` passed 5/5; `npx vitest run src/App.spec.ts`
  passed 9/9; `npm run typecheck`, production Web build, Python compile, `bash -n`,
  Compose config and `git diff --check` passed. The build retained only the existing
  large-chunk warning.
- Specification sample: all five fenced Python templates compile and the JSON
  Schema parses. The template matches AstrBot 4.26.2 runtime annotations, optional
  no-Schema config construction and its actual supported Schema value types.
- Live Web evidence: `GET /api/plugins/runtime` returned HTTP 200, `available=true`
  and four activated plugins. The downloadable specification returned HTTP 200,
  `text/markdown`, `no-cache`, 32,730 bytes and marker
  `DUDUDA-PLUGIN-SPEC 1.0.0`.
- Browser evidence: desktop 1440x1000 and mobile 390x844 both displayed the four
  Runtime plugins, `安装插件`, `下载规范`, GitHub/ZIP source tabs and a fitting
  install dialog with zero console/page errors. The real download completed as
  `dududa-plugin-development-spec.md`. The mobile inbox-to-Agent route
  regression is covered and the real mobile entry reaches the configuration tab.
- Deployment boundary: only `dududa-web-1` was rebuilt/recreated. The existing
  AstrBot and active NapCat retained their exact container IDs, start times and
  `RestartCount=0`; OneBot remained `connected`. No arbitrary third-party plugin
  was installed during live verification and no QQ message was sent.
- Evidence boundary: the live Web remains a loopback-trusted super-admin workbench;
  installation does not grant a Dududa Capability or prove remote administrator
  authentication. S23 therefore remains `partial` for its separate real-group gates.
- Recorded: 2026-08-24

- Commands: 19 MCP/repository contracts, three campus-service contracts, two
  Console tests and six focused Web routes were rerun; the broader completed
  slice also passed 42 Web server tests, TypeScript typecheck, Web production
  build, Ruff and Compose config checks.
- Result: all focused reruns passed and the generated production catalog has 17
  mapped Capabilities. All static/build checks passed; only the existing Web
  chunk-size warning remained.
- Live read-only samples: all eight public campus Capabilities and one iCourse
  Capability completed through the Unified Worker. The existing CAS helper
  issued a session, pinned `pyustc` logged into the second-class service, and
  the Web Capability path returned the five module facets 德/智/体/美/劳.
- Browser evidence: the MCP workbench displayed four Servers and 17 approved
  Capabilities; `ustc-young` showed `configured/healthy`, a schema-generated
  form completed a real call, and Playwright observed no console/page errors.
- Deployment boundary: only `dududa-mcp-console-1` was rebuilt/recreated.
  `dududa-astrbot-1` and the active NapCat container retained their prior IDs
  and `StartedAt` values. No QQ Output, Memory write or online Bandit action
  occurred; credentials and session values were not printed or committed.
- Evidence boundary: these checks prove the four query MCPs and super-admin Web
  invocation, not Agent automatic Tool rollout or campus/arXiv/industry digest
  sources. Branch verification therefore remains `partial` for S23.
- Recorded: 2026-08-24

- Source parity: current `client.py` is byte-identical to the locally deployed
  Sub2API v0.6.2 baseline; every original command handler remains present.
- Command: `uv run --locked python -m unittest tests.test_sub2api_plugin`
- Result: 27 focused tests passed in 0.592 seconds. The sample covers the exact
  current-cycle cutoff/aggregation, four requested formatters and four-node
  merged-forward construction without calling a real QQ Output.
- Command: `git diff --check`.
- Result: passed.
- Runtime activation: AstrBot's scoped plugin reload API returned HTTP 200 with
  `重载成功。` for `astrbot_plugin_sub2api_readonly`. Runtime logs show only that
  plugin's handlers being removed and the plugin loading again as v0.6.3.
- Container boundary: `dududa-astrbot-1` retained
  `StartedAt=2026-08-17T17:08:00.582712293Z`, `RestartCount=0` and `running`;
  neither the AstrBot container nor its Compose project was restarted.
- Legacy boundary: the old `mmdustc-bot-astrbot-qq` Compose project has no
  AstrBot container to stop. Its sole remaining NapCat container is the active
  Connector reused by Dududa 2.0 and stayed running. The Sub2API service and its
  Postgres, Redis and proxy dependencies also stayed running. No QQ test message
  was sent.
- Recorded: 2026-08-17

## Previous Verification

- Command: `uv run --locked python -m unittest tests.test_sub2api_plugin tests.test_repository_contract`
- Result: 36 focused tests passed. The exact-scope Policy Reader enables
  `auto/on/locked`, disables `off`, missing or malformed managed Scope, and
  preserves the legacy static switch only when no Policy file is configured.
- Command: Compose config validation with the internal-test host data and
  feedback roots, followed by `git diff --check`.
- Result: passed. AstrBot receives the repository-external Policy through a
  read-only mount and the isolated plugin root contains only Dududa Core,
  ReplyPolish, automatic reread and Sub2API.
- Runtime evidence: the current Dududa AstrBot loaded
  `astrbot_plugin_sub2api_readonly`, resolved the private target Scope with
  `sub2api.auto_query=locked`, and NapCat
  established the OneBot v11 reverse WebSocket. Subsequent unrelated inbound
  events reached AstrBot, proving the transport is live.
- Runtime method smoke: the plugin completed the real `overview` read path and
  produced a normal response after all five read-only upstream requests
  succeeded. No credential, token value or business response body is recorded
  in this document.
- Evidence boundary: every observed `/sub2api overview` in group history was
  sent before the OneBot reconnection and will not be replayed. The Agent did
  not send a test message to the real QQ group; final end-to-end evidence waits
  for a user-issued post-reconnect command. Automatic reread still lacks its
  Web Policy Adapter.
- Verification remains `partial`; S23 remains `paused` for the broader live
  ladder, while the `/sub2api` repair is implementation-complete pending that
  single external command.
- Recorded: 2026-08-17

- Command: `npm exec vitest run -- src/composables/useWorkspace.spec.ts`
- Result: 1 file / 12 tests passed.
- Command: `npx vitest run --config vitest.server.config.ts server/internal-test.spec.ts server/internal-test-routes.spec.ts`
- Result: 2 files / 6 tests passed.
- Command: `uv run --locked python -m unittest tests.test_repository_contract`
- Result: 13 tests passed; the repository contract includes the read-only
  Compose mount for `astrbot_plugin_reread`.
- Command: parse `_conf_schema.json` and compile every restored reread Python
  source with Python 3's in-memory `compile()`.
- Result: passed without writing bytecode artifacts.
- Command: `npm run typecheck`
- Result: passed.
- Command: `npm run build`
- Result: passed; only the existing large-chunk warning remained.
- Runtime sample: `GET /api/health` on `http://127.0.0.1:5173` returned
  `connected` with 1/1 NapCat account online. The live Agent Catalog returned
  `consoleRole=super_admin`, `executionRole=admin`, and both
  `social.reread.auto` and `sub2api.auto_query` as installed, configurable,
  Scope-managed AstrBot targets. A fresh Scope config contained both keys with
  mode `off`.
- Evidence: the live Agent Console loads a dynamic server Catalog, reads and
  saves the authoritative `accountId + conversationId` Policy, and keeps model
  Tier, reasoning depth, answer length, reply intensity, context length and
  group-chat style as six orthogonal `adaptive/preferred/locked` settings.
  Focused cases prove `preferred` may change for a strong task signal, `locked`
  does not change, and saving or generating a candidate never calls the
  Workspace QQ `sendMessage()` path.
- Evidence: **上下文长度（运行预算）** applies the configured recent-history
  limits: compact 12 messages/6,000 characters, standard 30/18,000 and extended
  100/36,000. The response reports `messagesRead` and `charactersRead`, and the
  Console renders both the selected limit and actual usage. This is a per-Run
  history budget, not the Provider model's maximum Context Window.
- Historical evidence at 2026-08-17: the Runtime status distinguished administrator intent from actual
  behavior. Passive automatic reply was disabled (`rollout_mode=off`,
  delivery disabled, kill switch active); proactive participation remained
  `probe_shadow` and `NO SEND`. The Catalog truthfully reports iCourse and
  `gpt-image-2` unavailable in the current Console path. Automatic reread and
  `/sub2api 自动查询` are independently installed/configured AstrBot plugins,
  default `off` and managed per `accountId + conversationId`; WebUI configuration
  requires `super_admin`, while the declared Bot execution identity is `admin`.
  This was the pre-repair state: no online AstrBot consumed the Web Policy and
  the Policy Adapter was not connected. `triggerMatched=true` only meant a
  deterministic trigger was applicable; both plugins reported
  `selectedForRun=false` and no Tool call.
- Evidence boundary: reply intensity does not prove or control a live send
  probability. The candidate still reports `outputCalls=0`, `memoryWrites=0`
  and `toolCalls=0`. This proves the adaptive administrator workbench slice,
  not production AstrBot Runtime, live Capability execution, Provider
  Conformance or real-group authorization.
- This historical slice remained partial/paused. The 2026-08-26 latest verification
  above supersedes its passive-runtime status while leaving proactive behavior off.
- Recorded: 2026-08-17

- Command: `uv run --with pytest --project packages/dududa-agent python -m pytest tests/unit/compatibility/test_reply_polish.py tests/unit/compatibility/test_target_talk.py tests/unit/runtime/test_delivery.py tests/contracts/test_astrbot_output.py tests/unit/runtime/test_direct_chat.py tests/unit/runtime/test_orchestrator.py tests/test_repository_contract.py -q`
- Result: 58 tests and 12 subtests passed in 2.15 seconds.
- Evidence: SHORT/MEDIUM do not receive merged-forward eligibility; a LONG
  response still uses ordinary delivery unless it is explicitly validated and
  has at least two plain-text parts in a group with no attachment. Target
  metadata remains bound in Runtime, while merged-forward presentation omits a
  separate `@` component.
  AstrBot Output independently rejects `allow_forward_bundle=true` when the
  validated profile is absent, SHORT or MEDIUM.
- Evidence: Persona remains in model generation when `response_profiles` is
  disabled, and Persona plus ResponsePlan are serialized into the same model
  request when enabled. Repository contract checks confirm new group records no
  longer initialize `meme_rate`, the admin path no longer writes it, and default
  Compose does not mount Target Talk.
- Focused source/Compose review: Meme Manager, PokePro and Target Talk remain
  outside the 2.0 default path; automatic reread is mounted as an independent
  plugin with `enabled=false`; ReplyPolish is default-off and LONG-only; `/image`
  remains an explicit Core command. No running AstrBot/NapCat instance was
  changed or restarted by this work.
- Command: `npm run typecheck`
- Result: passed.
- Command: `npm run build`
- Result: passed; only the existing large-chunk warning remained.
- Evidence boundary: these checks prove repository defaults, generation wiring
  and delivery conditions, not natural real-group Chinese style or complete
  Production group context. S23 therefore remains `paused/partial`.
- Recorded: 2026-08-16

- Command: `npm exec vitest run -- src/composables/useWorkspace.spec.ts`
- Result: 1 file / 11 tests passed. Focused cases cover stable ordering with
  full-precision decimal sequence values, initial-Snapshot realtime replay and
  fallback when refresh removes the selected conversation.
- Command: `npx vitest run --config vitest.server.config.ts server/internal-test.spec.ts`
- Result: 1 file / 3 tests passed. The Provider request includes Dududa Persona,
  group channel rules, explicit non-imitation and unchanged fact/permission/task
  boundaries; candidate generation remains no-send.
- Command: `npx vitest run --config vitest.server.config.ts server/app.spec.ts -t "replays missed workspace events in order after an SSE reconnect"`
- Result: 1 focused test passed / 35 skipped. It verifies monotonic SSE IDs and
  ordered `Last-Event-ID` replay after reconnect.
- Evidence boundary: these checks prove message-path recovery and structural
  style wiring only. They do not prove durable cross-process delivery or
  sufficiently calibrated real Chinese group-chat style. NO SEND, NO MEMORY
  WRITE, NO TOOL CALL and NO BANDIT remain in force.
- Verification remains `partial`; S23 remains `paused` pending human style
  evaluation and the existing external gates.
- Recorded: 2026-08-16

- Command: `npm run typecheck`
- Result: passed.
- Command: `npx vitest run src/views/InternalTestView.spec.ts src/App.spec.ts`
- Result: 2 files / 10 tests passed.
- Command: `npx vitest run --config vitest.server.config.ts server/internal-test.spec.ts`
- Result: 1 file / 2 tests passed.
- Command: `npm run build`
- Result: passed; only the existing large-chunk warning remained.
- Browser vertical slice: `#/internal-test` loaded 300 de-identified windows
  without a NapCat account. One operator-triggered `gpt-5.6-terra` candidate
  completed in 3059 ms with `providerCalls=1`, `outputCalls=0`,
  `memoryWrites=0` and `toolCalls=0`; one feedback row was appended to the
  configured repository-external JSONL file.
- Evidence boundary: no candidate text, API Key, Base URL, QQ identifier or
  feedback content is recorded here or committed. The slice proves the Web
  Evaluation Adapter only; it is not AstrBot Runtime Shadow, Provider
  Conformance, live-group validation or authorization to send.
- Verification remains `partial`; S23 remains `paused`.
- Recorded: 2026-08-16

- Command: `PYTHONPATH=packages/dududa-agent/src:apps/astrbot-plugins .venv/bin/python -m unittest tests.test_provider_no_send_shadow tests.test_render_astrbot_candidate`
- Result: 4 focused tests passed in 0.166 seconds.
- Command: `.venv/bin/ruff check --select E,F,I ops/cli/run_provider_no_send_shadow.py tests/test_provider_no_send_shadow.py ops/cli/render_astrbot_candidate.py tests/test_render_astrbot_candidate.py`
- Result: passed. `git diff --check` also passed.
- Evidence boundary: this closeout reused fixtures and local files; it did not
  repeat Endpoint requests, corpus processing, container startup or QQ output.
- Recorded: 2026-08-15

- Command: `uv run --locked python -m unittest tests.contracts.test_production_composition.ProductionCompositionContractTests.test_timed_out_health_probe_publishes_unknown tests.contracts.test_production_composition.ProductionCompositionContractTests.test_transient_probe_timeout_keeps_unexpired_health_evidence tests.contracts.test_production_composition.ProductionCompositionContractTests.test_enabled_health_probe_publishes_and_periodically_refreshes tests.unit.models.test_health`
- Result: 11 focused tests passed in 3.053 seconds.
- Evidence: an initial timeout remains `UNKNOWN`; after one successful probe, a transient timeout keeps the
  endpoint `HEALTHY` only until the original evidence TTL; another timeout after expiry returns it to
  `UNKNOWN`. The periodic task and model-health publisher regressions remain green.
- Live no-send evidence: Core was synchronized and hot-reloaded without restarting AstrBot or NapCat;
  active timeout is 60 seconds. A group `419256533` Runtime preview returned HTTP 200 through Luna in
  23.516 seconds with a non-empty candidate, `delivery_ready`, `explicit_direct_reply`, zero Tool calls and
  `outputCalls=0`; `model_route_not_found` was absent.
- Evidence boundary: this closes the model-route failure and proves no-send execution only. Later natural
  target-group attempts reached model completion but were suppressed as `rollout_admission_changed`, exposing
  the independent Canary Send Guard defect recorded below.
- Recorded: 2026-08-30

- Command: `uv run --locked python -m unittest tests.unit.rollout.test_controlled_execution tests.contracts.test_astrbot_rollout`
- Result: 15 focused tests passed in 1.998 seconds; focused Ruff and whitespace checks passed.
- Evidence: a non-mentioned group request with the deterministic `proactive_group_participation` flag now
  remains admitted through the persistent pre-send guard and records one successful delivery in the Fake
  Output. The existing in-flight kill-switch case still suppresses delivery with zero sends.
- Live deployment: the fixed package module was hot-loaded into the running Core and a replacement
  `dududa/astrbot:local` image was built. AstrBot and NapCat both remained running with restart count 0.
- Evidence boundary: three target-group messages immediately after reload landed before the first model
  health refresh and failed without delivery. No later target-group message arrived during this verification
  window, so a post-fix natural QQ Delivery receipt remains pending; no artificial group message was sent.
- Recorded: 2026-08-30

- Evidence source: isolated fixed AstrBot 4.26.2 candidate startup associated
  with `e9cb9e0`.
- Result: partial. The candidate started with `--network none`, a temporary
  `/AstrBot/data`, read-only plugin mount, no NapCat and no exposed port;
  AstrBot 4.26.2, plugin loading and `DududaCore loaded` were observed.
- Evidence boundary: this proves an isolated startup shape only. It did not
  register or replace the running AstrBot, call a Provider, attach NapCat,
  select a group or send Output.

- Evidence source: isolated Provider no-send sampling and sanitized receipt
  implementation in `a866812`.
- Result: partial. Luna, Terra and Sol were sampled once each; every tier
  recorded `provider_calls=1` and `output_calls=0`. A separate injected failure
  sample retained no API Key, Base URL, Prompt, answer, QQ identifier or
  Provider error body.
- Evidence boundary: `ops/cli/run_provider_no_send_shadow.py` calls the
  Responses API directly. It does not traverse AstrBot Provider, Dududa Runtime,
  Connector or Rollout Bridge, so this is not AstrBot Runtime Shadow, real
  single-group Shadow, Provider Conformance or production-health evidence. The
  failure sample was injected, not an observed Endpoint incident.

- Evidence source: focused periodic model-health implementation and lifecycle
  cases in `05c307f`.
- Historical result at 2026-08-15: partial. Configuration then defaulted to disabled with 45-second refresh,
  15-second timeout and 90-second Evidence TTL. The fixed-model probe uses
  `max_tokens=8` and `request_max_retries=0`; success publishes `HEALTHY`, while
  failure/timeout publishes or retains `UNKNOWN`, expired evidence returns to
  `UNKNOWN`, and plugin termination cancels the refresh task.
- Current superseding evidence: the 2026-08-26 deployment enables the refresher at
  900/15/1800 seconds and registers all three models. Long-term health observation
  and a user-triggered QQ end-to-end sample remain outstanding.

- Command: `uv run --locked python -m unittest tests.test_render_astrbot_candidate -v`
- Result: partial; 2 focused tests passed in 0.144 seconds.
- Evidence: disabled mode merges Source/Provider additions by ID without
  replacing unrelated AstrBot configuration; explicit Shadow rendering reads
  private values outside Git, does not print the Key, and keeps delivery off,
  kill switch on and the group allowlist empty.
- Evidence boundary: the test uses an isolated temporary data root. It does not
  modify the running AstrBot/NapCat instance or prove live Provider health.
- Recorded: 2026-08-15

- Command: `uv run python -m unittest -q tests.contracts.test_production_composition.ProductionCompositionContractTests.test_builder_accepts_private_provider_evidence_file tests.contracts.test_production_composition.ProductionCompositionContractTests.test_builder_rejects_mismatched_private_provider_evidence tests.contracts.test_production_composition.ProductionCompositionContractTests.test_shadow_uses_endpoint_fixed_reasoning_after_healthy_evidence tests.contracts.test_production_composition.ProductionCompositionContractTests.test_shadow_stops_calling_provider_after_health_ttl`
- Result: partial; 4 focused tests passed in 0.245 seconds.
- Evidence: repository-external Evidence matching assembles the Builder;
  Provider/model mismatch is rejected; valid descriptor-bound health changes
  `UNKNOWN -> HEALTHY` and permits one Fake Shadow Provider call; advancing the
  fake clock beyond the health TTL changes it back to `UNKNOWN` and prevents a
  further Provider call.
- Evidence boundary: these are Fake Provider and fixed private-file fixture
  tests. The refresh implementation now has separate focused evidence, but it
  was not enabled when these tests ran. The later 2026-08-26 cutover supplies
  running-host registration/readiness evidence, but these Fake tests still do not
  prove a user-triggered QQ send or long-term production health.
- Verification remains `partial`; S23 remains `paused`.
- Recorded: 2026-08-15

- Command: `uv run python -m unittest tests.contracts.test_astrbot_model_provider tests.contracts.test_production_composition`
- Result: partial; 34 focused tests passed in 0.719 seconds.
- Evidence: Adapter passes request-level `max_tokens`; fixed Endpoint reasoning
  maps OFF/LIGHT/BALANCED/DEEP/MAXIMUM to omitted/low/medium/high/xhigh; Builder
  requires resolved Provider binding evidence; initial health is `UNKNOWN`.
- Candidate-image sample: fixed AstrBot 4.26.2 patch applied to the pinned base;
  an isolated `--network none` payload sample retained `max_tokens=321` and
  `reasoning_effort=high` while dropping an unapproved plugin kwarg. The running
  container was not replaced.

- Command: `uv run python -m unittest tests.contracts.test_production_composition tests.unit.runtime.test_perception tests.contracts.test_astrbot_rollout`
- Result: partial
- Historical checkpoint evidence: 27 unique focused tests passed in 1.005 seconds. An earlier six-test
  smoke passed in 0.196 seconds. The tests use a Fake AstrBot Provider and prove
  zero `text_chat()` calls during construction; `off` keeps legacy ownership
  with zero Provider calls and zero sends; `shadow` performs exactly one Fake
  Provider call while legacy keeps ownership and no send occurs; disabled or
  unresolved Providers fall back to unavailable/legacy; AnswerProfile flag
  projection and the then-current rule-only Perception were wired without a
  second model call. The 2026-08-26 evidence above supersedes that production
  shape with Dududa 2.0 Hybrid Perception and a governed Capability path.
- Historical-corpus evidence remains valid: 1,402 files / 155,567 unique group
  messages / 137,026 windows; 592 Teacher drafts + 8 request-stage reviews;
  464 compiled Silver rows; 23/6 train/test conversation groups; 137,026
  Student predictions; Demo HTTP 200 at `127.0.0.1:8766` with all private,
  no-send and non-production notices.
- Command: private minimal Responses API and Chat Completions probes; the
  credential-bearing invocation, API key and private Base URL are intentionally
  not recorded.
- Result: partial. Responses returned HTTP 200 for Luna/Terra/Sol in
  2.212/2.816/2.698 seconds with exact model IDs, text and usage. Chat
  Completions returned HTTP 200 for both ordinary and `reasoning_effort=low`
  requests on all three models, with exact model IDs and usage at roughly
  2.2--2.3 seconds.
- Historical evidence boundary: these probes proved one-shot protocol reachability
  only. The 2026-08-26 cutover subsequently registered Luna/Terra/Sol in the running
  AstrBot, completed one Chat call per model and enabled 900-second refresh. Only
  `low` is evidenced; long-term production health and quality remain unverified.
- Coverage gap: no human Gold, user-triggered QQ Delivery Receipt, long-term health,
  live campus/arXiv/industry Source, proactive Projection/Output composition,
  online Bandit or private/attachment/unmentioned-message support. S23 therefore
  remains `partial`.
- Recorded: 2026-08-15
