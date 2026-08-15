# S23 私有历史群聊离线 Demo 报告

日期：2026-08-15
状态：**S23A–S23E 离线里程碑完成；S23 实时 Shadow/Canary 未开始**

## 1. 结论

本轮已经交付一条可以实际运行和查看的纵向链路：

`静态历史导出 → 来源筛选与去重 → Conversation Window → Terra Silver
标注 → 本地 Student 训练/评测 → 全量本地预测 → 私有 HTML Demo`。

这批数据是专项授权的静态历史导出，不是当前 Dududa Bot 的实时流量。
本轮没有发送 QQ 消息，没有调用 Tool，没有写入 Memory，没有连接生产 Router，
也没有进行 Bandit 在线训练或探索。

Demo 当前可从本机打开：

- 地址：`http://127.0.0.1:8766/`
- 私有文件：`<private-data-root>/demo/index.html`
- 页面样本：300 条
- 页面明确标识 `PRIVATE DEVELOPMENT DATA`、`SILVER, NOT GOLD`、
  `NO SEND`、`NO MEMORY WRITE`、`NO TOOL CALL`、`NO BANDIT`、
  `NOT CURRENT DUDUDA BOT TRAFFIC` 和
  `STATIC TIER OFFLINE PREVIEW / 非生产路由`。

## 2. 为什么只让 LLM 标注 600 条

全部 137,026 个窗口如果逐条远程标注，会显著超过本轮 4–5 小时时间预算，
也没有必要。最终采用两段式方案：

1. Terra 作为唯一 Teacher，只标注 600 条分层窗口；
2. 三个本地轻量 Student 对全部窗口预测。

600 条占全部合格窗口约 **0.44%**。Teacher 用时 1,773.74 秒，约 29.6 分钟；
全量本地预测约 9 分 47 秒。该方案把远程调用控制在可测量的小样本上，同时仍让
全部历史窗口进入可浏览、可统计的离线结果。

没有为补齐零星失败重复整批调用，也没有进行超参搜索。原因是当前主要限制已经明确：
Silver 类别严重不均衡，继续磨模型不能替代人工 Gold。

## 3. 数据处理结果

| 指标 | 结果 |
| --- | ---: |
| 输入文件 | 1,402 |
| 输入字节 | 425,362,536 |
| 解析到的源记录 | 195,651 |
| 唯一群消息 | 155,567 |
| 有消息群 | 55 |
| 产生合格窗口的群 | 39 |
| 3–12 条、past-only 合格窗口 | 137,026 |
| Session gap | 30 分钟 |
| 重复记录 | 40,084 |
| 冲突记录 | 2,549 |
| 补缺记录 | 62,673 |
| 系统消息 | 7,091 |
| 撤回消息 | 3,069 |
| 未解析回复 | 18,292 |
| 排除私聊 | 是 |

切窗始终把 current message 放在最后，只使用此前历史。系统消息、当前
self-authored 消息和空消息按规则排除；撤回事件保留事实，但撤回正文不进入语义训练。
真实身份通过私有 opaque ref 处理，映射表和正文均未进入 Git。

## 4. Teacher 与 Silver

Teacher 固定为 `gpt-5.6-terra`，没有混用 Luna 或 Sol。

| 指标 | 结果 |
| --- | ---: |
| 分层目标 | 600 |
| 结构化草稿完成 | 592 |
| 请求阶段 Review | 8 |
| 质量条件合格预标注 | 464 |
| 编译后 Silver | 464 |
| 编译阶段 Review | 217 |
| 远程调用 P50 | 11.325 秒 |
| 远程调用 P95 | 22.860 秒 |

请求阶段的 8 条 Review：

| 原因 | 数量 |
| --- | ---: |
| 未知目标引用 | 4 |
| Teacher 引用文本无法定位 | 2 |
| 未验证的 reply 引用 | 1 |
| 未验证的 mention 引用 | 1 |

编译阶段 Review 的主要原因：

| 原因 | 数量 |
| --- | ---: |
| Teacher 报告存在歧义 | 102 |
| Teacher 决策不确定 | 98 |
| Teacher 置信度不足 | 9 |
| 请求阶段结构/引用问题 | 8 |

编译后的 Silver 分布：

| 任务 | 分布 |
| --- | --- |
| `need_tools` | false 447；true 17 |
| `semantic_complexity` | low 300；medium 160；high 4 |
| `answer_profile` | short 391；medium 73；long 0 |

这些标签只能称为 **Silver**。它们没有经过人工 Gold 复核，不能据此宣称真实中文
理解、工具判断、难度判断或回答长度已经校准。

## 5. Student 训练与评测

Student 使用字符 TF-IDF 加 Logistic Regression。数据按
`conversation_ref` 隔离划分，避免同一群同时进入训练与测试：

