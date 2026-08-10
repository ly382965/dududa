# 在线学习与 Contextual Bandit 设计

状态：S20 Offline Bandit 分支已进入 Tree 但尚未开始；当前没有 decision/feedback/OPE 实现，
也没有 Shadow、训练器或在线学习器。

## 1. 适用边界

Contextual Bandit 适合在**已经通过确定性硬约束的有限候选集合**中优化质量、延迟和成本，
不拥有权限、隐私、Schema、预算或副作用决策。

| Decision point | 允许用途 | 第一阶段策略 |
| --- | --- | --- |
| Model Route | 在同角色的合法 Endpoint 中选择模型 | 推荐；先 shadow，再 conservative canary |
| Capability/MCP | 对语义等价且均已授权的候选重排 | P2；不能暴露或授权新 Tool |
| Prompt | 在已评审、版本化、同安全语义的模板中选择 | P2；禁止生成任意 Prompt |
| Search/No Search | 低风险、允许联网且两种动作都能安全回答时选择 | P2；实时性/来源硬要求优先 |
| Persona Style | 在 Persona 与用户显式偏好允许的 style variant 中选择 | P2；不能改事实、拒绝或目标 |
| Recommendation | 在独立推荐边界中优化排序 | 可用，但需单独的曝光与反馈契约 |
| Reply/Ignore | 只做离线或 shadow 研究 | 默认禁止 live exploration，避免用群聊成员承担试验成本 |
| Answer Profile | 不作为首版 Bandit 决策点 | `SHORT/MEDIUM/LONG` 由确定性策略选择，显式用户要求与硬上限优先 |
| Proactive Send/Skip | 禁止作为 Bandit 决策点 | 目标、订阅、日程、频率、probe/follow-up 均保持确定性，禁止 live/shadow 候选取得发送权 |

高风险/不可逆 Tool、敏感数据 Provider、权限结果、Memory Scope、Confirmation、Content
Safety 和 Output 目标不进入探索。硬约束失败时返回确定性 baseline；Bandit 不能通过高奖励
抵消任何安全违规。

主动日报/探测即使进入最终 canary，Bandit 也不能选择是否发送、发送给谁、何时发送、推送
主题、Answer Profile、频率或无人响应后的动作。模型路由 Bandit 可以把 trigger/profile 当作
低基数上下文特征，但只能在已经固定 Role+Tier 且通过全部主动策略硬门禁的 Endpoint 中选择。

## 2. 决策契约

```python
class BanditDecisionPoint(StrEnum):
    MODEL_ROUTE = "model_route"
    CAPABILITY_RERANK = "capability_rerank"
    PROMPT_VARIANT = "prompt_variant"
    SEARCH_POLICY = "search_policy"
    PERSONA_STYLE = "persona_style"
    RECOMMENDATION = "recommendation"

class BanditMode(StrEnum):
    BASELINE = "baseline"
    EXPLOIT = "exploit"
    EXPLORE = "explore"
    SHADOW = "shadow"

@dataclass(frozen=True, slots=True)
class BanditFeature:
    feature_id: str
    value: bool | int | Decimal | str
    feature_revision: str
    sensitivity: Sensitivity

@dataclass(frozen=True, slots=True)
class BanditAction:
    action_id: str
    action_revision: ComponentRevision
    estimated_cost: Decimal | None
    estimated_latency_ms: int | None
    risk_level: RiskLevel
    payload_ref: ResourceRef

@dataclass(frozen=True, slots=True)
class ExplorationBudget:
    maximum_probability: Decimal
    remaining_exposures: int
    baseline_floor: Decimal
    budget_revision: str

@dataclass(frozen=True, slots=True)
class BanditDecisionRequest:
    schema_version: int
    decision_id: str
    experiment_id: str
    analysis_cluster_key: str
    randomization_unit_key: str
    request_digest: DigestString
    decision_point: BanditDecisionPoint
    context_features: tuple[BanditFeature, ...]
    eligible_actions: tuple[BanditAction, ...]
    baseline_action_id: str
    hard_constraint_digest: DigestString
    exploration_budget: ExplorationBudget
    as_of: datetime

@dataclass(frozen=True, slots=True)
class BanditDecision:
    schema_version: int
    decision_id: str
    request_digest: DigestString
    action_set_digest: DigestString
    recommended_action_id: str
    action_to_execute_id: str
    action_to_execute_revision: ComponentRevision
    propensity: Decimal
    behavior_action_probabilities: Mapping[str, Decimal]
    candidate_action_probabilities: Mapping[str, Decimal] | None
    mode: BanditMode
    policy_revision: ComponentRevision
    feature_schema_revision: str
    reward_policy_revision: str
    sampling_value: Decimal | None
    sampler_revision: str
    decided_at: datetime

class ContextualBanditPolicy(Protocol):
    async def choose(
        self,
        request: BanditDecisionRequest,
        *,
        call: PortCallContext,
    ) -> BanditDecision: ...
```

