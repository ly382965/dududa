# Dududa 2.0 阶段完成报告（截至 2026-08-10）

## 1. 报告口径

本报告冻结于以下现场：

- 控制分支：`codex/s08-s11`；
- S16：由 `22dd4e0` 合并，TreeWork 由 `e04fd1d` 完成返回；
- S17 工作树：`treework/layout-migration`；
- S17 实现提交：`8597d70`、`92fd28c`、`6b4ee09`，旧 marker 兼容修复为 `43fe543`。
- S18 设计/实现提交：`daf3111`、`5be566a`、`7e7cbab`、`4cd9ddc`。

状态依据依次为 TreeWork lifecycle/verification、Git 提交、分支 Verification 和测试记录。
“完成”只表示相应 Spec 批准的本地或离线范围已完成，不等于产品已经生产就绪。

## 2. 总体结论

1. S01-S16 的既定本地/离线工程范围已经完成，其中 S08-S16 的 TreeWork 叶分支均为
   `complete / verified`。
2. Mew/NapCat Web epic 已完成并验证；它是 QQ 操作工作台，不是 Agent Control Plane。
3. S17 三批路径迁移和旧 lock marker 兼容均已提交并通过代表性验证，已经 protected
   completion 并合入控制分支。
4. S18 已完成统一 Eval/Trace/CI 的离线实现与风险分层验证；S19、S22、S20 尚未开始。
   S23 是最终真实群外部门禁，当前不得进入。
5. 当前仍不是生产就绪状态。真实 Provider、生产 Memory/Tools、真实 Source Adapter、主动发送、
   在线 Bandit 和真实群质量均没有完成证据。

## 3. Sxx 工程状态

