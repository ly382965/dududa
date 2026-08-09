# 语义感知、静态模型路由与回答档位调研

状态：研究结论与实验方案，尚未实施

调研日期：2026-08-09

适用范围：S09 语义理解、S08 Static Model Router 的真实 Endpoint 门禁、S15
`SHORT / MEDIUM / LONG` AnswerProfile

## 1. 结论

本报告不重新设计已经完成的 Core、TierPolicy 或 Static Router。建议沿当前端口和所有权边界做
增量扩展：

1. S09 当前 320 条数据可以继续用于确定性 policy 回归，但不能证明中文多人群聊语义质量、
   实体 span、语言指代、OOS 拒识或真实模型校准；
2. Static Router 的 fail-closed、显式 Tier authority、同 Tier failover 和跨 Tier fallback DAG
   应保留；当前缺的是生产装配和真实 Endpoint capability evidence，不是另一套路由框架；
3. RouteLLM、FrugalGPT 等只进入离线对照实验，不替换 Dududa Router；未来学习排序也只能发生在
   所有硬过滤之后的同 Role、同 Tier compatibility class 内；
4. AnswerProfile 必须与 Model Tier、Reasoning Depth 正交，由独立、确定性的
   `ResponseProfilePolicy` 选择，Router 只消费其 digest 和数字预算投影；
5. 在取得合法 Provider 配置、低配额凭据、授权群聊样本和第二评审者之前，不得声称真实
   Endpoint、多人中文语义或三档回答已经产品可用。

| Topic | 当前已证明 | 尚未证明 | 建议决策 |
| --- | --- | --- | --- |
| Intent / Entity / Reference | 合成 fixture、Schema 严格解析、确定性 merge/eval | 真实中文群聊、实体 span、语言指代、OOS、校准 | additive v2 + 标注 pilot |
| Static Router | 硬过滤、预算、health、retry/failover/fallback 的 Fake 测试 | 任一真实 Endpoint 的能力和纵向可达性 | 保留实现，先闭合三个 P0 断点 |
| 外部路由框架 | 可作为 cost-quality 离线基线 | 与现有 Tier authority、安全边界兼容的生产替换 | adopt 方法，defer/reject runtime |
| AnswerProfile | 文档目标和静态 token/字符原语 | Policy、动态预算、Composer/Validator、人工 Eval | S15 确定性实现 |

## 2. 主仓证据与声明边界

### 2.1 S09 数据不是产品语义评测

数据入口为 `evals/perception-tiering/v1/`。`dataset-manifest.json` 明确记录：

- `dataset_kind = synthetic`；
- `label_basis = policy_gold`；
- `human_review_complete = false`；
- 32 个模板族，每族 10 个相关变体，共 320 个 case；
- development 80、test 240，统计单元是模板族而不是 320 个独立样本。

2026-08-09 的只读复核还得到：

| 项目 | 结果 | 含义 |
| --- | ---: | --- |
| group case | 320 / 320 | 没有 private 对照，但不等于真实群聊 |
| 仅 1 条消息 | 10 | 不是多轮 |
| 仅 2 条消息 | 310 | 主要是固定 reply edge |
| 3 条及以上消息 | 0 | 没有长依赖、多参与者话题漂移 |
| 含中文字符的 case | 50 | 很多中文文本仍带英文模板前缀 |
| Intent gold | 290，16 个 `synthetic.*` ID | 是模板 task kind，不是产品 taxonomy |
| Entity gold | 80 | 唯一值均为 `artifact / synthetic-artifact` |
| Reference gold | 280 | 全部是 `message` reference，多为结构化 reply edge |

可用以下命令复核关键计数：

```bash
jq '{dataset_kind,label_basis,human_review_complete,template_count,variants_per_template,case_count}' \
  evals/perception-tiering/v1/dataset-manifest.json
jq -s 'group_by(.context.messages|length) | map({messages:(.[0].context.messages|length),count:length})' \
  evals/perception-tiering/v1/cases.jsonl
jq -s '[.[]|.perception.entity_keys[]?] | {mentions:length,unique:unique}' \
  evals/perception-tiering/v1/gold.jsonl
jq -s '[.[]|.perception.reference_keys[]?] | {mentions:length,kinds:(map(.[0])|unique)}' \
  evals/perception-tiering/v1/gold.jsonl
```

