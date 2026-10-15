# 更新日志 (CHANGELOG)

本项目所有重要变更均会记录于此文件。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.1] - 2026-06-24

> **⚠️ 重要：本次更新需要重启 AstrBot，否则可能会导致插件加载失败。**
>
> 原因：本版本新增了 `on_llm_request` 钩子中的对话上下文清理逻辑与 UI 偏好设置 Web 路由，二者均在插件加载阶段注册；若不重启 AstrBot 使插件重新加载，新钩子与路由不会生效，且可能与已运行的旧实例产生状态不一致。

### 新增

- **L2 FAISS 索引定期 checkpoint**：新增隐藏配置 `l2_checkpoint_writes`（默认 50），L2 索引每 N 次写入异步落盘一次，把崩溃丢失窗口从「自启动以来全部增量」收敛到「最近 N 次写入」（0=禁用，仅关闭时保存）。此前 FAISS 索引仅在 shutdown 时整体持久化，运行期进程崩溃会丢失全部向量增量，而 SQLite 走 WAL 即时耐久，导致重启后 SQLite 有记录但 FAISS 缺向量、索引与元数据不一致。
- **UI 偏好设置 API**：新增 `iris_memory/web/routes/ui_preferences_routes.py`，将前端 UI 偏好（如深色模式）持久化到后端 JSON 文件。AstrBot 插件页面以 iframe 嵌入 Dashboard，受浏览器安全策略限制 `localStorage` 不可用（sandbox / 第三方存储分区），故改由后端存储，前端通过 bridge API 读写。
- **L2 记忆分页**：L2 记忆列表接口新增 `offset` 参数与 `total_count` 返回，前端 L2MemoryView 实现完整分页功能。

### 变更

- **对话清理策略重构（重大）**：新增隐藏配置 `enable_legacy_cleanup`（默认 `False`）。
  - **默认策略（推荐）**：在 `on_llm_request` 钩子中清空 `req.contexts`，保留对话 ID，使 AstrBot 主动回复（active_reply）能通过 `get_curr_conversation_id` 正常检测到对话存在；Agent 完成后对话历史由 AstrBot 正常保存，下次请求时再次清空。
  - **旧版策略**：在 `on_agent_done` 钩子中调用 `conversationManager.delete_conversation` 删除整个对话，会导致主动回复因 `get_curr_conversation_id` 返回 `None` 而失败，仅作为隐藏参数保留。
  - 两种策略均受 `context_control.enable_conversation_cleanup` 配置控制。
- **图片解析 SSRF 防护增强**：新增 `_GlobalOnlyTransport`（包装 httpx transport，在连接前再次强制校验所有 DNS 解析结果为全局地址）与 `_fetch_image_data_url`（下载图片转为 base64 data URL）。可达性检查与实际下载各自独立解析 DNS，存在 DNS rebinding 窗口（检查时解析到公网、下载时被切到内网），新方案在下载连接前再次强制校验，堵死向内网的 rebinding；同时图片字节转为 data URL，使 LLM provider 不再直连外网 URL。新增 10MB 大小限制，避免大图撑爆 LLM 上下文。
- **L2 检索超时范围扩大**：embedding 计算纳入 `l2_timeout_ms` 超时控制，避免 embedding provider 卡死时在 `on_llm_request` 会话锁内无限挂起。
- **L2 统计查询异步化**：`get_stats` 改走线程池（`asyncio.to_thread` + 新增 `_db_fetchone` / `_db_fetchall` 持锁取数），避免在事件循环线程持同步锁、与 executor 中的长 FAISS 检索争用而阻塞整个插件。
- **遗忘算法简化与修正**：
  - L2 遗忘评分移除恒不触发的 `D > 0` 分支（L2 记忆无 `connected_count`，`calculate_isolation_degree` 恒返回 0），权重统一从隐藏配置读取；
  - KG 验证度 V 由 `min(1.0, source_memory_count / 5)` 改为对数曲线 `log(source_memory_count + 1) / log(6)`（`source_memory_count` 为 0 时取 0），使少量来源即可获得较高验证度，与「`source_memory_count >= 3` 永不淘汰」保护阈值相配合。