| 阶段 | 当前状态 | 已有证据 | 尚未覆盖 |
| --- | --- | --- | --- |
| S01-S07 核心契约、安全、Connector、插件拆分、Memory/Iris 边界 | 已完成（步骤范围） | `c83d742`；双 Python 116 tests、wheel/import、镜像和插件/MCP smoke | 生产全能力、真实 Iris SDK、生产 Memory 迁移 |
| S08 Static Router | 已完成、已验证 | 三 Tier、硬过滤、admission、capacity、retry/failover/fallback、Fake/兼容 Adapter；S08-S11 审计双 Python 350 tests | 真实多 Provider 效果、Bandit |
| S09 Perception/Tiering + additive semantic contract | 已完成、已验证（合成范围） | 320 条合成 Eval；span/entity/reference/uncertainty 与 `ACCEPT/CLARIFY/ABSTAIN` 契约 | 真实中文群聊质量和人工校准 |
| S10 Offline Runtime | 已完成、已验证 | `9b64188`；双 Python 325 tests，显式 @ 直聊、Shadow、reconciliation | 生产 Provider、Tool/Memory/Attachment 全链 |
| S11 Controlled Rollout | 已完成、已验证（本地） | `716e227`；双 Python 350 tests，持久 claim、熔断、指标与回滚 | 真实 QQ Canary |
| Production Shape | 已完成、已验证 | 默认关闭 composition、sampling/health/SQLite 形状和关闭路径 | 真实 Endpoint conformance |
| S12A MCP v2 Spike | 已完成、已验证 | 双 Python 414 tests；结论为采用隔离 v2 worker，保留 v1 fallback | 生产网络负载 |
| S12 Unified MCP | 已完成、已验证（离线） | 双 Python 466 tests；统一 Client/Registry、长 Session、Schema snapshot、iCourse facade/Fake 同 Contract | 新真实 MCP Server、生产 Tool enablement |
| S13 Capability Runtime | 已完成、已验证（离线） | 双 Python 496 tests；Catalog/Retrieval/Planner/Executor/Validator，iCourse 四个只读映射 | 真实 Planning Endpoint、高风险或写 Capability |
| S14 Memory Lifecycle/Retrieval | 已完成、已验证（离线） | 双 Python 521 tests；删除/tombstone/export/restore、M0-M2、CJK BM25、固定合成 Eval | 生产接入、真实 Iris、Embedding/Hybrid、人工质量 |
| S15 AnswerProfile/Persona | 已完成、已验证（离线） | 双 Python 557 tests；SHORT/MEDIUM/LONG、动态预算、Persona generation 和 17-case 3x3 Eval | 真实 tokenizer、OC 资产和人工中文体验 |
| S15A Proactive Contracts | 已完成、已验证（离线） | 双 Python 590 tests；Target/Grant/Preview/Dispatch/Receipt、预算、kill switch、幂等恢复 | 真实发送 |
| S15B Durable Scheduler | 已完成、已验证（离线） | 双 Python 601 tests；IANA/DST、misfire、CAS/lease、30 日 fake clock | 生产 Scheduler 组合 |
| S15C Governed Sources | 已完成、已验证（fixture 范围） | 双 Python 616 tests；来源契约、provenance/freshness/citation/dedup 和三类固定 fixture | 真实校园/arXiv/行业 Adapter |
| S15D Digest Shadow | 已完成、已验证（no-send） | 双 Python各 6 个代表场景；fixture 日报、独立 Preview、零 Output | 真实来源、模型、持久 metadata 与投递 |
| S15E Probe Shadow | 已完成、已验证（no-send） | 双 Python各 6 个代表场景；群级 hard gates、TTL、cooldown、no-response | 真实群 Projection、人工打扰度、投递 |
| S16 Operations Hardening | 已完成、已验证、已合并（离线） | Release/State/Receipt、只读 Health、SQLite Backup、Restore Plan、失败单次回滚及 Compose contract | 真实容器升级/恢复、备份加密和生产 Driver |
| S17 Layout Migration | **已完成、已验证、已合并** | `e2cc296` 冻结设计；三批迁移 `8597d70`/`92fd28c`/`6b4ee09`；旧 marker 兼容 `43fe543`；双 Python/worker/Compose/build 代表证据通过 | 一 Release 兼容链接留到 S22；Manifest v2 延期 |
| S18 Evaluation/CI | **已完成、已验证、已合并（离线）** | `daf3111`/`5be566a`/`7e7cbab`/`4cd9ddc`；十个固定 runner、十四维且完整摘要绑定的 catalog、低敏 receipt/内部生成 run ID、append-only Runtime Trace、双 root/worker lock CI；350 个 bundle case、146 项 focused Contract 与 Python 3.10 风险样本通过 | 完整双 Python 642 项、Web/E2E、镜像/容器、完整故障注入和 SLO/回滚包审计留给 S19；真实质量仍是外部门禁 |
| S19 Local Integration Audit | 未开始 | Tree 已定义 | 双 Python全仓、镜像/配置/回滚包、SLO 冻结 |
| S22 Legacy Cleanup | 未开始 | Tree 已定义 | 仅删除有消费者迁移和上一 Release 恢复证据的兼容面 |
| S20 Offline Bandit | 未开始 | Tree 已定义 | decision/feedback/support/propensity 与 IPS/SNIPS/DR golden |
| S23 Real Group Validation | 最终外部门禁、未开始 | 无真实发送声明 | 单群 Shadow/Canary/日报/Probe 和分层放量 |
| Mew/NapCat Web | 已完成、已验证 | `4c6686b`；66 frontend、42 server、6 Playwright、352 repository tests | 两真账号人工 destructive mutation 仍属外部证据 |

## 4. 核心模块的产品完成度

