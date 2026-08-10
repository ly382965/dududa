# Branch Spec

Branch: governed-sources
Parent: proactive-outbound

## Development Design

### 1. 目标与完成边界

S15C 在 S15A 的 `SourceItem`、`SourceBatch`、`SourceFailure` 上增加受治理来源调用侧契约，
并使用本地固定校园/arXiv/行业 fixture 证明 Source-neutral 扩展路径。它不访问网络、不创建真实
MCP Server/Adapter、不调用 Scheduler/模型/Composer/Memory/Output，也不修改 iCourse。

本分支完成后只能声明“来源框架与 fixture contract 完成”；真实来源、实时新鲜度、许可持续
复核和真实内容质量仍是外部门禁。现有 Source DTO 字段和 digest domain 保持不变。

### 2. 契约与身份

新增 immutable/versioned `SourceDefinition`、`SourcePolicySnapshot`、`SourceCursor`、
`SourceProvenance`、`SourceItemIdentity`、`SourceFetchRequest` 和 `SourceFetchReceipt`，各自使用
独立 canonical digest：

- Definition 固定 source ID、类别、只读 Capability ID、host/path allowlist、payload/item 上限、
  最大年龄、是否要求 external ID/发布时间及 revision 通知策略；不允许任意 URL。
- Policy Snapshot 对排序后的全部 Definition 和 policy revision 整体签名；Subscription 继续只
  保存现有 `source_policy_id`，Fetch Request 再绑定精确 snapshot ID/digest。
- Cursor 是有界 opaque token 与 source snapshot revision；它只表示已观察位置，不授予权限。
- Provenance 绑定 source/capability definition/provider result、policy、Schema/result mapping
  revision 和 observation time，不保存原始 Provider body。
- Item Identity 将稳定业务身份与内容 revision 分离。优先 source-specific external identity；
  只有 Definition 明确允许时才使用 canonical URL fallback。
- Fetch Receipt 状态固定为 `SUCCEEDED/PARTIAL/NO_NEW_ITEMS/FAILED/CANCELLED`；只读来源没有
  `UNKNOWN` 副作用状态。

### 3. Port 与分权

新增 framework-neutral Port：

- `SourcePolicyRegistry`：解析精确 snapshot ID/digest；
- `SourceProvider`：接收 digest-bound Fetch Request，返回 Fetch Receipt；
- `SourceCursorStore`：读取并 CAS 当前 cursor；
- `SubscriptionSourceItemLedger`：按 subscription/source/item identity 分类和提交 dedup receipt；
- `SourceCapabilityReader`：只执行 Definition 固定的公开只读 Capability，不接受模型生成的
  capability ID、URL 或任意 Planner step。

`GovernedSourceProvider` 只负责 policy resolve、固定 Capability observation、严格 normalize、
allowlist/freshness/citation/size/injection 校验、dedup 和 batch 状态。未来 MCP 只能通过 S13
Capability 实现 `SourceCapabilityReader`；Source Domain 不 import MCP SDK/Client。

Cursor Store、Subscription Item Ledger 与未来投递账本保持分离。S15C 提供确定性内存参考实现
和 Contract Test，不在本分支增加 SQLite/生产迁移；S15D 只消费 Receipt/Batch。

### 4. 规范化与去重

Fixture observation 使用严格 JSON object：source ID、snapshot revision、next cursor 和 items。
每个 item 只接受 Definition 允许的字段与类型；未知字段、Schema 漂移、截断结果、非 PUBLIC
结果、host/path 越界、凭据 URL、fragment、tracking query、HTML/脚本/Prompt 指令、超长字段、
未来发布时间或缺失必填 identity/time 均 fail closed 为该 source 的 `SourceFailure`。

同 batch 按 stable identity 至多保留一个 item。Ledger disposition 固定为 NEW、DUPLICATE、
REVISION_HELD、REVISION_EMIT；默认 revision 只更新观察状态而不再次进入 batch，只有 Definition
显式 `notify_revisions` 时才产生 revision item。CAS 失败不猜测或覆盖。

只有全部规范化、引用和新鲜度验证通过的 `SourceItem` 可以进入 `SourceBatch`。部分 source 失败
允许返回 PARTIAL；全部失败返回 FAILED 且无 Batch；成功但无新 item 返回 NO_NEW_ITEMS。

### 5. Fixture 与验证

仓库新增带 manifest 的合成校园、arXiv 和行业 JSON fixture；其 URL/ID/文本均为固定测试数据，
不是已存在的真实 Server 或实时来源。Fake Capability Reader 与三个 fixture 通过同一 Contract。

测试覆盖严格 Schema、URL 规范化、allowlist、字段/总 payload 上限、freshness、citation、cursor
CAS、identity/revision、重复抓取、部分/全部失败、timeout/cancel/circuit、Prompt Injection 和
扩展性门禁。增加第四个 Fake Source 只能增加 Definition、fixture 和 binding，不得修改 Core
Domain、Scheduler、通用 Provider 或 MCP Client。

完成前运行双 Python 全仓与 focused warning-as-error、Ruff/format、import、lock、compile、wheel、
secret、whitespace 和必要 Web 回归。本分支不声明真实来源 Adapter、实时数据、生产运行或发送。