`eligible_actions` 只能由 Model Router、Capability Retriever 或其他 owning module 在完成全部
硬过滤后构造。Policy 必须验证 action set/request digest、baseline 存在、推荐与待执行动作均
在集合内、propensity 在 `(0, 1]` 且整个分布和为 1。`propensity` 必须等于 behavior policy 对
`action_to_execute_id` 的概率；这是 IPS/DR 的分母，不能误填成候选 Policy 的概率。

`SHADOW` 中 `recommended_action_id` 是候选 Policy 的建议，`action_to_execute_id` 必须是
baseline；此时 behavior distribution 对 baseline 的概率为 1，候选分布另存于
`candidate_action_probabilities`。`BASELINE/EXPLOIT/EXPLORE` 中推荐与待执行动作相同。Router
只能执行 `action_to_execute_id`，并在反馈中回报实际执行动作。`sampling_value` 与
`sampler_revision` 保存可审计的随机抽样证据；不得依赖无法重放的进程全局 RNG。

Context 只使用版本化、最小化、可解释特征，例如任务类别、长度 bucket、是否需要实时信息、
会话类型和预算 bucket；不得使用原始正文、真实 QQ/群 ID、敏感实体或可反推个人身份的高基数
键。`analysis_cluster_key` 和 `randomization_unit_key` 使用 experiment-scoped、定期轮换密钥
生成的不可逆伪名，只能用于群级估计和随机化，不能跨实验关联身份。

## 3. 决策日志与延迟反馈

```python
@dataclass(frozen=True, slots=True)
class BanditDecisionLogReceipt:
    schema_version: int
    decision_id: str
    request_digest: DigestString
    decision_digest: DigestString
    action_set_digest: DigestString
    persisted: bool
    logger_revision: ComponentRevision
    recorded_at: datetime

class BanditDecisionLog(Protocol):
    async def record_before_action(
        self,
        request: BanditDecisionRequest,
        decision: BanditDecision,
        *,
        call: PortCallContext,
    ) -> BanditDecisionLogReceipt: ...

class FeedbackObservationStatus(StrEnum):
    OBSERVED = "observed"
    PARTIAL = "partial"
    CENSORED = "censored"
    PENDING = "pending"

@dataclass(frozen=True, slots=True)
class RewardComponent:
    metric_id: str
    value: Decimal | None
    observed: bool
    source: str
    metric_revision: str

@dataclass(frozen=True, slots=True)
class BanditFeedback:
    schema_version: int
    feedback_id: str
    decision_id: str
    decision_digest: DigestString
    executed_action_id: str
    components: tuple[RewardComponent, ...]
    status: FeedbackObservationStatus
    attribution_window: timedelta
    observed_at: datetime
    feedback_digest: DigestString

class BanditFeedbackSink(Protocol):
    async def record(
        self,
        feedback: BanditFeedback,
        *,
        call: ServiceCallContext,
    ) -> FeedbackReceipt: ...

@dataclass(frozen=True, slots=True)
class FeedbackReceipt:
    schema_version: int
    feedback_id: str
    feedback_digest: DigestString
    disposition: Literal["recorded", "duplicate", "rejected"]
    sink_revision: ComponentRevision
    recorded_at: datetime
```

探索动作必须在执行前可靠记录 request、decision、完整 action set、behavior propensity、候选
分布和 Policy/Feature/Reward revision。Logger 重算 request/action-set/decision digest，并验证
receipt 与输入一致；日志失败时只能执行确定性 baseline，不能产生无法用于反事实评估的“隐形
探索”。实际执行动作若与 `action_to_execute_id` 不同，反馈必须拒绝归因并产生审计告警。
未收到点赞、追问或点击是 missing/censored feedback，不自动等于负奖励。任务成功、用户显式
反馈、延迟、Token/费用、重试和投递状态作为独立 reward components 保存；标量化权重属于
版本化 `RewardPolicy`，离线训练时应用。权限、隐私、事实保持和重复副作用是独立硬 Gate，
永远不进入可相互抵消的奖励和。

可把用户给出的公式作为一个预注册 RewardPolicy 示例：

```text
reward = alpha * explicit_satisfaction
       + delta * task_success
       - beta  * normalized_latency
       - gamma * normalized_token_cost
```

各分量先固定方向、量纲、截断范围、缺失处理和归因窗口；权重只在离线版本中调整。群聊中的
沉默、下一条无关消息或 Bot 自己生成的“成功”文本不能充当满意度。安全、权限、隐私、事实
和重复副作用不进入该公式，任何一项违规都直接使实验 Gate 失败。

## 4. Policy Snapshot 与更新

