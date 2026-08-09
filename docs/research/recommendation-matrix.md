# Dududa 2.0 环境与技术调研推荐矩阵

## 1. 本轮结论

截至 2026-08-09，本地主仓已经具备可锁定、可重建、可在 Python 3.10/3.12 和 Node 22 上验证的
开发环境；这不等于当前运行中的 AstrBot 已接入 Dududa Core。生产纵向链仍被 composition root、
sampling capability、health snapshot 和 SQLite 版本四项 P0 门禁阻断。

研究结论支持继续沿现有契约开发，不支持重写 S08 Static Router，也不支持把任一第三方框架直接
变成 Core authority。下一轮应先闭合 production-shape，再按单开发者 WIP=1 完成 MCP、Capability、
Memory、ResponsePlan、主动出站和本地总审计；真实群聊始终位于最后的 S23。

## 2. 总推荐矩阵

| Topic | 当前证据状态 | 决策 | 可直接开发 | 必须先 Spike/外部门禁 | 后置 |
| --- | --- | --- | --- | --- | --- |
| 本地开发环境 | 完成 | adopt 根 uv workspace、双 Python、Node 22、锁文件和 CI 同构命令 | 使用 `uv sync --locked`、`npm ci` 和固定验证入口 | 依赖升级仍需双版本及 warning-as-error 复核 | 无 |
| Production shape | 未就绪 | 保留 Router fail-closed，补 Adapter/装配证据 | `temperature=None` 契约、health state machine、唯一 composition root、镜像版本 smoke | 每个真实 Endpoint 的合法配置、文档和低配额 conformance 凭据 | 任一真实 QQ canary |
| Static Model Router | S08 静态范围完成；真实 Endpoint 未完成 | adopt 现有三 Tier hard filter/priority/fallback | 真实 Endpoint conformance harness 和 digest-bound evidence | 至少一个真实 Endpoint 闭合 health、limits、reasoning、usage、cancel、retention/residency | 学习排序 S20 |
| AnswerProfile | 只有设计 | adopt 确定性 SHORT/MEDIUM/LONG，和 Tier/Reasoning 正交 | DTO、policy、动态预算、final validator、3x3 matrix | 每档 5–10 个理想回答/反例和 QQ 分片体验；人工盲评 | 不交给 Bandit |
| 语义理解 | 合成 policy-gold 技术门禁通过，真实质量未证明 | additive v2 span/decision contract；不重写现有模块 | `TextSpan`、Entity/Reference mention、`ACCEPT/CLARIFY/ABSTAIN` 与 schema pilot | 授权中文 3–12 turn windows、第二标注者、仲裁和校准数据 | 广泛质量声明/真实泛化 |
| Unified MCP | 当前 v1 Server 可被 v2 Client legacy 模式调用 | spike v2 Client+Server 迁移，预期 adopt | Registry、generation、长 Session、Dududa Schema snapshot、取消/unknown outcome contract | 固定 v1/v2 fixture 完成并发、崩溃、Schema drift 和泄漏实验 | 任意写 Tool |
| Scheduler | 只有局部原语 | adopt Dududa SQLite occurrence/CAS；APScheduler 3 只作 Trigger oracle | occurrence、IANA timezone、misfire、lease、revoke 和 fake clock | SQLite 3.51.3+ 或 rollback journal ADR；双 Worker/fault injection | 真实定时发送 S23 |
| 校园/行业/arXiv 来源 | 官方 Feed/API 可用，全文权利未开放 | adopt allowlist metadata、有限摘要、规范链接 | USTC 教务 RSS、arXiv category Feed、官方 publisher RSS Adapter fixture | 用户冻结栏目、publisher、category/关键词、修订与条目上限 | HTML/OAI-PMH/full text |
| Memory | Scope/WriteGate 基础存在，检索与生命周期未闭环 | adopt exact+recency+BM25 baseline；embedding 只做 shadow | 删除/导出/冲突、显式写入闭环、CJK lexical baseline、统一 Eval harness | CJK tokenizer/bigram、embedding/hybrid 对照；授权数据和外部 Backend 隔离实验 | Graph/temporal 自动化 |
| Conversation Probe | 只有设计 | adopt 默认 off 的确定性群级 no-send detector | Opportunity Snapshot、TTL、hard gates、cooldown、Shadow Eval | 授权脱敏群聊窗口、标注指南、管理员流程和打扰预算 | 单群 canary S23 |
| Contextual Bandit | 只有可行性研究 | spike VW Worker + OBP research；当前禁止训练/live exploration | before-action DTO、support validator、合成 IPS/SNIPS/DR golden | 两个同 Role+Tier 合法 Endpoint、有效 propensity、显式反馈、足够 ESS | S20；不阻塞 S23 |
| WebUI | 已完成既定 NapCat 测试客户端范围 | 保持测试入口，不扩大验证 | 只在相应后端契约变化时补测试 | 无产品级 Control Plane 需求时不扩建 | 写控制面 |
| 真实群聊 | 未开始且不应开始 | defer | 只准备 SLO、kill switch、授权和回滚包 | 所有发布必需模块及 S19/S22 本地审计通过 | S23 唯一入口 |