- **bot 人格隔离配置说明修正**：`enable_persona_isolation` 的 hint 由「切换会导致记忆、用户画像重建」改为「不同 bot 人格的记忆与画像按人格 ID 逻辑隔离（共享底层存储、命名空间互不可见）；切换人格仅改变可见数据，不删除或重建」。
- **L1 总结解析日志增强**：`parse_summary_response` 新增 `json_parsed` 标记区分 JSON 解析与文本回退；JSON 解析失败时的警告补充模型未按 JSON 输出的提示与更换模型建议；文本回退仅提取到少量记忆时额外输出警告。

### 修复

- **L2 记忆更新并发错乱**：`update_memory` 在嵌入计算（锁外）完成后、写回 FAISS 前，重新校验 `faiss_idx` 归属。此前该记忆可能被并发 `delete_entries` 删除且槽位被 `add_memory` 经 free-list 复用，直接写回旧 `faiss_idx` 会误删并覆盖复用方的新向量，导致 FAISS 与 SQLite 错乱；校验不一致则放弃本次更新。
- **L2 checkpoint 配置未就绪崩溃**：`_mark_dirty` 读取 `l2_checkpoint_writes` 增加异常兜底，配置系统未就绪（初始化早期或测试环境）时仅标记脏、跳过 checkpoint，不再抛异常。
- **前端主题偏好丢失**：修复 Vue 响应式对象跨 bridge 序列化失败问题；主题存储改用后端 UI 偏好 API，适配 AstrBot iframe 嵌入环境下 `localStorage` 不可用的问题。

## [0.1.0] - 2026-06-19

### 安全

- **修复图片 URL 的 SSRF 漏洞**：图片可达性检查新增主机安全校验（仅允许 http/https，通过 DNS 解析拒绝私网 / 环回 / 链路本地 / 云元数据等非全局地址），并禁用自动重定向，防止恶意用户构造图片 URL 探测内网。
- **修复跨群隔离越权**：
  - `save_knowledge` 工具现在按群记忆隔离绑定 `group_id`，与 `search_knowledge_graph` 对齐，避免跨群写入污染其他群的知识图谱；
  - `correct_memory` 的群隔离校验改用正确的记忆隔离配置键 `enable_group_memory_isolation`。
- **修复异常信息泄露**：Web API 与管理指令不再把 `str(e)`（可能含文件路径、SQL/Cypher 片段）回显给客户端，统一返回通用错误消息，详情仅写入服务日志。

### 修复

- **`correct_memory` 误删与数据丢失**：原先用语义检索定位 `memory_id`（几乎必然误命中不相关记忆）、且「先删后写」无回滚。现改为按 ID 精确查询（L2 adapter 新增 `get_entry_by_id`）+「先写后删」，确保写入失败时原记忆不丢失。
- **画像并发丢失更新**：引入 `@profile_lock` 装饰器，按 (persona, group, user) 命名空间串行化所有画像「读-改-写」操作；画像索引更新加独立 `_index_lock`。
- **L2 记忆去重竞态（TOCTOU）**：去重检查与 FAISS / SQLite 写入并入同一锁临界区（新增 `_find_similar_unlocked`），消除「检查通过→释放锁→另一并发写入→重新取锁」的竞态，同时避免原先的重复嵌入计算。
- **图片解析任务泄漏**：超时取消的 pending 任务现被正确 `await`，避免任务泄漏与「Task was destroyed but it is pending」警告，确保 httpx 连接及时回收。
- **图片解析配额静默耗尽**：新增配额退还机制（`QuotaStatus.release` / `ImageQuotaManager.release_quota`），解析失败 / 跳过 / 超时后按实际失败数回补预扣配额。
- **组件系统状态重建竞态**：`SystemStatus` 改为先在局部构建完整对象再原子替换，避免后台组件并发完成初始化时读到半重建状态（如某组件已就绪却被报不可用）。
- **初始化异常静默降级**：`initialize_components` 在异常路径下仍尝试启动不依赖后台组件的定时任务，避免调度任务完全不注册。
- **`ImageCacheManager` 索引竞态**：缓存元数据索引（`hashes` 列表）的「读-改-写」加 `_lock` 保护，避免并发丢失更新。
- **L2 `delete_collection` 未持锁**：数据库关闭与目录清理纳入 `_lock` 保护，避免与并发检索 / 写入交错触发 SQLite 错误。
- **Dream 模块逻辑错误**：
  - 矛盾消解的 `NO_CONFLICT` 判定改为前缀匹配，避免正文包含该子串时误判为无矛盾；
  - 模式挖掘启用此前被忽略的 `dream_pattern_min_confidence` 配置阈值过滤低置信度模式。
