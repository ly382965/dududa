# Dududa 2.0 重构进度

更新时间：2026-08-10
历史基线：`main@2767cc9768d4bce63d4b4ee811add951ebce6870`

## 当前结论

- Phase 0–1 的审计、目标设计和迁移计划已完成。
- S01–S15C 的既定离线工程已完成到 S15C；S12/S13 已闭合统一 MCP 与受治理 Capability，
  S14 已闭合 Memory 生命周期、M0-M2 词法基线和固定合成 Eval，并通过双 Python、构建、
  Web 与安全综合 Verification；S15/S15A 已闭合回答档位/Persona 和主动出站默认拒绝契约。
- 旧 AstrBot Handler 在 `off/shadow` 下仍是权威入口；Canary 只对允许群的结构化显式 @
  取得持久单一所有权。真实 QQ 群运行统一延期到所有当前发布必需模块、既定 WebUI 测试和本地
  总审计完成之后；独立可选 S20 不属于该发布前置。
- S04、S06、S07、S14 新路径默认关闭；未迁移、改写或读取生产 Memory。
- 2026-08-09 新增的短/中/长回答已完成 S15 离线机械范围，主动出站已完成 S15A 契约、
  S15B 持久调度和 S15C 来源框架/合成 fixture；Digest/Probe Shadow 仍等待 S15D-S15E，真实
  校园/行业/arXiv Adapter、实时内容与发送继续作为外部门禁。
- 本文是当前实施状态的权威台账；`docs/design/` 保存冻结 Spec，历史基线文档不随实现结果
  改写。

“步骤完成”表示该步骤约定的代码、负向测试和退出门禁已通过，不表示产品模块满足统一完成
定义。模块只有具备真实 Adapter、端到端故障/取消/超时证据、生产 feature flag、shadow、
选择性切流和可执行回滚后，才能标记为完成。

## S01–S07 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S01 核心 Package | 已完成 | 可安装 `dududa-agent`、不可变领域 DTO、Runtime State、错误和严格配置；Python 3.10+ | Orchestrator、State Store、生产 Event 接入 |
| S02 契约与 Port | 已完成 | canonical codec/golden vectors、N/N-1 reader、Port binding、Protocol、Fake 和 Contract harness | 冻结仅由 Fake 证明的后续接口 |
| S03 安全基础 | 已完成 | Actor/Scope、默认拒绝 Authorization、Confirmation、Limiter/Budget、Content Safety、Redaction、Audit、幂等和 typed config | 替换旧插件权限入口或改变中文错误文案 |
| S04 Connector/Output | 已完成 | AstrBot Input Connector、Output Adapter、Attachment Repository、Delivery Receipt、引用/@/附件和去重 fixture | 第二平台、真实 Attachment Source、跨 Runtime 原子去重、模型调用 |
| S05 插件拆分 | 已完成 | Core 薄入口、命令/生命周期拆分、TargetTalk/ReplyPolish 纯逻辑；插件 ID、命令、Decorator 和 priority 保持 | 删除旧 Handler、目录迁移、Runtime 切流 |
| S06 Memory 安全边界 | 已完成 | MemoryScope/Selector/Record/Repository、显式 Write Gate、内存/JSON 参考 Adapter、隔离矩阵 | embedding、Graph、Reranker、自动摘要或自动写入 |
| S07 Iris/迁移边界 | 已完成 | fail-closed Iris Protocol Adapter、缺 metadata 隔离区、backup/dry-run/receipt/rollback CLI | 真实 Iris SDK Backend、生产数据迁移、语义检索、Runtime 接入 |

## S08–S11 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S08 静态 Model Router | 已完成 | Haiku/Sonnet/Opus 契约、Registry、硬过滤、流量 admission、容量、fallback、Fake 与兼容 Adapter | Bandit、随机路由、真实多 Provider 效果声明 |
| S09 Perception 与 Tiering | 已完成 | Rule/Model/Merger/Validator、Social Decision、Complexity、TierPolicy、320 条合成/固定 Eval | 人工标签确认、真实群数据校准、多轮与附件语义 |
| S10 Offline Runtime | 已完成 | Connector 到 Delivery receipt 的显式 @ 直聊闭环、两次模型预算、CAS/single-flight、Composition、reconciliation 与 Shadow | Tool、Memory、Attachment、生产 Provider 和主动群聊 |
| S11 Controlled Rollout | 已完成（本地） | typed mode、白名单、SQLite claim/tombstone、priority-100 AstrBot Bridge、发送前熔断、脱敏指标和回滚 CLI | 未经授权的真实 QQ 群发送、广泛生产切流 |