| 项目 | 数量 |
| --- | ---: |
| 训练群 / 样本 | 23 / 343 |
| 测试群 / 样本 | 6 / 121 |

所有指标均为 **held-out Silver agreement**，不是对人工 Gold 的准确率。

| 任务 | Accuracy | Macro-F1 | Weighted-F1 | 主要结论 |
| --- | ---: | ---: | ---: | --- |
| `need_tools` | 0.9917 | 0.4979 | 0.9876 | 与多数类基线相同，true 类未学到可靠召回 |
| `semantic_complexity` | 0.5702 | 0.2644 | 0.4468 | 略高于静态规则，但低于多数类准确率；medium/high 很弱 |
| `answer_profile` | 0.9421 | 0.4851 | 0.9141 | 与多数类基线相同，medium 未获得可靠召回 |

因此高 Accuracy 不能被解读为模型成熟。`need_tools` 和
`answer_profile` 的结果主要来自类别不平衡；`semantic_complexity` 也只适合用于
离线探索。

## 6. 全量预测与静态 Tier 预览

本地 Student 已对全部 **137,026** 个窗口完成预测：

| 输出 | 分布 |
| --- | --- |
| `need_tools` | false 135,397；true 1,629 |
| `semantic_complexity` | low 108,901；medium 28,091；high 34 |
| `answer_profile` | short 123,788；medium 13,238 |

Demo 没有创建第二套路由器。它把 Student 的 `semantic_complexity` 和置信度
投影到现有 `TaskComplexityAssessment`，再调用
`DeterministicModelTierPolicy` 展示 Haiku/Sonnet/Opus。低置信度或不满足
High guards 时仍按现有策略回落 Sonnet。

该结果只标记为 **STATIC TIER OFFLINE PREVIEW / 非生产路由**：

- Student 未接入生产 Router；
- 没有改变现有 Static Router 或 TierPolicy；
- 没有根据历史预测选择真实模型；
- 没有产生真实 Token 成本、延迟或回答质量证据。

## 7. 可复现命令

真实正文和模型产物只保存在仓库外。代码入口为
`ops/cli/private_corpus_pipeline.py`，本轮收口顺序如下：

```bash
uv run --locked --group corpus python ops/cli/private_corpus_pipeline.py compile \
  --output-root "<private-data-root>" --minimum-confidence 0.65
uv run --locked --group corpus python ops/cli/private_corpus_pipeline.py train \
  --output-root "<private-data-root>" --seed 230815
uv run --locked --group corpus python ops/cli/private_corpus_pipeline.py evaluate \
  --output-root "<private-data-root>"
uv run --locked --group corpus python ops/cli/private_corpus_pipeline.py predict \
  --output-root "<private-data-root>"
uv run --locked --group corpus python ops/cli/private_corpus_pipeline.py demo \
  --output-root "<private-data-root>" --sample-limit 300
uv run --locked --group corpus python ops/cli/private_corpus_pipeline.py serve \
  --output-root "<private-data-root>" --host 127.0.0.1 --port 8766
```

## 8. 下一阶段真正需要的输入

离线 Demo 已经闭环。若下一轮优先提升模型质量，最有价值的输入不是更多无标签原文，
而是一个小而均衡的人工 Gold 集：

1. 从当前 600 条中选取约 150–300 条，主动补足 Tool=true、medium/high 和 LONG；
2. 人工确认 `need_tools`、`semantic_complexity`、`answer_profile`；
3. 对歧义样本保留 abstain/无法判断，不强迫单标签；
4. 继续按群隔离评测，再决定是否扩大 Teacher 样本或更换 Student。

若进入实时 S23，则仍需独立提供：单群逐行为授权、当前 Dududa 流量的实时
Projection Adapter、生产 Provider conformance、真实来源 Adapter、Output 组合、
SecretRef、SLO、部署窗口和 rollback owner。实时 Shadow、入站 Canary、日报推送与
主动 Probe 均未因本轮 Demo 自动获得授权。

## 9. 完成边界

本轮可以声明：

- S23A–S23E 私有历史语料离线 Demo 已完成；
- 600 条是分层 Teacher 样本，不是全量 LLM 标注；
- 137,026 个窗口已完成本地 Student 预测；
- Demo 可在 localhost 打开；
- 结果和私有产物未提交 Git。

本轮不能声明：

- 当前 Dududa Bot 实时群聊已经验证；
- Teacher 标签是人工 Gold；
- Student 已达到生产语义质量；
- Student 已接生产 Router；
- 已进行 QQ 发送、Tool 调用、Memory 写入或 Bandit 在线学习；
- S23 实时 Shadow/Canary、日报推送或主动 Probe 已完成。