- **Token 预算估算偏小**：L2 检索的 Token 估算改用 `count_tokens`，修正原先 `len//2+1` 对中文严重偏小导致预算超用。
- **指令误触发**：`/iris_mem` 指令前缀改用单词边界匹配，避免正文出现「iris_memory」等子串被误判为指令。
- **隐藏配置默认值不一致与热修改盲区**：
  - `forgetting_threshold_kg` 代码 fallback（0.3）与 dataclass 默认（0.2）矛盾，统一为 0.2；
  - `profile_max_messages_for_analysis` 此前群聊 / 用户画像共用同一键、fallback 不一致（50/30），拆分为 `profile_max_messages_for_analysis`（群聊，50）与 `profile_max_messages_for_user_analysis`（用户，30）；
  - `l2_similarity_threshold` 此前仅在 L2 adapter 初始化时缓存，运行时热修改不生效；改为去重时实时读取，恢复「支持热修改」承诺。

### 变更

- **L2 / L3 架构轻量化（重大）**：
  - **L2 记忆库**：由 ChromaDB 迁移到 **FAISS（向量索引）+ SQLite（向量元数据与文本）**，去除 ChromaDB 自带的重型传递依赖，向量维度与召回行为不变。
  - **L3 知识图谱**：由 KuzuDB 迁移到 **SQLite**（关系模型表达节点和关系），去除 KuzuDB 的 C++ 原生扩展依赖，安装包体积与启动时间显著下降。
  - 配套 `2911125`：FAISS + SQLite 的复合操作改用 `RLock` 替代 `Lock`，确保跨组件线程安全。
  - 配套：精简 `CorrectMemoryTool` 节点更新逻辑；`SearchKnowledgeGraphTool` 改用新的 `search` 方法；L2 adapter 新增 `get_entry_by_id` 精确查询能力。
  - 测试与依赖同步更新：`tests/l2_memory/test_adapter.py` 调整用例，`requirements.txt` 移除 `chromadb`、`kuzu`，新增 `faiss-cpu`。
- **统一原子持久化**：新增 `iris_memory/utils/persistence.py`（写入临时文件 → `fsync` → `os.replace`），替换 L2 导出 / 导入、隐藏配置、L2 索引元数据等处此前的非原子覆盖写，避免写入中途崩溃导致文件截断与数据丢失（部分加载逻辑此前会静默丢弃全部数据回到默认）。
- **隐藏配置系统优化**：
  - 默认值调整：`l1_inject_max_content_chars` 200→300（减少注入截断丢信息）、`l2_similarity_threshold` 0.90→0.87（减少重复记忆堆积）、`image_max_parse_per_request` 5→3（与 `image_max_concurrent_parse` 对齐，形成「每批 3 张」统一批次语义）；
  - 硬编码可配化：将遗忘评分权重（L2 四项 + KG 四项）、L2 保留天数 `l2_retention_days`、KG 衰减系数 `forgetting_lambda_kg`、合并检索 `dream_consolidation_query_top_k` 共 11 项原硬编码魔法数字提升为隐藏配置项；
  - 死代码清理：移除从未被读取的预留配置 `l2_max_entries`、`l3_max_nodes`、`l3_max_edges`。

### 开发与质量

- `requirements.txt` 修正：移除代码未使用的 `PyJWT`，补充实际依赖但未声明的 `httpx`。
- 全量通过 `ruff check` 与 `ruff format`（共修复 62 处 lint 问题）。
- 新增与本次改动的代码通过 `pyright` 类型检查（0 错误）。
- 单元测试与组件测试 **617 项全部通过**。

### 已知技术债

- 全项目 `pyright` 仍有约 195 个既有类型标注告警（Optional 未判空、参数类型、Dict 当对象访问等），为长期累积、不影响运行时，将作为独立技术债迭代。
