# S08-S11 完成审计

审计日期：2026-08-04
审计提交：`716e227` 及其父提交
范围：静态模型选择、语义理解与难度判断、离线 Runtime、受控上线

## 结论

S08-S11 的本地实现与仿真门禁已经完成。难度判断与模型路由形成一条确定性链路：

```text
结构化 Connector
  -> Rule/Haiku Perception
  -> 完整结果校验与合并
  -> Deterministic Complexity Assessment
  -> Deterministic TierPolicy (haiku/sonnet/opus)
  -> Static Model Router
  -> Direct Chat / Composition / DeliveryRequest
  -> off | no-send shadow | allowlisted canary
```

Bandit、随机权重和在线探索没有进入配置、导入或执行路径。项目级唯一未完成成功标准是经明确授权的真实 QQ 群 shadow/canary 与 SLO 证据；本次审计没有凭据、授权群或发送窗口，因此没有执行外部发送。

## 要求证据矩阵

| 要求 | 状态 | 实现证据 | 验证证据 |
| --- | --- | --- | --- |
| S08 版本化模型契约、Registry、静态 Router、容量、fallback、Fake 与兼容 Adapter | 已完成 | `dududa.models.contracts/registry/admission/router`、AstrBot model Adapter | S08 双版本 198 项全仓、96 项聚焦测试；派生镜像宿主测试 |
| S09 Perception、Merger、Validator、Social Decision、Complexity、TierPolicy 和 Eval | 已完成（合成 Eval 待人工标签确认） | `dududa.perception`、`dududa.models.tiering`、`dududa.evaluation.s09`、320 条固定数据集 | S09 双版本门禁、不同顺序/种子可重复性与策略黄金集测试 |
| Perception 固定使用 Haiku，只有校验后的 assessment 能影响 Direct Chat Tier | 已完成 | `PerceptionBootstrapPolicy`、`DeterministicComplexityAssessor`、`DeterministicModelTierPolicy`、Runtime state binding | policy/state/selection 的负向测试拒绝用户 Tier 权威和不匹配 receipt |
| S10 Connector 到 Delivery receipt 的完整离线闭环 | 已完成 | `dududa.runtime.orchestrator/store/delivery/offline` | 双版本 325 项；并发 CAS、预算、取消、失败和四种 Delivery 状态 |
| S10 Shadow 无 Output/Memory/Tool/event-stop 副作用 | 已完成 | `ShadowRunner` 只依赖 `AgentRuntime` 与脱敏 Sink | side-effect guard 与不可交付 receipt 测试全部为零调用 |
| S11 typed mode、持久去重/tombstone、白名单、显式提及、发送前熔断、指标、回滚 | 已完成（本地） | `dududa.rollout`、`rollout_bridge.py`、Output `send_guard`、回滚 CLI | 双 SQLite 实例、并发、重启、TargetTalk 重叠、in-flight kill 和 UNKNOWN 仿真 |
| 既有 S01-S07 与仓库边界不回归 | 已完成 | Core 仍只依赖标准库/内部包；提交历史无 WebUI/Sub2API 路径 | 双版本全仓 350 项；import、compile、secret、shell、Compose、whitespace 全通过 |
| 授权真实群 shadow/canary 与冻结 SLO | 未执行 | 代码、配置和回滚边界已就绪 | 缺少明确授权、群 ID、凭据和发送窗口；不得用本地仿真替代 |

## 最终验证

| 门禁 | 结果 |
| --- | --- |
| Python 3.12 全仓 | 350 tests，2 个宿主环境跳过 |
| Python 3.10 全仓 | 350 tests，2 个宿主环境跳过 |
| Runtime/rollout `-W error` | 两个版本各 109 tests |
| AstrBot 派生镜像 | `dududa/astrbot@sha256:a72637301a6df1fe2a120a7ed3cb77406999e4c7f69f878ed64887d2d2d1ec09` |
| 断网镜像插件 smoke | 19 tests 全通过；Core registry 43 handlers，rollout priority 100 |
| Package smoke | `dududa-agent==0.1.0a1`，`dududa.rollout` 可导入，`pip check` 通过 |
| 静态/安全 | Ruff、compileall、372 文件 safety scan、Bandit 禁止扫描、scope 历史扫描通过 |
| 运维 | Shell、Compose、Memory/rollback CLI、JSON、`git diff --check` 通过 |

镜像中的 `jieba` 产生 Python 3.12 旧正则 `SyntaxWarning`，AstrBot 的旧 `register_star` 产生弃用警告；它们来自上游宿主依赖，不影响 19 项插件 smoke，也不是 S08-S11 新代码警告。Core Runtime/rollout 自身在 `-W error` 下通过。

## 未关闭的外部门禁

真实群验证前必须同时提供：

1. 明确授权的 QQ 群 ID 与允许测试的用户范围；
2. 可用但最小权限的 Bot/Provider 凭据；
3. shadow 和 canary 的开始/结束时间窗；
4. 已生成并验证的 digest-pinned image、plugin、config 回滚清单；
5. 预先冻结的重复回复、错误目标、未授权发送、敏感 Trace、延迟与成本阈值。

在这些输入缺失时，正确状态是“本地 S08-S11 完成，真实 canary 未授权”，不是扩大白名单或自动发送。
