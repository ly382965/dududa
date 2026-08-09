# dududa20-prototype / dududa20-plugin 批判性审查与可迁移性报告

审查日期：2026-08-08

当前 Dududa 基线：`4c6686bab559be1ffe0e66de0860828e44876678`

prototype 基线：`0873928957acf0a165975321a4e56d8c617d8ee5`

plugin 基线：`97f55f41ea583392d72764ca94d7ce5db3be0e6c`

审查对象：[`dududa20-prototype`](https://github.com/Shaywww/dududa20-prototype)、
[`dududa20-plugin`](https://github.com/Shaywww/dududa20-plugin)。报告中的 `P/` 和 `G/`
路径分别指 prototype 与 plugin；所有判断固定在上述提交，不跟随后续 `main` 漂移。

## 1. 结论

这两个仓库可以作为“需求、失败场景和局部算法素材库”，但不能作为当前 Dududa 的新基线，
也不应整体合并、cherry-pick 或直接部署。

核心判断如下：

1. `dududa20-prototype` 确实包含一套较大的 Runtime 原型，且大部分测试在修正作者机器的
   绝对路径后可以运行；但它的 DTO、依赖方向、路由、权限、投递和上线控制均弱于当前
   Dududa 已完成的 S01-S11。
2. `dududa20-plugin` 在与特定 prototype 提交、固定目录和 AstrBot 环境配对时可以加载，
   但不是独立插件，也不是 README 所称的薄 Adapter。它会建立第二条全消息处理链，不能与
   当前 `astrbot_plugin_dududa_core` 并存启用。
3. 两个仓库当前都没有 LICENSE、COPYING 或 NOTICE。公开可见不等于获得复制、修改和再分发
   授权。在贡献者补充许可证、签署贡献/转让确认或项目方确认既有权利链之前，不复制代码、
   测试数据和文档原文。
4. 可吸收的主要价值是测试向量和需求：Structured Output 整包校验、MCP 错误/取消/熔断、
   Connector 跨会话拒绝、Memory WriteGate、Persona Fact Anchor、搜索排序和运维门禁。
   这些内容应按当前契约重新实现，而不是搬运旧模块。
5. 这不是“纯空壳”，但整体属于**半成品文档驱动的 checklist/feature-stacking 原型**：
   宽度和测试数量很大，关键契约、纵向闭环、默认安全与真实证据仍浅。第 6 节给出可复核的判定边界。
6. Contextual Bandit 适合 Dududa 未来的同 Tier Endpoint 优化，但不应直接接入这两个
   协作仓库。它们缺少合法 action set、propensity、执行前持久日志和可回滚策略发布；
   应先将少量有价值的场景迁入当前 Dududa，再按 S20A/S20B 实施。
7. 当前 Dududa 继续作为唯一权威 Runtime，S08-S11 不重新设计；真实群聊测试仍放在
   全部模块、本地审计和测试 WebUI 完成之后。

## 2. 总体处置表

| 对象 | 当前判断 | 处置 |
| --- | --- | --- |
| prototype 生产代码 | 无可直接合并模块 | 保留只读审查副本，不合并 |
| plugin 生产代码 | 能配对加载，但不能独立、安全上线 | 不安装，不与当前插件并行启用 |
| 需求和失败场景 | 有价值 | 转成当前仓库 Issue/测试向量 |
| 小型 Eval fixture | 可补充边界样本，但不能证明科学有效性 | 取得授权后转换 Schema、人工复标 |
| 纯规则素材 | 搜索排序、Profile 提取等有局部价值 | 逐项重写并做行为对照测试 |
| Router / Runtime / DTO | 与当前 S08-S11 冲突 | 舍弃 |
| Mock 校园数据及失败回退 Mock | 会产生假数据和假成功 | 删除该方案，不迁移 |
| Docker / Compose / 运维脚本 | 存在旧入口、硬编码路径和构建错误 | 仅参考检查项，不使用脚本 |

“可直接复用”是指可以进入当前生产实现，而不是“文件可以被 Python 导入”。按这个标准，
当前可直接复用的生产代码数量为 **0**。这不是对原型工作量的否定，而是由许可证、契约和
安全边界共同决定的工程结论。

## 3. 审查基线：当前 Dududa 的开发哲学

本报告以当前 `.TreeWork/spec.md`、`docs/design/model-routing.md`、
`docs/adr/0004-unified-mcp-client.md`、`docs/refactor/implementation-plan.md` 和
`docs/refactor/s08-s11-completion-audit.md` 为准：

- Core 只依赖标准库和内部包；AstrBot、Provider SDK、MCP SDK、存储和凭据属于 Adapter。
- 公共 DTO 必须版本化、`frozen=True`、`slots=True`、防御性不可变，并绑定 canonical digest。
- 难度判断和模型路由是一条单向流水线，但模块权威分离：

```text
Connector / Context
  -> 固定 Haiku 的 Perception + Rule Perception
  -> 整包 Validator + 确定性 Merger
  -> TaskComplexityAssessment
  -> TierSelectionContext
  -> DeterministicTierPolicy (Haiku / Sonnet / Opus)
  -> StaticModelRouter 硬过滤、固定优先级、原子容量准入
  -> Provider Adapter
```

- 隐私、驻留、retention、能力、上下文、预算、健康和流量阈值是硬约束，不能由模型名、
  Prompt 或高奖励绕过；fallback 必须是显式无环配置。
- 默认拒绝，无假成功、无生产 Mock 数据、无自动 Memory/Tool；副作用必须显式授权。
- Shadow 没有发送、Memory、Tool 或 `event.stop` 能力；Canary 必须白名单、持久 claim、
  发送前复核 kill switch，并能回滚。
- S08-S11 当前不接 Bandit、随机权重和在线探索。同一输入与同一 snapshot 的决策必须一致。

这条基线已经在当前 Dududa 中实现并完成本地审计，因此协作者实现只能补充尚未覆盖的场景，
不能反向替换更严格的契约。

## 4. 实际可运行性

| 检查 | 结果 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| 两仓库 `compileall` / `py_compile` | 通过 | Python 语法基本有效 | Runtime 正确、依赖完整、生产安全 |
| prototype `uv build` | sdist/wheel 构建成功 | 包结构可构建 | wheel 可独立运行 |
| 只安装 wheel 声明依赖 | `import dududa` 成功；导入 Runtime 因缺 `httpx` 失败 | `pyproject.toml` 依赖不完整 | 可发布性 |
| 原样运行 prototype 测试 | 收集失败 | 测试依赖作者目录布局 | 独立可复现性 |
| 临时改写绝对路径，AstrBot 4.14.6 | `1113 passed, 5 failed, 5 deselected` | 大量局部行为已有测试 | 当前架构合规、测试本身可信 |
| AstrBot 4.26.2 断网加载配对仓库 | 加载成功，注册 16 个 priority-0 Handler 和 12 个 MCP 能力 | 特定组合可以启动 | 模型回复、真实投递、权限和上线安全 |
| 插件相关 351 项断网测试 | `349 passed, 2 failed` | 多数装配测试可跑 | 完全离线；两项天气测试真实访问 `wttr.in` |
| Compose 配置解析 | 通过 | YAML 可解析 | 镜像能构建或启动 |
| Compose 构建 | 失败，根目录没有其寻找的 Dockerfile | 部署文件发生迁移漂移 | 可部署性 |
| Shell `bash -n` | 通过 | Shell 语法有效 | 运维语义和目标环境正确 |

prototype 的 5 个失败集中在运维门禁、manifest/smoke 和 logger bridge；另有两个
Output Adapter 测试调用 coroutine 却没有 `await`。部分测试包含恒真断言，例如
`result is not None or result is None`。因此“超过一千项通过”只能说明实现面较广，不能直接
转化为质量置信度。

本次没有执行真实模型、真实 MCP、真实 QQ 发送或真实群聊测试，也没有使用生产凭据。

## 5. 模块完成度与兼容性

这里的“实现状态”描述协作者仓库中是否存在相应代码；“兼容性”描述它是否满足当前 Dududa
契约。这两个维度不能混为一谈。

| 模块 | 协作者实现状态 | 与当前哲学的兼容性 | 决策 |
| --- | --- | --- | --- |
| 模型路由器 | 部分实现：8 个 Role、主/备模型 | 不兼容：无难度 assessment、TierPolicy、三档 Tier、Endpoint Descriptor 和容量准入 | 舍弃实现 |
| Memory | 部分实现：Scope、Candidate、WriteGate、JSON 存储 | 仅概念接近；存在自动写入、弱 Scope/回执绑定 | 只参考负向场景 |
| MCP 集成 | 部分实现：registry、stdio JSON-RPC、12 个服务 | 默认允许、默认/失败回 Mock，deadline 与取消不闭合 | 保留测试思想，按 ADR-0004 重写 |
| 输入 Connector | 部分实现：AstrBot 输入、图片/文件处理、判重 | 固定路径、任意路径/URL、进程内判重、全消息入口 | 只迁移测试向量 |
| 语义理解 | 部分实现：Rule/Model、结构化输出、Merger | 有可取方向；无当前版本化 Schema、可信证据链和 Complexity/Tier 闭环 | 扩充当前 S09 测试，不换实现 |
| OC / Persona | 部分实现：预设、Renderer、Fact Anchor | 方向基本可取；仍需当前事实/拒绝/目标绑定和确定性约束 | 作为内容与测试素材 |
| Runtime / Delivery | 大量代码存在 | 多权威路径、假成功、弱幂等、无持久 ownership | 舍弃实现 |
| S11 Rollout | 未实现 | 无 `off/shadow/canary`、白名单、持久 claim、kill switch | 使用当前 Dududa 实现 |
| Control Plane / WebUI | 部分实现 | 鉴权和审计存在高风险，部署入口已失效 | 仅参考需求；本轮不深验 UI |
| Eval / 运维 | 部分实现 | 样本过小、网络测试未隔离、路径和环境硬编码 | 拆出 fixture/checklist 后重建 |

### 5.1 模型路由与智能难度判断

prototype 的 `router/router.py:17-26` 只有角色枚举；`router/router.py:151-168` 默认把八个
角色都配置到 `gpt-5.6-sol`。实际 `application/dududa_core.py:529-546` 的统一 LLM 入口又
固定使用 `RESPONSE_COMPOSITION`，plugin 的模型感知也经该入口调用。因此“八角色路由”在
配置和真实调用路径之间没有闭环。

它缺少当前 S08/S09 已具备的：

- `TaskComplexityAssessment`、可信 evidence refs 和 assessment digest；
- Haiku/Sonnet/Opus 的 `TierSelectionContext` 与 `TierDecision`；
- Endpoint 能力、上下文、reasoning、隐私、驻留、retention 和流量快照；
- 调用前估算、预算门禁、共享 quota pool 和原子 reservation；
- 可重放 selection fingerprint、显式 fallback DAG 和失败分类。

此外，prototype 的 `route_hint` 在允许时可以直接影响 Provider 的 `model_id`
（`router/router.py:252-268`），不能满足当前“用户文本不可信、RouteHint 只能在硬过滤后的
候选中重排”的约束。

更严重的是，无 Provider 或调用失败时会返回成功形态的 stub，Direct Chat 甚至回显用户输入
（`router/router.py:270-280, 355-370`）。这违反“无假成功”。旧 plugin `_router.py` 只是按
text/file/image 映射模型的第二套 Router，应直接废弃。

结论：模型名称、token、temperature、effort 等配置值可以人工转换成当前 Endpoint Catalog
的候选配置，但 Router、Provider 和调用链不迁移，也不重新设计当前 S08/S09。

### 5.2 DTO、Port 与依赖方向

prototype 的 `ModelRequest` 虽然 `frozen=True`，内部仍含可变 `list[dict]` 和 `dict`
（`router/router.py:99-109`）；`RuntimeState` 也包含可变 trace list。Envelope、ModelRequest、
DeliveryReceipt 等关键对象没有统一 Schema 版本、canonical digest 和 component revision。

Port 大量使用裸参数、`Any` 或 `**kwargs`，没有统一携带绝对 deadline、取消、预算、幂等和
审计上下文。Core 又依赖 Pydantic，具体 HTTP/FastAPI 依赖还没有完整声明到 wheel。

结论：DTO、Protocol、Core package 和 Runtime State 全部不迁移。任何候选逻辑必须重新接到
当前 `dududa.contracts`、`dududa.ports` 和 Adapter 边界。

### 5.3 Memory

`MemoryScope -> MemoryCandidate -> WriteGate -> Delivery Ack` 的概念方向可以保留，尤其适合
生成新的拒绝、跨群隔离、重复确认和迁移回滚测试。但当前插件会自动保存文本、图片或文件
相关内容，部分路径不能证明发生在可靠投递确认之后；这与首个 Runtime 的 Memory-off、显式
候选和受约束 WriteGate 不一致。

结论：不迁移 Repository、Scope 或写入链。只提取当前测试未覆盖的场景；Profile 的称呼、
偏好和所在地规则只能生成显式候选，不能自动写入生产 Memory。

### 5.4 MCP 与校园能力

stdio JSON-RPC、错误归一化、allowlist、幂等重试、取消和熔断的测试思路有价值；天气、新闻、
搜索排序等只读能力也可成为后续 Adapter 候选。但现有实现有三项阻断问题：

1. MCP access 配置缺失时默认允许（`mcp/access.py:47-58, 109-117`）；空 allowlist 也会变成
   allow-all（`mcp/client.py:450-476`）。
2. 多个校园服务默认返回硬编码 Mock；真实 MCP 失败时 `UnifiedMCPProvider` 还能静默回落
   Mock（`mcp/client.py:561-601`），会把虚构课表、考试、成绩或通知当成事实。
3. 手写 Client 没有完整接入当前 `PortCallContext`、绝对 deadline、取消、结果大小、来源和
   生命周期契约。

它还把连接、发现和业务 Provider 分散在多条路径中，不能满足当前 ADR-0004 的“一个统一
Client、一个 Registry、复用受控 session”边界；迁移时应补标准握手通知、session 关闭和
重启恢复测试。

结论：保留错误场景和服务需求，不迁移 Client。按 ADR-0004 由一个统一基础设施 Client 管理
Registry、受控 session、SDK、权限、Schema、重试、熔断和关闭；任何 live 失败必须显式失败，
绝不退回生产 Mock。

### 5.5 Connector、插件与投递

plugin `main.py:13` 硬编码 `/opt/dududa20-prototype/...`，两个仓库没有包版本、commit digest
或兼容矩阵绑定。`main.py` 约 495 行，集中导入 40 多个对象、构造全局 Provider/Router，默认
启用 Router、模型感知和 Hybrid Renderer，并注册 `ALL` 消息 Handler；它不是独立薄壳。

prototype 的分发名为 `dududa-agent==0.1.0`，当前主项目也发布同名包（当前为
`0.1.0a1`）；直接安装可能覆盖当前包而不一定立刻报 ImportError。plugin 的 AstrBot ID
`dududa20` 也不同于当前 `astrbot_plugin_dududa_core`，切换它会改变加载优先级和回滚对象。

其他关键问题：

- Vision 未单独配置 key 时，会把 `DEEPSEEK_API_KEY` 发往另一个默认网关
  （`plugin/main.py:74-80`）。
- 任意绝对路径和任意 URL 可进入附件读取/下载路径，缺少可信来源和 SSRF 边界。
- 消息去重和 pending delivery 只在进程内，重启、并发实例和回放不受保护。
- `after_message_sent` 路径无条件生成 `SUCCEEDED`，而 prototype Output Adapter 自己也只
  构造 result chain，没有证明真实发送成功。
- Trace 保存消息、session 和回复片段，不符合当前低基数、脱敏指标契约。
- 没有 `off/shadow/canary`、显式提及门禁、持久 claim、发送前 kill switch 或回滚闭环。

结论：不安装该 plugin，不添加第二个 `ALL` 入口。需要的新命令或产品能力只能进入当前
`astrbot_plugin_dududa_core` 的既有 composition root 和 rollout bridge。

### 5.6 语义理解、OC 与 Eval

Structured Output “字段整体校验失败即丢弃”、Rule 证据优先、Persona 渲染保持事实锚点、
引用和拒绝结论，这些方向与当前哲学一致。不过当前 Dududa 已经有更严格的 Validator、Merger、
Complexity、TierPolicy 和确定性 Renderer，因此只需要补场景，不需要换实现。

prototype 共有约 50 个小型 Eval case：Perception 10、Social 8、Social Policy 10、Memory 4、
OC 3、Tool 4、Capability Retrieval 11。它们可作为边界回归候选，但样本过小、来源单一，且
部分阈值直接要求 100%，不能证明泛化、校准、最佳 Tier 或真实群聊效果。取得授权后仍需要：

- 转成当前版本化 fixture Schema；
- 去除真实 ID、路径、网络和实现细节；
- 由不了解实现输出的人重新标注；
- 按模板族和会话 lineage 分组，避免数据泄漏；
- 与当前 320 条 S09 固定数据集合并时保留独立来源和 digest。

## 6. 是否属于半成品文档驱动的 vibe coding

### 6.1 直接判定

**是，但必须限定这个结论的含义。**

无法从 Git 仓库反推作者是否使用了 AI，也不应将“vibe coding”当成对作者动机的
指控。本报告只对可观测的工程结果下结论：这是一个按半成品 2.3/2.5 文档条目快速铺开
模块宽度的原型，实现方式更接近 **checklist-driven feature stacking**，而不是通过生产反馈
逐层收敛的架构。

| 判定维度 | 实际证据 | 结论 |
| --- | --- | --- |
| 需求覆盖 | Router、Memory、MCP、Connector、Perception、Persona、Control Plane 都有文件和测试 | 宽度高 |
| 契约深度 | 可变 frozen DTO、大量裸参数/`Any`、无统一 version/digest/call context | 核心边界浅 |
| 纵向闭环 | 8 Role 默认同一模型，实际 LLM 入口固定一个 Role；真实失败又回到 stub/Mock | 功能名称没有连成产品行为 |
| 权威路径 | Core、Orchestrator、plugin Router、prototype Router 同时存在 | 多路径互相绕过 |
| 安全默认 | MCP 缺配置/空 allowlist 可放行，失败回 Mock，插件功能默认开启 | 不满足 fail closed |
| 测试证据 | 数量较大，但含绝对路径、真网络、恒真断言、未 `await` 和小型同源 fixture | 能证明局部行为，不能证明产品质量 |
| 可部署性 | wheel 漏依赖，Compose 入口失效，plugin 硬编码 `/opt` 配对路径 | 作者环境外不可复现 |
| 研究迭代 | 无真实群数据、独立标注、模型对照、置信区间或基于失败的迭代证据 | 不是科学验证后的智能系统 |

### 6.2 不应否定的部分

“原型”不等于“无价值”。下列工作说明它不是只创建了空类和 README：

- prototype 有超过千项可运行的局部测试，很多失败、取消、Scope 和结构化输出场景确实被考虑；
- Structured Output 整包拒绝、Rule 优先 Merger、Memory WriteGate、Persona Fact Anchor 等思路是可用的；
- plugin 与固定 prototype/AstrBot 组合可以断网加载，证明它至少完成了一次具体装配；
- MCP 取消/熔断、Connector 跨会话、Memory 迁移回滚和 Persona 保真场景，可以转成新主线的需求与负向测试。

所以应批评的不是“写得少”，而是**用功能数量和测试数量代替了契约闭环、默认安全、
科学证据和可运维性**。这正是它不能成为当前 Dududa 基线的根本原因。

## 7. 可吸收内容清单

### 7.1 现在可以吸收的“思想和需求”

| 候选 | 使用方式 | 不做什么 |
| --- | --- | --- |
| Structured Output 负向场景 | 补畸形 JSON、部分字段、越权实体、跨 Context 引用测试 | 不复制旧 Pydantic DTO |
| MCP transport 故障场景 | 补 initialize/discover/call、取消、超时、崩溃、half-open、重复调用测试 | 不搬手写 Client |
| Connector 场景 | 补跨会话 reply、拆分 @/图片、重复消息、重启回放测试 | 不搬固定路径插件 |
| Memory 场景 | 补跨群/跨人隔离、WriteGate 拒绝、投递 UNKNOWN、迁移回滚测试 | 不启用自动写入 |
| Persona 场景 | 补 Fact Anchor、引用、拒绝、目标用户和附件约束保持测试 | 不让 Renderer 改事实 |
| 搜索排序需求 | 将权威来源、同域去重、视频意图等规则写成独立规格 | 不直接复制实现 |
| Control Plane ADR | 提取独立进程、只读优先和审计需求 | 不迁移现有鉴权代码 |
| 运维门禁清单 | 对照当前 `manage.sh`/CI 查漏补缺 | 不使用硬编码脚本 |

### 7.2 许可证解决后才评估的代码/数据候选

- `mcp/web_search_service.py` 的纯 `_rank_results` 规则；
- weather/news 的只读解析逻辑，但必须增加 provenance、大小上限和严格错误；
- `core/profile.py` 的确定性提取规则，但输出只能是 Memory/Profile Candidate；
- `tests/evals/fixtures/` 中经人工复标的小型样本；
- Connector、MCP、提示注入和投递相关的负向测试输入。

即使取得授权，这些候选也应逐项移植，不应复制整个文件。每项都需要独立 Issue、当前契约
适配和对照测试。

## 8. 明确舍弃的内容

- prototype 的 Router、Runtime、State、DTO、Protocol 和 OpenAI Provider；
- plugin 的整个 `main.py` 消息链及 `_router.py`；
- 失败时回显用户输入、返回 stub 或报告成功的所有路径；
- 所有生产 Mock 校园数据及 live-failure-to-mock 行为；
- `random.random()` 驱动的群聊参与、reply rate 和 meme rate 决策；
- 缺配置默认允许、空 allowlist 允许全部、隐私分支 `pass` 的权限逻辑；
- 自报 Header 角色的 Control Plane RBAC，以及审计失败仍放行的写路径；
- 进程内 pending delivery/幂等作为生产一致性方案；
- 硬编码 `/opt`、`/root/data/plugins` 的测试和部署脚本；
- 当前 Dockerfile、Compose 和旧 `packages.control_plane` 启动入口。

## 9. 实时学习 / Contextual Bandit 对这两个仓库的判定

### 9.1 它们当前没有 Bandit Learning

在两个固定提交中，没有发现 Bandit policy、propensity、reward event、decision/feedback join、
OPE、policy artifact 或 rollout 实现。prototype 的“概率参与”只是：

```text
reply_rate / meme_rate / interruption_cost
  -> random.random()
  -> ANSWER / REACT / IGNORE
```

这是无状态抽样，不会从反馈更新参数，不记录行为概率，不可重放，也无法做离线策略评估。
它不是 epsilon-greedy，更不是 Contextual Bandit。将 `reply_rate` 改成“可学习参数”也不会
自动获得 Bandit 的统计性质。

| Bandit 生产前提 | prototype / plugin 现状 | 影响 |
| --- | --- | --- |
| 稳定且合法的 action set | 8 Role 默认同模型，实际调用固定 Role，无 Tier/硬过滤 | 无法定义“当时可选的同类动作” |
| 执行前持久决策日志 | Trace 为普通进程内记录，无 action set/distribution/digest | 无法恢复行为策略 |
| 精确 propensity | `random.random()` 结果未与决策持久绑定 | IPS/DR 不可识别 |
| 可信 outcome | 无 Provider 时可返回 stub，MCP 失败可回 Mock，投递可被记为成功 | reward 会被假成功污染 |
| 延迟反馈关联 | 无独立 feedback ID、时间窗口、幂等 join | 用户反应无法归因 |
| 冻结快照和回滚 | 无 policy version/artifact/digest/last-known-good | 在线更新不可审计 |
| 安全 rollout | plugin 功能默认开，无 off/shadow/canary 能力分离 | 不得进入真实群探索 |

因此，**不应在 `dududa20-prototype` 的 Router 或 Social Decision 上继续堆 Bandit**。
那会让学习器优化一条本身就会假成功、绕过权限且不能重放的路径。

### 9.2 与 Bandit 相关但只能作为素材的部分

| 现有素材 | 可用之处 | 迁移方式 |
| --- | --- | --- |
| `ModelRole` 与 ModelResponse latency/usage | 可帮助列举候选 feature/outcome | 映射到当前版本化 DTO，不复用旧 Router |
| `reply_rate` / `meme_rate` / `interruption_cost` | 揭示了社交打扰成本这个产品变量 | 作为人工 Policy 需求，第一阶段不作 Bandit action |
| Trace 中的 role/model/latency/error 概念 | 说明需要路由观测 | 重新定义 before-action receipt，不迁移原始 Trace 格式 |
| 小型 Eval fixture | 可作 synthetic environment 的边界种子 | 先解决许可证，再脱敏、复标和转换 Schema |
| 成本、延迟、成功率目标 | 可作 reward component 候选 | 分量保存，不立即压成单一分数 |

`random.random()` 的现有社交决策、旧 Router 和旧 Trace 本身全部舍弃。可迁移的是“需要
观测哪些变量”，不是其实现。

## 10. 迁入当前 Dududa 后的 Bandit 技术方案

### 10.1 唯一合法的首期决策点

```text
DeterministicTierPolicy 确定 Role + Haiku/Sonnet/Opus
  -> StaticModelRouter 按隐私、驻留、retention、Schema、上下文、预算、健康、容量硬过滤
  -> 得到两个以上同 Role + 同 Tier + 语义兼容的 eligible Endpoint
  -> Bandit 只重排/选择 Endpoint
  -> before-action durable log
  -> Provider 执行
  -> 延迟 Feedback Worker
  -> OPE 与安全门禁
  -> 原子发布 immutable Policy Snapshot
```

第一阶段 Bandit 不得选择 Tier，不得授权 MCP/Tool/Memory/投递，不得绕过任何硬过滤，
不得在群聊探索 Reply/Ignore。Prompt、Search、Tool 和 Persona Style 以后必须建立各自独立的
experiment/reward 契约，不能与模型路由混训。

### 10.2 推荐技术栈

外部项目状态按 2026-08-08 调研；算法库只负责策略计算，不代替 Dududa 的契约、日志、
权限和发布门禁。

| 组件 | 定位 | 选择 |
| --- | --- | --- |
| [Vowpal Wabbit 9.11.2](https://github.com/VowpalWabbit/vowpal_wabbit) | 成熟 online contextual bandit、ADF、exploration 和 IPS/DR reduction；BSD-3-Clause | **生产策略引擎首选**，放独立 Worker/Adapter |
| [MABWiser 2.7.4](https://github.com/fidelity/mabwiser) | LinUCB/LinTS/`partial_fit`，轻量易比较 | 离线基线，不作请求路径依赖 |
| [Open Bandit Pipeline 0.5.7](https://github.com/st-tech/zr-obp) | IPS/SNIPS/DR/Switch-DR 与合成数据工具较全 | 独立 research container 交叉验证 OPE |
| [River 0.25.0](https://github.com/online-ml/river) | 在线学习与 drift 组件 | 只研究 drift；不用其较慢 LinUCB 作首版 |
| [contextualbandits 0.3.30](https://github.com/david-cortes/contextualbandits) | 算法广 | 只作研究对照；二元 reward、Cython/OpenMP 与序列化增加运维风险 |

单人首版的最小组合：

```text
dududa-agent Core
  - 标准库 Bandit DTO / Protocol / Validator
  - Static Router 仍拥有 hard eligibility

services/bandit-worker
  - Vowpal Wabbit --cb_explore_adf
  - decision/feedback 幂等 join
  - nearline learner + immutable artifact publisher

runtime storage
  - 单实例先用 SQLite WAL append-only event store
  - Parquet export + artifact manifest + SHA-256 digest

offline evaluation
  - DuckDB/NumPy 实现项目自有 IPS/SNIPS/DR/ESS/cluster bootstrap
  - OBP 独立环境交叉检查 estimator
```

第一版不引入 Kafka、Feast、Ray、Celery、MLflow 或 VW RL Client。单 Bot/单 Worker 使用 SQLite WAL
足够；只在多写实例或锁竞争成为真实问题后迁 PostgreSQL。

### 10.3 日志、Reward 和 OPE 底线

保守行为策略使用与静态 baseline 的混合分布：

```text
p_behavior(a | x)
  = (1 - epsilon) * I[a = baseline]
  + epsilon * p_candidate(a | x)
```

每次执行前必须原子持久 decision/experiment ID、完整 action set 及其顺序、baseline/candidate/
behavior distribution、executed action、精确 propensity、feature/reward/policy revision、
snapshot/digest 和采样值。日志失败时只允许执行确定性 baseline。

Reward 要保存可审计分量，不只保存加权总分：

```text
explicit_satisfaction
task_success
delivery_success
quality_audit_score
latency
token_cost
retry/fallback
```

隐私、权限、事实保持、重复发送和错误目标必须是零容忍硬门禁，不得被高满意度抵消。
用户显式 reaction/`/rate`、有 Schema 的任务回执和盲审才是质量反馈；群聊沉默、下一条无关消息、
Bot 自称“完成”不是 reward。未观测反馈标记 `PENDING/CENSORED`，不能按 0 填充。

候选 Policy 发布前同时报告 IPS、SNIPS、DR、ESS、最大 importance weight、action coverage 和
paired effect；按 group/conversation 做 cluster bootstrap，不将同群消息当作独立样本。

### 10.4 S20A / S20B 实施顺序

**S20A：离线与 Shadow 基础，可在真实群测前完成**

1. 冻结 Bandit ADR、DTO、Feature/Reward Schema 和安全非目标。
2. 实现 append-only decision/feedback store、before-action receipt 和幂等 join。
3. 实现 Static Baseline、合成环境和 IPS/SNIPS/DR golden tests。
4. 接入 VW Adapter，先只跑 synthetic/offline replay。
5. 进入 log-only 和 recommendation-only Shadow；candidate 没有发送/Tool/Memory 能力。
6. 演练 artifact digest、原子发布、last-known-good、kill switch 和 rollback。

S20A 只能证明接口、覆盖、日志、延迟和建议可重放，不能声称策略提升。

**S20B：受控在线学习，只能作为最终真实群验证的内部子门禁**

1. 先用静态 Router 完成授权单群 baseline/shadow。
2. 预注册 eligible Endpoint、epsilon 上限、SLO、停止规则和反馈窗口。
3. 仅对同 Tier 安全 Endpoint 开启极小 conservative canary；不为追样本临时提高 epsilon。
4. 达到 support/ESS 后做 OPE 和 cluster bootstrap。
5. 质量下界、成本/延迟和零安全违规同时通过后，才允许 exploit。
6. 任何安全违规、coverage 崩塌、异常 importance weight 或 drift 立即回静态 baseline。

完整的主仓库 Bandit 审计与方法学参考保留在
`docs/reviews/core-modules-bandit-critical-audit.md`；本节的核心结论是：**先舍弃两个协作仓库的
决策实现，再在当前 Dududa 已硬化的 Static Router 后接 Bandit。**

## 11. 单人迁移顺序

### P0：隔离和权利边界

1. 将两个审查提交记入只读第三方来源清单，不安装、不部署、不合并。
2. 请贡献者补 LICENSE 或书面贡献/转让确认，并明确测试数据、Persona 文案和第三方来源。
3. 为每个候选建立独立 Issue，只记录需求、输入/输出和失败条件，不以旧文件为模块边界。
4. 先把绝对路径、真实网络、恒真断言和未 `await` 测试列为不可迁移项。

完成条件：权利链明确；候选清单可追溯；当前生产配置和 Runtime 没有变化。

### P1：只迁移测试价值

1. 对照当前覆盖率，优先补 MCP default-deny、超时/取消/熔断、Connector 跨会话/重放、
   Memory WriteGate 和 Persona Fact Anchor 的缺失负向用例。
2. 所有外部 HTTP 使用 Fake Transport；网络测试必须显式标记并默认不运行。
3. fixture 转换为当前版本化 DTO，并重算 canonical digest；不兼容输入应 fail closed。
4. 跑当前全仓、import boundary、Ruff、secret scan、双 Python 版本和断网插件 smoke。

完成条件：新增测试能在旧缺陷实现上失败、在当前实现上通过；无生产行为变化。

### P2：按现有单人主线实现新增产品能力

按 `docs/refactor/implementation-plan.md` 的顺序，把候选内容放回拥有它的阶段：

1. **S12 MCP**：先写 Capability/Adapter Spec，再重写统一 Client、Registry、握手、持久
   session、Schema cache、超时/重试/熔断和结果提取；只切只读课程路径，失败显式，不返回 Mock。
2. **S13 Tool/语义**：吸收取消、逐步授权、Prompt Injection、城市守卫和搜索排序 fixture，
   先覆盖只读能力，不复制通用 Planner，也不让动态 Tool 自动获得权限。
3. **S14 Memory**：只比较新增的隔离、TTL、冲突、删除/导出和投递依赖案例；自动写入仍关闭，
   所有写入经过当前 Repository contract 和 WriteGate。
4. **S15 OC/Persona**：迁移事实锚点、引用、拒绝、目标和附件保持 fixture；资产版本化、带 digest、
   可人工审查和可回滚。
5. 模型配置只转换为当前 Endpoint Descriptor、Reasoning Profile 和 Catalog 数据，不修改
   S08/S09 的难度判断或静态路由算法；Control Plane/WebUI 只承担测试与观测。

每项能力都必须独立可关闭、默认关闭、失败显式、可回滚，并通过当前契约测试。

### P3：完成 S20A 离线 Bandit 基础

只有在静态 Router 的真实 Provider 装配、S12-S19 本地门禁和两个以上同 Tier 合法 Endpoint
就绪后，才执行第 10.4 节 S20A。本阶段可使用合成数据、历史脱敏回放和无副作用 Shadow，
不进入真实群探索。

### 最终阶段：真实群聊

只有全部接受的模块、WebUI 测试和本地总审计完成后，才执行：

```text
授权单群 Shadow
  -> 冻结并检查 SLO
  -> 静态 Router 授权单群 Canary
  -> 如明确授权，再进入 S20B 极小 Bandit Canary
  -> 通过重复回复、错误目标、敏感 Trace、延迟和成本门禁
  -> 再决定是否分层放量
```

本次协作者仓库审查不改变该顺序。

S19 本地总审计完成后才进入最终外验证。S20A 可在其前完成，S20B 则必须置于 S23
真实群验证内，且不得跳过静态 baseline。

## 12. 证据定位

主要证据均固定在本报告顶部所列提交：

- prototype Router：`packages/dududa-agent/src/dududa/router/router.py`
- prototype Runtime 多权威路径：
  `packages/dududa-agent/src/dududa/application/dududa_handlers.py`、
  `dududa_prod.py`、`runtime/orchestrator.py`
- prototype MCP：`packages/dududa-agent/src/dududa/mcp/access.py`、`client.py`、各校园服务
- prototype Delivery：`packages/dududa-agent/src/dududa/core/delivery.py`、
  `adapters/astrbot/output_adapter.py`
- plugin 入口和旧 Router：`dududa20-plugin/main.py`、`dududa20-plugin/_router.py`
- prototype 包装/部署：`pyproject.toml`、`deploy/docker-compose.yml`、`deploy/Dockerfile`
- 当前权威设计：`.TreeWork/spec.md`、`docs/design/model-routing.md`、
  `docs/adr/0004-unified-mcp-client.md`、`docs/refactor/implementation-plan.md`、
  `docs/refactor/s08-s11-completion-audit.md`

## 13. 最终建议

把这次误开发的结果定义为一次“探索性原型”，而不是失败的主线实现。保留它最有价值的方式
是提取需求、故障案例和小型数据，再让这些材料接受当前 Dududa 的契约、安全和科学性门禁。

工程决策保持简单：**不合并两个仓库，不重做 S08-S11，不在旧 Router/Social
Decision 上堆 Bandit，不提前真实群测；先补授权，再迁移测试场景，最后按当前 Dududa
契约实现少量新增 Adapter 与 S20A。**
