# Verification

Branch: real-group-validation

## Latest Verification

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
  60/36,000. The response reports `messagesRead` and `charactersRead`, and the
  Console renders both the selected limit and actual usage. This is a per-Run
  history budget, not the Provider model's maximum Context Window.
- Evidence: the Runtime status distinguishes administrator intent from actual
  behavior. Passive automatic reply remains disabled (`rollout_mode=off`,
  delivery disabled, kill switch active); proactive participation remains
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
- Verification remains `partial`; S23 remains `paused` pending the existing
  environment and authorization gates.
- Recorded: 2026-08-17

- Command: `uv run --with pytest --project packages/dududa-agent python -m pytest tests/unit/compatibility/test_reply_polish.py tests/unit/compatibility/test_target_talk.py tests/unit/runtime/test_delivery.py tests/contracts/test_astrbot_output.py tests/unit/runtime/test_direct_chat.py tests/unit/runtime/test_orchestrator.py tests/test_repository_contract.py -q`
- Result: 58 tests and 12 subtests passed in 2.15 seconds.
- Evidence: SHORT/MEDIUM do not receive merged-forward eligibility; a LONG
  response still uses ordinary delivery unless it is explicitly validated and
  has at least two plain-text parts in a group with no target or attachment.
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
- Result: partial. Configuration defaults to disabled with 45-second refresh,
  15-second timeout and 90-second Evidence TTL. The fixed-model probe uses
  `max_tokens=8` and `request_max_retries=0`; success publishes `HEALTHY`, while
  failure/timeout publishes or retains `UNKNOWN`, expired evidence returns to
  `UNKNOWN`, and plugin termination cancels the refresh task.
- Evidence boundary: the implementation has focused evidence but is not enabled
  in the running AstrBot. It does not establish formal Provider Conformance,
  deployed continuous health or live single-group execution.

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
  is not enabled in the running AstrBot; these tests do not prove real AstrBot
  Provider Conformance, candidate deployment, continuous production health,
  live single-group Shadow or QQ send.
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
- Evidence: 27 unique focused tests passed in 1.005 seconds. An earlier six-test
  smoke passed in 0.196 seconds. The tests use a Fake AstrBot Provider and prove
  zero `text_chat()` calls during construction; `off` keeps legacy ownership
  with zero Provider calls and zero sends; `shadow` performs exactly one Fake
  Provider call while legacy keeps ownership and no send occurs; disabled or
  unresolved Providers fall back to unavailable/legacy; AnswerProfile flag
  projection and rule-only Perception are wired without a second model call.
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
- Evidence boundary: the probes prove one-shot protocol reachability only. The
  candidate path now carries output/reasoning parameters, but the models are not
  registered in the running AstrBot. A default-off refresh implementation now
  exists, but it has not been enabled against formally conformant Providers and
  no continuous production-health evidence exists. Only `low` was remotely
  sampled.
- Coverage gap: no human Gold, live Dududa traffic, real Endpoint Conformance or
  health, container deployment and Release binding, live campus/arXiv/industry
  Source, production Projection/Output composition, QQ send, online Bandit or
  single-group ladder Receipt. S23 therefore remains `paused/partial`.
- Recorded: 2026-08-15
