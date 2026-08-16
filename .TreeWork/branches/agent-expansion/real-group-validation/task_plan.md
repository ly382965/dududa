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
  send, and disabled or unresolved Providers fall back to legacy.
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
- [x] Workspace SSE 使用单调事件 ID 和最近 512 条有界内存重放；浏览器重连
  可通过 `Last-Event-ID` 按序补放，ID 无效、过旧或服务重启时回退到
  `workspace.refresh`。前端按 `timestampMs`、无损十进制 sequence、消息 ID
  稳定排序，并重放初始快照期间收到的实时事件。
- [x] Web Agent 可选择 SHORT/MEDIUM/LONG，分别映射 Luna/Terra/Sol；生成指令
  复用 `configs/personas/registry-v1/dududa.json`，按群聊/私聊规则调整表达，
  同时保持 NO SEND、NO MEMORY WRITE、NO TOOL CALL、NO BANDIT。
- [x] Persona 不再依赖 `response_profiles` 开关：关闭回答档位时仍进入同一次
  模型生成；开启时 Persona、群聊情境与 AnswerProfile 在同一请求中自然融合，
  不复述人设、不自我介绍、不套固定口号、不机械追加表情，也不模仿具体群成员。
- [x] SHORT/MEDIUM 始终按普通 QQ 消息投递；LONG 单段同样普通投递。只有
  `profile_validation.valid=true` 的显式 LONG，且目标为群聊、至少两个纯文本
  part、无定向用户、无附件时，Output Adapter 才允许合并转发。
- [x] Dududa 1.0 自动行为已退出 2.0 仓库默认路径：Meme Manager、Reread、
  PokePro 不在默认插件集合，Target Talk 不再由默认 Compose 挂载；ReplyPolish
  默认关闭且仅作为 LONG-only 兼容层。新群不再生成 `meme_rate`，管理命令不再
  写入该字段；显式 `/image` 图片生成能力继续保留。
- [ ] One authorized group's no-send/no-write Shadow proves zero Output, Tool
  write, Memory read/write, wrong-target and sensitive-Trace events.
- [ ] Explicit-mention inbound Canary is limited to approved test users and
  frozen message/run budgets; all delivery outcomes are reconciled.
- [ ] Manual digest then scheduled digest use approved live sources with valid
  provenance, freshness and citations and produce no duplicate, quiet-hour,
  revoked or unsubscribed delivery.
- [ ] A separately authorized low-frequency group Probe produces no personal
  target/mention, Memory access, auto-follow-up or send after no response.
- [ ] Every safety maximum remains zero; frozen latency/cost/quality measures,
  kill-switch and exact rollback evidence are recorded without post-hoc
  threshold changes.
- [ ] All canaries end disabled, retention/deletion actions are recorded, and a
  sanitized S23 report contains no raw message, prompt, answer, real QQ/group/
  user ID, credential or Provider error body.
- [x] Progress, Findings and Verification are synchronized and all changes are
  locally committed without push.

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
- [x] Implement the production Builder, automatic plugin wiring, AnswerProfile
  feature flag and rule-only Runtime Perception; sample the production
  composition, Perception and Rollout contracts.
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
- [x] Remove Dududa 1.0 automatic social behavior from repository defaults,
  stop new `meme_rate` initialization/writes, keep ReplyPolish default-off and
  retain explicit `/image`; preserve historical source/config/data for rollback
  and do not mutate the running AstrBot/NapCat instance.
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
- Fabricating campus/arXiv/industry MCP Servers or treating fixtures/iCourse as
  live news sources.
- Redesigning S01–S20 contracts, expanding WebUI beyond the bounded internal-test
  surface or changing running containers before an approved deployment window.
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
