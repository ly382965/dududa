# Contextual Bandit 技术栈调研

## 1. 结论

Bandit Learning 适用于 Dududa，但当前只能规划为可选 S20，并且首个决策点严格限定为：

> 在 Static Router 已完成全部 hard filter 后，对**同一 ModelRole、同一 ModelTier、等价隐私与
> 能力边界**的合法 Endpoint 进行排序。

当前没有第二个通过真实 conformance 的同 Role+Tier Endpoint、没有 before-action propensity
日志，也没有可归因奖励，因此**不能训练、不能做有效 OPE、不能 live exploration**。

判定：

- **adopt**：版本化 Bandit DTO、before-action log、delayed feedback、support/propensity
  校验、静态 baseline 和合成 estimator golden tests；
- **spike**：Vowpal Wabbit 作为隔离 Worker 的 ADF policy engine；Open Bandit Pipeline 作为
  独立 research environment 的 OPE 交叉验证；
- **defer**：shadow 排序和极小 conservative canary；
- **reject**：跨 Tier、权限、Memory Scope、高风险 Tool、主动发送、目标、日程、AnswerProfile
  的学习决策，以及在无 support 的确定性日志上声称 IPS/DR 效果。

## 2. 一手来源与维护状态

访问日期均为 2026-08-09。

