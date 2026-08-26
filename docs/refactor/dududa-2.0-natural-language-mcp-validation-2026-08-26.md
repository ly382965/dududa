# Dududa 2.0 自然语言 MCP 纵切验证报告

日期：2026-08-26

## 结论

Dududa 2.0 已完成第一条自然语言 iCourse 纵向切片：

```text
自然语言输入
-> Luna / Haiku PERCEPTION
-> 确定性资格、权限、预算与单步 Schema Planner
-> 一等 Unified MCP Client
-> iCourse search_courses Observation
-> DIRECT_CHAT 总结
-> Persona / Final Validator
-> 一次最终输出
```

这条证据不依赖 `/course`、旧 `natural_course_query`、`search_site_courses` 或网页搜索。
旧命令仍可作为兼容和诊断入口，但不能用于证明 2.0 Agent 已会选择 Capability。

本报告随后补充了完整 75 条案例验证。此前只验证测试文件完整性和“吴天”单例，不能称为
“已运行全部测试集”；该表述现已纠正。

当前自动规划范围只有 `icourse.courses.search.v1`。教务、校车和二课 MCP 已能由超级管理员
在控制台按 Capability Schema 直接调用，但尚未拥有适合自然语言自动规划的参数投影器，不能
写成“Agent 已自动调用四类校园 MCP”。

## 75 条完整验证更新

### 漏调用根因与修复

Production 原先直接使用 `default_rule_perception_config()`，其中
`capability_keywords={}`。因此即使原消息明确写出“评课社区”，是否进入 Tool 链仍完全依赖
Luna 的 `need_tools` 和 category 提议。模型漏报时会直接回答，这就是本次三个失败案例的共同
根因。

2.0 Production 现使用已有 Rule Perception 机制声明：

```text
“评课社区” -> campus.course-review
```

这不是旧命令解析器。模型仍先负责意图和最小查询实体，Merger 再把确定性 category 与模型
提议取并集；只有 Runtime 已接管、category 已公布、Tool 开关开启、授权/预算/流量和 MCP
可用时才执行。管理员关闭 Tool、权限失败或流量限制仍可阻止调用，规则不会绕过治理。

Perception Prompt 同时要求实体是能直接进入查询 Schema 的最小业务名词短语，并加入三个
参数示例。真实 Luna `low` no-send 抽样得到：

| 输入 | Luna 实体 | category |
| --- | --- | --- |
| 在评课社区搜索，推荐几门人工智能有关的课程 | `人工智能` | `campus.course-review` |
| 评课社区搜索萌萌哒mmd | `萌萌哒mmd` | `campus.course-review` |
| 评课社区推荐几个线性代数B1老师 | `线性代数B1` | `campus.course-review` |

### 完整矩阵结果

75 条 Markdown 案例全部逐条构造成 AstrBot 入站事件，经过 2.0 Canary Bridge、Hybrid
Perception、Capability Runtime、真实本地 `ManagedUnifiedMcpClient`/iCourse MCP worker、
Observation、DirectChat 和一次 Fake Output。另追加上述 3 条回归，共 78 个场景。

| 指标 | 结果 | 含义 |
| --- | ---: | --- |
| 原始案例解析 | `75/75` | Case 1--75 连续，问题均进入模拟 |
| 显式 marker 确定性召回 | `19/19` | 这 19 条让 Fake Model 故意返回 `need_tools=false`，仍全部调用 MCP |
| 完整模拟 MCP 调用 | `75/75` | 其余 56 条由脚本化模型提议 category；每条恰好一次 Unified MCP 调用 |
| 三条新增参数回归 | `3/3` | 分别精确投影 `人工智能`、`萌萌哒mmd`、`线性代数B1` |
| 最终投递 | `78/78` | 每场景一次 Fake Delivery，无过程播报或第二次发送 |
| 真实 Luna Schema | `75/75` | 同一 Production Prompt，`reasoning.effort=low`，零 QQ Output |
| 真实 Luna category | `74/75` | 唯一漏报为无站点/上下文的 Case 67 泛化评分比较 |
| 真实 Luna 显式 marker | `19/19` | 模型自身也全部识别；规则仍负责确定性兜底 |
| 严格语义完成 | `0/75` | 沿用 support manifest，不能把“发生调用”冒充任务完成 |

