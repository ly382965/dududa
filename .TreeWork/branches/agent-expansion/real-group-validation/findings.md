# Findings

Branch: real-group-validation

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- S23 completion is the bounded single-group ladder plus closeout. Expansion to
  3–5 groups is a later authorization decision, not an inherited grant.
- iCourse cannot satisfy digest-source readiness; it remains a course-review
  MCP and no campus/arXiv/industry live source is currently implemented.
- The five-hour budget is protected by labeling 600 stratified windows
  (0.44% of 137,026 eligible windows) with Terra and running a local Student
  over the full corpus. The remaining eight Teacher failures stay in Review;
  they do not justify another remote pass.
- The completed corpus pipeline is the reusable baseline and will not be
  rerun merely because Luna and Sol are now reachable. A later multi-model
  calibration run uses a 20--24 window throughput probe, adaptive Luna cap of
  120--350, Terra review cap of 50, Sol ambiguity cap of 15, no new calls after
  T+3.5 hours and a hard stop at five hours.
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
- 首版生产装配使用 `RuleOnlyRuntimePerception`，不为未经校准的语义感知额外
  调用模型；回答生成仍经过 Static Router 和 DirectChat Model Call。
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

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Silver is heavily imbalanced: 447/464 rows say no Tool, only 4/464 are high
  complexity, and no LONG AnswerProfile survived compilation. A balanced human
  Gold set is required before threshold calibration or production integration.
- The running AstrBot/NapCat stack is not the S19 derived candidate and has not
  been authorized for replacement. S23 needs an explicit deployment window and
  a rollback owner before mutation.
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