## S12–S15B 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S12 Unified MCP | 已完成（离线） | framework-neutral DTO/Port、严格 Registry、长生命周期 Client、隔离 v2 worker、iCourse facade/Legacy 回滚和 Fake/iCourse 同 Contract | 新真实 Server、实时来源、凭据和生产 Tool enablement |
| S13 Capability Runtime | 已完成（离线） | 分离的 Capability Catalog、Retrieval、有限 Planner、逐步授权 Executor、Observation Validator、iCourse 只读映射和配置式 Fake 扩展 | 真实 Planning Endpoint、高风险/写能力、人工语言质量和生产 Tools Rollout |
| S14 Memory Lifecycle/Retrieval | 已完成（离线） | generation-bound 读取、CAS 删除/tombstone、scoped export、archive/restore、JSON v2 crash replay、正式 Retrieval Port、M0/M1/M2、纯 Python CJK BM25 与固定合成 Eval | Runtime/旧命令消费者迁移、真实 Iris、授权数据/人工质量、Embedding/Hybrid、自动写入和生产切流 |
| S15 Response Profile/Persona | 已完成（离线） | SHORT/MEDIUM/LONG Plan、动态预算、Plan/Persona generation checkpoint、typed assets、Catalog CAS/LKG、最终机械 Validator 与 17-case 3x3 Eval | 真实 Provider tokenizer、人工中文/Profile/Persona 质量、最终预算校准和真实 QQ 体验 |
| S15A Proactive Contracts | 已完成（离线） | initiated-run/Target/Grant/Trigger/Subscription/Preview/Dispatch/Receipt v1 契约、当前 Actor 解析、默认拒绝策略、global/Scope quota、metadata-only Preview、稳定幂等、crash recovery、双 Python 590 项全仓测试 | 持久 Scheduler、真实来源、模型合成、生产 Registry/Output、QQ 发送和真实群证据 |
| S15B Durable Scheduler | 已完成（离线） | framework-neutral Scheduler Ports、typed JSON、SQLite Subscription/slot authority、IANA/DST、misfire、CAS/lease/reclaim/ack、暂停/撤销失效、重启/篡改与 30 日 fake-clock 仿真 | 生产 Scheduler 组合、Source、模型、Output、真实订阅与 QQ 发送 |

## 产品模块完成度

