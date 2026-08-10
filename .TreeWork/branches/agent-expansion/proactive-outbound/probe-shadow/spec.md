# Branch Spec

Branch: probe-shadow
Parent: proactive-outbound

## Development Design

### 1. 目标与边界

S15E 用合成、脱敏的群活动投影完成确定性 Conversation Probe Shadow。它只接受群级公共话题，
产生短 TTL `ConversationOpportunitySnapshot`、绑定的 `ProactiveTrigger/InitiatedRunRequest` 和固定
SHORT 候选；支持 `COLLECT` 与 no-send `SHADOW`，默认关闭，不进入 `CANARY`。

输入不是 `MessageEnvelope` 或聊天正文集合，而是版本化 `ProbeConversationWindow`：精确 Scope、
TargetPolicyRef、opaque topic refs、有界公共 topic summary、最近人类/Bot 活动时间、Sensitivity、
显式 hard blockers 和 projection revision。Runtime 不读取个人 Memory、不调用模型/Tool/Capability，
不创建 Output/Dispatch/Scheduler claim，也不产生或调度自动追问。

### 2. Policy、Detector 与硬 Gate

新增 digest-bound `ProbePolicySnapshot`，绑定最小静默、最大话题年龄、Opportunity TTL、近期 Bot
冷却、普通 Shadow 冷却、no-response 长冷却、SHORT limits、Response/Persona snapshot 和组件
revision。首版 Detector 是可复现的 B2 baseline：先拒绝非群/非 PUBLIC、active dialogue、directed
question、conflict/safety、个人目标、个人 Memory 需求、pending delivery、unresolved probe、过短
静默、近期 Bot 发言和过期话题；不做模型软打分，不把更久沉默解释成更高发送意愿。

Runtime 在 Detector 前检查独立 probe control、mode、kill switch、非空 exact Scope allowlist、quiet
hours、调用期限和当前 Target/Grant；任一失败均不构造 Opportunity。Snapshot、Trigger 和 Run 的
Scope/TargetPolicyRef canonical-equal，Trigger expiry 不超过 Snapshot expiry。

### 3. 状态、重复与反馈

新增 `ProbeStateStore` Port 和原子内存参考实现。状态按显式 namespace + Scope 保存 revision、最近
Opportunity digest、active-until、cooldown-until 和最后反馈；`claim` 原子完成重复/cooldown 判断与
写入。S15E Runtime 固定使用 `shadow:<policy-snapshot>` namespace，不能污染未来 live ledger。

`NO_OBSERVED_RESPONSE` 是外部观察事实，只通过显式 `record_outcome` 进入更长冷却；它不被解释为
负奖励，也不会创建新 Trigger。`ENGAGED` 只关闭 active 状态并保留普通冷却。S15E 不实现反馈
采集 Adapter，测试只用合成 observation 验证边界。

### 4. SHORT 候选与 no-send 记录

`DeterministicProbeComposer` 把 Opportunity 投影为一个公共话题 block；`ProbeCandidateBuilder`
构造独立 SHORT `ResponsePlan`，复用 Persona Renderer 和最终 Validator，并再次拒绝 @/CQ mention、
target users、附件或多 block 漂移。普通 `ProbeShadowMetadata` 只保存 window/opportunity/trigger/run/
plan/candidate/persona/state digest、disposition 和 reason codes，不保存 topic summary 或正文。

`COLLECT` 到 Opportunity/claim 为止，零 Composer；`SHADOW` 可构造候选但对象图无 Output、Dispatch、
Scheduler、Memory、Tool、Capability 或 model。重复、过期、冷却和 hard-gate 拒绝都只形成 no-send
metadata。

### 5. 抽样验证

验证限制为六类代表样本：

1. 公共群窗口生成 exact-bound Opportunity/Trigger/Run 和单 block SHORT 候选；
2. Scope/Sensitivity/个人目标/个人 Memory hard-gate matrix；
3. active dialogue/directed question/conflict/safety/近期 Bot/pending 状态在 Composer 前停止；
4. TTL 边界到期后永不因更久静默复活；
5. duplicate、普通 cooldown 和 `NO_OBSERVED_RESPONSE` 长冷却边界；
6. 第 1/2/30 天抽样保持零 Output、零 follow-up、metadata 无正文。

只运行双 Python focused warning-as-error、受影响 import/static/build/secret/whitespace。Web 未改则
跳过；全仓双 Python 留到 S19/最终总集成。真实相关性、打扰度和真实群反馈仍是外部门禁。