`report.json` 的 Entity、Intent、Reference F1 均为 1.0，校准项为
`Brier = 0.036715625`、`ECE = 0.1528125`。这些数值来自固定 model fixture 和同源
policy gold，只能证明生成器、解析器和 policy 回归一致，不能证明真实模型置信度。

当前 `IntentCandidate` 只有 ID、confidence 和 evidence；`EntityCandidate` 没有 source
message、start/end span、surface 或 normalized value；`ReferenceCandidate` 没有指代表达
span/surface。因而当前契约无法计算计划中的 Entity exact span/type F1，也无法区分 Connector
提供的 reply/@ 结构边和“他、这个、上面那个课程”等语言指代。

### 2.2 真实 Endpoint 的三个 P0 断点

| 断点 | 主仓证据 | 后果 | 正确修复方向 |
| --- | --- | --- | --- |
| Runtime 未装配 | `plugins/astrbot_plugin_dududa_core/composition.py` 初始 `rollout_bridge=None`，生产路径没有安装 rollout runtime | 事件仍走旧路径 | 建立唯一 composition root，先以 `off` 做零副作用 smoke |
| temperature 能力冲突 | `packages/dududa-agent/src/dududa/runtime/perception.py` 和 `runtime/direct_chat.py` 固定 `temperature=0`；AstrBot Adapter 声明不支持且拒绝非空值 | 请求在真实调用前 capability mismatch | Runtime 默认传 `None`；仅 conformance 证明后启用参数 |
| health 永远 UNKNOWN | Adapter `health()` 固定返回 `UNKNOWN`；Router 对 UNKNOWN fail closed | 没有可选 AstrBot Endpoint | 增加有证据且有 freshness 的 health snapshot，不放宽 Router |

此外，现有 `AstrBotProviderBindingEvidence` 只覆盖 model ID、输出上限、residency、retention、
单次请求、日志脱敏、deadline 和 cancellation。它没有证明 context/input limit、reasoning 参数
语义、原生 Schema、temperature、seed、stream、usage、finish reason、rate-limit header 或
request ID；共享 Contract Test 使用的是 `_AstrBotProvider` harness，不是真实 Provider。

### 2.3 AnswerProfile 仍是目标契约

`docs/design/model-routing.md` 已正确规定 AnswerProfile、Tier、Reasoning 和 Role 四者正交，
但 `packages/dududa-agent/src/dududa/responses` 尚未形成 `ResponseProfilePolicy`、版本化
`ResponsePlan` 和最终 Profile Validator。当前 `max_output_tokens`、`MAX_LENGTH` 和
ReplyPolish 的静态 `chunk_chars=520` 只是实现原语，不能被表述为已经支持三档回答。

## 3. Intent、Entity、Reference 与拒识

### 3.1 一手来源与采用决策

所有来源均访问于 2026-08-09。

