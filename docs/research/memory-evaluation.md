# Memory 架构与评测调研

状态：研究结论已用于 S14 离线实现；不代表生产 Memory 已启用，也不代表真实中文质量成立

访问与核验日期：2026-08-09

主仓基线：`codex/s08-s11`，调研期间不读取两个 `dududa20-*` 隔离仓

外部源码与临时实验：`/tmp/dududa-research`，不进入主仓依赖或发布物

## 0. S14 实现回写

S14 沿用本报告的 Core ownership 和“先资格过滤、后质量优化”结论，但按批准 Goal 收窄了
首轮实验：本阶段只实现 `M0 no-memory -> M1 recency -> M2 CJK BM25`，不做
Embedding/Hybrid shadow。删除/tombstone、scoped export、archive/checkpoint restore、正式
Retrieval Port、generation/time-bound read 和 JSON v2 crash replay 已落地；生产 Iris、旧命令、
Context Builder 和自动写入均未接入。

M2 采用同一有界授权候选集上的纯 Python CJK bigram Okapi BM25，而没有采用本文候选的
SQLite FTS5 持久索引。原因不是否定 FTS5，而是当前候选规模没有证据支持第二个派生存储，
同时会引入 tokenizer/SQLite runtime 漂移和额外删除一致性面。固定合成 bundle 记录
Precision/Recall/recall-any/all/MRR/binary nDCG、ranking fingerprint 和五类安全机会分母；
`human_review_complete=false`、`real_chinese_quality_claimed=false`、`network_allowed=false`。

## 1. 结论

1. **保留 Dududa 自有 Memory Core。** 现有 `MemoryScope`、带完整性保护的
   `ScopeSelector`、Repository Snapshot、显式 Write Gate 和 fail-closed Iris Protocol
   是正确的安全边界。Mem0、Letta、Zep/Graphiti、Iris 均不能替换这些边界。
2. **S14 不重新设计核心模块。** 沿用现有 Scope/Repository/Write Gate，补齐
   `ScopedMemoryRetriever`、`MemoryAdministration`、`MemoryRanker`、`commit_delete()` 和正式
   `MemoryRetrievalResult`；生产命令和 Context Builder 作为独立消费者迁移后置。
3. **检索按简单到复杂递进：** S14 只冻结 `no-memory -> recency -> CJK BM25`。
   所有方案先做相同的精确 Scope、TTL、visibility 过滤；Embedding/Hybrid 只有在未来授权
   held-out 数据上稳定优于简单基线，才可进入 shadow。
4. **首版只允许显式写入。** `/remember` 经过确定性 Write Gate；自动抽取、自动遗忘、
   自动合并冲突和 Graph Memory 均后置。模型只能产生候选，不能获得写权限。
5. **框架判定：** Mem0 OSS 和 Graphiti 只做隔离 Spike；Letta 直接集成 `reject`；
   Zep Cloud `defer`、旧 Community Edition `reject`；Iris 因 Dududa 固定版本无许可证
   保持 `blocked`。
6. **隐私与删除是先决门禁。** 任意跨 Scope 泄漏、外部敏感数据发送、删除后重建复活，
   均直接判定整个候选失败，不与质量分数加权折中。

### 1.1 候选总表

| 候选 | 固定版本/commit | 许可证与维护状态 | Dududa 判定 |
| --- | --- | --- | --- |
| Mem0 OSS | `v2.0.17` / `12c47f5`；核验 HEAD `4debc58` | Apache-2.0；2026-08-07 仍有提交，活跃 | `spike`：隔离对照或 Ranker；替换 `MemoryRepository` 为 `reject` |
| Letta legacy | `0.16.8` / `1131535`；核验 HEAD `ff19ffe` | Apache-2.0；官方 README 明确为 legacy | 概念 `adopt`；直接运行时集成 `reject` |
| Letta Code | `v0.30.14` / `a75f4d9` | Apache-2.0；2026-08-09 发布，活跃；Node.js 22.19+ | 完整 Agent Harness，直接集成 `reject` |
| Graphiti | `v0.29.3` / `021d3a5`；核验 HEAD `425bf24` | Apache-2.0；活跃 | Temporal/Graph 独立 `spike`，生产 `defer` |
| Zep | HEAD `ba4fc3c` | 当前仓 Apache-2.0，但不是产品源码；CE unsupported | Cloud `defer`；旧 CE `reject` |
| Iris | Dududa pin `2421646`；release `0.2.0` / `e6f4322` | 两个版本均无 LICENSE；`5c1f8ae` 才加入 AGPL-3.0 | `blocked` |
| LoCoMo | repo `3eb6f2c` | 数据/仓库 CC BY-NC 4.0；稳定、低频维护 | research Eval `adopt`，不得 vendor 到商业发行物 |
| LongMemEval | repo `9e0b455`；cleaned data `98d7416` | 代码和 cleaned data MIT；2026-05 仍更新 | 外部辅助基准 `adopt` |

## 2. 主仓现状与真实缺口

### 2.1 已实现且应保留

- `packages/dududa-agent/src/dududa/memory/models.py:28` 已定义 `MemoryType`；
  `:89` 的 `MemoryScope` 精确绑定 platform、Bot、conversation、group、user、Persona 和类型。
