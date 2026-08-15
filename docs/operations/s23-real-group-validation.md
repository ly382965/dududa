# S23 单群真实场景验证 Runbook

## 1. 当前状态

S23 是发布前的真实证据阶段，不是默认上线。S17-S20、S22 和既定 WebUI 回归已经完成本地范围；
S23 分支也已补齐配置驱动的入站生产 Runtime 纵切，但当前只用 Fake AstrBot Provider 做过聚焦
契约验证：27 项最终抽样在 1.005 秒内通过，此前 6 项冒烟在 0.196 秒内通过。它仍只能执行
离线 readiness 与 no-send 验证：

- `configs/release/s19-pilot-slo-v1.json` 仍为 `s23_ready=false`；
- 没有完成 conformance 的真实模型 Endpoint；
- 没有校园、arXiv 或行业资讯的 live Source Adapter；
- 没有生产 Probe Projection/Output composition；
- 没有单群授权、私有 SecretRef 绑定或部署窗口。

在这些门禁关闭前，不读取真实群消息、不修改运行中的 NapCat/AstrBot、不调用真实模型或来源，
也不发送 QQ 消息。iCourse 是评课社区 MCP，不能作为资讯日报来源。

当前入站 production shape 的边界如下：

- `runtime_enabled` 默认 `false`；关闭、配置非法或 AstrBot Provider 无法解析时回退 legacy；
- `runtime_models_json` 只声明实际接入的 1–3 个 Haiku/Sonnet/Opus Endpoint，API Key 仍由
  AstrBot Provider 管理；
- Dududa Core 继续拥有 Tier、预算、Runtime 状态和 rollout 所有权；Provider 只实现模型调用 Port；
- 首版使用 rule-only Perception，`off` 零 Provider 调用，`shadow` 每条消息只产生一次候选回答
  Provider 调用，且不 claim、不调用 Output；
- `conformance_verified=true` 只是 Builder 输入，不是本 Runbook 第 5 节要求的真实 Conformance、
  health、Release 绑定或授权证据。

## 2. 固定验证阶梯

同一个授权群按下列顺序逐级执行。每一级使用新的 manifest 和 Grant，只有操作员审核上一阶段的
脱敏 Receipt 后才能晋级。

| 阶段 | 允许行为 | 关键门禁 |
| --- | --- | --- |
| Preflight | 只核对配置、证据和私有引用 | 不读群、不调用 Provider、不发送 |
| Shadow | 读取授权时间窗并运行真实理解/路由链 | Output、Memory、Tool write 均为 0 |
| Inbound Canary | 批准测试用户结构化明确 `@` 后回复 | 固定请求/消息预算，逐条核对投递结果 |
| Manual Digest | 操作员触发一次日报 | live 来源、引用、新鲜度、目标和预算通过 |
| Scheduled Digest | 激活一个有界 occurrence | 手动日报先通过；时区、quiet hours、misfire、退订通过 |
| Probe Canary | 低频群级主动消息 | 不 `@` 个人、不读个人 Memory、不自动追问，冷却不少于 24 小时 |
| Closeout | 关闭全部 Canary 并清理证据 | Receipt 对账、删除/保留、kill switch 和回滚完成 |

3-5 群扩展不属于本轮。单群 Closeout 后必须重新授权，不能继承原 Grant。

## 3. Readiness Manifest

提交模板位于 `configs/release/s23-readiness.template.json`。真实 manifest 建议放在仓库外的私有
运行目录；仓库和 manifest 都只保存 opaque reference 和 digest，不保存真实 QQ/群/用户 ID
或凭据值。

manifest 绑定：

- candidate、上一 release 和回滚 archive 的精确 digest；
- 单独冻结且 `s23_ready=true` 的 SLO policy ID/digest；
- Bot、单群和测试用户的私有引用；
- 部署授权窗和独立的群数据可读窗；
- 用途、保留期限、删除负责人和私有 audit sink；
- OneBot 与 Provider 的 SecretRef；
- Endpoint conformance、健康、路由目录和启用 Role/Tier；
- 当前阶段独立 Grant、预算、quiet hours、kill switch 和停止策略；
- 后续阶段需要的前序 Receipt、Source、Schedule 或 Projection 证据。

模板本身是合法 JSON，但必须 fail closed。离线检查命令：

```bash
PYTHONDONTWRITEBYTECODE=1 \
  uv run --locked python ops/cli/validate_s23_readiness.py \
  --manifest configs/release/s23-readiness.template.json \
  --at 2026-08-11T12:00:00+08:00
```

退出码含义：

| 退出码 | 含义 |
| --- | --- |
| `0` | 当前阶段 manifest 结构完整且处于有效窗口；不代表真实证据已解析或允许执行 |
| `1` | JSON、字段、类型、digest、时间或 IANA timezone 非法 |
| `2` | manifest 合法但仍有 readiness blocker |

报告只包含 manifest identity digest、阶段、时间、digest 和稳定 blocker code。字段
`validation_scope=manifest_only` 且 `live_execution_authorized=false` 始终成立：离线脚本不会把
自声明的证据 digest 升级为真实授权。它不会解析 Secret、读取群聊、连接 Provider/来源、检查
容器或输出私有引用值。

## 4. 外部输入和私有绑定

Preflight 前由操作员提供：

