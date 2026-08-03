# Dududa 2.0 重构进度

更新时间：2026-08-02
历史基线：`main@2767cc9768d4bce63d4b4ee811add951ebce6870`

## 当前结论

- Phase 0–1 的审计、目标设计和迁移计划已完成。
- S01–S07 的**增量实施步骤已完成**，S08 是下一步。
- 对应产品模块仍是**部分完成**：旧 AstrBot Handler 继续处理生产消息，尚无新 Runtime
  Orchestrator、State Store、shadow、canary 或选择性切流。
- S04、S06、S07 新路径默认关闭；未迁移、改写或读取生产 Memory。
- 本文是当前实施状态的权威台账；`docs/design/` 保存冻结 Spec，历史基线文档不随实现结果
  改写。

“步骤完成”表示该步骤约定的代码、负向测试和退出门禁已通过，不表示产品模块满足统一完成
定义。模块只有具备真实 Adapter、端到端故障/取消/超时证据、生产 feature flag、shadow、
选择性切流和可执行回滚后，才能标记为完成。

## S01–S07 实施状态

| 步骤 | 状态 | 已交付 | 明确未做 |
| --- | --- | --- | --- |
| S01 核心 Package | 已完成 | 可安装 `dududa-agent`、不可变领域 DTO、Runtime State、错误和严格配置；Python 3.10+ | Orchestrator、State Store、生产 Event 接入 |
| S02 契约与 Port | 已完成 | canonical codec/golden vectors、N/N-1 reader、Port binding、Protocol、Fake 和 Contract harness | 冻结仅由 Fake 证明的后续接口 |
| S03 安全基础 | 已完成 | Actor/Scope、默认拒绝 Authorization、Confirmation、Limiter/Budget、Content Safety、Redaction、Audit、幂等和 typed config | 替换旧插件权限入口或改变中文错误文案 |
| S04 Connector/Output | 已完成 | AstrBot Input Connector、Output Adapter、Attachment Repository、Delivery Receipt、引用/@/附件和去重 fixture | 第二平台、真实 Attachment Source、跨 Runtime 原子去重、模型调用 |
| S05 插件拆分 | 已完成 | Core 薄入口、命令/生命周期拆分、TargetTalk/ReplyPolish 纯逻辑；插件 ID、命令、Decorator 和 priority 保持 | 删除旧 Handler、目录迁移、Runtime 切流 |
| S06 Memory 安全边界 | 已完成 | MemoryScope/Selector/Record/Repository、显式 Write Gate、内存/JSON 参考 Adapter、隔离矩阵 | embedding、Graph、Reranker、自动摘要或自动写入 |
| S07 Iris/迁移边界 | 已完成 | fail-closed Iris Protocol Adapter、缺 metadata 隔离区、backup/dry-run/receipt/rollback CLI | 真实 Iris SDK Backend、生产数据迁移、语义检索、Runtime 接入 |

## 产品模块完成度

| 模块 | 状态 | 判断依据 |
| --- | --- | --- |
| 核心 Package | 部分完成 | Package、DTO、State、Port 和测试已完成；Orchestrator/State Store/切流未完成 |
| 安全组件 | 部分完成 | v2 组件及负向测试已完成；生产仍使用兼容权限入口，尚未贯穿新 Runtime |
| Connector / Output / Attachment | 部分完成 | 单 Adapter 契约已完成；真实附件读取、持久去重和生产 Bridge 未完成 |
| Memory | 部分完成 | 安全边界与迁移工具已完成；真实 Iris、Context Builder、生产读取/写入未完成 |
| 插件拆分 | 部分完成 | 源码拆分和真实 AstrBot registry 已验证；旧 Handler 仍是权威入口 |
| 模型路由、语义理解、OC Runtime | 未完成 | 仅有冻结设计；从 S08 开始实现 |
| Unified MCP / Capability Runtime | 部分完成 | 现有 iCourse Server 和 10 个工具可用；统一 Client/Registry/Planner 尚未实现 |
| Bandit、WebUI、真实群聊放量 | 未完成 | 只有计划与安全边界，无实现或线上证据 |

## 2026-08-02 验证证据