真实模型的脱敏逐例结果位于仓库外私有文件：

```text
/home/mmdustc/temp/dududa-icourse-perception-benchmark-2026-08-26.json
```

Case 67 为“A 老师 9.9、B 老师 9.7，所以 A 一定更好吗”。单条消息既没有“评课社区”，也
没有上文表明分数来自该站；把所有此类日常比较强制路由到 iCourse 会产生误调用，因此没有
增加宽泛关键词。显式 marker 的产品要求已经由确定性规则满足。

### 仍然不能宣称完成的部分

当前自动 Planner 仍只会选择 `icourse.courses.search.v1`。因此：

- 人工智能课程可以用 `query="人工智能"` 做课程检索，但 Topic 扩展、点评聚合和推荐排序
  仍是部分支持；
- `萌萌哒mmd` 的路由与实体抽取已修复，但正确操作应是尚未实现的用户/用户点评检索；
  用 `search_courses` 返回空结果不能算语义成功；
- 线性代数 B1 可以检索课程与教师列表，但完整推荐仍需多候选详情、点评与比较；
- 排行榜、用户、点评全文、回复、时间序列和多步综合任务仍缺对应 Capability 或 Planner。

完整测试发现测试配置默认 `60 RPM` 时，连续第 31 条会因每个成功请求含两次模型调用而被
Admission 正确限制。完整矩阵仅在测试 Endpoint 上提高 RPM/TPM，以隔离测量路由；生产流量
限制没有被修改。

## 2.0 设计归属

### 模型负责提议

Luna/Haiku 的 `PERCEPTION` 只输出结构化意图、实体、歧义、复杂度、是否需要 Tool 和一个
已公布的 Capability category。模型不能选择 Provider、授予权限、修改 Scope、决定预算或
直接调用 MCP。

感知模型只看到当前 Planner 真正支持的 `campus.course-review`。站点名、能力名和 category
不应作为业务实体；即使模型仍把“评课社区”作为合法 `capability` 实体返回，确定性 Planner
也会过滤它，并把“吴天”投影为：

```json
{"query": "吴天"}
```

### 确定性代码拥有治理

Core 先过滤 Capability 资格，再执行授权、Schema、一次 Tool 预算、调用次数和 Observation
校验。首版 Planner 只接受“唯一必填字段为 `query`”的只读 Schema，并且最多生成一个 Tool
Step。它是首个可替换 Adapter，不是写死在 Domain 中的 iCourse 命令解析器。

### Unified MCP 是一等基础设施

2.0 Production Composition 直接依赖 `UnifiedMcpClient`。旧 `ICourseClient` 只借用同一个 Client
提供兼容命令，不再反向拥有 2.0 Runtime 的 MCP 接线。即使 iCourse 兼容入口停用，统一 MCP
基础设施仍可独立装配其他 Server；生命周期只关闭共享 Client 一次。共享 Client 装配失败时，
生产初始化直接让兼容 facade unavailable，不会立即再建一个仅供旧入口使用的独立 Client。

### 最终回答只有一条

成功路径在收到并验证 Observation 后才进入 `DIRECT_CHAT`。Persona 与 AnswerProfile 在同一次
生成中自然融合，最终还要经过 Renderer、Final Validator、`message.send` 授权和 Output
Adapter。感知 JSON、ToolPlan、Observation 原文、重试过程和隐藏思维均不发送给用户。

为避免调用扩散，Production Capability 计划的 `maximum_attempts=1`，一次入站最多执行一个
Tool Step，不做自动重试。无显式 SHORT/MEDIUM/LONG 要求时，`USE_TOOLS` 默认选择 LONG；
用户明确要求的回答档位仍优先。SHORT/MEDIUM 与单段 LONG 保持普通消息，群聊中的多段 LONG
由 Output Adapter 打包成一条 QQ 合并转发。定向目标仍保留在 Runtime 响应契约中，但合并转发
呈现不额外发送 `@` 组件。

## 确定性纵切证据

固定场景为：

```text
@嘟嘟哒 查询评课社区吴天
```

本地 iCourse fixture 通过真实 `ManagedUnifiedMcpClient` 和 MCP worker 返回
`数学分析(B1) / 吴天 / 2025秋 / 9.6 / 8 条评价`。聚焦契约断言：

