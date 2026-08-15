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
- `conformance_verified` 只是 Builder 的装配输入，不替代 S23 Preflight 所需
  的真实 Conformance、health 和候选 Release 绑定证据。
- Builder 不再从配置布尔值伪造 Conformance；AstrBot Context 必须解析真实
  `AstrBotProviderBindingEvidence`。Endpoint 初始健康为 `UNKNOWN`，发布真实健康
  快照前 Router 不会调用 Provider。思考深度当前是 Endpoint 固定 Profile。

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Silver is heavily imbalanced: 447/464 rows say no Tool, only 4/464 are high
  complexity, and no LONG AnswerProfile survived compilation. A balanced human
  Gold set is required before threshold calibration or production integration.
- The running AstrBot/NapCat stack is not the S19 derived candidate and has not
  been authorized for replacement. S23 needs an explicit deployment window and
  a rollback owner before mutation.
- 当前 focused Contract 使用 Fake AstrBot Provider；尚未证明真实 Endpoint 的
  协议兼容、健康、延迟、成本、输出质量或部署环境可用性。
- 当前运行中的 AstrBot 只注册 DeepSeek V4 Pro/Flash 和 GPT-5.5，尚未切换到
  已打补丁的候选镜像，也未注册 Luna/Terra/Sol。候选样板的 light/balanced/deep
  是待 Conformance 的 pilot 初值；真实请求只抽样验证过 `low`，不能据此声称
  medium/high/xhigh 或持续观测已经通过。