| 门禁 | 结果 |
| --- | --- |
| 宿主机完整测试 | Pass：116 tests，2 个仅因宿主机无 AstrBot 跳过 |
| Python 3.10 动态测试 | Pass：同一干净 wheel 安装后 116 tests，2 个 AstrBot-only 跳过 |
| 静态导入与格式 | Pass：Ruff check；80 个 S01–S07 Python 文件无需再次格式化 |
| Python 编译 | Pass：Package、插件、服务、脚本和测试 |
| Shell | Pass：`manage.sh`、`setup_dev.sh`、iCourse setup/start 脚本 |
| Compose | Pass：解析后只有 `astrbot`、`napcat` |
| 仓库安全扫描 | Pass：216 个 tracked/untracked 文件，无凭据或运行数据 |
| 干净 wheel | Pass：`dududa-agent==0.1.0a1`；根包加 55 个子模块可导入；含 `py.typed`，不含 `.pyc`；`pip check` 通过 |
| Memory 迁移入口 | Pass：脚本 mode `100755`、`--help`、4 个 apply/rollback fixture |
| 派生 AstrBot 镜像 | Pass：无缓存重建；镜像 ID `sha256:9a8831c8cbca26d21b797db398a4b8d241d2c324b41c61fc868d968acb036e9d` |
| 镜像 Package | Pass：Python 3.12、`dududa==0.1.0a1`、55 个子模块、`py.typed` 和 `pip check` |
| 镜像 AstrBot 测试 | Pass：6 tests，无 skip；Core / TargetTalk / ReplyPolish registry 为 `42 / 1 / 1`，`natural_course_query` priority 为 8 |
| iCourse MCP | Pass：`--network none` 下发现 10 个工具，空库 `icourse_stats` 成功 |
| 干净启动 | Pass：隔离网络、随机端口和一次性数据目录中启动 AstrBot 4.26.2，并加载四个自研插件；实例和临时网络已清理 |
| 空白检查 | Pass：`git diff --check`；另对未跟踪的 S01–S07 交付范围执行尾随空白扫描 |

镜像构建从 digest-pinned AstrBot 基础镜像开始，但 iCourse 的开放版本依赖仍会在线解析；上表
记录本次产物证据，不把它描述成完整的供应链锁定。

## 已收紧的边界

- 所有 55 个子模块可以作为首次导入，顶层惰性导出不再产生循环依赖。
- 核心 Package 只依赖 Python 标准库和内部模块，不导入 AstrBot、模型、MCP 或 Iris SDK。
- Runtime、canonical/binding、Security、Connector/Output/Attachment 和 Memory 的 digest、
  Scope、权限、幂等、deadline/cancellation 与不可变集合均有负向测试。
- 多角色授权不能把一个角色的 permission 与另一个角色的资源约束拼接；
  `SecurityConfig.role_constraints` 是 v2 严格配置的必填映射，缺失或不匹配默认拒绝。
- Memory 等待会响应 deadline/cancellation；Iris 后端写入被取消时回滚本地 record、
  decision 和 idempotency 状态。
- JSON Memory 临时文件使用独占、no-follow 创建；预置 symlink 不会覆盖其目标。
- Attachment 有界流在 token 或调用任务取消后回收 `__anext__` 子任务。

## 残余边界

1. **生产入口未切流。** `astrbot_plugin_dududa_core.main` 仍注册并委托旧 Handler；当前没有
   Agent Runtime Orchestrator、RuntimeStateStore、shadow、canary 或 kill switch 证据。
2. **Attachment Actor 绑定不完整。** `AttachmentAccessRequest` 没有独立 `Actor` 字段；当前
   只能验证 `AuthorizationDecision.actor_digest`，Repository 没有第二份当前 Actor 做交叉核对。
3. **去重只完成键和单 Adapter 语义。** `(platform, bot_id, conversation_id, message_id)` 四元键
   已定义并测试；跨进程/跨 Runtime 原子唯一约束和 tombstone 留待 State Store。
4. **真实附件读取未实现。** AstrBot 组合层使用 fail-closed `RejectingAttachmentSource`，不会
   静默丢弃或越权读取附件。
5. **真实 Iris 未接入。** 当前只有 `IrisBackend` Protocol、fail-closed Repository 和 Fake
   Backend 契约测试；仓库没有 Iris SDK 实现。
6. **生产 Memory 不变。** 旧 `/remember` 仍写旧 JSON；Memory v2 自动读取/写入均关闭，迁移
   CLI 只允许离线显式执行。
7. **Hook 证据分层。** 宿主机两个 AstrBot 测试会 skip；真实 Hook 证据来自本次重建镜像，
   不能把宿主测试与镜像 smoke 合并成同一结果。

## 下一步

严格进入 S08：实现单 Provider、`PERCEPTION`/`DIRECT_CHAT` 两角色的静态 Model Router，
先完成 descriptor、隐私/预算/健康硬过滤、错误映射、fallback 和共享 Contract Test。
S08 不接生产 Event，不实现多 Provider 优化、图片角色或 Bandit；通过后再进入 S09。

## 历史基线

2026-07-18 的 Phase 0–1 基线为 8 tests、Compose 两服务、六个锁定第三方插件、派生镜像和
网络禁用 MCP 握手通过。该结果保留在 `baseline.md`，只用于比较，不再代表当前实现状态。