```python
@dataclass(frozen=True, slots=True)
class RewardTerm:
    metric_id: str
    weight: Decimal
    direction: Literal["higher", "lower"]
    minimum_value: Decimal
    maximum_value: Decimal
    missing_policy: Literal["censored", "ignore", "reject_feedback"]

@dataclass(frozen=True, slots=True)
class RewardPolicy:
    schema_version: int
    reward_policy_id: str
    revision: str
    terms: tuple[RewardTerm, ...]
    attribution_window: timedelta

@dataclass(frozen=True, slots=True)
class BanditPolicyDefinition:
    schema_version: int
    policy_id: str
    decision_point: BanditDecisionPoint
    algorithm: Literal["static", "linucb", "thompson_sampling"]
    artifact_revision: ComponentRevision
    baseline_action_id: str
    maximum_exploration_probability: Decimal
    minimum_baseline_floor: Decimal
    enabled: bool

@dataclass(frozen=True, slots=True)
class BanditPolicySnapshot:
    schema_version: int
    snapshot_id: str
    policies: tuple[BanditPolicyDefinition, ...]
    reward_policies: tuple[RewardPolicy, ...]
    feature_schema_revision: str
    reward_policy_revision: str
    snapshot_revision: str

@dataclass(frozen=True, slots=True)
class BanditPolicyUpdate:
    schema_version: int
    expected_revision: str
    policies: tuple[BanditPolicyDefinition, ...]
    reward_policies: tuple[RewardPolicy, ...]
    feature_schema: SchemaRef

class BanditPolicyRegistry(Protocol):
    def acquire_snapshot(self) -> BanditPolicySnapshot: ...

class BanditPolicyPublisher(Protocol):
    async def publish(
        self,
        update: BanditPolicyUpdate,
        *,
        call: ServiceCallContext,
    ) -> str: ...
```

在线请求只读取 immutable snapshot。训练、参数更新和 drift 检测在 Service Worker 中完成，
一次校验后原子发布；失败保留 last-known-good。第一版使用可解释的 LinUCB 或 Thompson
Sampling baseline；只有离线证据证明需要时才引入更复杂的 neural bandit。Action/Feature
Schema 或奖励归因变化必须创建新 experiment lineage，不能把不可比数据直接累计。
冷启动使用静态 baseline、离线先验和保守探索，不为“快速收集数据”放宽边界。按时间监测
action coverage、reward/feature drift 与 calibration；漂移超阈值回 baseline 并重新评估。
同一群/会话内动作可能改变后续上下文，训练与评测必须按 cluster 处理这种 interference。

## 5. 保守探索与评测门禁

1. 先完成 hard eligibility，再由 Bandit 排序；空集合走 owning module 的确定性降级。
2. `SENSITIVE/RESTRICTED`、高风险或不可逆动作默认 exploration probability 为 0。
3. 每个 decision point、Scope 和时间窗有独立 ExplorationBudget；baseline 质量下界不可突破。
4. 先用合成已知策略/replay 验证 estimator，再 shadow（记录但不影响动作），再小流量 canary；
   每级都可独立回滚。Shadow 只验证接口、候选覆盖、延迟和策略建议，不能证明未执行动作的
   效果；确定性 baseline 对其他动作没有 positivity/support。
5. 只对历史受控探索或安全 canary 产生的、具有 propensity/support 的日志做离线策略评估；
   至少同时报告 IPS、SNIPS、Doubly Robust、有效样本量、最大 importance weight、覆盖率和
   与 baseline 的 paired effect。
6. 群聊反馈按 conversation/group 做 cluster 或 hierarchical bootstrap；不能把同群消息当
   独立样本。延迟/删失反馈分别报告，不做零填充。
7. 上线前冻结 primary endpoint、最小效果量、95% CI、探索上限、guardrail risk bound、
   sequential testing/多重比较方法和停止规则，禁止看到结果后修改。
8. 任一权限/隐私/事实/重复副作用 Gate 违规立即停止实验；“总奖励更高”不能保留该 Policy。

## 6. 必需测试

- action set 只含硬过滤通过项，Bandit 不能返回集合外动作；
- behavior/candidate propensity 分布、抽样证据、snapshot/reward revision 和 before-action 日志可复现；
- shadow 推荐与实际 baseline 执行严格分离，feedback 只归因给实际执行动作；
- 日志失败、Policy 不可用、action 漂移或预算耗尽稳定回退 baseline；
- 高风险、敏感数据和无授权搜索的 exploration probability 恒为 0；
- `SEND/SKIP`、主动目标、订阅/日程/频率、Answer Profile 和 probe/follow-up 不存在可执行
  Bandit action；伪造这些 decision point 的请求整体拒绝；
- delayed/partial/censored feedback 不被误记为零；重复 feedback 幂等；
- IPS/SNIPS/DR 使用合成已知策略进行 estimator bias/coverage 测试；
- group-level bootstrap、drift、回滚和 last-known-good 发布测试；
- 原始消息、真实用户/群 ID、Credential 和附件正文不进入 feature/decision/feedback 日志。
