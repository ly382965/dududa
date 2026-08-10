# Branch Spec

Branch: proactive-contracts
Parent: proactive-outbound

## Development Design

### 1. 目标与完成边界

S15A 冻结主动出站的框架无关契约，并实现一个完全离线、默认拒绝的确定性控制层。它证明
Target Policy、Grant、Scope、revision、时间窗、频控、kill switch、Preview 隔离、稳定业务幂等
和恢复复用 `PreparedDispatch` 的语义；不实现 Scheduler、真实来源、模型合成或真实发送。

入站 `AgentRuntime` 不改动。后台入口只接受 `InitiatedRunRequest`，不得伪造 Connector 消息、
用户 Actor 或 mention。Preview 使用独立 `ProactivePreviewPort` 和
`proactive.subscription.preview` 动作，不能进入投递状态机。

### 2. 所有权与依赖方向

新增 `dududa.proactive`，拥有主动出站 DTO、canonical digest、配置、Target/Grant Registry、
确定性 eligibility/revalidation、Prepared Dispatch ledger 和离线 Fakes。新增
`dududa.ports.proactive`，只定义 Clock、Registry、Store、authorization/limiter/audit/kill-switch、
Preview 与 Delivery Orchestrator Protocol。

```text
trusted scheduler/opportunity producer (future S15B/S15E)
  -> ProactiveTrigger + exact TargetPolicyRef
  -> InitiatedRunRequest
  -> deterministic initiation gate
  -> future source/composition stages
  -> deterministic pre-dispatch revalidation
  -> PreparedDispatch + stable business key
  -> future OutputAdapter
```

Core 不 import AstrBot、MCP SDK、APScheduler、Provider SDK 或插件目录。MCP、模型和 Persona 不
拥有目标、授权、时间、预算、幂等或发送决定。现有 S01-S15 Runtime、Router、TierPolicy、
ResponsePlan 和 Delivery 契约不重新设计。

### 3. 版本化契约

首版冻结以下不可变 `schema_version=1` 契约：

- 枚举：Trigger kind、Run mode、Subscription/Target status、Grant kind、Source category；
- 授权与目标：`ProactiveAuthorizationGrant[Ref]`、`ProactiveTargetPolicy[Ref]`；
- 输入事实：`ScheduleSpec`、`ProactiveSubscription`、`ScheduleOccurrence`、
  `ConversationOpportunitySnapshot`、`ProactiveTrigger`；
- 运行与预览：`InitiatedRunRequest`、`ProactivePreviewRequest/Result`；
- 后续阶段边界：`SourceItem/SourceBatch`、`ProactivePolicyDecision`、`PreparedDispatch`、
  `DispatchClaim`、`ProactiveRunReceipt`。

构造器严格验证类型、非空值、aware UTC 时间、正数上限、排序/去重集合、one-of 和时间顺序。
所有关键对象有独立 domain-tagged canonical digest；digest 覆盖除自身外的全部语义字段。
`ProactiveTrigger` 的 occurrence/opportunity 严格 one-of 且必须匹配 kind、Scope、TargetPolicy Ref
和有效期。Run/Subscription/Snapshot/Trigger 之间的 Ref 必须 canonical-equal。

### 4. Target Policy 与 Grant 解析

`ProactiveTargetRegistry` 分别保存 immutable generation 中的 Grant 与 Target Policy；发布先完整
验证再原子替换，读取返回精确 revision。Target Ref 不是授权缓存。每次启动和准备发送都重新
解析，并验证：

- Policy ID/revision/digest、exact Scope digest、ACTIVE 状态、expiry 和 trigger kind；
- operator grant 只能是 `OPERATOR_ENABLE_TARGET`，group grant 只能是
  `GROUP_POLICY_ENABLE`，订阅 grant 只能是 `SUBSCRIPTION_OWNER`；
- Grant ID/revision/digest、`message.send.proactive` action、Scope、policy revision、trigger/
  category allowlist、expiry/revocation 和 authorization decision digest；
