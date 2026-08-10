# Branch Spec

Branch: digest-shadow
Parent: proactive-outbound

## Development Design

### 1. 目标与边界

S15D 把 S15B 的 scheduled Trigger、S15C 的 fixture-backed `SourceProvider` 和 S15 的
`ResponsePlan`/Persona/最终 Validator 串成确定性日报候选链。它只支持 `COLLECT`、no-send
`SHADOW` 和已有独立授权 `PREVIEW`；不创建 `PreparedDispatch`，不依赖 `OutputAdapter`，不
ack Scheduler claim，不接模型、网络、Memory 或真实来源。

`COLLECT` 只记录 Trigger metadata，零 Source 调用。`SHADOW` 可以读取合成 fixture、构造并
验证候选，但只持久化不含正文的 metadata。`PREVIEW` 由现有
`IsolatedProactivePreviewService` 先授权，再调用本分支 Producer 同步返回正文；普通 metadata
仍不保存正文。`OFF`、kill switch、配置不匹配和 `CANARY` 在 Source 调用前拒绝。

### 2. 配置与结果契约

新增 digest-bound `DigestCompositionPolicySnapshot`，精确绑定 snapshot ID、Source Policy
ID/revision/digest、排序后的 source IDs、Response Policy revision、Persona Catalog
snapshot/digest、Persona ID/version、SHORT/MEDIUM limits 和组件 revision。日报最大档位固定为
MEDIUM；订阅 LONG 会显式收窄而不是映射模型 Tier。

新增 `DigestShadowMetadata`，只记录 run/origin/subscription、Source Fetch/Batch、item set、
ResponsePlan、候选响应、Persona 和 disposition digest 及 reason codes，不保存 Source body、
标题、摘要或最终正文。`ProactiveRunReceipt` 继续作为 COLLECT/SHADOW 标准运行结果，不修改
S15A v1。

### 3. 组合链与分权

- `DeterministicDigestComposer` 只把已规范化 Batch 投影为 `DraftResponse`；每个 SourceItem
  保留 title/summary/published_at、FactAnchor、Citation 和 source digest，不生成新事实/URL。
- `DigestCandidateBuilder` 生成 typed Source Fetch origin、独立 ResponsePlan、解析固定 Persona、
  调用 Renderer 和最终 Render/Profile/Content Validator；模型不参与。
- `DigestShadowRuntime` 负责 mode/config/subscription/target binding、Source 调用、metadata 和
  `ProactiveRunReceipt`，对象图禁止 Output/Dispatch/Scheduler ack。
- `DigestPreviewProducer` 复用 Candidate Builder，但使用
  `preview:<preview_id>:<subscription_id>` state namespace，不能消费正式日报 cursor/item ledger。
- 新 Port 仅为 `DigestComposer`、`DigestShadowMetadataSink` 和 `DigestShadowRunner`；现有
  Source/Subscription/Actor/Persona/Renderer/Validator Port 直接复用。

### 4. 状态与失败语义

`SUCCEEDED/PARTIAL` 且至少一个新 item 才构造候选；`NO_NEW_ITEMS` 为成功 no-op；全部失败、
取消、Schema/Validator/Persona 错误产生 FAILED metadata，均不返回或持久化正文。PARTIAL
候选必须保留失败来源 warning。重复 item 不再次产生候选。

SHADOW 的 item dedup 使用正式 subscription namespace；Preview 使用隔离 namespace。S15D 不
拥有 Scheduler occurrence/claim 状态，也不把“候选已构造”解释为已发送或可发送。

### 5. 抽样验证

采用六类高价值样本，不重复全仓：

1. LONG -> MEDIUM plan、Fact/Citation/Persona/长度完整链；
2. COLLECT/OFF/kill-switch/CANARY 均在 Source 前停止；
3. SHADOW 成功只写 metadata，依赖图无 Output/Dispatch/Memory/模型；
4. PARTIAL、NO_NEW、FAILED、CANCELLED 的代表样本；
5. PREVIEW namespace 与正式 dedup 隔离；
6. fake clock 第 1/2/30 天抽样证明重复候选和 Output 调用为 0。

运行双 Python focused warning-as-error、受影响 Contract、Ruff/import/build/secret/whitespace；
Web 未改则不运行，双 Python 全仓留到 S19/最终总集成。真实内容质量与真实发送仍是外部门禁。
