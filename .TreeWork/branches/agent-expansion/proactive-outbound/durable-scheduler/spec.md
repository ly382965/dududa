# Branch Spec

Branch: durable-scheduler
Parent: proactive-outbound

## Development Design

### 1. 目标与完成边界

S15B 在 S15A 的主动契约之上实现一个持久、时钟可注入、双 Worker 可竞争的 Scheduler 与
Subscription lifecycle。它只把有效订阅物化为 `ScheduleOccurrence` 和结构化
`ProactiveTrigger`，并通过 CAS/lease 交付一次；不读取来源、不调用 MCP/模型、不合成正文，
也不持有 Output Adapter。

本分支使用 SQLite 参考实现证明重启与多连接语义。生产组合仍不存在且默认关闭。S15A 的
Target/Grant、Policy、quota、Preview 和 Dispatch 契约不重新设计。

### 2. 新增契约与 Port

新增 immutable/versioned `ScheduleTriggerClaim`、`ScheduleClaimReceipt`、
`SubscriptionMutationReceipt` 和 occurrence state/disposition 枚举，并使用独立 canonical
digest。Claim 完整绑定原 Trigger digest、worker、lease revision、claim/expiry；Receipt 绑定
claim、occurrence、最终 state 和 record revision。

新增框架无关 Port：

- `ProactiveSubscriptionStore`：CAS publish、按 ID 读取、列出当前 ACTIVE snapshot；
- `ProactiveScheduleStore`：原子写入 occurrence/trigger、列出 due、claim/reclaim、ack 和按
  subscription revision 失效；
- `ProactiveScheduler`：materialize 与 claim/ack 的应用边界。

Core 不 import APScheduler、AstrBot、MCP、Provider 或插件目录。APScheduler 以后最多实现时间
oracle，不能成为 claim authority。

### 3. Subscription 持久生命周期

SQLite Store 保存完整 `ProactiveSubscription` typed snapshot 和 mutation receipt：

- create 要求 revision 1 且 `expected_revision=None`；
- update/pause/resume/revoke 要求新 revision 恰为 current+1，并 CAS 匹配 expected revision；
- mutation ID + payload digest 提供稳定幂等；同 ID 不同 payload 或 stale revision 冲突；
- `REVOKED` 是保留的最小 tombstone，不允许恢复；`PAUSED -> ACTIVE` 使用新 revision；
- publish 新 revision 时，旧 revision 尚未 emitted 的 occurrence 在同一事务中失效；
- 无效 schedule/时区在 DTO 边界拒绝，旧 snapshot 保持不变，不能猜测默认时间。

Adapter、命令和 Web 不直接写 SQLite；未来只能调用同一个 Store/Service Port。本分支不新增
管理 UI 或真实 Actor 授权入口。

### 4. 时间、DST 与 misfire

Scheduler 从 injected aware UTC clock 取得 `now`，按订阅 IANA zone 计算候选 local date：

- 每个 `(subscription_id, local_date)` 最多一个 canonical occurrence，跨 revision 也不重复；
- 普通和 ambiguous/fold 时间选择最早 UTC instant，避免重复小时产生两次；
- nonexistent/gap 时间固定 `SKIP_NONEXISTENT` 并持久保留 slot tombstone，不擅自顺延；
- 只扫描 `misfire_grace` 覆盖的有界 local-date 窗口，未来 occurrence 不物化；
- `scheduled_for <= now <= eligible_until` 写入 READY；超过 grace 写入
  `SKIPPED_EXPIRED`；gap slot 写入 `SKIPPED_NONEXISTENT`，两者都不在重启时补发；
- 系统时钟回拨只能再次看到已有唯一键，不能新增或倒退 terminal state。

Occurrence ID 和 Trigger ID 从 subscription ID、local date、revision 和 schedule revision 的
canonical digest 派生，不依赖 worker、tick 时间或随机 UUID。

### 5. Claim、恢复与撤销

SQLite 使用 `BEGIN IMMEDIATE`、唯一键和 record revision 作为多连接 authority：

- READY occurrence 可由一个 worker claim；同 worker 的活 lease 重试返回原 claim；
- 另一 worker 在 lease 未过期时得到冲突；lease 过期后可用递增 revision reclaim；
- ack 必须携带当前完整 claim，原子转为 EMITTED；exact ack 幂等，旧/伪造 claim 拒绝；
- PAUSED/REVOKED 或 revision replacement 将 READY/CLAIMED 置为 INVALIDATED；旧 worker 不能 ack；
- `SKIPPED_EXPIRED`、`INVALIDATED`、`EMITTED` 均 terminal，不可回到 READY；
- claim 只授予产生结构化 Trigger 的一次所有权，不授予来源、模型或发送权限；S15A Policy
  仍需在未来消费者中重新校验。

### 6. SQLite 参考实现

数据库路径、busy timeout、容量、terminal retention 和 journal mode 使用严格 config。默认
DELETE/FULL；WAL 只在仓库既有安全版本门禁通过时允许。文件创建后尝试收紧为 `0600`，拒绝
`:memory:` 作为耐久证据。Schema、subscription payload 和 receipt 均有版本字段及 digest
复核；损坏行 fail closed。

完整 subscription 使用显式 JSON projection/parser，不使用 pickle，也不保存真实 QQ 数据。
测试只使用临时目录与合成 Scope。

### 7. 验证范围

Unit/Contract 覆盖 CAS mutation、pause/resume/revoke tombstone、重复 tick、双 Store/双 Worker、
claim expiry/reclaim/ack、重启、时钟回拨、misfire、weekday/weekend、IANA DST fold/gap 和 30 日
fake-clock 仿真。门禁要求错误目标、重复 occurrence、expired 补发和撤销后 claim 均为 0。

完成前运行双 Python 全仓、warning-as-error focused、Ruff/format、import、lock、compile、wheel、
secret、whitespace 和必要 Web 回归。本分支不声明真实 Scheduler deployment、真实订阅、来源、
模型、Output 或 QQ 发送完成。