| 模块 | 产品判断 | 说明 |
| --- | --- | --- |
| 模型路由器 | 部分完成 | 静态路由和确定性安全边界较完整；真实 Endpoint 目录、质量/成本/延迟证据和生产装配未完成 |
| Memory | 部分完成 | 生命周期、安全 Scope 和词法基线已完成；生产读写、真实 Iris、语义/混合检索与人工 Eval 未完成 |
| MCP 集成 | 离线框架完成 | iCourse 是唯一真实兼容 Server；新 Server 只留通用 Registry/Capability 接口，不虚构校园/arXiv/行业 MCP |
| Connector/Output | 部分完成 | AstrBot Connector/Output 和本地 rollout 已完成；真实附件、第二平台和生产全链未完成 |
| 语义理解 | 部分完成 | 结构化语义契约和合成 Pilot 已完成；真实中文、多轮、附件和人工 gold 未完成 |
| Persona/OC | 机制完成、内容未完成 | ResponsePlan、Persona Resolver/Renderer/Validator 已完成；正式 OC 资产和体验校准仍需产品输入 |
| 主动消息/推送 | 离线 no-send 链完成 | 契约、Scheduler、fixture Source、Digest/Probe Shadow 已完成；生产来源、Projection、Output 和授权发送未完成 |
| Bandit | 未完成 | S20 离线基础尚未开始；更后的在线学习还缺合法同档 Endpoint、propensity 和可归因反馈 |
| WebUI | 既定 Mew 范围完成 | 多账号 QQ 工作台已验证；不扩建第二套 Agent 控制面 |

## 5. S17/S18 收口现场

S17 是 path-only 迁移，不重新设计 Runtime、MCP、插件或运维行为。

- 已提交批次 1：`plugins/`、`config/`、两个 MCP service 迁至目标目录；
- 已提交批次 2：`docker/`、`scripts/`、Compose、环境模板和管理入口迁至 `deploy/`、`ops/`；
- 已提交批次 3：v1 `plugins.lock.json`、`patches/`、`vendor/` 迁至 `third_party/`；
- 已补兼容：已安装插件的两个已知旧 marker 路径在比较时确定性归一化，未知差异仍拒绝；
- 根入口和旧目录暂以一 Release 兼容链接保留，S22 才能基于证据删除；
- Manifest v2 因源码 hash、依赖锁和许可证证据不足而延期，当前不得写成已启用；
- S17 已收口；S18 在不改写各领域指标的前提下增加统一 catalog/runner/receipt，补全原有
  Runtime Trace 路径，并修复 isolated MCP worker CI 和 Node 22 构建输入。
- S18 只证明离线技术门禁；完整发布候选总审计和实际镜像/容器证据进入 S19。

## 6. 当前无需外部输入的工作

S19 的离线部分、S22 和 S20 离线基础都可以继续使用仓库、Fake、固定 fixture、
fake clock 和派生镜像完成。它们不需要真实聊天、API Key、QQ 登录态或生产容器修改。

用户可以并行准备但不应直接提交敏感数据的输入包括：Endpoint 公开目录、Intent/风险分类、
SHORT/MEDIUM/LONG 样例、来源与调度策略、Memory 产品策略、数据治理规则和标注人员。
详细字段、优先级和 S23 授权模板见
[外部输入准备清单](external-input-checklist.md)。

## 7. 后续顺序

恢复开发后沿既有 Tree 串行执行：

```text
S17（完成） -> S18（完成） -> S19 -> S22 -> S20 离线基础
```

S20 不阻塞 S23。只有 S17、S18、S19、S22、既定 Web 回归和发布包均通过后，才另行授权
S23。真实群测试顺序保持：no-send Shadow -> 明确 @ Canary -> 手动日报 -> 定时日报 ->
低频 Probe -> 3-5 群分层放量。

## 8. 当前主要风险

1. S17 canonical 布局已成为控制分支权威，但兼容链接必须在 S22 以消费者/恢复证据清理，
   不能提前或无限期保留。
2. Iris 固定版本缺少明确许可证证据，Manifest v2 不得据此声称供应链已验证。
3. 最新完整全仓基线停留在较早阶段；S15D-S16 采用了批准的抽样测试，完整回归应在 S19 集中执行。
4. 真实 Endpoint、Source、Memory 和 QQ 行为都缺少外部证据；合成测试不能替代生产质量声明。
5. TreeWork 的部分父 epic lifecycle 尚未聚合完成叶节点状态，判断进度时应以叶节点和本报告为准。
