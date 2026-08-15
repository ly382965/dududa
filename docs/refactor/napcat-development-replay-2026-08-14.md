# NapCat 本机开发语料回放报告（2026-08-14）

## 1. 结论

本机当前嘟嘟哒账号的群聊记录可以作为 Dududa 的私有开发语料，用于只读回放、契约兼容、
规则分布和无发送 Shadow。旧账号不属于本轮开发数据，已从最终回放中排除；精确账号映射只在
运行时通过参数或环境变量提供。用户另有数百个群的长期聊天记录；该外部语料只在 S23 真实测试
环境中接入，不作为 S21 的输入或开工前置。

回放工具位于 `ops/cli/napcat_history_replay.py`，聚合报告写入 Git 忽略的
`.TreeWork/out/napcat-real-replay-report.json`。工具不保存或打印聊天正文、群号、发送者 QQ 号/
昵称、媒体 URL 或原始 OneBot 响应，也不调用模型、Memory 写入、Tool 或 Output。

运行时必须显式提供本机账号映射，不在仓库保存具体值：

```bash
DUDUDA_REPLAY_ACCOUNT_ID='<approved-bot-id>' \
DUDUDA_REPLAY_ACCOUNT_LABEL='<approved-log-label>' \
uv run python ops/cli/napcat_history_replay.py
```

## 2. 当前 NapCat 状态与来源

| 来源 | 账号范围 | 本次结果 | 口径 |
| --- | --- | --- | --- |
| NapCat 容器接收日志 | 仅 `嘟嘟哒` | 检查 84,210 条；84,159 条可回放；51 条只有群头、缺发送者/正文 | 覆盖 2026-06-29 至 2026-08-14；展示格式有损，但范围较广 |
| Dududa Web 历史接口 | 当前在线 `嘟嘟哒` | 9 个群；旧运行实例本次取得 1,464 条结构化消息 | 当前实例尚未部署本次游标方向修复，不能当作完整历史 |
| NapCat Debug Adapter 只读核验 | 当前在线 `嘟嘟哒` | 单群窗口扩大后确认至少 38,567 条结构化唯一消息 | 仍是窗口下限，不是完整总量；正文未落盘 |
| 旧账号日志 | 旧账号 | 1,303 条元数据命中后丢弃 | 只检查账号标签以过滤；正文不进入开发回放 |

NapCat 当前版本中，向旧消息翻页需要 `reverse_order=true`，向新消息翻页需要
`reverse_order=false`。原 Web Gateway 映射相反，会让 `before` 重复当前页。源码已修正并通过
聚焦 Web 测试；当前运行实例没有重启，因此本报告没有把其结构化分页结果描述成完整数据。

## 3. 回放结果

最终运行检查 85,674 条来源记录，85,623 条进入回放；其中日志和 Gateway 样本可能重叠，不能
相加解释为唯一消息总量。83 条当前 Bot 自发消息在前置阶段按 self-message 跳过，其余 85,540 条
依次通过消息契约、Rule Perception、规则 fallback 合并、复杂度评估、Social Decision、静态
TierPolicy；模块异常为 0。

| 观察项 | 结果 |
| --- | ---: |
| 复杂度 LOW / MEDIUM / HIGH | 4,014 / 81,523 / 3 |
| Social `DIRECT_REPLY` / `IGNORE` | 506 / 85,034 |
| Tier HAIKU / SONNET / OPUS | 0 / 85,540 / 0 |
| 回答档位 SHORT / MEDIUM / LONG | 11 / 493 / 2 |

全部 Tier 都落到 SONNET，不表示真实群消息都应使用中型模型。当前回放没有 Model Perception，
规则 fallback 置信度为 0.59，低于 TierPolicy 的 0.6 阈值，因此静态 Router 按设计选择保守默认档。
ResponsePlan 只为 506 条 `DIRECT_REPLY` 候选选择回答档位。这证明链路可运行，也说明真实难度分流
仍需要 Provider-backed Perception 或人工校准证据。

## 4. 能证明与不能证明

本次可以证明：当前本机记录能够稳定进入核心契约；自发消息可在前置阶段排除；规则、复杂度、
Social、Tier 和 ResponsePlan 对真实中文形态无崩溃；报告不含原始身份或正文。

本次不能证明：Intent/Entity 准确率、应否回复准确率、模型回答质量、Persona 体验、Probe 打扰度、
Memory 检索质量或 Bandit 收益。原始聊天没有人工 gold，也没有 action set、propensity 和可归因
reward。它适合持续开发回归，不应被包装成产品质量评测。

## 5. 对后续顺序的影响

1. S21 不依赖真实聊天；继续使用 Fake join、Fake service 和固定 Profile Catalog 实现控制后台。
2. 本机嘟嘟哒数据可以在 S21 开发期间反复运行私有 replay，发现 Connector、分页和规则回归。
3. S21 完成后，S23 先在隔离测试环境挂载外部长期记录，做全量无发送历史 Shadow 和小样本人工标注。
4. 历史 Shadow 通过后才进入单群实时 no-send Shadow、明确 @ Canary、日报、Probe 和分层放量。
5. 外部长期记录不直接写入 Memory，也不能直接作为 Bandit 训练集。
