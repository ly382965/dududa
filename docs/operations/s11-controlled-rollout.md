# S11 受控上线与回滚

本文说明 Dududa 新 Runtime 的本地 `off / shadow / canary` 控制边界。S11 只接收白名单群中对当前 Bot 的结构化显式提及，并且固定关闭 Tool 和 Memory。模型难度判断、TierPolicy 和静态 Model Router 继续使用 S08-S10 的确定性实现，不接入 Bandit。

## 1. 三种模式

| 模式 | Runtime 执行 | Runtime 发送 | 旧链路所有权 | 是否停止 AstrBot Event |
| --- | --- | --- | --- | --- |
| `off` | 否 | 否 | 是 | 否 |
| `shadow` | 有界后台执行 | 否 | 是 | 否 |
| `canary` | 仅准入消息 | 仅通过发送前复核后 | 未取得 claim 时是；取得 claim 后永不回退 | 取得持久 claim 后立即停止 |

默认配置为 `off`、`rollout_delivery_enabled=false`、`rollout_kill_switch=true`。旧配置缺少 S11 字段时也会得到这组安全默认值。

## 2. 配置字段

配置位于 AstrBot 的 `astrbot_plugin_dududa_core_config.json`，WebUI Schema 已暴露以下字段：

| 字段 | 约束 |
| --- | --- |
| `rollout_mode` | 只接受 `off`、`shadow`、`canary` |
| `rollout_revision` | 每次修改模式、白名单、发送开关或熔断时更新 |
| `rollout_delivery_enabled` | Canary 实际发送的独立开关 |
| `rollout_allowlisted_groups` | 精确群号白名单；不会写入 Trace 或指标 |
| `rollout_kill_switch` | 紧急熔断；发送前会重新读取磁盘配置 |
| `rollout_tools_enabled` | S11 必须为 `false` |
| `rollout_memory_enabled` | S11 必须为 `false` |
| `rollout_maximum_text_bytes` | 按 UTF-8 字节限制输入 |
| `rollout_shadow_max_in_flight` | Shadow 后台任务容量 |
| `rollout_shadow_timeout_ms` | Shadow 总超时 |
| `rollout_canary_timeout_ms` | Canary Runtime 总超时 |

配置解析使用精确类型，不接受字符串形式的布尔值。发送前若文件缺失、JSON 损坏、revision 改变、模式改变、发送关闭、熔断开启或白名单改变，已取得所有权的任务会停止发送，但不会回退旧链路。

## 3. 准入与单一所有权

一次 Runtime 准入必须同时满足：

1. 群号在白名单中；
2. Connector 从消息组件中解析到对当前 Bot ID 的 `At`，正文中的伪造 `@名字` 不算；
3. 输入是非空、有限长的纯文本，不含附件；
4. 消息不是 Bot 自己发送；
5. Tool 和 Memory 均关闭；
6. kill switch 关闭；Canary 还要求 delivery enable 打开。

Core rollout handler 的 AstrBot priority 为 `100`，高于原自然语言课程入口的 `8` 和 TargetTalk 默认的 `0`。Canary 先在 SQLite 中原子 claim，再调用 `event.stop_event()`。重复 handler、并发进程或重启回放看到已有 claim 时也会停止旧链路，但不会再次运行或发送。

平台发送前，Output Adapter 在 `event.send()` 紧前再次读取控制配置，并先提交发送 tombstone。若进程在发送边界崩溃，重启恢复为 `UNKNOWN`；系统不会根据猜测盲目重发。

## 4. Runtime 安装边界

插件初始化会创建控制 Provider、只读聚合指标和 SQLite ownership ledger，但默认不自动连接真实 Provider。完成 S10 Runtime 装配后，由进程内 composition root 显式调用：

```python
install_rollout_runtime(
    plugin,
    runtime,
    runtime_budget,
    policy_snapshot_id,
)
```

未安装 Runtime 时，handler 是无操作，旧链路保持权威。这避免仅修改配置便意外开始真实群发送。

## 5. 指标与检查

`plugin.rollout_metrics.summary()` 返回不可变聚合摘要。指标只包含模式、阶段、固定 revision、模型 role/tier、候选/实际结果、固定延迟桶、用量合计和有限失败类别。消息正文、回复正文、prompt、Provider body、QQ 号、群号、消息 ID 和凭据没有对应字段。

本地重点测试：

```bash
PYTHONPATH=packages/dududa-agent/src:. python3 -m unittest \
  tests.unit.rollout.test_config_admission \
  tests.unit.rollout.test_ledger \
  tests.unit.rollout.test_metrics \
  tests.unit.rollout.test_controlled_execution \
  tests.contracts.test_astrbot_rollout \
  tests.contracts.test_astrbot_output \
  tests.test_rollout_rollback
```

## 6. 回滚清单

回滚不能只切换镜像 tag。清单必须同时固定：

- `image_reference`：带 `@sha256:` 的镜像引用；
- `plugin`：只读挂载插件快照的 revision、来源、目标和目录摘要；
- `config`：AstrBot 配置快照的 revision、来源、目标和目录摘要；
- `target_control_revision`：回滚后的控制版本；
- `target_rollout_mode=off`，且配置快照内 delivery 关闭、kill switch 开启；
- Compose 文件和 AstrBot service 名称。

只验证清单和两个快照：

```bash
python3 scripts/rollback_dududa_rollout.py /secure/release/rollback.json
```

显式执行回滚并保存当前插件与配置备份：

```bash
python3 scripts/rollback_dududa_rollout.py \
  /secure/release/rollback.json \
  --apply \
  --backup-dir /secure/backups/dududa-before-rollback
```

脚本先校验两个目录摘要和配置中的 `off` 控制，再替换 config/plugin bind mount 来源，最后用 digest-pinned 镜像强制重建 AstrBot service。任一步失败会恢复本次替换前的目录。

## 7. 外部验证边界

本地仿真覆盖白名单、结构化提及、TargetTalk 重叠、并发 claim、进程重启、发送中熔断和 `UNKNOWN`。真实 QQ 群 shadow/canary 仍需操作者明确提供授权群、凭据、发送窗口和回滚快照；S11 本地开发不会自行发送外部消息。

按当前项目顺序，真实群验证只在所有模块、WebUI 测试和本地总审计完成后启动；提前获得凭据或群号也不会跳过这些前置门禁。
