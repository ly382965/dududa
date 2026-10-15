# S21 Bot Control Plane 离线完成审计

日期：2026-08-14

## 1. 结论

S21A Control Plane Foundation、S21B Group Onboarding、S21C Governed Operations
和 S21 Completion Audit 已完成既定离线工程范围。

这意味着 Dududa 已有一条可执行的受治理控制链：Bot 入群后先保持零 Agent 服务，授权管理员
选择版本化 `GroupServiceProfile`，Core 计算 Desired/Effective，提交不可变 Assignment，Runtime
只读取当前有效 snapshot；Web 负责呈现事实和提交专用命令，不拥有权限、健康、Capability 或
发送权。

这不表示真实群、真实 Provider、真实 Source、生产身份系统或在线 Bandit 已完成。S23 继续
暂停，只有外部适配、人工质量和逐行为授权准备好后才能恢复。

## 2. 设计哲学如何落地

> Dududa 是受治理的群体情境适应 Runtime。模型、插件、群体情境和 Bandit 都只能在治理内核
> 给出的合法候选中工作，不能改变身份、Scope、Capability、Assignment 或发送权。

S21 将这条原则具体化为四层分权：

| 层 | 拥有的权力 | 明确不拥有 |
| --- | --- | --- |
| Web Control Plane | 展示权威投影、选择初值、提交专用命令、展示 Receipt | 本地推导 Effective、健康、权限或发送成功 |
| Control Plane Core | operator session、RBAC、Scope、CAS、命令、Audit/Receipt、Assignment/LKG | 模型选择、MCP 传输和 QQ 发送实现 |
| Runtime | 读取不可变 Effective Assignment | 猜测或扩宽管理员选择的服务 |
| Model/Plugin/Context/Bandit | 产生候选、证据或合法集合内的排序 | 开服务、授予 Capability、写 Assignment、取得发送权 |

## 3. S21 分支状态

| 阶段 | 状态 | 主要交付 |
| --- | --- | --- |
| S21A Foundation | 已完成、已验证 | Profile/Assignment、join/pending、operator session/RBAC、Query/Command、Projector、Audit/Receipt、Fake join/service |
| S21B Group Onboarding | 已完成、已验证 | Profile Catalog、Desired/Effective、Preview/Activate/Update/Pause/Resume/Rollback、SQLite CAS/LKG、重启恢复、Runtime snapshot、群服务 Web 页 |
| S21C Governed Operations | 已完成、已验证 | 六面运维投影、Model 与 MCP/Capability 快照适配、明确 unavailable、Python/Node/Web 查询链、专用 mutation discovery |
| S21 Completion Audit | 已完成、已验证 | command ID 全局唯一、SQLite 等锁后 deadline 重验、Agent no-send、浏览器只读设置、组合抽样和中文状态同步 |

## 4. 完成定义逐项证据

| 要求 | 结论 | 证据边界 |
| --- | --- | --- |
| 新群无 Profile 时零服务 | 通过 | pending record 不产生 Runtime Assignment；Fake join 后 snapshot 为 `None` |
| 只有授权管理员可操作 | 通过 | operator session、Bot/Group Scope、RBAC、过期/未知 session 负向用例 |
| Desired/Effective 可解释 | 通过 | Service Catalog 依次过滤 installed、health、grant、rollout，并保留稳定 reason code |
| Profile 不自授 Capability | 通过 | Profile 只引用业务 service ID；Capability Registry 与 MCP Registry 继续独立 |
| CAS、幂等、唯一命令 | 通过 | stale revision/并发仅一个成功；idempotency replay 返回同一结果；command ID 跨 preview/assignment 全局唯一 |
| Audit 与 Receipt | 通过 | 成功 mutation 原子保存业务结果、Audit 和 Receipt；原始 session/操作者身份不落投影 |
| 重启与 LKG | 通过 | SQLite history/current snapshot 跨实例恢复；rollback 使用当前资格重算，不能恢复已撤权服务或循环回滚 |
| 超时后不迟到写入 | 通过 | SQLite 取得 `BEGIN IMMEDIATE` 写锁后重新验证 cancellation/deadline，过期调用回滚且不生成 onboarding |
| 运维投影不伪造状态 | 通过 | Model 使用缓存 Registry/Health；MCP/Capability 缺缓存健康时为 degraded；未绑定面为 unavailable |
| Web 不成为第二权威 | 通过 | Python DTO 定义状态，Node 原样代理，Vue 不推导权限/健康/Effective；运维失败不复用旧浏览器结果 |
| Agent 与真人 QQ 分离 | 通过 | Agent Draft 不调用 NapCat；permission 不改本地成功状态；settings 为无事件只读控件；真人聊天发送路径保持不变 |
| 学习组件不能扩权 | 通过 | mutation catalog 只有现有 Group Service 专用 action；Model/Plugin/Context/Bandit 没有 Assignment 或 Output 写入口 |

## 5. 本次审计修复的具体问题

1. 同一个 `command_id` 原先可在不同 idempotency key、甚至 preview/assignment 两张表中重复成功。
   现在内存 Repository 使用统一 command ID 集合，SQLite 使用事务内统一 ledger。
2. SQLite 原先可能在等待写锁期间越过 deadline，取得锁后仍提交配置。现在每个写事务取得锁后
   再验证一次调用上下文，过期或取消即回滚。
3. Agent Console 原先虽禁用控件，但仍保留 `v-model` 和点击处理器。现在配置只使用
   `:value/:checked` 展示，禁用按钮没有 mutation handler。
4. S21C 前置审查已修复 rollback 绕过当前资格、paused update 污染 LKG、重复 rollback 和 Web
   切群丢失最新 Assignment。

这些修复都对应已复现事故；没有新增 hash、contract freeze、第二套 baseline 或泛化 gate。

## 6. 数据使用边界

- 本机当前“嘟嘟哒”账号收到的数据已获准用于开发、离线回放和 no-send Shadow。
- 旧账号 `1778159807 / 萌萌哒mmd` 继续排除。
- 原始正文、QQ/群号和媒体地址不得提交 Git。
- S21 没有修改 Connector、历史分页、Perception 或会话投影，因此本次没有读取或重跑聊天语料。
- 外部数百群长期记录继续只在 S23 隔离测试环境提供。

## 7. 抽样验证

本次按风险抽样，不重复全仓矩阵：

- Python：14 个 Control Plane 用例与 4 个相关 import-boundary 用例通过；
- Ruff：受影响 Core、Port、Adapter 和测试通过；
- Node：Control Plane client/server 36 项通过；
- Web：App、ControlPlaneView、useWorkspace 16 项通过；
- Build：Vue/Node typecheck 与 production build 通过；
- E2E：移动端真人 QQ 与不可用 Agent Runtime 分离场景 1 项通过；
- `git diff --check` 通过。

## 8. S23 仍需外部输入

1. 生产 Core HTTP 与 operator identity/session 适配；
2. 真实 Provider、Source、Group Projection 和 Output Adapter 及 Conformance；
3. 外部数百群长期语料的隔离只读挂载、时间范围和去标识规则；
4. 人工标注方案，以及相关性、正确性、风格和打扰度样本；
5. 真实 Endpoint 凭据与成本/限流参数，但不得提交仓库；
6. 明确分开的 no-send Shadow、显式 @ Canary、手动日报、定时日报和低频 Probe 授权；
7. 在线 Bandit 仍需 before-action propensity、反馈归因、同安全档 action support 和单独授权。

在这些输入到位前，保持 no-send、主动行为默认关闭、在线 Bandit 不运行，并停止在 S23 门前。