| 模块 | 状态 | 判断依据 |
| --- | --- | --- |
| 核心 Package | 部分完成 | Package、DTO、Orchestrator、CAS Store、Delivery/reconciliation、Shadow 和 rollout Ports 已完成；真实 Provider/Tool/Memory/Attachment 全能力未完成 |
| 安全组件 | 部分完成 | 授权、预算、内容安全、隐私、持久 claim 和发送前熔断已贯穿 S10/S11；旧命令兼容权限仍保留 |
| Connector / Output / Attachment | 部分完成 | AstrBot Connector/Output、持久 rollout 去重、Bridge 和发送 tombstone 已完成；真实附件读取和第二平台未完成 |
| Memory | 部分完成 | S14 离线生命周期、删除/恢复、词法检索和合成安全/质量回归已完成；生产仍默认关闭；真实 Iris、Context Builder/旧命令迁移、授权数据人工 Eval、Embedding/Hybrid、shadow 与生产读写未完成 |
| 插件拆分 | 部分完成 | 源码拆分、priority-100 rollout handler 和镜像内 43/1/1 registry 已验证；旧 Handler 按回滚设计继续保留 |
| 模型路由、语义理解、OC Runtime | 部分完成 | S08/S09 和 S10 最小 Composer/Renderer 已实现；真实质量、完整 OC 资产和多轮能力仍待 Eval |
| 回答档位 / ResponsePlan | 已完成（S15 离线范围） | SHORT/MEDIUM/LONG 与 Tier/Reasoning 正交，动态预算、Runtime/Composer/Persona/Delivery 绑定和 3x3 合成 Eval 已通过；真实体验仍待外部门禁 |
| Unified MCP / Capability Runtime | 已完成（离线） | S12 Unified Client/Registry、独立 worker、iCourse facade/Legacy 回滚，以及 S13 Catalog/Retrieval/有限 Planner/Executor/Validator 和四个只读映射均有本地证据；生产 Tools 仍关闭，真实 Planner Endpoint、新 Server 和在线来源未实现 |
| 主动消息/订阅推送 | 部分完成（S15B） | S15A initiated-run/Target/Grant/默认拒绝控制，以及 S15B 持久 Scheduler、DST/misfire、Subscription CAS、claim/reclaim/ack 和 30 日仿真已实现；生产仍默认 off | Source、Digest/Probe Shadow、生产组合与真实发送均未实现 |
| Bandit | 未完成（S20） | 当前无配置或执行 hook；禁止学习主动 send/skip、目标、日程、频率和 Answer Profile |
| WebUI 测试工作 | 进行中 | 按既定测试计划推进，本次顺序调整不追加核验范围 |
| 真实群聊放量 | 最终阶段（未开始） | 仅有本地仿真和安全边界；必须等待所有当前发布必需模块、既定 WebUI 测试和本地总审计完成；可选 S20 不阻塞 |

## 2026-08-10 S15B 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 调度与持久状态机 | Subscription create/update/pause/resume/revoke CAS、跨 revision local-date 唯一 slot、READY/CLAIMED/EMITTED/SKIPPED/INVALIDATED、稳定 materialization/claim/ack receipt 均已实现 |
| 时间语义 | New York、Berlin、Lord Howe 的 normal/fold/gap round-trip 测试通过；gap 固定 tombstone，fold 取最早 UTC，未来任务不物化，过期 misfire 不补发 |
| 并发与恢复 | 双 SQLite 实例只有一个 live claim；同 worker 幂等、lease 过期递增 reclaim、旧 claim ack 拒绝、重启 exact ack 与持久行篡改拒绝通过 |
| 30 日 fake-clock | 30 个 occurrence、30 个 emitted、零重复 slot、零过期补发；重复 tick 和时钟回拨不恢复终态 |
| 双 Python | 3.10.20 与 3.12.13 各 `601 tests OK`、2 个既有 AstrBot-only skip；各自 29 项 Proactive/Scheduler `-W error` 聚焦套件全过 |
| 构建与边界 | changed-file Ruff/format、compileall、uv lock、sdist/wheel 安装/import/pip check、782 文件 secret scan、Shell/CLI/Compose/whitespace 全过 |
| unchanged Web | 66 frontend + 42 server tests、typecheck、production build 和 production dependency audit 通过；未扩建 Control Plane，未修改运行中的 NapCat/AstrBot 容器 |

## 2026-08-10 S14 阶段证据

| 门禁 | 当前结果 |
| --- | --- |
| 生命周期与检索实现 | generation/time-bound read、CAS delete/tombstone、scoped export、archive/checkpoint restore、JSON v1/v2、Iris unsupported、M0/M1/M2 focused suites 已通过 |
| 固定合成 Eval | 8 cases、56 live records、8 tombstones、同一 state revision 9；normal/reverse/fixed-shuffle ranking fingerprint 一致 |
| 安全机会 | 每个策略的 cross-Scope、future-created、expired、tombstoned、Restricted 分母均为 8，暴露事件均为 0，并记录合成机会的一侧 95% 上界 |
| 词法回归 | 预注册 7-case lexical subset 上 M2 binary nDCG@K `1.0`，M1 `0.0`；只作 synthetic regression，不作真实中文质量声明 |
| 双 Python | 3.10.20 与 3.12.13 各 `521 tests OK`、2 个 AstrBot-host-only skip；各自 50 项 Memory/Eval/Iris/import `-W error` 聚焦套件全过、零 skip |
| 构建与边界 | changed-file Ruff/format、compileall、uv lock、sdist/wheel 安装/import/pip check、729 文件 secret scan、Shell/CLI/Compose 和 whitespace 全过 |
| unchanged Web | 66 frontend + 42 server tests、typecheck 和 production build 通过；未扩建 Control Plane，未运行或修改 NapCat/AstrBot 容器 |

