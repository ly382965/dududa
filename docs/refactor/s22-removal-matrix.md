# S22 兼容面移除矩阵

更新时间：2026-08-10
基线：S19 candidate `e303dc86fc4bf6ff2c3ccbc08e23e6fbcee29af7`

## 结论

S22 处理了 S19 固定 catalog 中的全部 18 个兼容面：十个路径别名和插件专用 iCourse
Client 已删除；两个根操作入口及五个仍有真实消费者的兼容面保留。S19 catalog 继续作为
pre-S22 历史证据，不因本次结论而改写。

## 决策矩阵

| S19 surface | S22 决策 | 当前证据或保留原因 |
| --- | --- | --- |
| `root-env-link` | 删除 | CI、管理脚本和当前文档均使用 `deploy/env/.env.example` |
| `root-config-link` | 删除 | Persona fixture 与所有模板消费者使用 `configs/` |
| `root-docker-link` | 删除 | Compose、CI 和文档使用 `deploy/docker/` |
| `root-plugins-link` | 删除 | 测试通过 canonical `apps/astrbot-plugins` bootstrap 导入 |
| `root-scripts-link` | 删除 | 根 wrapper 转发 `ops/`，当前命令使用 `ops/cli/` |
| `root-patches-link` | 删除 | v1 lock 与安装器使用 `third_party/patches/` |
| `root-vendor-link` | 删除 | v1 lock 与安装器使用 `third_party/vendor/` |
| `root-plugin-lock-link` | 删除 | 唯一 v1 authority 为 `third_party/plugins.lock.json` |
| `legacy-icourse-service-link` | 删除 | Docker、Compose、Spike 和文档使用 `services/mcp/icourse/` |
| `legacy-unified-worker-link` | 删除 | 双锁、CI 和测试使用 `services/mcp/unified-worker/` |
| `legacy-icourse-client` | 删除 | 插件只构造 Unified facade 或 fail-closed unavailable facade；无 MCP SDK stdio 旁路 |
| `root-manage-wrapper` | 保留 | 稳定 operator CLI，单向转发 `ops/manage.sh` |
| `root-compose-wrapper` | 保留 | 稳定 Compose 入口，与 canonical Compose 渲染逐字节一致 |
| `legacy-astrbot-handler` | 保留 | `off/shadow` 下仍由旧 Handler 持有发送权，直到 S23 切流 |
| `legacy-role-policy` | 保留 | 当前插件权限、TargetTalk 和 ReplyPolish 仍消费该策略 |
| `legacy-memory-json` | 保留 | 生产 `/remember` 尚未迁移到 S14 Memory v2 |
| `legacy-mcp-protocol-mode` | 保留 | 隔离 worker 仍需以 legacy protocol 连接 iCourse MCP v1 Server |
| `legacy-audit-identities` | 保留 | AstrBot `AuditLog` 与 S18 Runtime Trace 语义不同，尚无生产迁移 |

已持久化 `.dududa-lock.json` 中的旧 patch/vendor marker 仍在读取时归一化。这是数据兼容，
不是旧文件系统路径的消费者，也不授权重建 symlink。

## 回滚证据

- 精确 source archive：`/tmp/dududa-s22-evidence/s19-e303dc8.tar`
- archive commit：`e303dc86fc4bf6ff2c3ccbc08e23e6fbcee29af7`
- archive SHA-256：`80500b51187905a45801e195a3d906adac2b11fcbced172a0657e3f00386dc77`
- archive mode/size：`0600`，`10,506,240` bytes
- S19 candidate receipt：`sha256:ec2ecdfafeb765474b999efc3708ac29aeab5c52470e15f4d72e0116ce6c8790`

回滚恢复整个 S19 Release，不在当前代码上临时重建路径别名或插件直连 Client。

## 验证摘要

- Python 3.12：完整仓库 `651 tests OK`，2 个 AstrBot-host-only skip；
- Python 3.10：32 个 S22 风险样本通过，2 个 AstrBot-host-only skip；
- 隔离 worker：2 tests 通过；根 worker/Capability 契约 11 tests 通过；
- 派生 AstrBot 镜像：`sha256:ca19efc3d7d6a1fc608f34ee80e057502b35143ed72619988ef9f6df1dbc5c0a`，
  无网/只读 smoke 证明 `unified/unified_ready`、MCP 1.29/2.0 隔离和 19 个插件测试；
- wheel、首次 import、`pip check`、根/canonical Compose 等价、secret scan 824 files、双锁、
  Shell、JSON、compile 和 whitespace 均通过；
- Web、完整 Eval 和 30 日调度矩阵未重复运行，因为 S22 未修改这些表面，沿用 S19 候选证据。