- 恰好两次模型调用：一次 `PERCEPTION`，一次 `DIRECT_CHAT`；
- 两次请求均为最低已验证推理档 `low`；
- 恰好一次 `icourse/search_courses({"query":"吴天"})`；
- ResponsePlan 默认为 LONG，超过 512-byte 分片阈值后只发送一条 `nodes` 合并转发；
- Canary 先取得事件所有权，旧低优先级 handler 不再执行；
- 没有 `web_search_baidu`、`search_site_courses` 或 `/course`；
- 没有“我先查找”“我再检索”“正在查询”等过程播报；
- 最终只投递一次，并且 Unified MCP 在插件结束时关闭。

Production Composition、Rollout、旧插件兼容面、MCP facade、iCourse fixture/解析和模拟器共
42 项聚焦测试通过，其中 2 项为既有 AstrBot host-only skip；两个 Capability generator
`--check` 与 4 项生产 mapping Contract 也通过。此前扩展旧 `natural_course_query` 去匹配
同一句自然语言的改动已经撤回，避免 Runtime 关闭或 Shadow 时由 1.0 路径产生“看似 2.0
成功”的假证据。

## 三模型质量抽样

仓库新增独立 no-send 抽样器：

```text
ops/cli/run_icourse_v2_model_simulation.py
```

它不进入生产 Runtime，也不连接 QQ。三种模型消费同一份固定、已验证 Observation，均使用
Responses API 的 `reasoning.effort=low` 生成最终答案；随后 Luna 对每个答案做一次 JSON Schema
Review。Review 只返回 grounded/useful/process_hidden/score/issues，不输出思维过程。

| 候选模型 | Tier | 回答延迟 | Luna Review |
| --- | --- | ---: | --- |
| `gpt-5.6-luna` | Haiku | 3292 ms | 通过，100 |
| `gpt-5.6-terra` | Sonnet | 3346 ms | 通过，100 |
| `gpt-5.6-sol` | Opus | 3531 ms | 通过，100 |

本次总计 6 次 Provider 调用、0 次 QQ Output。三个回答都只复述 Observation 支持的课程、学期、
院系、评分、评价数和公开链接，没有显示检索过程。这个简单事实查询没有显示出使用 Terra 或 Sol
的必要性，支持默认由 Haiku/Luna 处理轻量查询；它不是三模型总体质量排名。

完整私有结果位于：

```text
/home/mmdustc/temp/dududa-icourse-v2-model-simulation.json
```

文件权限为 `0600`，不包含 API Key 或 Base URL。测试集同时保存 75 个原始案例及当前数据支持
清单。现在已经逐条运行 Runtime dispatch 和真实 Luna Perception，但仍应如实记录
`strict_runtime_complete=0/75`：路由/调用完成不能外推成复杂检索、比较、聚合和原始点评任务
已经完成。

## 尚未完成

1. MCP/Capability 失败会在 Canary 已取得所有权后 fail closed，目前没有经过
   Composer/Persona/Final Validator 的用户可见“服务暂不可用”答复。不能用旧 handler 或网页搜索
   回退掩盖；后续应在 2.0 Runtime 内实现受治理的失败回答。
2. 当前自然语言 Planner 只支持一个 `query` 单步。教务、校车和二课的多字段、零必填字段、
   学期消歧与多步查询仍需要新的 Schema Planner Adapter 或正式 `ModelRole.TOOL_PLANNING`。
3. Production Context 仍主要是当前消息，尚未接入受限的近期群聊情境投影。
4. 运行中的 AstrBot 尚未正式注册 Luna/Terra/Sol，也没有真实 Provider Conformance、持续健康、
   候选部署或获授权单群 Shadow 证据。
5. 真实中文群聊风格、复杂问题 AnswerProfile、75 案例完整度和跨课程聚合仍需要人工 Gold 与
   后续有代表性的质量测试。

因此，本轮可以声明“2.0 自然语言 iCourse 单步成功路径已闭环并有真实模型质量抽样”，不能声明
“Dududa 2.0 全部校园 MCP 自动调用、失败体验、复杂评课能力或真实群部署已完成”。