## 2026-08-04 S08–S11 验证证据

| 门禁 | 结果 |
| --- | --- |
| Python 3.12 / 3.10 全仓 | 两个版本均 Pass：350 tests，宿主机各有 2 个 AstrBot-only skip |
| Runtime/rollout warnings-as-errors | 两个版本均 Pass：109 tests |
| S09 Eval | 320 条版本化合成/固定数据集通过策略回归；人工确认仍为 false |
| 静态与边界 | Ruff、独立首次导入、Bandit 禁止扫描、WebUI/Sub2API 历史 scope 扫描通过 |
| Python / Shell / Compose | compileall、Shell syntax、两个 CLI `--help`、Compose parse 通过 |
| 仓库安全 | safety scan Pass：372 files；`git diff --check` 通过 |
| 派生 AstrBot 镜像 | `dududa/astrbot@sha256:a72637301a6df1fe2a120a7ed3cb77406999e4c7f69f878ed64887d2d2d1ec09` |
| 镜像插件 smoke | `--network none` 下 19 tests 全通过；Core registry 43 handlers、rollout priority 100 |
| 镜像 Package | `dududa-agent==0.1.0a1`、`dududa.rollout` 可导入、`pip check` 通过 |

完整要求到证据映射见 `s08-s11-completion-audit.md`。

## 2026-08-02 S01–S07 验证证据

| 门禁 | 结果 |
| --- | --- |
| 宿主机完整测试 | Pass：116 tests，2 个仅因宿主机无 AstrBot 跳过 |
| Python 3.10 动态测试 | Pass：同一干净 wheel 安装后 116 tests，2 个 AstrBot-only 跳过 |
| 静态导入与格式 | Pass：Ruff check；80 个 S01–S07 Python 文件无需再次格式化 |
| Python 编译 | Pass：Package、插件、服务、脚本和测试 |
| Shell | Pass：`manage.sh`、`setup_dev.sh`、iCourse setup/start 脚本 |
| Compose | Pass：解析后只有 `astrbot`、`napcat` |
| 仓库安全扫描 | Pass：216 个 tracked/untracked 文件，无凭据或运行数据 |
| 干净 wheel | Pass：`dududa-agent==0.1.0a1`；根包加 55 个子模块可导入；含 `py.typed`，不含 `.pyc`；`pip check` 通过 |
| Memory 迁移入口 | Pass：脚本 mode `100755`、`--help`、4 个 apply/rollback fixture |
| 派生 AstrBot 镜像 | Pass：无缓存重建；镜像 ID `sha256:9a8831c8cbca26d21b797db398a4b8d241d2c324b41c61fc868d968acb036e9d` |
| 镜像 Package | Pass：Python 3.12、`dududa==0.1.0a1`、55 个子模块、`py.typed` 和 `pip check` |
| 镜像 AstrBot 测试 | Pass：6 tests，无 skip；Core / TargetTalk / ReplyPolish registry 为 `42 / 1 / 1`，`natural_course_query` priority 为 8 |
| iCourse MCP | Pass：`--network none` 下发现 10 个工具，空库 `icourse_stats` 成功 |
| 干净启动 | Pass：隔离网络、随机端口和一次性数据目录中启动 AstrBot 4.26.2，并加载四个自研插件；实例和临时网络已清理 |
| 空白检查 | Pass：`git diff --check`；另对未跟踪的 S01–S07 交付范围执行尾随空白扫描 |

镜像构建从 digest-pinned AstrBot 基础镜像开始，但 iCourse 的开放版本依赖仍会在线解析；上表
记录本次产物证据，不把它描述成完整的供应链锁定。

## 已收紧的边界

- 所有 55 个子模块可以作为首次导入，顶层惰性导出不再产生循环依赖。
- 核心 Package 只依赖 Python 标准库和内部模块，不导入 AstrBot、模型、MCP 或 Iris SDK。
- Runtime、canonical/binding、Security、Connector/Output/Attachment 和 Memory 的 digest、
  Scope、权限、幂等、deadline/cancellation 与不可变集合均有负向测试。
