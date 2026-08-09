# Unified MCP、Scheduler 与公开来源调研

## 1. 总结

| Topic | 结论 | 当前不能做的事 |
| --- | --- | --- |
| Unified MCP Client | **SPIKE，预期 adopt Python SDK v2**；v1.29 只作限时 legacy fallback | 直接把依赖从 `<2` 改成 v2；每次调用新建进程；让 SDK cache 成为 Dududa Schema authority |
| Scheduler | **ADOPT Dududa 自有 SQLite occurrence/CAS**；APScheduler 3 只作 Trigger/DST 对照 | 让 APScheduler job store 成为双 Worker claim authority；在 SQLite 3.51.2 以下跑并发 WAL |
| 校园来源 | **ADOPT 官方 RSS metadata**；HTML 抓取先 Spike | 私人校园数据、任意 URL、全文镜像或把 robots allow 当成版权授权 |
| 行业来源 | **ADOPT 官方 publisher allowlist RSS** | 聚合站、无来源摘要、猜测不存在的 Feed 或缓存/转载全文 |
| arXiv | **ADOPT category RSS/Atom metadata**；query API 先 Spike | 高频轮询、并发 legacy API、无许可托管 PDF、默认重复推送每个 revision |

所有外部来源访问日期为 2026-08-09。临时 PoC 位于 `/tmp/dududa-research`，没有第三方源码
进入主仓。

## 2. Unified MCP Client

### 2.1 一手来源