- 当前实时 `AuthorizationDecision` 仍为 ALLOW，且绑定相同 Actor/Scope/action/request digest。

缺失、角色替换、revision/digest 漂移或 Registry 不可用一律拒绝，不能凭字符串 ID 降级。

### 5. 默认拒绝控制

`ProactiveControlConfig` 对 Digest 和 Probe 分别配置 mode、Scope digest allowlist、quiet hours、
全局/Scope 频控、kill switch 和 policy revision。默认配置为 OFF、空 allowlist、kill switch on。
空 allowlist 永远表示无人获准。只有 `CANARY` 才可能形成可发送的 Prepared Dispatch；
OFF/COLLECT/SHADOW 只能得到无投递 receipt，PREVIEW 在 delivery 入口类型上被拒绝。

确定性 Gate 按顺序检查：契约/digest -> mode -> allowlist -> kill switch -> Target/Grant ->
Subscription/Trigger freshness -> quiet hours -> authorization -> limiter/audit。任一依赖错误或证据
缺失都返回稳定 reason code 且不调用后续副作用端口。`ServiceCallContext` 仅证明服务调用身份，
不能替代目标或订阅授权。

### 6. Preview 隔离

Preview request 必须携带完整请求 Actor、exact Scope、TargetPolicy Ref 与完整 request digest，
并对独立动作 `proactive.subscription.preview` 实时授权。Preview 不创建 occurrence、trigger claim、
PreparedDispatch、DeliveryRequest 或 DeliveryReceipt，也不调用主动 Output Port。Result 绑定输入、
authorization、response/source digest；正文只存在于同步返回值，Fake Store 只记录脱敏 metadata。

S15A 使用无模型的固定 validated-response fixture 证明接口和零投递。真正的来源读取和内容合成
属于 S15C/S15D。

### 7. Prepared Dispatch 与恢复

业务幂等键固定为：trigger kind + 已持久化 occurrence/opportunity digest + exact target Scope +
item-set-or-none + validated-response digest。它明确排除 worker、claim、attempt、delivery ID、时间戳
和 Adapter/binding revision。`NegotiatedBindingReceipt` 单独保存在 Prepared Dispatch 并独立验证。

`ProactiveDispatchStore.prepare()` 使用 trigger 作为稳定 ownership key：第一次原子写入；完全相同
请求返回既有对象；同 Trigger 的不同内容、Scope、Target Ref 或 key 产生 conflict。已有 prepared、
attempted 或 UNKNOWN 记录恢复时只能复用原 Prepared Dispatch 和业务键，不能重新合成。S15A 只
实现内存 Fake 和 Contract；持久 CAS/lease、multipart reconciliation 在 S15B/S15D/S16 接续。

### 8. Fakes 与兼容边界

提供可注入 `FakeClock`、InMemory Target Registry、InMemory Dispatch Store、Recording Preview
Store 和 `FakeProactiveOutput`。Fake Output 只接受显式测试调用并记录计数，不连接任何平台。
默认/off、Shadow 与 Preview 测试对象图不持有 Output。所有 fixture 使用合成 ID/Scope/内容。

现有响应式 `message.respond`/`message.send` 不自动获得 `message.send.proactive`。所有新增字段和
Port 为 additive；本分支不修改现有 Output Adapter 或生产 composition root。回滚可删除 S15A
composition/export，已存在的入站对象仍可读取。

### 9. 验证范围

Unit/Contract 覆盖所有 DTO/digest、one-of、Scope/ref/grant replacement、过期/撤销、默认 off、
空 allowlist、quiet hours、全局/Scope 限流、kill switch、Preview 独立授权和零投递、Prepared
Dispatch CAS/idempotency、Adapter revision 稳定性与恢复冲突。Import boundary 证明 Core 无外部
框架依赖。双 Python 全仓、warning-as-error 聚焦、build/lock/compile/secret/whitespace 和必要 Web
回归在完成前运行。

本分支不声明真实来源、真实模型质量、真实 Scheduler 耐久性、生产授权或 QQ 发送已完成。
