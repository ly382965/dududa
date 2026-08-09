# Production Shape 预检

## 1. 总结判定

**NOT READY：S08-S11 的库级实现和离线测试成立，但当前生产纵向链不可达。**

本结论基于 2026-08-09 对主仓代码、Compose 声明和运行容器元数据的只读检查。没有读取
容器环境变量、QQ 标识或聊天数据，没有发送消息，也没有启动、停止、重启或替换容器。

## 2. 三个 P0 断点

| 断点 | 直接证据 | 实际后果 | 下一阶段修复门禁 |
| --- | --- | --- | --- |
| Rollout Runtime 未装配 | `composition.py:51` 初始化为 `rollout_bridge=None`；生产代码没有调用 `install_rollout_runtime()` | Lifecycle 只在 bridge 非空时处理，所有事件继续走旧路径 | 建立唯一 composition root；默认 off；离线 host smoke 证明初始化、关闭、失败回滚且零发送 |
| temperature 能力冲突 | `perception.py:229`、`direct_chat.py:322` 固定 `temperature=0`；Adapter 在 `model.py:645` 声明不支持并在 `model.py:701` 拒绝非空值 | 真实 AstrBot Provider 请求必然在调用前报 capability mismatch | Runtime 配置默认传 `None`；只有 Endpoint conformance 证明支持时才允许参数；Fake/真实 Adapter 共用 contract tests |
| UNKNOWN 被 Router 排除 | Adapter `health()` 在 `model.py:318` 只返回 `UNKNOWN`；Router `router.py:1162`、`:1179` fail-closed 排除 UNKNOWN | 即使完成 bridge 装配，也没有可选 AstrBot Endpoint | 实现有证据的健康观测和快照新鲜度；初始 UNKNOWN 仍拒绝，探测成功才 AVAILABLE，过期/失败恢复 UNKNOWN |

这三项不能通过放宽 Router、把 UNKNOWN 当作健康或静默丢弃 temperature 来绕过。Router 的
fail-closed 行为是正确的；缺失的是生产 Adapter 能力证据和 composition 装配。

## 3. 建议的 production-shape 离线 Smoke

下一阶段先增加一个 P0 装配门禁，再继续 S12：

```text
AstrBot plugin config (rollout off)
  -> validated endpoint registry + Provider binding evidence
  -> operational health snapshot
  -> StaticModelRouter
  -> Perception + DirectChat + OfflineRuntime
  -> install_rollout_runtime(plugin, runtime, budget, policy_snapshot)
  -> Lifecycle bridge
```

必须覆盖：

1. 配置缺失、Provider 绑定不符、健康未知时 fail closed，legacy 路径不被截断；
2. 合法 Fake/Adapter conformance 下 bridge 非空，但 rollout `off` 仍零模型、零发送；
3. `shadow` 只写脱敏 receipt，不获取 Output capability；
4. canary 在 kill switch、allowlist、重复 claim 和重启恢复下保持单一发送所有者；
5. `terminate()` 关闭 bridge、Provider 和持久资源；部分初始化失败不得留下后台任务；
6. request 中 `temperature=None` 可由当前 AstrBot Adapter 接受；声明支持的测试 Provider 才
   单独验证 temperature 映射；
7. health 从 UNKNOWN -> AVAILABLE -> stale UNKNOWN 的快照转换可重复，Router 决策原因稳定。

在该 Smoke 通过前，不应重新设计 Static Router，也不应声称一个真实 Adapter 已完成纵向接入。

## 4. 当前双 Compose 形态

| 项目 | 当前事实 | 风险/约束 |
| --- | --- | --- |
| 旧 AstrBot | `m.daocloud.io/.../soulter/astrbot:latest`，digest `369164f...`，`[::1]:6185` | 不是 `dududa/astrbot:local`，未挂载主仓 Core；不能证明主仓 Agent 正在运行 |
| 旧 NapCat | 上游 latest 对应本地 digest `9254ec...`，`[::1]:6099` | 与旧 AstrBot 共用旧 bot network 和数据卷 |
| Dududa Web | `dududa/web:local` digest `47b386...`，`127.0.0.1:5173` | 1/1 账号在线；容器仍为旧 Node 20 构建，本 Goal 未切换 |
| 共享 edge | 三者都连接 `mmdustc-edge` | 当前别名唯一时可通信；完整主仓 Compose 会复制旧兼容别名 |

主仓 `compose.yml` 的 AstrBot/NapCat 声明 `bot-astrbot-qq-astrbot`、
`bot-astrbot-qq-napcat`，旧栈已占用同名 edge aliases，并占用宿主 6185/6099。直接执行完整
`docker compose up` 会引入 DNS 多目标或端口冲突，因此本阶段只允许 `config --quiet`。

旧 AstrBot 容器只挂载旧部署数据和一个外部 iCourse 路径，没有挂载本主仓的
`plugins/astrbot_plugin_dududa_core`。Web 容器只读挂载主仓 token 文件。当前 Web 健康状态
只能证明 NapCat -> Web 链路，不证明 Connector -> Runtime -> Router -> Provider -> Output。

## 5. SQLite 生产阻断

运行中 AstrBot 的 Python 是 3.12.13，但 SQLite 是 3.46.1。该版本处于 SQLite 官方
[WAL-reset corruption bug](https://www.sqlite.org/wal.html#walresetbug) 的影响范围
（3.7.0–3.51.2，访问 2026-08-09）。主仓 `SQLiteRolloutLedger` 使用 WAL；未来 Scheduler
还要求双 Worker/CAS，因此这是独立于前三项的 P0 生产安全门禁。

下一阶段二选一并形成 ADR：

- 派生 AstrBot 镜像固定并验证 SQLite 3.51.3+，对真实打包方式做版本 smoke；或
- 首版持久并发路径使用 rollback journal + `BEGIN IMMEDIATE`/CAS，并用两进程故障注入验证。

禁止在当前 3.46.1 容器上进行双连接 WAL 压力或修改生产 Ledger。

## 6. 修复与验证顺序

1. P0：固定派生镜像的 Python/SQLite/依赖版本，新增镜像版本 smoke；
2. P0：让 Runtime 的 sampling 参数与 Endpoint conformance 一致，先支持 `None`；
3. P0：实现可靠 health snapshot，不改变 Router 对 UNKNOWN 的 fail-closed 语义；
4. P0：建立唯一 production composition root 并安装 rollout bridge；
5. P0：在 `--network none` 派生镜像中跑 plugin import、装配、off/shadow 零副作用 smoke；
6. P1：设计从旧 Compose 到主仓 Compose 的端口、别名、镜像和回滚切换清单；
7. 只有上述本地门禁及后续所有模块完成后，才申请真实群聊 shadow/canary。

本 Goal 只记录方案，不实施这些 S12-S20 或生产切换工作。