1. 单个 Bot/群和测试用户引用、数据可读窗、有效期不超过 7 天的部署授权窗；
2. 数据用途、保留期限、删除负责人和私有审计位置；
3. 至少一个真实模型 Endpoint 的公开能力目录及私有 Provider SecretRef；
4. OneBot/NapCat 私有连接引用和 SecretRef；
5. 各阶段独立预算、quiet hours、kill-switch 负责人和停止条件；
6. 允许配置/重启当前实例的部署窗口，或一个隔离测试实例。

真实 Secret 值和 QQ 标识映射只进入本机私有部署配置或 Secret Store。不得写入 Git、命令行
参数、普通日志、Receipt 或 readiness 报告。

以下 digest 由工程命令生成，操作员不手工伪造：release/archive、SLO、stop policy、Endpoint
conformance/health/catalog、Source/Projection evidence 和前序阶段 Receipt。

## 5. Preflight

Preflight 在任何真实群读取前完成：

1. 验证 candidate 和上一 release 均可恢复，rollback archive 可读且校验一致；
2. 验证冻结 SLO 的 policy ID/digest，全部安全计数上限为 0；
3. 在私有进程中解析 Bot、群、测试用户和 SecretRef，确认引用均指向同一授权环境；
4. 对实际启用 Endpoint 执行 conformance、健康和 Role/Tier 绑定检查；
5. 检查系统时钟、IANA timezone、授权窗、数据可读窗和保留期限；
6. 检查行为 kill switch 和精确回滚命令，但不执行破坏性 restore；
7. 运行 readiness checker，只有退出码 `0` 才能进入该阶段。

完成第 4 步后，才允许把真实 Endpoint 对应的 AstrBot Provider ID 写入私有部署配置并打开
`runtime_enabled`。仓库内 Fake Provider Contract、历史 HTTP 200 最小探测或配置中的
`conformance_verified` 字段都不能替代该步骤。

Preflight 失败时修正输入并重新生成证据。不得通过删除 blocker、使用 fixture digest 或把
`s23_ready` 直接改为 `true` 绕过。

## 6. Shadow 和入站 Canary

### 6.1 Shadow

Shadow Grant 必须满足：`output_enabled=false`、`max_messages=0`、`memory_allowed=false`、
`allowed_capabilities=[]`。只读取 manifest 绑定的数据窗，运行真实 Connector、Perception、Tiering
和 Router 路径，记录低基数统计与 digest。

退出前核对：

- Output 调用、Capability 调用、Memory 读写均为 0；
- wrong target、cross-scope、sensitive trace 均为 0；
- Router 只选择 manifest 允许的 Endpoint；
- 原始消息、Prompt、回答和 Provider error body 未进入提交证据。

操作员审核 Receipt 后，签发新的 Inbound Grant。

### 6.2 Inbound Canary

只接受同一群内、批准测试用户发送的结构化明确 `@`。Memory 保持关闭，Capability 只能来自
Grant 的只读 allowlist。每个请求和 Delivery Receipt 必须一一对账；超预算、非测试用户、非明确
`@`、过期 Grant 或未知投递结果立即停止该阶段。

## 7. 日报 Canary

Manual Digest 需要至少一个批准的 live Source Adapter。Source evidence 必须绑定官方来源、
许可证/条款、allowlist、provenance、freshness、revision、引用和去重策略；fixture 和 iCourse
不能替代 live 证据。

先执行一次手动 occurrence，核对目标、条目数、字数、引用、新鲜度和 Delivery Receipt。通过后
才签发 Scheduled Digest Grant，并额外绑定 IANA timezone、发送时刻、quiet hours、misfire、
每日上限、暂停/退订负责人和 schedule policy digest。

## 8. Probe Canary

Probe 只能在入站、手动日报和定时日报均通过后开始。它需要真实且脱敏的群级 Projection
Adapter evidence，并满足：

- 目标是群，不是个人；不 `@` 任何成员；
- Memory 关闭，不读取个人画像；
- 冷却不少于 86400 秒；
- 无人回应后不追加消息；
- 每次发送均重新检查 Grant、预算、quiet hours 和 kill switch。

## 9. 停止与回滚

以下任一事件立即关闭当前行为，不晋级其他行为：

- wrong target、重复投递、quiet-hour/撤销后投递；
- 未授权 Capability、跨 Scope Memory、个人 Probe 目标；
- 过期或无引用日报、敏感 Trace、未知 Delivery outcome；
- Endpoint health 为 `UNKNOWN`、缺 Receipt、SLO 超线；
- kill switch 或回滚检查失败。

关闭后保留故障现场的私有证据，执行冻结回滚路径，并按
[升级与回滚设计](upgrade-and-rollback.md)核对上一 release。禁止在未完成对账时自动重试发送。

## 10. Closeout 和证据

Closeout 必须：

1. 关闭所有行为、Subscription、Schedule 和 Output；
2. 对账每个 Decision、Dispatch 和 Delivery Receipt；
3. 执行保留/删除计划并记录删除 Receipt；
4. 验证 kill switch 和精确回滚路径；
5. 输出脱敏 SLO、事故和外部门禁报告。

可提交证据仅包含不可逆 digest、低基数计数、SLO 聚合和稳定 reason code。原始聊天、Prompt、
回答、真实 QQ/群/用户 ID、凭据、完整 `.env`、Provider error body 和私有 audit 内容均不提交。

S23 只有在完整单群阶梯及 Closeout 证据存在后才能标记完成。在此之前应保持 TreeWork 分支
`partial/paused`，不能用离线 checker、S19 Release 或 S20 合成 Bandit 结果替代真实 Receipt。