- `packages/dududa-agent/src/dududa/ports/memory.py:31` 已有 `MemoryRepository` 的
  snapshot、get、retrieve、list、commit_write 契约。
- `packages/dududa-agent/src/dududa/memory/repository.py:79` 先验证 selector 再创建短期 snapshot；
  `:262` 拒绝混用 snapshot/revision/request/selector；`:403` 在读取时执行精确 Scope、TTL 和
  visibility 过滤。
- `packages/dududa-agent/src/dududa/memory/write_gate.py:38` 的 `ExplicitMemoryWriteGate`
  明确禁止自动写入；`:179` 校验来源、类型、Scope、敏感度、TTL、Delivery 和授权。
- `packages/dududa-agent/src/dududa/memory/iris.py:120` 提供 fail-closed Repository Adapter；
  当前只有 `IrisBackend` Protocol/Fake，不把 Iris SDK 引入 Core。
- JSON/In-memory Repository、迁移 dry-run、backup、receipt、rollback 和跨 Scope 契约测试已存在。

### 2.2 开工时尚未完成（历史快照）

以下是本报告形成时的缺口，不是 2026-08-10 的当前状态；S14 已关闭项见 2.3。

1. **当前不是 BM25。** `repository.py:142-174` 的 `retrieve()` 只做字符串包含过滤，随后按
   `(updated_at, memory_id)` 逆序排列。
2. **设计 Port 尚未进入代码。** `docs/design/memory.md:254-367` 已定义
   `commit_delete()`、`SemanticMemoryIndex`、`MemoryRetrievalPolicy`、
   `ScopedMemoryRetriever`；`:649-669` 已定义 `MemoryAdministration`，但正式 Python Port
   尚不存在。
3. **Runtime 仍是占位。** `packages/dududa-agent/src/dududa/runtime/state.py:116` 把
   `MemoryRetrievalResult` 指向 `ProvisionalRuntimePayload`；S10 直聊链没有 Memory Retrieval。
4. **生产命令绕过新边界。** `plugins/astrbot_plugin_dududa_core/commands/memory.py:24-25`
   的 `/remember` 直接 append legacy 用户 JSON；`:29-39` 的 `/forget` 用字符串包含删除；
   `:54-56` 的 export 直接打印 legacy 数组。三者均未经过 Write Gate、版本、Snapshot、
   管理授权或删除回执。
5. **删除/导出闭环缺失。** Repository 没有删除事务和 tombstone，Semantic/Graph/缓存索引
   没有级联删除契约，也没有“删除后重启/重建不能复活”证明。
6. **真实 Iris 未接入。** 当前只证明内部 Protocol/Fake 自洽，尚不能证明与固定 Iris 版本、
   真实数据和迁移格式兼容；许可证问题还在其前面阻断。

结论：S06-S07 是“Memory 安全骨架完成”，不是“Memory 产品能力完成”。S14 应实现已有文档
契约并接通生产消费者，不扩大 Core 的职责。

### 2.3 S14 后当前边界

- 已关闭：正式生命周期/检索 DTO 与 Port、delete/tombstone、scoped export、service
  archive/checkpoint restore、JSON v1-to-v2 与跨重启幂等证据、generation/time-bound read、
  M0/M1/M2 和固定合成 Eval。
- 保持 fail closed：Iris 无法证明的 delete/archive/restore 明确 unsupported，不继承本地假删除。
- 仍未完成：旧 `/remember`/`/forget`/export 消费者迁移、Context Builder、生产 Iris、真实数据
  与人工标注、Embedding/Hybrid 对照、Runtime enablement 和 S23。
- S14 只证明 reference Adapter 和 synthetic lexical regression；产品 Memory 仍是“部分完成”。

## 3. 外部框架调研

### 3.1 Mem0

**事实。** Python SDK `v2.0.17` 发布于 2026-08-05，tag 指向
`12c47f524935692e27ad48d829f35fa1e4417181`；2026-08-07 的核验 HEAD 为
`4debc58a83377b18be81ae1e5969a300736b2fac`。仓库和 release 均为 Apache-2.0，维护活跃。

**可借鉴。** 统一 add/search/get-all/update/delete/delete-all/history API、身份 filter、TTL、
语义/BM25/entity 多信号检索以及公开 benchmark harness。可用于独立进程中的检索对照。

**不可直接采用。** 固定版本 `add(..., infer=True)` 默认让 LLM 决定 add/update/delete；
身份只要求 `user_id/agent_id/run_id` 至少一个，不能表达或证明 Dududa 的完整 Scope；
`search()` 允许高级 metadata filter 和 wildcard，它们不是授权凭证。README 的新算法成绩还明确
说明含 managed-platform 专有优化，不能当作 OSS release 的可复现结果。

**Telemetry 门禁。** 固定版本 `MEM0_TELEMETRY` 默认值为 `True`，初始化 PostHog
`https://us.i.posthog.com`。任何 Spike 必须设置 `MEM0_TELEMETRY=false`，使用合成数据，
并在无网络环境验证无 DNS/连接尝试。

**判定。** `spike` 为隔离对照或 `SemanticMemoryIndex` Adapter；直接实现/替换
`MemoryRepository`、Write Gate 或 Scope authority 为 `reject`。

一手来源：