- 多角色授权不能把一个角色的 permission 与另一个角色的资源约束拼接；
  `SecurityConfig.role_constraints` 是 v2 严格配置的必填映射，缺失或不匹配默认拒绝。
- Memory 等待会响应 deadline/cancellation；Iris 后端写入被取消时回滚本地 record、
  decision 和 idempotency 状态。
- JSON Memory 临时文件使用独占、no-follow 创建；预置 symlink 不会覆盖其目标。
- Attachment 有界流在 token 或调用任务取消后回收 `__anext__` 子任务。

## 残余边界

1. **真实群验证延期到最终阶段。** S11 已有本地 Bridge/Shadow/Canary/kill switch 证据；
   即使提前具备群 ID、凭据和发送窗口，也要等所有当前发布必需模块、既定 WebUI 测试和本地
   总审计完成后才执行。独立可选 S20 不属于该发布前置。
2. **Attachment Actor 绑定不完整。** `AttachmentAccessRequest` 没有独立 `Actor` 字段；当前
   只能验证 `AuthorizationDecision.actor_digest`，Repository 没有第二份当前 Actor 做交叉核对。
3. **去重分层。** S10 Runtime Store 证明同进程 CAS/single-flight；S11 SQLite rollout ledger
   证明跨进程 claim 与发送 tombstone。通用多平台持久 RuntimeState 仍未实现。
4. **真实附件读取未实现。** AstrBot 组合层使用 fail-closed `RejectingAttachmentSource`，不会
   静默丢弃或越权读取附件。
5. **真实 Iris 未接入。** 当前只有 `IrisBackend` Protocol、fail-closed Repository 和 Fake
   Backend 契约测试；仓库没有 Iris SDK 实现。
6. **生产 Memory 不变。** 旧 `/remember` 仍写旧 JSON；Memory v2 自动读取/写入均关闭，迁移
   CLI 只允许离线显式执行。S14 的 synthetic M2 `Recall@K=1.0` 只证明固定 lexical fixture，
   不证明真实中文质量或生产可启用性。
7. **Hook 证据分层。** 宿主机两个 AstrBot 测试会 skip；真实 Hook 证据来自本次重建镜像，
   不能把宿主测试与镜像 smoke 合并成同一结果。
8. **三档回答已完成机械契约。** 不得把长回答映射 Opus 或短回答映射 Haiku；当前
   `ResponsePlan` 和 Validator 证据不等于真实中文质量、Persona 风格或最终预算已校准。
9. **主动出站完成到 S15C。** 定时器只产生结构化 Trigger claim，不伪造用户消息；MCP
   不拥有订阅、调度或发送。S15C 只提供受治理来源契约、原子内存参考 state 和合成 fixture，
   不是已存在的真实来源；在 S15D-S15E Shadow/回滚门禁完成前不做生产组合或真实群发送。

## 下一步

S15C Verification 完成后，按 Tree 继续 S15D-S15E；Web 未受影响时不重复回归，再执行
S16-S19 本地回归、
30 日 fake-clock/no-send 仿真、故障注入和 S22 回滚/兼容审计。全部关闭后，才冻结群 ID、
凭据、分行为 SLO、发送窗口和 digest-pinned 回滚清单，并按“入站 Shadow -> 明确 @
Canary -> 手动日报 -> 定时日报 -> 低频 Probe -> 分层放量”执行 S23。Bandit 不是主动链路
前置，也不得对主动行为开启探索。

后续分支采用风险分层验证：优先运行受影响 Contract、聚焦 warning-as-error 与抽样仓库回归；
只有跨模块高风险变更或 S19/最终总集成才重复双 Python 全仓，避免每个 Sxx 重复执行同一套
600 余项测试。

## 历史基线

2026-07-18 的 Phase 0–1 基线为 8 tests、Compose 两服务、六个锁定第三方插件、派生镜像和
网络禁用 MCP 握手通过。该结果保留在 `baseline.md`，只用于比较，不再代表当前实现状态。
