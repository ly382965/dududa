# S20 离线 Bandit 完成报告

日期：2026-08-11

## 结论

S20 已完成可重放的离线 Bandit 基础，但没有接入生产 Router、Runtime、AstrBot 或主动出站。
本阶段不训练策略、不调用真实模型、不读取用户数据，也不进行 Shadow 或在线探索。

## 已交付

- 新增 framework-neutral `dududa.bandit` Package，复用现有 `ModelEndpointRef`、Role/Tier 和
  canonical codec，没有复制 Static Router。
- Decision 保存完整合法 action set、behavior distribution、sanitized context 和 Router 证据；
  static baseline 直接绑定 Router 已选择的 `planned_endpoint`，不重新解释 route hint 或排序。
- Execution Receipt 绑定 exact chosen action、Decision digest 和现有 `EndpointAdmissionResult`；
  admission 拒绝或 Provider failover 不能替换原 action。
- Feedback 区分 `OBSERVED/CENSORED/INVALID`，绑定执行 Receipt、Reward Policy、观察窗口、
  版本化原始分量和 provenance digest；沉默或缺失反馈不能伪装为零奖励。
- OPE 样本保存完整 behavior/evaluation distribution，并验证相同动态 action set 上的 support、
  propensity floor 和最大 importance weight。
- 使用有限 `Decimal` 和 `ROUND_HALF_EVEN` 实现 IPS、SNIPS、DR 和 ESS；按 `sample_id` 排序，
  最终统一量化到 12 位小数。

## 固定 Golden

`evals/bandit-offline-v1/` 包含四个纯合成样本、Manifest、Report 和 Data Card：

| 指标 | 固定结果 |
| --- | --- |
| IPS | `0.812500000000` |
| SNIPS | `0.650000000000` |
| DR | `0.787500000000` |
| ESS | `3.846153846154` |

正常、逆序和固定 shuffle 输入产生完全相同的 typed Report。Bundle 明确声明零网络、零真实
Endpoint、零模型调用、零用户数据、零训练和 `release_ready=false`。

## 证据边界

聚焦测试覆盖跨 Role/Tier、重复 action/Endpoint、分布不完整、全 action support 缺失、零/低
propensity、过大权重、缺失/截尾 reward、无效 DR prediction、重复样本、零 SNIPS 分母、执行
替换、Reward Policy 不匹配、越窗反馈以及 artifact 篡改。生产 Package 反向 import 扫描证明
Models、Runtime、Proactive 和 AstrBot 没有 `dududa.bandit` hook。

这些结果只证明离线契约和 estimator 算术正确。真实 Bandit 仍需要至少两个同 Role+Tier 且
安全等价的 Endpoint、before-action propensity、可归因反馈、预注册探索预算、SLO 和回滚授权。