- [Mem0 v2.0.17 source](https://github.com/mem0ai/mem0/tree/12c47f524935692e27ad48d829f35fa1e4417181)
- [Mem0 v2.0.17 release](https://github.com/mem0ai/mem0/releases/tag/v2.0.17)
- [固定版本 Memory API](https://github.com/mem0ai/mem0/blob/12c47f524935692e27ad48d829f35fa1e4417181/mem0/memory/main.py)
- [固定版本 telemetry](https://github.com/mem0ai/mem0/blob/12c47f524935692e27ad48d829f35fa1e4417181/mem0/memory/telemetry.py)
- [Mem0 论文 arXiv:2504.19413v1](https://arxiv.org/abs/2504.19413v1)
- [官方 memory-benchmarks `4b61c5d`](https://github.com/mem0ai/memory-benchmarks/tree/4b61c5d31b9c668a12b4f5e78064248a02c82d2b)

### 3.2 Letta / MemGPT

**事实。** 旧 `letta-ai/letta` 最新 release `0.16.8` 指向 `1131535`，Apache-2.0；
核验 HEAD `ff19ffe` 的 README 明确写明该仓库是 V1 API 的 legacy server，活跃开发已转到
`letta-ai/letta-code`。Letta Code `v0.30.14` 指向 `a75f4d9`，2026-08-09 发布，
Apache-2.0，要求 Node.js `>=22.19.0`。

**可借鉴。** MemGPT 的虚拟上下文/分层记忆概念、可编辑 memory block、archival semantic
search、版本历史和显式 memory management tool。它证明工作上下文与长期存储应分层管理。

**不可直接采用。** Letta Code 是 stateful Agent Harness，拥有 Agent identity、memory、skills、
subagents、channels、schedule、permission 和主动运行。引入它会形成第二个 Runtime、权限系统、
调度器和发送链，并绕开 Dududa 已有 Connector/Router/Capability/Delivery 所有权。

**判定。** 分层概念 `adopt`；legacy server 和 Letta Code 直接集成均 `reject`。

一手来源：

- [Letta legacy `ff19ffe` README](https://github.com/letta-ai/letta/blob/ff19ffeafeb54bd2a7dc5d4a552f10191732a235/README.md)
- [Letta 0.16.8 release](https://github.com/letta-ai/letta/releases/tag/0.16.8)
- [Letta Code v0.30.14](https://github.com/letta-ai/letta-code/tree/a75f4d93ef1c61946c7f3e4dec2b3ecf17c17680)
- [Letta Code release](https://github.com/letta-ai/letta-code/releases/tag/v0.30.14)
- [MemGPT 论文 arXiv:2310.08560v2](https://arxiv.org/abs/2310.08560v2)

### 3.3 Zep / Graphiti

**事实。** Graphiti `v0.29.3` 指向 `021d3a5`，Apache-2.0，2026-07-27 发布；核验 HEAD
`425bf24`，维护活跃。Zep 仓库核验 HEAD `ba4fc3c`，但 README 明确说明它不是 Zep 产品或
服务源码，只包含 Zep Cloud 示例、集成、ingestion 和 benchmark；`legacy/` 中 Community
Edition 已 deprecated 且 unsupported。

**可借鉴。** Graphiti 的 episode、带 valid/invalid 时间的 relation、BM25 + cosine + graph
search、RRF/MMR/cross-encoder recipes，以及按 episode 删除派生节点/边的实现，可作为 Temporal
Graph Spike 的参考。

**安全差距。** Graphiti `search(..., group_ids=None)` 允许无分区查询；空列表还会在内部转换为
`None`。它只有 `group_id` 分区，不能表达 Dududa 的 platform/Bot/conversation/user/Persona/
memory-type selector。`remove_episode()` 会保留其他 episode 共享的节点/边，不能自动证明用户
删除已覆盖所有派生事实。

**Telemetry 门禁。** Graphiti 默认开启 PostHog，写入
`~/.cache/graphiti/telemetry_anon_id`，环境变量为 `GRAPHITI_TELEMETRY_ENABLED`。Spike 必须设为
`false` 并在 network-none 下运行。

**判定。** Graphiti 仅在简单检索有稳定增益后做独立 `spike`，生产 `defer`；Zep Cloud 因数据
外传、retention 和商业服务依赖 `defer`；旧 CE `reject`。

一手来源：

- [Graphiti v0.29.3](https://github.com/getzep/graphiti/tree/021d3a57d511f21b10adaf7fa923bd5c1fce5e9d)
- [Graphiti release](https://github.com/getzep/graphiti/releases/tag/v0.29.3)
- [Graphiti hybrid search source](https://github.com/getzep/graphiti/blob/021d3a57d511f21b10adaf7fa923bd5c1fce5e9d/graphiti_core/search/search.py)
- [Graphiti telemetry source](https://github.com/getzep/graphiti/blob/021d3a57d511f21b10adaf7fa923bd5c1fce5e9d/graphiti_core/telemetry/telemetry.py)
- [Zep repository positioning `ba4fc3c`](https://github.com/getzep/zep/blob/ba4fc3cc5b00cda7dde63833007467ffd6cba3a8/README.md)
- [Zep/Graphiti 论文 arXiv:2501.13956v1](https://arxiv.org/abs/2501.13956v1)

### 3.4 Iris

项目身份已唯一确认：`Leafliber/astrbot_plugin_iris_chat_memory`。Dududa
`plugins.lock.json` 固定 `242164667d19061a316e8e8651d96c02690d4e4f` 并应用本地 Scope patch。

许可证时间线：

| 版本 | 日期 | LICENSE |
| --- | --- | --- |
| Dududa pin `2421646` | 2026-06-25 | 无 |
| release `0.2.0` / `e6f4322` | 2026-07-02 commit；2026-07-01 release | 无 |
| `5c1f8ae` | 2026-07-04 | 首次加入 AGPL-3.0 |
| main `3155821` | 2026-07-28 | AGPL-3.0，仍有维护 |

AGPL 文件晚于固定提交和最新 release，不能推定对旧版本追溯授权。升级到 `5c1f8ae` 之后也需要
先评估 AGPL 网络交互和发行义务，不能用升级动作绕过评审。

功能上，Iris 的 L1/L2/L3、画像、FAISS/SQLite、图谱和批量删除可供兼容测试参考；其后续
CHANGELOG 仍持续修复私聊 L1 污染、group seed 隔离、Persona export/import 隔离和删除/更新竞态，
说明本地 patch 只能作为 defense in depth，不能代替 Core Scope。

**判定。** 在取得上游对旧提交的明确书面许可，或升级到有许可证的提交并完成 AGPL 评审前，
保持 `blocked`；不得进入新 lock、镜像或发布物。当前 `IrisBackend` Protocol/Fake 可以保留。

一手来源：

- [Dududa 固定 Iris commit](https://github.com/Leafliber/astrbot_plugin_iris_chat_memory/tree/242164667d19061a316e8e8651d96c02690d4e4f)
- [Iris 0.2.0 release](https://github.com/Leafliber/astrbot_plugin_iris_chat_memory/releases/tag/0.2.0)
- [首次加入 AGPL-3.0 的 commit](https://github.com/Leafliber/astrbot_plugin_iris_chat_memory/commit/5c1f8aef2cc61cb2052e04487dae71b6ffbfc310)
- [核验 main `3155821`](https://github.com/Leafliber/astrbot_plugin_iris_chat_memory/tree/3155821d28edc782e5ab2cf9af956e755101f713)

## 4. Benchmark 与数据许可

### 4.1 LoCoMo

最终 ACL 2024 论文为 CC BY 4.0；arXiv v1 页面为 CC BY-NC-SA 4.0。官方仓库
`3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376` 的唯一许可证是 CC BY-NC 4.0，因此仓库代码和
数据均按非商业材料处理，不复制到未来商业发行物。

当前仓库不是论文最初的 50 段对话全集。README 明确说明当前是为质量与成本筛出的 10 段子集：

- 10 conversations，272 sessions，5,882 turns；平均 27.2 sessions、588.2 turns；
- 1,986 QA，其中 category 1-4 共 1,540 条带正常 gold/evidence；category 5 adversarial 446 条；
- 不发布图片，只保留 URL、BLIP caption 和图片搜索 query；
- `data/locomo10.json` SHA-256：
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`。

判定：研究 Eval `adopt`；下载到外部缓存并记录 attribution/manifest，禁止 vendor 和商业默认使用。

一手来源：

- [ACL 2024 final paper](https://aclanthology.org/2024.acl-long.747/)
- [LoCoMo repository `3eb6f2c`](https://github.com/snap-research/locomo/tree/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376)
- [LoCoMo data README](https://github.com/snap-research/locomo/blob/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/README.MD)
- [LoCoMo CC BY-NC 4.0](https://github.com/snap-research/locomo/blob/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/LICENSE.txt)

### 4.2 LongMemEval

论文 arXiv v2 为 CC BY 4.0；官方代码仓 `9e0b455f4ef0e2ab8f2e582289761153549043fc`
为 MIT；官方 cleaned Hugging Face 数据集 card 也声明 MIT。仓库在 2026-05 更新，并指向后续
LongMemEval-V2，维护状态优于 LoCoMo。

固定 cleaned dataset commit：`98d7416c24c778c2fee6e6f3006e7a073259d48f`。

| 文件 | 大小 | SHA-256/LFS oid |
| --- | ---: | --- |
| `longmemeval_oracle.json` | 15,388,478 B | `821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c` |
| `longmemeval_s_cleaned.json` | 277,383,467 B | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |
| `longmemeval_m_cleaned.json` | 2,737,100,077 B | `9d79e5524794a2e6900a3aa9cb7d9152c5a3e8319c9a87c25494ba1eacee495f` |

三份数据均为 500 问题；30 条 question ID 以 `_abs` 结尾，用于 abstention。类型分布：
`single-session-user=70`、`single-session-assistant=56`、`single-session-preference=30`、
`knowledge-update=78`、`temporal-reasoning=133`、`multi-session=133`。S 约 115k token/40 sessions，
M 约 500 sessions。Retrieval 指标应排除无 evidence 的 30 条 abstention，但回答 Eval 必须保留它们。

判定：`adopt` 为外部辅助基准；先用 oracle 做 pipeline smoke，再用 S；M 只在资源预算明确后下载。

一手来源：

- [LongMemEval paper arXiv:2410.10813v2](https://arxiv.org/abs/2410.10813v2)
- [LongMemEval code `9e0b455`](https://github.com/xiaowu0162/LongMemEval/tree/9e0b455f4ef0e2ab8f2e582289761153549043fc)
- [LongMemEval MIT license](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/LICENSE)
- [cleaned dataset `98d7416`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/98d7416c24c778c2fee6e6f3006e7a073259d48f)

### 4.3 适用性限制

LoCoMo 与 LongMemEval 都是英文、合成或人工编辑的双人对话，不能替代中文 QQ 的多用户、
多群、私聊、引用、口语、省略和 Persona Scope 数据。外部 benchmark 只验证一般检索/推理能力；
发布门禁必须另建合成和获准脱敏的 Dududa 数据，并按 group/conversation/user/time 聚类切分。

## 5. Memory 类型与生命周期

### 5.1 分类

采用 CoALA 的工作记忆/长期记忆区分，但映射到 Dududa 已有所有权，不新增平行数据库：

| 科学分类 | Dududa 所有权 | 首版规则 |
| --- | --- | --- |
| 工作记忆 | `ConversationContextStore`、当前 `RuntimeState` | 有界、短期、不可通过长期语义检索；不变成 `MemoryRecord` |
| 情景记忆 | `MemoryType.EPISODIC` | 事件、时间、来源、evidence 与原始 Scope；默认同 conversation；优先不可变追加 |
| 语义记忆 | `USER_PROFILE`、`GROUP_MEMORY`、`EXPLICIT_USER_MEMORY` | 稳定事实/偏好/群知识；有版本、证据、可见性和冲突集合 |
| 程序记忆 | Core policy、Persona、Skill/Capability 版本 | 不属于用户 Memory；模型不得通过 Memory 写入修改代码、权限或 Prompt |

CoALA 明确区分 working、episodic、semantic、procedural；Generative Agents 用完整 experience
stream、recency/relevance/importance 和 reflection 展示了情景到抽象知识的可能路径；MemGPT 展示了
上下文层级管理。三者是架构参考，不是允许首版自动 reflection/写入的证据。

一手来源：

- [CoALA arXiv:2309.02427v3](https://arxiv.org/abs/2309.02427v3)
- [Generative Agents arXiv:2304.03442v2](https://arxiv.org/abs/2304.03442v2)
- [MemGPT arXiv:2310.08560v2](https://arxiv.org/abs/2310.08560v2)
- [LongMemEval indexing/retrieval/reading](https://arxiv.org/abs/2410.10813v2)

### 5.2 显式写入

首版唯一可持久化路径：

```text
/remember
  -> trusted Actor + ConversationScope
  -> MemoryCandidate(EXPLICIT_USER_REQUEST)
  -> deterministic ExplicitMemoryWriteGate
  -> versioned MemoryWriteCommand
  -> MemoryRepository.commit_write
  -> persisted receipt
```

- 模型、Tool、summary 只能产生 transient candidate；首版一律不提交。
- 敏感/Restricted、凭据模式、错误 Scope、未授权、过期 TTL、错误 Delivery 依赖全部拒绝。
- 写入前检查 content hash 重复和 subject/predicate 冲突；重复不产生第二条，冲突进入待处理集合。
- 显式命令也不能绕过敏感度和 Scope。

### 5.3 遗忘、过期和冲突

“降低检索分数”与“删除数据”必须分开：

- **TTL/retention：** 到期记录先于排序被过滤；后台可按冻结策略物理清理。
- **recency decay：** 只影响排序，绝不自动删除或改变事实真值。
- **自动遗忘：** 首版 `reject/defer`。没有用户授权和可回放策略时，不按访问频率、模型评分或
  群聊沉默删除记录。
- **冲突：** 新事实不静默覆盖旧事实；保存 evidence、版本和有效时间。只有同 subject/predicate/
  context 且 policy 明确允许 `latest-wins` 时，才能把旧版本标为 superseded；否则返回
  `MemoryConflictGroup`，要求澄清或不引用。
- **Knowledge update：** LongMemEval 的 78 条 update 和 133 条 temporal 问题必须单独报告，
  不能被总体准确率掩盖。

### 5.4 Delete 与 Export

`MemoryAdministration` 从当前 Actor/Scope 重新授权，调用方不能提交任意 user/group selector。

删除事务至少覆盖：

1. canonical record/version 与 tombstone；
2. lexical/embedding index；
3. 可选 graph 派生节点、边和 source references；
4. retrieval/result cache、outbox 和未完成候选；
5. export/read replica 与重建清单；
6. backup retention/restore 后的 tombstone replay。

删除返回幂等 `MemoryDeleteReceipt`；同 key 重放结果相同，版本变化时报 conflict。必须验证删除后
进程重启、索引 rebuild、旧 backup restore 都不会让记录重新可读。SQLite FTS5 默认只写
delete-key，旧 term 可能保留到 merge；本地索引需同时启用 FTS5 `secure-delete=1` 与
`PRAGMA secure_delete=1`，并把 backup/文件级残留纳入单独策略，不能只看 SQL 查询结果。

Export 只分页导出当前授权 Scope 的 canonical record、版本、时间、来源、evidence refs、
sensitivity/visibility 和 schema revision；不导出 embedding、内部 selector proof、凭据或其他群记录。
需有 export -> clean import -> exact authorized read 的 round-trip 测试。

生命周期一手来源：

- [Mem0 固定版本 CRUD/history](https://github.com/mem0ai/mem0/blob/12c47f524935692e27ad48d829f35fa1e4417181/mem0/memory/main.py)
- [Graphiti episode removal](https://github.com/getzep/graphiti/blob/021d3a57d511f21b10adaf7fa923bd5c1fce5e9d/graphiti_core/graphiti.py)
- [LongMemEval knowledge update/temporal/abstention](https://arxiv.org/abs/2410.10813v2)
- [SQLite FTS5 secure-delete](https://www.sqlite.org/fts5.html#the_secure_delete_configuration_option)
- [SQLite core secure_delete](https://www.sqlite.org/pragma.html#pragma_secure_delete)

## 6. Scope 与隐私边界

### 6.1 不变量

1. platform、Bot、conversation、group、user、Persona、MemoryType 必须由 Connector/Policy 的
   受信对象生成，不从自然语言或模型实体猜测。
2. Repository/数据库查询先应用精确 Selector、TTL、visibility 和 candidate limit，之后才排名。
3. 空/缺字段是错误，不是 wildcard；任何 backend 不支持 exact filter 时 fail closed。
4. `SAFE_USER_PROFILE` 是具名、签名、短 TTL selector，只能读取显式 public-safe 字段；
   private-to-group 和 cross-group 默认拒绝。
5. `SemanticMemoryIndex` 只接收已授权的最小 projection 和不透明 Scope digest；不得接收 Actor、
   evidence、原始 Scope 或全局 record。Ranker 只返回已知 ID/score；未知/重复 ID 拒绝整批。
6. `RESTRICTED` 永不送外部 ranker；Sensitive 默认只允许冻结的本地模型。读取权限不等于将正文或
   query 发给外部 embedding Provider 的权限。
7. Trace 只记录 revisions、IDs、数量、类型和 reason code，不记录正文、QQ ID、群号或 query。

### 6.2 外部实现为何不能作为权限边界

- Mem0 的 user/agent/run filter 是调用参数，不是绑定 Actor/当前 Scope 的授权证明。
- Graphiti 的 `group_ids=None` 是合法全图搜索，空列表会变成 `None`。
- Iris 本地 patch 和后续隔离修复只能降低风险，不能替代 Core 端 exact Selector。

隐私边界一手来源：

- [Mem0 add/search filter source](https://github.com/mem0ai/mem0/blob/12c47f524935692e27ad48d829f35fa1e4417181/mem0/memory/main.py)
- [Graphiti optional group scope source](https://github.com/getzep/graphiti/blob/021d3a57d511f21b10adaf7fa923bd5c1fce5e9d/graphiti_core/search/search.py)
- [Graphiti graph API](https://github.com/getzep/graphiti/blob/021d3a57d511f21b10adaf7fa923bd5c1fce5e9d/graphiti_core/graphiti.py)
- [Dududa fail-closed Scope ADR](../adr/0003-fail-closed-memory-scope.md)

## 7. 检索实验

### 7.1 共同前提

- 冻结同一 dataset/model/config manifest、seed、answer model、Prompt、candidate limit、`k`、
  Context token budget 和 reference time。
- 所有策略读取同一 `MemoryRepositorySnapshot`，在数据库端先做 exact Scope/TTL/visibility。
- 先测 retrieval，再把相同 retrieval output 交给 answer model；防止回答模型掩盖检索差异。
- 外部 benchmark 不调参；调参只使用合成/本地 dev set，最终在完整外部集和中文 held-out 集报告。
- LoCoMo 按 conversation、Dududa 数据按 group/conversation/user/time 聚类；禁止同一会话跨 split。

### 7.2 五组基线

| ID | 策略 | 精确定义 | 判定 |
| --- | --- | --- | --- |
| M0 | no-memory | 保持当前消息/短期 Context 不变，但不注入任何 durable `MemoryRecord` | `adopt` 为必需对照 |
| M1 | recency | exact eligible records 按 `updated_at, memory_id` 确定性逆序取 Top-K | `adopt` 为降级基线 |
| M2 | BM25 | SQLite FTS5；英文词元 + 版本化 CJK bigram projection；同 Scope SQL filter | `adopt` 前先完成 tokenizer Spike |
| M3 | embedding | 固定本地 embedding 对已授权 projection 排名；首选 BGE small zh | `spike`，先 shadow |
| M4 | hybrid | BM25 与 dense 各自排名后用 RRF 融合；recency 作为独立 M4R ablation，不偷偷混入 M4 | `spike`，需稳定优于 M2/M3 |

LongMemEval 官方代码直接提供 no-retrieval、full history、BM25 和多个 dense retriever；Graphiti
固定版本提供 BM25 + cosine + RRF recipe；Generative Agents 提供 recency/relevance/importance
消融依据。它们共同支持基线选择，但 Dududa 不复制其默认 Scope 或 Prompt。

一手来源：

- [LongMemEval baseline implementation](https://github.com/xiaowu0162/LongMemEval/tree/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval)
- [SQLite FTS5/BM25/tokenizers](https://www.sqlite.org/fts5.html)
- [Graphiti search recipes](https://github.com/getzep/graphiti/blob/021d3a57d511f21b10adaf7fa923bd5c1fce5e9d/graphiti_core/search/search_config_recipes.py)
- [Generative Agents recency/relevance/importance](https://arxiv.org/abs/2304.03442v2)
- [BGE-M3 paper arXiv:2402.03216v5](https://arxiv.org/abs/2402.03216v5)

### 7.3 中文 BM25 门禁

本机系统 Python SQLite 为 `3.45.1`，锁定的项目 Python 3.12.13 使用 SQLite `3.53.1`；
两者均可用 FTS5，系统还编译了 `SECURE_DELETE`，但本机没有 `sqlite3` CLI。S14 实现与 CI
应使用锁定项目 Python，不能依赖 CLI。内存 PoC 对文档“校园通知”的结果：

| tokenizer/query | 命中数 |
| --- | ---: |
| `unicode61`, `MATCH '校园'` | 0 |
| `unicode61`, `MATCH '校园*'` | 1 |
| `trigram`, `MATCH '校园'` | 0 |
| `trigram`, `MATCH '校园通'` | 1 |
| `unicode61` + `校园 园通 通知` bigram projection，`MATCH '校园'` | 1 |

因此不能把默认 `unicode61` 直接称为中文 BM25，也不能只换 trigram 后忽略常见两字词。M2 开工前
必须冻结 locale-aware tokenizer/projection revision：保留 Latin/数字词元，对连续 CJK 生成重叠
bigram，文档与 query 使用同一规范化，并用中文短词、混合英文、emoji、引用和错别字 fixture 验证。

### 7.4 Embedding 候选

| 模型 | revision | 许可 | 规格 | 用途 |
| --- | --- | --- | --- | --- |
| `BAAI/bge-small-zh-v1.5` | `7999e1d3359715c523056ef9478215996d62a620` | MIT | 512 维、512 token；单份权重约 95.8 MB | 首选中文轻量本地 baseline |
| `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` | MIT | 1024 维、8192 token、多语言、dense/sparse/multi-vector；权重约 2.27 GB | 较重对照，`defer/spike` |

主仓当前 lock 没有 torch/transformers/sentence-transformers/FlagEmbedding。Embedding 必须放独立
可选依赖组或 worker，固定 model/tokenizer revision 和 artifact hash；不得把大模型运行时加入
Core 基础依赖。真实聊天数据首版不出本机。

一手来源：

- [BGE small zh fixed revision](https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/7999e1d3359715c523056ef9478215996d62a620)
- [BGE-M3 fixed revision](https://huggingface.co/BAAI/bge-m3/tree/5617a9f61b028005a4858fdac845db406aefb181)
- [BGE-M3 paper](https://arxiv.org/abs/2402.03216v5)

## 8. 指标、统计与失败条件

### 8.1 必报指标

| 维度 | 指标 |
| --- | --- |
| 安全 | cross-Scope 泄漏率、过期返回率、删除返回/复活率、Restricted/未授权外传次数，硬目标均为 0 |
| Retrieval | Precision@K、Recall@K、MRR、nDCG@K、LongMemEval recall-any/recall-all；按类型与 Scope 分层 |
| 时间/冲突 | latest/current accuracy、historical accuracy、conflict detection/abstention、stale fact selection |
| 回答 | grounded answer accuracy、evidence citation/support、无依据 Memory 引用率、abstention accuracy |
| 写入 | explicit save precision、敏感拒绝率、重复率、冲突发现率、未送达写入数 |
| 删除/导出 | cascade completeness、重启/重建/restore 复活率、export round-trip、越权导出数 |
| 运行 | index time、P50/P95/P99 retrieval、storage、Context token、模型/Provider 成本、rebuild time |

Retrieval 与 answer 分开报告。30 条 LongMemEval abstention 没有 answer location，不进入 Recall@K，
但进入回答 abstention。LLM judge 需固定 model/prompt/revision，并对分层样本做盲人工复核。

### 8.2 统计

- 预注册 primary metric、`k`、最小有意义 effect、预算与失败线后再跑 final test。
- 相同 query 的策略对比使用 paired bootstrap；群/会话相关样本使用 cluster/hierarchical bootstrap，
  报 95% CI、样本数、cluster 数和 repeated-run variance。
- “0 次观察到泄漏”需报告分母和单侧置信上界，不能宣称真实概率等于零。
- 结果必须绑定 dataset SHA、model/tokenizer revision、index schema、tokenizer、Policy/Ranker revision、
  answer model、Prompt digest、seed 与代码 commit。

### 8.3 硬失败条件

以下任一出现，候选不得进入 shadow/生产：

1. 任意跨 platform/Bot/group/private/user/Persona/MemoryType 泄漏；
2. Index 返回不在授权候选集中的未知/重复 ID、过期记录或 tombstone；
3. Restricted/Sensitive 数据违反 ranker residency/egress policy；
4. 删除未覆盖 primary、lexical、vector、graph、cache、export 或 restore/rebuild 路径；
5. Mem0/Graphiti Spike 产生未批准 PostHog/DNS/网络请求；
6. 自动候选绕过显式 Write Gate，或 recency/模型评分触发自动删除；
7. Graphiti/Mem0 在无精确 Selector 的情况下执行搜索；
8. embedding/hybrid/graph 对 BM25/recency 没有预注册、可重复的稳定增益，或增益不足以抵消
   P95、存储、Token、维护和隐私成本；
9. 缺 dataset/model/config revision、许可记录、可重放 manifest 或错误归因；
10. LoCoMo 被复制进不满足 CC BY-NC 条件的发行物。

## 9. 与现有 MemoryPort 的集成位置

保持既有领域模型和依赖方向，只补齐文档已定义的接口：

```text
AstrBot /remember, /forget, /memory export
  -> application command adapter
  -> MemoryWriteGate or MemoryAdministration
  -> MemoryRepository (authoritative record + tombstone)
  -> lexical/vector/optional graph index projection

Runtime after trusted Actor/ConversationScope
  -> MemoryRetrievalPolicy issues exact ScopeSelectors
  -> MemoryRepository snapshot + exact bounded candidates
  -> optional SemanticMemoryIndex rank IDs only
  -> conflict/sensitivity policy
  -> formal MemoryRetrievalResult
  -> Context Builder
```

S14 实现结果与后续消费者边界：

1. 已在 `memory/models.py`、digests/serialization 与 `ports/memory.py` 落地正式
   rank/retrieval/conflict/delete/admin DTO 和 Port；正式 `MemoryRetrievalResult` 已替换 Runtime
   provisional alias，但 S10 默认 no-memory 行为不变。
2. InMemory/JSON 已通过 delete/export/archive/restore Contract；Iris 无证明能力的 lifecycle
   操作显式 unsupported。S14 没有增加 SQLite/向量/Graph Backend。
3. `DeterministicScopedMemoryRetriever` 永远先由 Repository 产生精确、有界、授权候选，再交给
   ranker；Restricted 在去重前排除，ranker 未知/重复/digest-mismatch ID 整批拒绝。
4. plugin `/remember`、`/forget`/export 与 Context Builder 均未在 S14 迁移；它们属于后续明确
   consumer migration，必须保留 feature flag、legacy rollback 和 Runtime 默认关闭。
5. Mem0/Graphiti/Embedding 仍只保留研究候选，不进入 Core import graph；Iris 解除许可证阻断前
   不实现真实 Backend。

## 10. S14 单人执行顺序

| 顺序 | 工作 | 退出门禁 |
| --- | --- | --- |
| S14.0 | 冻结 snapshot/lifecycle/restore/ranking/Eval Spec | Scope/authority、公式、分母和外部边界明确 |
| S14.1 | 正式 Retrieval/Delete/Admin/Rank DTO、digest、serializer 与 Port | Schema/导入顺序、deadline/cancel/错误契约通过 |
| S14.2 | generation、delete/tombstone/export/archive/restore | CAS/幂等/冲突、round-trip、重启/恢复不复活、故障回滚通过 |
| S14.3 | JSON v1/v2 replay 与 Iris unsupported 边界 | 写/删/恢复证据跨重启；Iris 不产生本地假删除 |
| S14.4 | exact eligibility + M1 recency + 纯 Python CJK BM25 | 全 Scope/TTL/candidate cap、tokenizer/formula/tie-break 和 rank-output 验证通过 |
| S14.5 | 固定 M0-M2 synthetic Eval 与文档回写 | manifest/golden/order 可重放；安全暴露为 0；不声明真实质量 |

Context Builder、旧命令迁移、Embedding/Hybrid、Graph/Temporal Memory、自动写入、自动
reflection/reranker 和生产 Iris 均不属于本次 S14。

## 11. 外部数据与负责人输入

### 11.1 未来可选研究材料（S14 未下载或 vendor）

- LoCoMo 外部 research cache：约 2.8 MB，固定 SHA，附 CC BY-NC attribution；
- LongMemEval oracle：15.4 MB；S：277.4 MB；M：2.74 GB，仅按阶段下载；
- BGE small zh 单份 safetensors：约 95.8 MB；BGE-M3 约 2.27 GB，暂不下载；
- 合成中文多群/多用户/私聊/冲突/TTL/delete/export fixture；
- SQLite FTS5/CJK tokenizer、telemetry-off 和 network-none 可复现实验。

### 11.2 后续需要负责人冻结

1. retention、TTL 默认值、backup 删除/到期窗口和 restore 后 tombstone 策略；
2. 哪些 user-profile 字段允许 `SAFE_USER_PROFILE` 在群聊使用；
3. 是否允许获准脱敏真实聊天进入离线 Eval，以及保存位置/期限/访问者；
4. embedding 必须全本地，还是允许哪些 sensitivity/residency 发送到哪个 Provider；
5. `/forget` 是按 ID、精确内容还是人工选择；模糊关键词只能做候选列表，不能直接批量删除；
6. export 格式、加密/交付渠道和 evidence 是否对用户可见；
7. Iris 旧提交书面许可，或 AGPL 升级/发行评审结论；
8. LoCoMo 非商业限制是否符合项目未来用途；不符合则只保留方法，不运行/分发该数据。

当前阶段不需要 QQ 凭据、真实群号、生产 Memory 文件或外部模型 API Key。没有这些输入不阻塞
Port、Fake、合成 Scope 数据和 M0-M2；它们只阻塞真实数据 Eval、Embedding/Hybrid、Iris 和
生产切流。