各 Topic 的一手来源、版本/commit、许可证、维护状态、实验和失败线分别见：

- `environment-readiness.md` 与 `production-shape-preflight.md`；
- `mcp-scheduler-sources.md`；
- `memory-evaluation.md`；
- `perception-routing-response.md`；
- `proactive-messaging.md`；
- `contextual-bandit.md`。

## 3. 生产前四个 P0

1. **运行形态**：建立唯一 composition root 并调用 `install_rollout_runtime()`；默认 `off`，部分
   初始化失败必须回滚且不残留后台任务。
2. **参数语义**：Runtime 默认传 `temperature=None`；只有 conformance 证明支持时才发送采样参数，
   不得由 Adapter 静默丢弃。
3. **健康证据**：实现 `UNKNOWN -> AVAILABLE -> stale/failed UNKNOWN` 的有界快照；继续保留 Router
   对 UNKNOWN 的 fail-closed。
4. **持久化安全**：派生 AstrBot 镜像固定 SQLite 3.51.3+，或对并发持久路径采用 rollback journal +
   `BEGIN IMMEDIATE`/CAS。不得在当前 SQLite 3.46.1 容器做 WAL 并发压力。

四项都可先用 Fake/派生镜像离线验证，不需要读取生产凭据、聊天记录或发送 QQ 消息。

## 4. 外部输入清单

| 输入 | 阻塞范围 | 缺失时允许继续的范围 |
| --- | --- | --- |
| 每个 Provider 的合法 `provider_id/endpoint_id/model_id`、Tier/Role、官方能力/价格/retention/residency 文档及版本 | 真实 Endpoint enablement | Fake Router、conformance harness |
| 只用于 synthetic conformance 的低配额凭据或 Provider sandbox | 真实网络 contract test | captured fixture 和纯离线测试 |
| 固定 AstrBot/Provider 镜像、SDK 及实际下游请求计数/取消可观测方法 | Adapter enablement | Fake Adapter |
| 经授权中文群聊样本的同意、撤回、去标识和保存期限规则 | 语义/Probe 真实数据 Eval | synthetic schema pilot |
| 产品 intent taxonomy、unsupported capability 和高风险 action 清单 | 语义标签冻结、Tool policy | 数据指南 dry-run |
| SHORT/MEDIUM/LONG 每档 5–10 个理想回答和反例、字符/分片体验 | AnswerProfile 阈值冻结 | 使用标为 `pilot default` 的临时值 |
| 第二标注者、盲评者和仲裁人 | 一致性/人工质量声明 | 单人 schema pilot，不声称可靠性 |
| 校园栏目、行业 publisher、arXiv category/关键词/修订策略与每日上限 | 来源正式配置 | 固定公开 fixture |
| IANA 时区、发送时间、quiet hours、misfire 窗口、每群日上限和管理员停用流程 | 主动出站策略冻结 | fake-clock/no-send 默认配置 |

这些输入不阻塞本地环境、接口 DTO、Fake、负向 Contract Test 和研究 Spike。不得为了通过门禁构造
虚假的 Provider 能力、群聊标签或用户满意度。

## 5. 下一轮建议 Tree

Alignment 仍未结束，以下只是下一次 Tree revision 的建议，不在本 Goal 执行 `tw align end` 或
`tw tree apply`：

```text
root
  production-shape-gate       P0：镜像/SQLite、sampling、health、composition
  semantic-contract-eval      P0：additive v2 span + synthetic/schema pilot
  capability-runtime
    mcp-v2-spike              S12A：v2 Client/Server + v1 legacy fixture
    unified-mcp               S12
    bounded-capability        S13
  memory-retrieval            S14：生命周期 + lexical baseline + shadow comparison
  response-persona            S15：AnswerProfile + dynamic budget + Persona Eval
  proactive-outbound
    proactive-contracts       S15A
    durable-scheduler         S15B
    governed-sources          S15C
    digest-shadow             S15D
    probe-shadow              S15E
  operations-and-layout       S16 -> S17
  eval-and-local-audit        S18 -> S19 -> S22
  real-group-validation       S23（依赖全部发布必需本地分支）
  optional-bandit             S20（独立、非 S23 前置）
```

单开发者实施顺序固定为：

```text
production-shape-gate
-> semantic-contract-eval
-> S12A -> S12 -> S13 -> S14 -> S15
-> S15A -> S15B -> S15C -> S15D -> S15E
-> S16 -> S17 -> S18 -> S19 -> S22
-> S23
```

S20 只有在至少两个真实 Endpoint 属于同一 compatibility class、存在 action 前 propensity 和有效反馈
后才单独排期。它不能选择 Tier、AnswerProfile、主动发送、目标、时间、Memory Scope 或 Tool 权限。

## 6. 本轮完成定义

本轮只证明“环境和方案已闭环”：开发环境可重建、生产阻断有直接证据、每个 Topic 有来源和可复现
门禁、后续 Tree 有明确顺序。它不证明真实 Provider、真实中文群聊质量、主动消息体验或 Bandit 收益，
也不授权任何生产切流和 QQ 发送。
