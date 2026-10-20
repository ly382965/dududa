> 本记录描述 Codex 时期的 3.0（Agent 由本机 Codex CLI app-server 执行）；3.1 已改用 omp，现行部署见 [3.1 运维手册](v3.md)。

# Dududa 3.0 验证记录 · 2026-10-15

本次验证从 **3.0 Runtime** 进入，实际调用本机 Codex CLI，通过原生 MCP 执行业务，再重建 Runtime 与 Codex 进程验证 thread 恢复。未用 2.0 Runtime 或固定模型答案代替真实链路。

## 环境与结果

| 项目 | 记录 |
| --- | --- |
| Runtime 标记 | `dududa-3.0` |
| 验证模式 | `real-local-codex` |
| 本机 CLI | `codex-cli 0.153.0-alpha.5` |
| 实际模型 | `gpt-6-astra` |
| 正式脚本内真实 Codex run | 2 次 |
| 正式脚本整体结果 | `passed: true` |
| 真实 QQ 消息发送 | 0 条 |
| 本地机器可读报告 | `runtime/v3/verification.json`，运行产物，不提交到源码 |

正式验证命令：

```bash
uv run --locked python ops/cli/verify_dududa_v3.py --output runtime/v3/verification.json
```

该入口没有 stub 开关，失败时返回失败；不会改走 2.0。报告可在本机重新生成，需要可用的 Codex 认证及模型网络，运行会产生真实调用。

## 新 Runtime 的真实执行

| 场景 | 结果与证据 |
| --- | --- |
| 规则 `/ping` | 通过；走 3.0 规则路径，未启动 Codex |
| 规则校车查询 | 通过；直接调用共享校车服务，未启动 Codex |
| Codex 多步工具调用 | 通过；实际调用 `memory_search` 与 `shuttle_query`，耗时 75,922 ms |
| 持久化 thread 恢复 | 通过；重建 Runtime 与 Codex 进程后恢复同一 thread，耗时 75,060 ms |
| 会话和预览隔离 | 通过；验证正式会话与预览范围相互隔离 |

多步任务和恢复任务使用同一 thread：`01a13f4a-0796-71e1-99f8-124408959253`。两次 turn 分别为 `01a13f4a-0864-7c72-a3ef-2a3c485dcf2e` 与 `01a13f4b-30a3-7fb2-be2b-7a93f1571222`，见本地报告。

另外完成了本机 Codex 调用 `services_list` 的独立验证，约 48 秒，成功返回工具目录；之后恢复该 thread 再次调用同一工具，约 40 秒完成，工具调用正确归属于新的 run。两次均不计入正式脚本的两次 run。

上述耗时是本次环境中的单次观测，包含模型与工具处理，不是延迟承诺。校车使用仓库内版本化静态资料，没有验证学校是否发布了更新的班次。

## HTTP、适配器与自动化检查

实际启动了新的 Python HTTP Host，由 Web 的 `HttpRuntimeV3Client` 跨进程调用：

- `/ping` 返回 `runtime=dududa-3.0`、`route=rule`、`status=completed`。
- 预览 `/remember` 返回规则结果；直接检查真实 SQLite，指定测试记忆前后均为 0 条。
- 两次任务均未产生 QQ 投递记录。

自动化检查：

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| `python -m unittest discover -s tests/v3 -v` | 31 项通过 | 新 Host、规则、会话、权限、MCP、协议、错误、取消、上下文计数及无副作用检查 |
| Ruff | 通过 | 新 Runtime、3.0 测试和真实验收脚本 |
| Web `npm test` | 304 项通过 | Web 与服务端测试，包括新版适配器 |
| Web 类型检查与构建 | 通过 | TypeScript / Vue 检查及生产构建 |
| 4:3 架构图 | 通过 | SVG 尺寸 1600 × 1200，浏览器实际渲染并检查文字布局 |

协议测试使用明确的测试进程来覆盖 App Server 事件和错误，不能单独证明模型可用；真实模型证据来自上面的正式脚本。2.0 的历史 100 条基准、MCP 查询及录制结果未计入本次统计。

## 尚未验证的范围

本次没有向真实 QQ 会话发送消息，没有切换或部署线上机器人；QQ 实际登录、触发和发送仍需在明确开放的测试会话中验收。

没有逐项访问所有公网校园服务，也没有验证私有 CAS、研究生作业提交、助教汇报或通知订阅。后者仍属于封存的 2.0 功能。规则校车和 Codex 多步查询的成功，不代表这些业务已经迁移。

启动和重新验证见 [3.0 操作说明](v3.md)，实现边界见 [Runtime 设计](../design/dududa-3.0-runtime.md)。