| 来源 | 访问日期 | 版本 / commit | 许可证 | 维护状态 | 决策与边界 |
| --- | --- | --- | --- | --- | --- |
| [MASSIVE](https://huggingface.co/datasets/AmazonScience/massive) | 2026-08-09 | dataset 1.1，HF `ff6bd8e4b27c3543e4f8fe2108f32bb95a6f8740`；paper arXiv:2204.08582v2 | 数据 CC-BY-4.0；论文为 arXiv non-exclusive distribution | 数据最后更新 2022-11-16，静态 | **adopt** 中文 intent/slot 外部对照；52 个 locale variant 含 zh-CN/zh-TW、60 intent、55 slot；不能代表群聊、多轮或 OOS |
| [CrossWOZ](https://github.com/thu-coai/CrossWOZ) | 2026-08-09 | `df82c9fdff91b9b130f2d6b89110d3870ba6260e` | Apache-2.0 | 最后提交 2023-01-10，静态 | **adopt** 多轮 dialogue state/act 对照；约 6K 对话、102K utterance、平均约 17 turns；不是多人 QQ 群 |
| [CLINC OOS](https://github.com/clinc/oos-eval) | 2026-08-09 | `828f8093932c8fe6ca7936c3d2e52903b1c523de` | CC-BY-3.0 | 最后提交 2021-05-31，静态 | **adopt** 150 intent + OOS 的拒识实验结构；英语、单 utterance，不直接训练产品模型 |
| [CLUENER2020](https://github.com/CLUEbenchmark/CLUENER2020) | 2026-08-09 | `2e8fccd1b8cde6b471fe440b9d766e920fb418ab` | 仓库无 LICENSE | 最后提交 2022-11-21，静态 | **reject** 数据导入；**adopt** 中文字符 span 契约思路，不能复制未授权数据 |
| [Label Studio](https://github.com/HumanSignal/label-studio) | 2026-08-09 | stable `1.23.0` tag `2a9bfbcbf0a844b999de97e601d16050a893f5fb`；HEAD `10321da9cb01017414318ebf25b29e70142681a2` / `1.24.0.dev0` | Apache-2.0 | 2026-08-08 仍活跃 | **spike** 隔离标注工具；不进入 Agent runtime，不把标注服务变成生产依赖 |
| [On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a.html) | 2026-08-09 | PMLR 70，2017-07-17 | 论文页面未提供软件许可证；不导入代码 | 方法稳定 | **adopt** 仅在可取得 logits 时评估 temperature scaling；不校准 LLM 自报 confidence |
| [SelectiveNet](https://proceedings.mlr.press/v97/geifman19a.html) / [repo](https://github.com/geifmany/selectivenet) | 2026-08-09 | PMLR 97，2019；repo `a6d0a8fd33dae61da910b61a2aae93102d2d4869` | repo 无 LICENSE | repo 最后提交 2019-04-24 | **reject** 代码；**adopt** selective risk、coverage 和 reject option 指标 |

这些公开数据分别覆盖 multilingual intent/slot、中文多轮 task dialogue、OOS 和中文实体 span，
但没有一个来源代表 Dududa 的多人中文 QQ 群。产品结论必须来自经授权的自有群聊 pilot，不能用
这些数据拼出“真实群聊已经验证”的声明。

### 3.2 接口边界

现有处理链保持不变：

```text
Connector structural facts
  -> Rule Perception
  -> fixed bootstrap Model Perception
  -> Merger / Validator
  -> semantic candidates + ambiguity
  -> Complexity Assessor
  -> TierPolicy
```

所有权必须满足：

- Connector 只提供平台事实，如 author、reply_to、@、附件引用和稳定 message ref，不判断 intent；
- Rule Perception 可信地投影结构事实，不把模型文本当作权限；
- Model Perception 只能提出严格 Schema 候选，不能选择 Tier、Provider、回复目标或工具权限；
- Merger/Validator 绑定 evidence 和 Scope，结构边优先于模型推断；
- OOS、歧义和缺槽决定 `ACCEPT / CLARIFY / ABSTAIN`，不通过伪造一个 `unknown` intent 混入
  业务 taxonomy；
- 用户要求“使用 Opus”仍是非可信文本，不进入 RouteHint。

建议以 additive schema v2 扩展，不删除 v1 reader，也不改变 Perception Port：

```python
TextSpan(
    message_ref,
    start,
    end,
    surface,
    text_digest,
)

EntityMention(
    entity_id,
    kind,
    span,
    normalized_value,
    confidence,
    evidence_refs,
)

ReferenceMention(
    reference_id,
    kind,
    mention_span,
    target_ref,
    link_source,       # structural | linguistic
    confidence,
    evidence_refs,
)

IntentCandidateV2(
    intent_id,
    taxonomy_revision,
    slot_entity_refs,
    confidence,
    evidence_refs,
)

SemanticDecision(
    action,            # accept | clarify | abstain
    calibration_revision,
    threshold_policy_revision,
    reason_codes,
)
```

span 规则必须冻结为：文本先执行 NFC；索引单位为 Unicode code point；区间为半开
`[start, end)`；同时保存 surface 和规范化文本 digest。QQ/浏览器提供的 UTF-16、UTF-8 byte
或其他 offset 只在 Adapter 边界转换。digest 或 surface 对不上时 fail closed，禁止猜测修复。

### 3.3 标注、校准和 OOS 实验

#### 阶段 A：schema dry-run

- 50 个 conversation window，由 Owner 标注；
- 每个 window 3--12 turns，保留多参与者和 reply chain；
- 覆盖 reply/@、省略、代词、别名、话题切换、中文网络表达、代码混写、命令形态、缺槽和 OOS；
- 只用于修改标注指南和 taxonomy，不报告模型质量。

#### 阶段 B：pilot

- 200 个独立 conversation cluster；
- 至少 100 个由两名标注者完全独立标注，随后仲裁；
- Intent/OOS 报告 Krippendorff's alpha 或 Cohen's kappa；span/link 报告双人 exact F1；
- 建议进入 main 的标注一致性门槛为 Intent/OOS alpha >= 0.80、Entity span/type pairwise
  F1 >= 0.90、Reference link agreement >= 0.85；未达到时先修指南，不训练阈值。

#### 阶段 C：main

- 按 group、conversation、reply-chain、time window 分组切分，禁止同一 cluster 跨 split；
- 每个关键 intent/OOS/reference stratum 至少 60 个独立 cluster；若要证明更低风险，按目标置信
  区间重新计算样本量，不能把同模板变体当作独立样本；
- development 用于模型、calibrator 和阈值；held-out test 只运行一次；
- 真实文本必须有授权、撤回、去标识、用途和保存期限规则，普通 Trace 不保存正文。

决策规则建议为：

```text
calibrated in-scope score >= tau_accept
and top1-top2 margin >= delta
and required slots/references resolved
  -> ACCEPT

multiple plausible in-scope candidates
or required slot/reference missing
  -> CLARIFY

OOS / unsupported capability / insufficient evidence
  -> ABSTAIN
```

LLM 输出的 `confidence` 不能直接解释为概率。若 Provider 能提供 logits，可在 development 上
拟合 temperature scaling；否则应训练独立的 outcome calibrator 或只保留离散风险带，并明确标记
`uncalibrated`。阈值、calibrator revision 和数据 digest 必须进入 Eval artifact。

### 3.4 指标与失败线

| 对象 | 主指标 | 辅助诊断 |
| --- | --- | --- |
| Intent | macro/micro-F1、exact set match、per-intent recall | taxonomy confusion、missing slot |
| Entity | exact span + type F1 | overlap F1、正确 span 条件下 normalized-value accuracy |
| Reference | mention exact span F1、antecedent link accuracy、unresolved F1 | 距离、参与者数、结构/语言来源分层 |
| OOS | AUROC、AUPRC、FPR@95TPR | in-scope/OOS 混淆矩阵 |
| Calibration | NLL、Brier、reliability diagram、ECE | classwise/adaptive ECE、cluster bootstrap CI |
| Operational | selective risk-coverage | ACCEPT/CLARIFY/ABSTAIN 比例和人工负担 |

建议在 pilot 前预注册以下初始失败条件，并只允许在查看 held-out test 前调整一次：

- 找不到同时满足 coverage >= 70% 且 accepted-risk 的 cluster-bootstrap 95% CI 上界 <= 5% 的阈值；
- OOS false accept > 2%；
- Intent macro-F1 < 0.85，或任何有足够支持的产品关键 intent recall < 0.80；
- 任何跨 Scope target/reference、span digest/offset 不一致或未经授权的高风险 action；
- 校准后 NLL/Brier 变差，或者只因改变 bin 得到更好 ECE；
- development/test 泄漏、test 后重新调阈值或没有第二标注者却宣称人工 gold 完成。

## 4. Static Model Router 与真实 Endpoint conformance

### 4.1 一手来源与采用决策

所有来源均访问于 2026-08-09。

| 来源 | 访问日期 | 版本 / commit | 许可证 | 维护状态 | 决策与边界 |
| --- | --- | --- | --- | --- | --- |
| [RouteLLM](https://github.com/lm-sys/RouteLLM) / [paper](https://arxiv.org/abs/2406.18665) | 2026-08-09 | repo `0.2.0`，`0b64fdafe049e596a3f5657c219329f24af24198`；paper v4 | 代码 Apache-2.0；论文 arXiv non-exclusive distribution | repo 最后提交 2024-08-10 | **defer** runtime；**adopt** strong/weak score 为离线 baseline。其两模型 authority 和针对模型对校准不兼容 Dududa 三 Tier authority |
| [FrugalGPT](https://github.com/stanford-futuredata/FrugalGPT) / [paper](https://arxiv.org/abs/2305.05176) | 2026-08-09 | repo `0.0.1`，`2b23e6acbd4b39f71912816640dcc59e45aa4b5e`；paper v1 / TMLR 2024 | 代码 Apache-2.0；论文 arXiv non-exclusive distribution | repo 最后提交 2025-02-09 | **reject** 生产集成；cascade 可能重复调用、延迟、计费和内容暴露；**adopt** cost-quality 方法 |
| [RouterBench](https://github.com/withmartian/routerbench) / [paper](https://arxiv.org/abs/2403.12031) | 2026-08-09 | code `0.1`，`cc67d1008bd8f3cf1e8040cc3ba4034d31b93c0c`；paper v2；HF data `784021482c3f320c6619ed4b3bb3b41a21424fcb` | 代码 MIT；HF dataset card 未声明许可证 | code 最后提交 2024-06-12，数据最后更新 2024-03-27 | **adopt** cost-quality curve / AIQ / oracle 对照；**reject** 数据和 runtime |
| [vLLM Semantic Router](https://github.com/vllm-project/semantic-router) | 2026-08-09 | release `v0.3.0` commit `9afc5a421886f44085f9070a8fbd878b80724f64`；HEAD `1a5758272179bbad7fc3628a21e848e96eb7e28b` | Apache-2.0 | 2026-08-09 活跃 | **reject** 控制面集成，避免 Go/Rust/K8s 运行面和现有 Registry/Router ownership 重叠；**adopt** signal/policy 分类词汇 |

### 4.2 Router 的稳定边界

保留当前顺序：

```text
TierAuthority
  -> frozen routing + operational snapshots
  -> role / tier / privacy / residency / retention hard filters
  -> modality / schema / reasoning / context / output capability filters
  -> budget / admission / health / freshness / quota filters
  -> deterministic priority, endpoint_id, provider_id
  -> bounded retry / same-tier failover / explicit cross-tier fallback DAG
```

具体约束：

- 智能难度判断属于 Perception/Complexity/TierPolicy，Static Router 不重新解释难度；
- Endpoint 名称、模型品牌或 Prompt 不能授予 Tier；
- UNKNOWN、stale 或 revision mismatch 的 health 继续 fail closed；
- 同 Tier failover 与显式跨 Tier fallback 是故障处理，不是质量学习 action；
- 未来 bandit/learned ranker 只能在所有硬过滤后，对同 Role、同 Tier、同隐私和能力语义的
  compatibility class 排序；它必须有 before-action propensity、shadow、kill switch 和回滚；
- RouteLLM/FrugalGPT 不进入 Provider Adapter，也不持有凭据、预算或发送所有权。

### 4.3 EndpointConformanceEvidence v1

建议把每个 Endpoint 的真实证据独立版本化，而不是给整个 Provider 写一个宽泛布尔值：

```text
provider_id / endpoint_id / model_id / role / tier
host, SDK, container and adapter revisions
official capability, pricing, retention and residency document revisions
request-matrix digest and sanitized provider request IDs
verified context/output limits and supported modalities
reasoning/temperature/seed/schema/stream semantics
usage/finish/safety/error/rate-limit mappings
deadline/cancel/downstream-request-count evidence
checked_at / expires_at / evidence_digest
```

只有公开、脱敏的摘要和 digest 可进入仓库。API key、Header、Prompt、completion 和原始错误正文
保留在受控测试环境，不能写入普通日志或 Trace。

### 4.4 真实请求矩阵

测试只使用合成、非敏感 prompt 和低配额测试凭据。

| 组 | 请求 | 必须证明 |
| --- | --- | --- |
| A：绑定 | baseline、显式 model ID、错误 model ID | 实际 Provider/model binding、request ID、binding drift fail closed |
| B：采样 | `temperature=None`、合法值、seed 重复 | 参数是否支持、unset 与 zero 区别、seed 是否真实生效 |
| C：Reasoning | 每个声明的 profile | Provider 参数映射、effective profile、reasoning usage/上限语义 |
| D：容量 | 小 output、声明边界、near-context、over-context | input/context/output 限制和稳定错误类别 |
| E：Schema | 合法 JSON Schema、不可满足 Schema、malformed output | native support、repair 次数、最终 OUTPUT_INVALID |
| F：Stream | 正常 stream、中途 cancel、deadline | 事件顺序、部分结果语义、网络请求真实终止 |
| G：Usage | cached/non-cached、reasoning、length finish | token 字段、cost settlement、finish reason、安全标记 |
| H：错误 | 400/401/403/408/422/429/5xx | 稳定 failure kind、outcome_unknown、Retry-After/reset |
| I：幂等 | 相同 key/digest、key 冲突、超时后重放 | 实际下游请求次数、tombstone、无重复未知副作用 |
| J：隐私 | 合成 canary、日志/trace 检查 | key/Header/Prompt/completion 不泄漏，retention/residency 有依据 |

不得通过高频压测制造 429。优先使用 Provider sandbox、低配额账户、官方测试机制或经过审批的
captured error fixture。能力断言建议至少重复 3 次；延迟和错误率使用固定 case 各至少 30 次，
报告 p50、p95、失败率和 cluster-bootstrap CI。

### 4.5 可复现离线路由实验

前提是至少两个同 Role、同 Tier Endpoint 已分别通过相同 conformance。对冻结 task set 的每个
任务预先取得所有兼容 Endpoint 输出，再离线比较：

1. 当前 static priority；
2. cost-only；
3. 同 compatibility class random；
4. RouteLLM 风格 score；
5. 知道所有输出后的 oracle，仅作上界。

每次 Eval 固定 dataset digest、endpoint evidence digest、price revision、policy digest、输出和人工
rubric。按 conversation/task-family cluster bootstrap，禁止在线选择后只评价被选 Endpoint。

| 维度 | 指标 |
| --- | --- |
| 质量 | task success、人工 pairwise win、per-stratum success |
| 成本 | cost per request、cost per successful task、预算拒绝率 |
| 延迟 | p50、p95、timeout rate |
| 路由 | selection share、fallback/retry、regret against oracle |
| 综合 | RouterBench 风格 cost-quality Pareto / AIQ |
| 安全 | privacy/tier/schema/health hard violation count |

实验失败条件：

- 任一隐私、权限、Tier、Schema、health 或 residency 硬边界违规；
- 相对 static baseline 的质量差异 95% CI 下界低于 -2 percentage points；
- cost per success 增加超过 10%，或 p95 latency 增加超过 20%；
- 任一预注册 stratum 质量下降超过 5 percentage points；
- 没有 before-action propensity、不可重放 policy snapshot，或拿在线选择日志冒充反事实评估；
- 未通过 conformance 的 Endpoint 被纳入 action set。

### 4.6 生产 enablement 失败线

下列任一条件都必须保持 Endpoint disabled：

- model/provider binding 缺失或发生漂移；
- reasoning、context/output、Schema、temperature 或 stream 语义未验证却被声明支持；
- deadline/cancel 只让 Adapter 返回，但未终止真实网络请求；
- AstrBot/SDK 内部重试次数无法观测或突破 Dududa attempt budget；
- usage 无法稳定映射，导致预算不能结算；
- 日志、异常或 Trace 泄漏 credential、Header、Prompt 或 completion；
- retention/residency 只有推测，没有官方或合同依据；
- health 为 UNKNOWN、stale、revision mismatch 或 probe 失败。

## 5. SHORT / MEDIUM / LONG AnswerProfile

### 5.1 一手来源与采用决策

所有来源均访问于 2026-08-09。

| 来源 | 访问日期 | 版本 / commit | 许可证 | 维护状态 | 决策与边界 |
| --- | --- | --- | --- | --- | --- |
| [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval) / [paper](https://arxiv.org/abs/2311.07911) | 2026-08-09 | path commit `e6890f85757dd84e27ca6df2dd30651dafad28e0`；父仓 HEAD `015539128d9a7dbe14b5f5308a198a15da808949`；paper v1 | 代码 Apache-2.0；论文 CC-BY-4.0 | path 2026-07-22 仍有更新 | **adopt** 可机器验证的长度、句数、关键词、语言和格式 checker；不复制英语限定规则作为中文质量标准 |
| [AlpacaEval](https://github.com/tatsu-lab/alpaca_eval) | 2026-08-09 | `v0.6.6` tag `f19c323d8309d0d6f306bd26597db44fc6c62d57`；HEAD `cd543a149df89434d8a54582c0151c0b945c3d20`；HF data `2edc6fad8be6b14ea7230aabfd08188da6b8b814` | 代码 Apache-2.0；数据 CC-BY-NC-4.0 | code 最后提交 2025-08-09 | **spike** 输出顺序随机化、position bias 和 length-controlled 分析；不导入 NC 数据，自动 judge 不作发布门禁 |
| [HELM](https://github.com/stanford-crfm/helm) | 2026-08-09 | `v0.5.16`；HEAD `63754d05db6f874e41a395880fb573890a13e791` | Apache-2.0；各数据集另行授权 | 2026-06-01 起 maintenance mode | **adopt** versioned scenario/metric/result 结构；**reject** 新 runtime dependency |
| [OpenAI Evals](https://github.com/openai/evals) | 2026-08-09 | `3.0.1.post1`；HEAD `8eac7a7de5215c907fbddc30efdaf316913eccdd` | 代码 MIT；内置数据各自授权 | 最后提交 2026-04-14 | **adopt** private custom eval 与数据授权分离思路；**defer** dependency |
| [Chatbot Arena](https://arxiv.org/abs/2403.04132) / [FastChat](https://github.com/lm-sys/FastChat) | 2026-08-09 | paper v1；FastChat `587d5cfa1609a43d192cedb8441cac3c17db105d` | FastChat Apache-2.0；论文 arXiv non-exclusive distribution | FastChat 最后提交 2025-06-02 | **adopt** anonymous、随机 A/B、pairwise 人工比较；**reject** 整套 Arena server |

### 5.2 所有权和接口边界

```text
Perception: non-authoritative AnswerProfileHint
  -> SocialDecision / ProactivePolicyDecision
  -> ResponseProfilePolicy
  -> immutable ResponsePlan
  -> Composer
  -> Persona Renderer
  -> Profile / Fact / Citation / Safety Validators
  -> OutputAdapter
```

- `AnswerProfileHint` 只能表达用户说了“一句话”“详细解释”等证据，不能直接获得更多预算；
- `ResponseProfilePolicy` 属于 `dududa.responses` 或共享 Domain，不属于 Models Registry；
- `ResponsePlan` 绑定 SocialDecision 或 ProactivePolicyDecision digest，记录 requested、uncapped、
  selected profile、预算、reason/evidence、policy revision 和 selection fingerprint；
- Models 只接收 `response_plan_digest`、visible token upper bound 和总 generated token budget；
- Composer 和 Persona 都只能执行同一个 immutable plan，不能重新选择档位；
- Profile 只控制用户可见详略和结构，不改变 Model Tier 或 Reasoning Depth；
- 必测反例是 `OPUS + DEEP + SHORT` 与 `HAIKU + LIGHT + LONG`；
- LONG 是结构完整，不是输出隐藏 Chain of Thought；SHORT 也不能删除必要引用、拒绝理由或警告。

### 5.3 确定性选择顺序

```text
hard safety / required citations / refusal reason / platform and budget cap
  -> explicit detail request in current message
  -> task type and verification requirement
  -> conversation and group policy
  -> allowed persistent preference
  -> configured default
```

当前消息的明确要求优先于持久偏好。硬上限可以把 `uncapped_profile` 收窄为
`selected_profile`，但如果最低合规内容仍放不下，必须分页、澄清或 `DEFER`，不能静默截断。

没有显式要求时建议：

- 问候、情绪回应、日常聊天、简单 yes/no、主动 Probe -> SHORT；
- 普通事实问答、必要解释、常规操作、校园/行业日报 -> MEDIUM；
- 多步论证、方案比较、重要验证、完整研究摘要 -> LONG。

### 5.4 v1 pilot 预算

以下数字是待 pilot 校准的产品默认，不是枚举语义，也不是最终 SLA：

| Profile | visible token 上限 | 中文字符上限 | delivery part 上限 | 结构目标 |
| --- | ---: | ---: | ---: | --- |
| SHORT | 128 | 180 | 1 | 直接结论或自然回应；不强制标题 |
| MEDIUM | 512 | 720 | 2 | 结论 + 必要依据、步骤或来源 |
| LONG | 1536 | 2400 | 5 | 摘要 + 范围/假设 + 结构化分析 + 替代/风险 + 适用来源/下一步 |

实际预算取 token、字符、平台分片和 Runtime 总预算的最小值。不要设置硬性最少字数；回答短于
上限不自动失败，必须结合 required content、结构完整性和冗余度判断，避免为 LONG 注水。

### 5.5 自动 Eval

冻结的 Eval case 必须覆盖 Complexity x AnswerProfile 3x3、显式 override、预算 cap、中文、
中英混写、群聊/私聊、工具结果、拒绝、安全警告和引用。

| 检查 | 方法 |
| --- | --- |
| Profile selection | macro-F1、confusion matrix、per-class recall、跨两档错误 |
| 显式指令 | 一句话、字数、条目数、格式、语言等 deterministic checker |
| 硬预算 | 实际可见 token、Unicode 字符、delivery part 均不超过 plan |
| 完整性 | required content/section ID 全部出现 |
| 内容保持 | ContentDraft 到 final 的 fact/citation/refusal/target/attachment ID set 不丢失、不新增 |
| 冗余 | 重复 n-gram、重复段落、首个直接答案位置；只作诊断，不能单独判质量 |
| 安全 | 无隐藏 CoT、无凭据/原文泄漏、无目标或 Scope 漂移 |
| 可重复性 | dataset、policy、prompt、model、endpoint evidence 和 result digest 全部冻结 |

LLM-as-a-judge 只能补充诊断。它必须随机化 A/B 顺序并控制长度偏差，但不能替代硬 checker 或
人工发布门禁。

### 5.6 人工盲评

1. 对同一完整 conversation、同一 ContentDraft 和事实/引用集合生成候选；
2. 与 fixed-MEDIUM baseline 做匿名 A/B，隐藏模型、系统、Profile 和生成顺序；
3. 每对输出随机左右位置；
4. 两名评审独立评价 correctness、completeness、relevance、profile fit、群聊自然度和冗余；
5. 分歧由第三人仲裁，记录原始评分而不只保留最终胜负；
6. 以 conversation/task-family 为 cluster bootstrap 95% CI，禁止把同模板变体当独立样本。

建议在 pilot 前预注册：

- 字符/token/part hard cap、明确用户要求、必要事实/引用/拒绝/安全项满足率均为 100%；
- 跨两档错误为 0；
- Profile macro-F1 >= 0.85，且 SHORT/MEDIUM/LONG recall 均 >= 0.80；
- 相对 fixed-MEDIUM 的整体人工质量非劣效界为 -5 percentage points；
- profile-fit 应显著优于 fixed-MEDIUM，且不能以 correctness/completeness 下降换取；
- 任何 target、Scope、事实、引用、拒绝理由或附件漂移均阻断发布；
- 所有数值只能在 pilot 后、查看 held-out test 前冻结一次。

## 6. 后续开发前需要补充的外部输入

| 输入 | 最低内容 | 缺失时禁止的声明 |
| --- | --- | --- |
| Provider 清单 | 合法 `provider_id/endpoint_id/model_id`、Role、Tier、base URL/SDK 所有权 | 不得声称真实 Endpoint 存在 |
| 官方能力文档 | context/output、reasoning、Schema、stream、usage、价格、retention、residency 的版本化 URL | 不得生成 enablement evidence |
| 测试凭据 | sandbox 或低配额、可撤销、只用于 synthetic conformance；不入仓 | 不得运行真实请求矩阵 |
| Host 可观测性 | 固定 AstrBot/SDK/container digest，以及观测真实下游请求次数的方法 | 不得证明 deadline/cancel/幂等 |
| 产品 taxonomy | intent ID/revision、slot、unsupported capability、高风险 action | 不得冻结 Intent/OOS gold |
| 授权群聊数据规则 | 同意、撤回、去标识、用途、保存期限、访问角色 | 不得声称中文多人群聊质量或校准 |
| 第二标注者/评审者 | 独立标注与盲评能力 | 不得声称 human-reviewed gold 或人工非劣效 |
| AnswerProfile 样例 | SHORT/MEDIUM/LONG 各 5--10 个理想回答和反例 | 数字只能标记为 pilot default |
| 平台体验约束 | QQ 群可接受字符、合并转发、分片和频率 | 不得冻结可见预算和 delivery parts |

## 7. 推荐执行顺序

1. 先修复 Runtime composition、temperature、health 和 SQLite 四个 production-shape P0 门禁；
2. 冻结 semantic additive v2、annotation guide、taxonomy/OOS 决策和 AnswerProfile pilot policy；
3. 完成 50-window schema dry-run，不训练、不作质量声明；
4. 取得 Provider 外部输入并生成逐 Endpoint conformance evidence；
5. 只有至少两个同 Role+Tier Endpoint 通过 conformance，才运行离线路由对照；
6. 完成 200-window 语义 pilot、阈值预注册和标注一致性门禁；
7. 实现确定性 ResponsePlan、Composer/Persona 共享 plan 和最终 Validators；
8. 运行自动 Eval 与匿名人工 A/B，冻结 held-out 发布门槛；
9. 全部核心模块、本地 smoke、故障注入和回滚门禁完成后，才进入真实群聊 shadow/canary；
10. Bandit 保持后续阶段，只在同 compatibility class 中 shadow，绝不选择 Tier、AnswerProfile、
    权限、目标、主动发送或高风险工具。