| 来源 | 版本/commit | 许可证与维护状态 | 结论 |
| --- | --- | --- | --- |
| [Vowpal Wabbit](https://github.com/VowpalWabbit/vowpal_wabbit) | PyPI 9.11.2（2026-03-07）；HEAD `5801d820`（2026-07-15） | BSD-3-Clause；活跃，HEAD 正在加强 invalid importance weight 校验 | spike；门禁后才可 adopt：`--cb_explore_adf` 适合动态合法 action set；放独立 Adapter/Worker，不让 C++ 类型进入 Core |
| [Open Bandit Pipeline](https://github.com/st-tech/zr-obp) | Spike 固定 PyPI 0.5.7（2023-04）；master `8cbd5fa`/pyproject 0.5.5（2022-11）只作维护证据 | Apache-2.0；未归档但主分支与 PyPI 版本漂移、维护缓慢 | research-only：复核 IPS/SNIPS/DR 和合成数据，不进入生产请求路径 |
| [MABWiser](https://github.com/fidelity/mabwiser) | 2.7.4；HEAD `b104071`（2024-08-30） | Apache-2.0；维护较慢 | defer：可做 LinUCB/LinTS 离线对照，但不提供 Dududa 所需日志/OPE/发布治理 |
| Li et al., [Contextual-Bandit Approach to Personalized News](https://arxiv.org/abs/1003.0146v2) | arXiv v2，2012 | 预印本内容为 arXiv non-exclusive distribution license；稳定经典论文，仅引用 | replay/LinUCB 来源；同时提醒 replay 只利用 action 匹配样本，数据效率有限 |
| Dudik et al., [Doubly Robust Policy Evaluation and Learning](https://arxiv.org/abs/1103.4601v2) | arXiv v2，2011 | 预印本内容为 arXiv non-exclusive distribution license；稳定论文，仅引用 | adopt DR 作为一项估计器，不把它当作 support 缺失的补救 |
| Agarwal et al., [Making Contextual Decisions with Low Technical Debt](https://arxiv.org/abs/1606.03966v2) | arXiv v2，2017 | 预印本内容为 arXiv non-exclusive distribution license；稳定论文，仅引用 | adopt predict/log/learn 分离、版本化策略和可回放架构 |
| Saito et al., [Open Bandit Dataset and Pipeline](https://arxiv.org/abs/2008.07146v5) | arXiv v5，2021；NeurIPS Datasets & Benchmarks | 预印本为 arXiv non-exclusive distribution license；配套代码 Apache-2.0 | adopt 可复现实验/OPE 比较流程，不直接外推电商数据结果到 QQ Router |

Star 数没有参与选型。VW 获得生产候选资格，是因为它原生表达 action-dependent features、
exploration probability 和在线更新；OBP 被限制在研究环境，是因为其 OPE 覆盖较好但仓库与 PyPI
已经出现版本漂移且依赖较重。

研究 Spike 的制品已冻结为 VW 9.11.2 sdist SHA-256
`c0ecf8d773c0174a9ab7b0f9207a2608c894bc2fbec50380ca276e89553fd379` 和 OBP 0.5.7 sdist
SHA-256 `3060d67fedfcfadf1e7a6f2608987f74412b5eb74d2c567edeb147595c68f2a0`。正式实验还必须冻结
VW 完整 options、feature hash seed、PRNG seed、feedback 应用顺序和 checkpoint digest；仓库 HEAD
不作为可替换的安装来源。

## 3. 唯一允许的决策位置

```text
TaskComplexityAssessment
  -> DeterministicTierPolicy
  -> StaticModelRouter hard filters
       role / tier / privacy / residency / retention / capability
       context / output / reasoning / deadline / budget
       health / freshness / traffic / atomic capacity
  -> eligible same-role + same-tier endpoints
  -> optional Bandit ranker
  -> sample action + atomic admission
       admission fail: close as NOT_EXECUTED, remove action, make a new logged decision
       admission pass: bind executed action + propensity, then Provider attempt
```

Bandit 返回集合外 action、改变 tier、放宽隐私、复活 unhealthy Endpoint 或绕过 admission 时，整个
决策无效并回退静态优先级。候选少于两个时不创建 Bandit decision。

明确禁止：

- `SEND/SKIP`、probe/follow-up、目标群/用户、订阅、发送时间或频率；
- SHORT/MEDIUM/LONG AnswerProfile 或 visible budget；
- Intent/Entity 结论、安全政策、Memory Scope、Capability 权限；
- 敏感数据 Provider、高风险 Tool、跨 tier 或跨 role 选择；
- 将群聊沉默、没有点赞、Provider timeout 直接当作用户负奖励。

## 4. 最小日志契约

Decision 必须在 Provider 调用前持久化，至少绑定：

```text
decision_id
occurred_at / decision_point / role / tier
sanitized context feature schema + digest
complete eligible action set + endpoint descriptor digests
behavior policy id/revision/artifact digest
chosen action
chosen propensity
per-action probability distribution (or sufficient reconstructable support)
static baseline action
catalog/policy/load/health snapshot revisions
request/route fingerprints
exploration mode and epsilon/budget
admission receipt + executed endpoint + executed/not-executed disposition
```

禁止记录 prompt、回答正文、QQ ID、群号或可逆的用户特征。Feature 必须在 action 前冻结；不得把
调用后的 latency、成功结果或 reward 泄漏进 context。需要按群/会话聚类评估时，只使用在受控
评估环境中由独立密钥生成的不可逆 `evaluation_cluster_id`；该值不得用于在线决策，也不得反推裸 ID。

采样 Endpoint 与实际执行 Endpoint 必须相同，propensity 才可用于该次 action。容量 admission 失败
后不得把静态 fallback Endpoint 填进原 decision；应把原 decision 记为 `NOT_EXECUTED`，从候选集中
移除失败项，并在调用 Provider 前生成一份新的候选分布、decision 和 propensity。Provider 失败后的
failover 同样是新的 attempt decision。第一版 OPE 只使用具有明确 executed action 的 decision，
并单独报告未执行率；不能通过丢弃容量失败样本掩盖与 context 相关的选择偏差。

Feedback 通过 `decision_id` 延迟关联，区分：

- 自动可观测：调用成功、协议/Schema 验证、deadline、延迟、Token、成本、fallback；
- 显式质量：任务回执、`/rate` 或获准的人工盲评；
- censored/unknown：无显式反馈、群聊沉默、窗口过期；
- invalid：重复、越窗、policy/reward revision 不匹配或 action 不是实际执行项。

Reward Policy 必须版本化，质量、任务成功、成本和延迟分别保留原始分量，再计算组合奖励。禁止
只保存一个不可解释的浮点数，也禁止事后改变权重后继续与旧实验比较。

## 5. Propensity、Support 与 OPE

### 5.1 不可省略的条件

IPS/SNIPS/DR 都要求 behavior policy 对 evaluation policy 可能选择的 action 有 support，并需要
正确的 action propensity。确定性静态 Router 对未选择 Endpoint 的 propensity 为 0，因此其普通
历史日志不能用于比较“如果选择另一个 Endpoint”。DR 可以降低方差/模型误差，不能创造 support。

每份 OPE 报告必须同时给出：

- support coverage 和被排除的 context/action strata；
- propensity 分布、最小值、最大 importance weight 和 clipping sensitivity；
- IPS、SNIPS、DR 点估计及预注册置信区间；
- effective sample size（ESS）；
- 按受保护的 `evaluation_cluster_id`、conversation 和 time cluster 的 bootstrap；
- 与 static baseline 的质量、任务成功、P50/P95 延迟、Token/成本和失败率分量；
- 数据窗口、reward completeness、censoring、policy/artifact revision。

DR 还必须记录 outcome model 的 feature schema、训练数据窗口、artifact digest 和校准证据，并用
out-of-fold prediction/cross-fitting 避免在同一反馈上训练又评估。缺失或 censored reward 不能当作
0；报告已知反馈覆盖率、分层缺失率和敏感性分析，在缺失机制无法辩护时不发布 policy value 结论。

只报告一个 OPE 均值或只挑最有利 estimator 属于失败。

### 5.2 可复现实验

**阶段 A：合成 Golden**

构造已知 ground-truth reward 的小环境，覆盖 2–5 个动态 action、context drift、delayed reward、
缺失反馈、极小 propensity 和 support violation。固定 seed，验证 IPS/SNIPS/DR 的实现、偏差趋势、
ESS 和拒绝规则。OBP 只在隔离 research environment 复核结果，不加入主仓运行依赖。

**阶段 B：真实 Router Shadow**

至少两个 Endpoint 先独立通过相同 Provider conformance。Bandit 仅计算建议，不改变静态 action，
验证候选集合、feature digest、策略 artifact、延迟和 deterministic replay。由于 action 仍确定性，
该阶段只能验证日志和策略一致性，不能声称 OPE 质量提升。

**阶段 C：以后单独授权的支持数据**

在同 role+tier、安全等价 Endpoint 中预注册极小 exploration budget，记录非零 propensity；任何安全
Gate、SLO floor、成本上限或 artifact 校验失败立即回退 static baseline。当前 Goal 和 S20A 都不
执行这一步。

## 6. 失败条件

- 候选不满足同 role+tier 或任一 hard filter；
- decision log 在 action 后写入，或缺 candidate set、propensity、policy/artifact digest；
- 采样 action 与 admission 后实际执行 Endpoint 不同，却仍复用原 propensity；
- chosen propensity 非有限正数、概率和不为 1，或 evaluation policy 超出 support；
- 合成环境中 estimator 未能在预注册误差/覆盖范围内恢复已知 policy value；
- IPS/SNIPS/DR 结论方向不一致却没有诊断，ESS 太低或权重由极少样本主导；
- reward 含沉默、未授权正文、跨窗口反馈或事后修改的权重；
- DR outcome model 未版本化、未做 out-of-fold/cross-fitting，或 censored reward 被填成 0；
- Shadow 改变真实路由、增加模型调用或使 Router P95 超过预注册预算；
- artifact 不可重放、无法回滚，或任一安全 Gate 违规。

数值阈值必须在合成/pilot 阶段基于流量和方差预注册，不能在正式评估后挑选。

## 7. 集成优先级

| 工作 | 结论 | 前置 |
| --- | --- | --- |
| Bandit DTO、validator、static baseline、合成 OPE golden | P2 / S20A 可开发 | 先完成 production Router 纵向链 |
| VW ADF Worker Adapter Spike | spike | 至少两个合法同 role+tier Endpoint |
| OBP research container 交叉验证 | spike | 冻结日志与 reward schema |
| Shadow recommendation | defer | before-action 日志完整、无额外模型调用 |
| Conservative live exploration | S20B/S23 后置 | support 计划、显式授权、SLO/回滚和用户数据 |
| 主动消息、AnswerProfile、跨 Tier Bandit | reject | 永不进入当前 Bandit 决策边界 |

用户后续需要补充的是脱敏显式反馈定义、Endpoint 真实价格/限额/retention 和可用于人工盲评的样本；
现在不需要提供 QQ 凭据或群号。没有这些数据只阻塞 S20B，不阻塞 Static Router、MCP、Memory、
ResponsePlan 或主动消息的确定性本地开发。
