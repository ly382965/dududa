# Conversation Probe 可行性调研

## 1. 结论

Conversation Probe 可以做，但首版必须是**确定性、默认关闭、群级、低频、可撤销**的独立
initiated-run。研究结论不支持“让 LLM 持续产生隐藏想法并自行决定插话”，也不支持用用户沉默
训练更积极的发送策略。

本 Topic 判定：

- **adopt**：现有 `docs/design/proactive-messaging.md` 的 TargetPolicy/Grant、quiet hours、
  durable claim、冷却、预算、发送前重验、no-response 长冷却和 Shadow 零 Output 边界；
- **spike**：只产生 `ConversationOpportunitySnapshot` 的 no-send 检测器和人工标注 Eval；
- **defer**：经过全部本地门禁后的单群、单次、显式授权 canary；
- **reject**：持续 LLM inner-thought 循环、自动中断、人级画像、主动私聊、自动追问和 Bandit
  `SEND/SKIP`。

## 2. 一手来源

访问日期均为 2026-08-09。论文仅用于引用和方法分析，不复制图表、数据或实现。

| 来源 | 版本/状态 | 权利/维护状态 | 对 Dududa 的结论 |
| --- | --- | --- | --- |
| Deng et al., [Towards Human-centered Proactive Conversational Agents](https://arxiv.org/abs/2404.12670v1)，SIGIR 2024，DOI `10.1145/3626772.3657843` | arXiv v1，正式发表 | arXiv 版本 CC BY 4.0；ACM 正式版另受出版条款约束；稳定出版物 | adopt Intelligence/Adaptivity/Civility 三维评价，尤其 timing、pace、boundary respect、trust；不能只优化任务成功 |
| Rizk et al., [A Snooze-less User-Aware Notification System](https://arxiv.org/abs/2003.02097v1)，IUI 2020 Workshop | arXiv v1，概念框架 | ACM/作者版权，非 OSS；稳定但没有可复用实现 | adopt suppress/aggregate/schedule/显式偏好；reject 首版个体行为学习和不可解释分类 |
| Liu et al., [Proactive Conversational Agents with Inner Thoughts](https://arxiv.org/abs/2501.00383v2)，CHI 2025，DOI `10.1145/3706598.3713760` | arXiv v2，正式发表；24 人形成性研究、100 个模拟会话/10 名评审 | arXiv 版本 CC BY 4.0；ACM 正式版另受出版条款约束；论文所链项目站当前重定向后 404，无可采用实现 | adopt relevance、information gap、expected impact、urgency、coherence、originality、balance、dynamics 作为标注维度；reject 持续 hidden-thought/Memory/自动 interruption 实现 |
| Horvitz, [Principles of Mixed-Initiative User Interfaces](https://doi.org/10.1145/302979.303030)，CHI 1999 | DOI 稳定的正式论文 | ACM 版权，非 OSS；经典稳定来源 | adopt 预期收益与打扰成本、用户控制、可撤销和不确定时不行动原则 |

第三篇论文的效果证据不能直接外推到 QQ 群。形成性研究只覆盖单机构的 24 人、每组三人、每人
四场对话；技术评估用 8 个 PersonaChat 派生 AI persona，每次四个纯 AI、15 turns、10 个
icebreaker、每个 condition 50 场，10 名评审各看 5 对。虽然 turn appropriateness、coherence
等显著提高，这不等于真实长期群聊中的打扰度下降。Dududa 只复用评价维度，不复用连续 thought
生成、Memory 或论文阈值。论文报告使用 Mann-Whitney U 的显著性结果，但评分包含 evaluator
重复测量且未按 evaluator/group 聚类；这里只能表述为“论文在该设置中报告显著”，不能把其 p 值
当作 QQ 群长期效果的置信证据。

## 3. 首版架构

```text
sanitized group activity projection
  -> deterministic Opportunity Detector
  -> ConversationOpportunitySnapshot (short TTL, public topic only)
  -> eligibility + policy gates
  -> NO-SEND Shadow recommendation
  -> human review / offline metrics

later, separately authorized:
  -> one PreparedDispatch
  -> pre-send policy/grant/quiet-hour/cooldown/kill-switch recheck
  -> OutputAdapter
  -> no-response long cooldown; never auto-follow-up
```

Opportunity Detector 不拥有发送权限。它只能输出带 TTL、Scope digest、topic refs 和 reason codes
的候选快照；发送仍由 ProactiveInitiationPolicy 和 Delivery Orchestrator 唯一拥有。

### 3.1 硬 Gate

以下任一条件不满足，结果只能是 `INELIGIBLE`：

1. 精确群 Scope 的 operator grant 和 group-policy grant 都 active；
2. 群 allowlist 非空且包含目标，Trigger kind 明确允许 probe；
3. 当前不在 quiet hours，群级/全局日预算和长冷却有余额；
4. 没有未完成 occurrence、dispatch、未知 delivery receipt 或近期 Bot 发言；
5. 话题只来自同一群公开上下文，未过期，未含个人/敏感内容；
6. 没有活跃人类对话、点名问答、冲突升级、安全事件或更高优先级通知；
7. 候选可以表达为不 `@` 个人、不读 Memory、固定 SHORT 的单条公共话题内容；
8. 最新授权、策略、kill switch、Output health 在发送前仍可解析且 digest 一致。

### 3.2 软证据

软证据只用于在 Shadow 中排序人工审查队列，不能越过硬 Gate：

- `topic_age_seconds`、最近人类消息间隔和消息速度；
- topic continuity/freshness，而不是简单关键词相同；
- 是否存在尚未被覆盖的信息缺口；
- 预期新增信息量和重复度；
- conversation coherence、originality；
- Bot 最近发言占比和群体 balance；
- urgency 只允许用于纠错/时效信息，不得绕过 quiet hours 或授权；
- 敏感度、不确定度和来源可信度作为负向信号。

首版不把“静默越久”单调解释为“越应该说话”。超过话题 TTL 后必须失效，而不是继续累积发送
动机。

## 4. 可复现 Spike

### 4.1 数据

1. 先用合成群聊覆盖活跃对话、自然结束、短暂停顿、话题过期、冲突、点名问答和 Bot 刚发言；
2. 用户授权后，从脱敏会话抽取 30 个 pilot conversation window；
3. 冻结标注指南后扩展到 200–500 个完整 conversation window；若声称跨群泛化，必须按群整体
   切分，不能只按群/话题/日期组合切分，并报告 distinct group/topic 数；
4. 原始正文、QQ ID、群号不进入 Git，仓库只保存合成/获准脱敏 fixture 和 manifest。

每个窗口独立标注：`hard_eligible`、topic freshness、relevance、information gap、coherence、
turn appropriateness、expected usefulness、disturbance risk，以及 `SEND_NOW | WAIT | NEVER`
人工建议。该建议只做 Eval 标签，不直接成为生产授权。

### 4.2 Baseline

- B0：永不产生候选（no-send）；
- B1：只用最小静默时间；
- B2：硬 Gate + topic TTL + cooldown；
- B3：B2 加上述确定性软证据，只用于 Shadow 推荐。

### 4.3 指标

| 类型 | 指标 |
| --- | --- |
| 安全 | wrong-scope、未授权、quiet-hour、敏感内容、重复 occurrence、自动追问，目标均为 0 |
| 检测 | eligible precision/recall、`SEND_NOW/WAIT/NEVER` macro-F1、分群/分话题 bootstrap CI |
| 体验 | relevance、coherence、turn appropriateness、usefulness、disturbance 的 1–7 盲评 |
| 运行 | 每群候选/日、冷却遵守率、topic-expired reject、P95 检测耗时、额外模型/Token 成本 |
| 长期 | no observed response、明确参与、管理员 pause/revoke；沉默按 censored 记录，不计负奖励 |

### 4.4 失败条件

- 任一安全指标非 0；
- Scope、grant 或 topic provenance 无法在 receipt 中重建；
- 标注一致性过低且仲裁后仍无法冻结定义；
- 相比 B2，B3 只增加候选量而没有提高盲评相关性/时机，或显著提高 disturbance；
- 规则对话题 TTL、冷却、重启或重复事件不具确定性；
- no-send Shadow 产生 OutputAdapter、Memory write、Tool write 或真实 QQ 发送调用。

质量阈值应在 30 条 pilot 后预注册，禁止看到正式 test 结果后修改。

## 5. 集成边界与优先级

| 工作 | 优先级 | 所属阶段 |
| --- | --- | --- |
| TargetPolicy/Grant/Fake Clock/Store/Output 和默认 off 负向契约 | P0 | S15A，可直接开发 |
| Opportunity Snapshot、TTL、硬 Gate、no-send baseline | P1 | S15E 前置 Spike |
| 脱敏 pilot、标注指南、盲评工具 | P1，依赖用户数据许可 | S15E Eval |
| 单群 probe canary | P2，依赖用户显式授权 | S23，所有本地模块完成后 |
| 连续 inner thoughts、个人 Memory、Bandit send/skip | reject/defer | 不进入当前路线 |

需要用户以后补充的不是 QQ 凭据，而是：允许用于研究的脱敏会话样本、默认 quiet hours、每群
日上限、管理员同意/停止流程和一小批“该说/该等/永不说”的人工示例。真实群号与发送窗口只在
S23 前单独申请。