| 来源 | 版本/commit | 许可证与维护 | 影响 |
| --- | --- | --- | --- |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[v2.0.0 Release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0) | v2.0.0，commit `6f69a375...`，2026-07-28 发布；2026-08-07 仍有更新 | MIT，活跃 | 新 `Client` 生命周期、transport auto/legacy、取消和 cache 能力值得 Spike；当前 FastMCP v1 Server 不能原地升级 |
| [Python SDK Client lifecycle](https://py.sdk.modelcontextprotocol.io/client/) | v2 文档，对应 2.0.0 系列 | MIT 项目文档，活跃 | 一个长生命周期 `async with Client` 持有 session；重连产生新 generation，禁止复用旧 session |
| [Python SDK Client caching](https://py.sdk.modelcontextprotocol.io/client/caching/) | v2 文档 | MIT 项目文档，活跃 | response cache 明确不缓存 `server/discover`；只有调用方提供的 `prior_discover` 可跳过 probe，freshness 仍由 Dududa 负责 |
| [MCP Specification](https://github.com/modelcontextprotocol/modelcontextprotocol)、[Cancellation](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/cancellation) | protocol tag `2026-07-28`，commit `5f5440bb...` | 仓库处于 MIT -> Apache-2.0 迁移；普通文档 CC-BY-4.0；活跃 | 取消是协作通知，不等于未知写操作可重试；Dududa 仍需 idempotency/unknown-outcome 语义 |

来源超过三个，但同一 SDK 的代码、生命周期、cache 和协议取消分别用于不同契约判断，不能只根据
README 推断。

### 2.2 实测兼容性

在隔离临时环境使用 Python SDK v2.0.0 Client 连接主仓当前 v1.29 iCourse stdio Server：

- 协商协议 `2025-11-25`；
- discover 得到 10 个工具；
- 同一 Client 生命周期连续调用 `icourse_stats` 5 次成功；
- `mode=auto` 会先发送 v2 `server/discover`，当前 v1 FastMCP 在 stderr 产生 31 项验证错误后
  才 fallback；
- 按 Server 显式配置 `mode=legacy` 可避免这一噪声和额外失败路径。

该结果证明“可以开展迁移 Spike”，不证明当前 v1 Server 已支持 v2。SDK v2 已移除主仓使用的
`mcp.server.fastmcp.FastMCP` 路径，client/server 必须作为一次显式迁移一起验证。

当前 v1.29.0 还会在 `pydantic-settings 2.15.0` 下产生 `lifespan` 未解析警告；同一握手在
2.14.2 和 `-W error` 下通过。过渡期依赖限制为 `>=2.14.2,<2.15.0`，它是可删除的兼容约束，
不是长期拒绝升级 Pydantic。2.14.2 只是尚未检测该未解析 `ForwardRef`，并未从上游代码层修复它；
不采用依赖 FastMCP 内部类型命名空间的本地 `model_rebuild()` monkeypatch。S12 应迁移到 v2 Server，
或等待 v1 上游修复后重新启用 2.15+ 的 warning-as-error contract。

### 2.3 推荐架构

```text
Capability Runtime
  -> McpRuntimeRegistry
       server config + transport mode + generation
       one long-lived Client/session per server
       bounded reconnect/circuit breaker
  -> Dududa Schema Snapshot Authority
       canonical tool schema digest
       generation + discovered_at + expires_at
       atomic publish + last-known-good
  -> audited call/timeout/cancel/result normalization
```

一次断线后销毁旧 Client 和 generation。新连接重新 initialize/discover，并在 Schema 与批准的
Capability manifest 不一致时拒绝发布；不得把过期 cache 静默解释为当前能力。

### 2.4 可复现 S12 Spike

固定 v1.29.0 Server fixture 和 v2.0.0 Client，记录 SDK/协议/Server commit，执行：

1. 100 次顺序调用只启动一次 stdio 子进程；
2. 20 路并发受配置上限约束，无重复 initialize/discover；
3. connect、initialize、discover、call 分别超时；
4. 调用中 cancel，检查任务、pipe 和子进程是否泄漏；
5. Server 在读前、执行中、写回前后崩溃，区分 safe-retry 与 outcome-unknown；
6. Schema 增删/类型变化，验证 last-known-good、refresh/bypass 和 drift 拒绝；
7. v1 `legacy` 与 v2 native Server 分别通过共享 transport contract。

指标：进程启动数、session generation、discover 次数、P50/P95、取消完成时间、泄漏任务/FD、
Schema drift reason code 和未知结果盲重试数。以下任一项失败即不能 adopt：每调用重启进程、取消
残留任务/子进程、过期 Schema 被采用、未知写结果自动重试、Capability 权限由 discovery 自动获得。

## 3. Durable Scheduler

### 3.1 一手来源

| 来源 | 版本/状态 | 许可证 | 影响 |
| --- | --- | --- | --- |
| [APScheduler 3.11.3](https://github.com/agronholm/apscheduler/releases/tag/3.11.3) | commit `4308ec95...`，2026-06-28 发布，维护活跃 | MIT | Trigger/DST/misfire 可作 oracle；不作为双 Worker claim authority |
| [APScheduler 3 FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html) | 3.x 官方文档 | MIT 项目文档 | 官方明确多个进程共享 job store 可能重复执行或漏任务 |
| [SQLite Transactions](https://www.sqlite.org/lang_transaction.html) | SQLite 当前文档 | public domain | SQLite 同时只允许一个 writer；`BEGIN IMMEDIATE` 可在读前取得写事务 |
| [SQLite WAL](https://www.sqlite.org/wal.html#walresetbug)、[Release history](https://www.sqlite.org/changes.html) | WAL-reset bug 影响 3.7.0–3.51.2，3.51.3 修复 | public domain | 双连接/进程 WAL 是硬安全门禁，不能只测唯一约束 |
| [Python `zoneinfo`](https://docs.python.org/3.12/library/zoneinfo.html) / [PEP 495](https://peps.python.org/pep-0495/) | Python 3.12 文档；IANA tzdb 语义 | PSF 文档许可 | DST fold/gap 必须由明确 policy 处理，不能用固定 UTC offset 替代 IANA zone |

### 3.2 所有权与数据模型

Scheduler 只负责根据订阅 revision 物化 occurrence 和竞争 claim：

```text
subscription_id + revision + local_date + scheduled_local_time
  -> unique occurrence_id
  -> scheduled_for / eligible_until / status
  -> BEGIN IMMEDIATE
  -> conditional INSERT or UPDATE ... RETURNING claim lease
  -> commit
```

执行、来源获取、授权、内容和发送仍由 ProactiveDeliveryOrchestrator 拥有。Occurrence 的业务
idempotency 不包含 worker、attempt、Adapter revision 或 wall-clock latency。订阅 pause/revoke/
revision 变化后，旧 occurrence 在发送前重验时失效。

### 3.3 DST、misfire 与未知投递

- IANA timezone 是输入，`local_date + local_time + fold policy` 决定 occurrence；
- spring-forward 不存在时间：首版固定 `SKIP_NONEXISTENT`，不擅自顺延；
- fall-back 重复时间：同一 local date/spec revision 只物化一次，预先冻结 fold 选择；
- `now > eligible_until` 的 misfire 永久 `EXPIRED`，重启不补发；
- clock rollback 不得重建同一业务 key；
- Delivery `UNKNOWN` 只能进入 reconciliation，不能创建第二个 send attempt；
- worker lease 过期允许重取处理权，但必须复用同一 PreparedDispatch/idempotency key。

### 3.4 SQLite 版本门禁

本机 uv Python 的 SQLite 3.53.1 可用于 Spike；系统 Python 3.45.1 和运行中 AstrBot 的 3.46.1
均处 WAL-reset bug 影响范围。S15B 前必须二选一：

1. 派生镜像固定 SQLite 3.51.3+ 并在镜像 smoke 中断言版本；或
2. Scheduler DB 禁用 WAL，使用 rollback journal + `BEGIN IMMEDIATE`/CAS，接受更低并发。

本 Goal 不修改生产 Ledger，也不在受影响容器执行并发压力。

### 3.5 可复现实验

- 2 与 8 Worker 分别竞争同一 occurrence 10,000 次；
- fake clock 运行 30 天，覆盖正常日、重启和 clock rollback；
- `America/New_York`、`Europe/Berlin`、`Australia/Lord_Howe` 的 gap/fold；
- 在 claim 前、事务提交后、PreparedDispatch 后、发送前后注入 SIGKILL；
- busy lock、磁盘满、只读 DB、损坏行、订阅 CAS 冲突；
- revoke/pause 与 materialize/claim/send 并发。

硬指标：duplicate claim/send=0、漏 eligible occurrence=0、expired misfire send=0、revoked send=0、
wrong target=0。任何一项非 0 即失败；吞吐和 P95 只决定 worker 数，不得降低正确性。

## 4. 公开来源

### 4.1 来源矩阵

| 类别/来源 | 版本与维护状态 | 内容权利/robots | 结论 |
| --- | --- | --- | --- |
| [中科大教务处通知 RSS](https://www.teach.ustc.edu.cn/category/notice/feed) | RSS 2.0，WordPress 5.0.25；2026-07-31 仍更新 | [robots](https://www.teach.ustc.edu.cn/robots.txt) 未禁止该 Feed；未声明开放全文许可 | adopt metadata/有限摘要/规范链接；post ID 作稳定 external ID |
| [中科大总站通知](https://www.ustc.edu.cn/tzgg.htm) | HTML，持续维护 | 站点明确版权所有，无 RSS | spike 结构稳定性；不缓存/再分发全文 |
| [中科大新闻网](https://news.ustc.edu.cn/) | HTML，持续维护 | 版权所有，无 RSS | defer；仅在用户加入 allowlist 后做 metadata Adapter |
| [OpenAI News RSS](https://openai.com/news/rss.xml) | 2026-08 仍更新 | 官方 Feed，未授予全文再分发许可 | adopt allowlisted metadata/link摘要 |
| [Google DeepMind RSS](https://deepmind.google/blog/rss.xml) | 2026-08 仍更新 | 官方 Feed，未声明开放全文许可 | adopt allowlisted metadata/link摘要 |
| [GitHub Changelog RSS](https://github.blog/changelog/feed/) | 2026-08 仍更新 | 官方 Feed，内容权利保留 | adopt allowlisted metadata/link摘要 |
| Anthropic 猜测 RSS URL `https://www.anthropic.com/news/rss.xml` | 2026-08-09 返回 404 | 无来源可授权 | reject；不得把猜测 URL 加入配置 |
| [arXiv RSS](https://info.arxiv.org/help/rss.html) | 官方每日 Feed 文档，持续维护 | metadata 与内容权利按 arXiv 条款 | adopt category 日报 |
| [arXiv API manual](https://info.arxiv.org/help/api/user-manual.html) / [Terms](https://info.arxiv.org/help/api/tou.html) | legacy Atom API；当前官方条款 | legacy API 总计单连接、每 3 秒最多一次；描述性 metadata CC0；PDF 版权逐篇不同 | query/关键词先 Spike，禁止并发高频与无许可 PDF 镜像 |
| [arXiv OAI-PMH](https://info.arxiv.org/help/oa/index.html) | OAI-PMH 2.0，2025-03 重写 | metadata 批量接口；遵守官方 ToU | defer 到离线 bulk/index 需求出现 |

robots 只说明爬虫访问偏好，不是内容许可证。所有非明确开放内容默认只保存标题、短摘要、分类、
发布时间、规范 URL、稳定外部 ID、内容 digest 和 observation time。

### 4.2 规范化与去重

统一 `SourceItem` 仍保留 source-specific identity：

- USTC WordPress：post GUID/数字 ID；URL 去 tracking/fragment，内容修改更新 digest；
- 行业 RSS：首选官方 GUID，否则 canonical URL + published time；同事件跨 publisher 不自动合并，
  只在确定性规则匹配时建立 cluster ref；
- arXiv：base paper ID 与 revision 分离。

```text
paper_id    = 2608.06377
revision_id = v1
external_id = 2608.06377v1
canonical   = https://arxiv.org/abs/2608.06377v1
```

默认第一次出现 base ID 才进入日报。v2+ 更新本地记录但不重复推送；只有订阅显式启用
`notify_revisions` 才产生新的 eligible item。Feed ETag/lastBuildDate 是 source snapshot revision，
不是 item revision。

### 4.3 来源实验和失败条件

每个 Adapter 先保存固定、获准分发的最小 fixture，验证：正常项、缺 ID/时间、修订、重定向、
tracking URL、HTML/prompt injection、超长字段、非 allowlist 域名、429/5xx/timeout、ETag 304 和
重复抓取。

指标：parse success、stable-ID coverage、duplicate rate、revision accuracy、freshness、429 数、
P95 fetch、缓存字节和无引用项数。失败条件：非 allowlist URL、无 provenance item、全文/敏感数据
落库、robots/ToU 违反、arXiv 频率超限、同 item 重复出现在同 occurrence、来源文本成为系统指令。

## 5. 集成顺序与外部输入

| 工作 | 优先级/判定 | 前置输入 |
| --- | --- | --- |
| MCP v2 Client + v1 legacy fixture Spike | P0 / spike | 无用户凭据，使用本地 iCourse fixture |
| Unified MCP 实现与 Capability 接入 | P0 / expected adopt | Spike 和 ADR 通过 |
| SQLite Scheduler CAS + fake clock | P1 / adopt | SQLite 策略 ADR、timezone/quiet-hour 默认值 |
| USTC 教务 RSS Adapter | P1 / adopt | 用户确认校园单位/栏目 allowlist |
| arXiv category Feed | P1 / adopt | 分类、关键词、revision policy、每日条目上限 |
| 行业 publisher RSS | P1 / adopt | publisher/category allowlist |
| HTML/OAI-PMH/full text | P2 / defer | 真实缺口、许可复核和独立容量设计 |

以后需要用户冻结：校园单位、行业 publisher/category、arXiv 分类/关键词/是否推送修订版；IANA
时区、发送时间、quiet hours、misfire 窗口和条目上限；无稳定 ID、内容变化及跨来源同事件的去重
策略。真实 QQ 标识、凭据和发送窗口当前不需要。
