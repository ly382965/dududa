# Dududa 2.0 项目会议总结

- 日期：2026-08-24
- 当前工作分支：`treework/real-group-validation`
- TreeWork 状态：`paused / partial`
- 功能现场基线：`7c5b58b docs(runtime): record scoped sub2api reload`

## 一、30 秒结论

Dududa 2.0 已经完成 S01-S22 约定的本地或离线工程主链，核心契约、静态模型路由、
语义理解框架、统一 MCP、Capability、Memory 生命周期、短中长回答、主动行为 no-send
链路、离线 Bandit、运维与 Bot Control Plane 都已有实现和验证。

当前处于 S23 内测阶段。历史群聊数据已经形成可浏览的离线 Demo，Web 管理工作台、
三档模型候选接入、群聊风格、上下文预算、插件配置和 Sub2API 查询也已形成纵向功能。
但产品还不能称为正式上线：真实 Agent 自动回复仍关闭，生产群聊上下文投影尚未接通，
Memory、Tool、主动推送和在线 Bandit 都没有进入真实群运行链。

一句话判断：**框架和离线工程已经比较完整，当前瓶颈已经从“有没有模块”转为
“能否把这些模块接入同一条真实运行链，并用人工评价证明群聊效果”。**

## 二、产品与设计哲学

> Dududa 是受治理的群体情境适应 Runtime：一个不可卸载的最小治理内核，组合可逆、
> 可观察、分作用域的能力插件；系统把群聊理解为随时间变化且带不确定性的群体情境，
> 在事实、权限、人格和任务要求不变的前提下适应表达；所有自我改进先成为可评测、
> 可撤销的候选资产，Bandit 只在安全等价的合法候选之间学习分配预算。

目前已经落地的原则：

1. 模型只产生候选，身份、Scope、权限、预算和发送权属于确定性 Runtime。
2. 理解、决策、执行和表达分层；模型 Tier、推理深度、回答长度和人格彼此正交。
3. WebUI 是统一 Bot Control Plane。管理员提供初始服务、允许范围和可选硬锁，Agent
   可以在合法范围内自适应，但不能自行开服务或扩权。
4. MCP Registry 只管理连接事实，Capability Registry 决定业务能力和授权。
5. 主动消息、Memory 写入和在线学习均默认关闭，只有对应真实运行链准备好后才启用。

长期方向已经明确，但尚未实现的部分包括通用 Plugin Runtime、长期 Group Context、
关系证据、候选 Skill/Prompt/Style 演化与在线 Bandit。

## 三、模块完成度

“完成”仅表示相应 Sxx 定义的本地或离线范围完成，不表示已经生产上线。

| 模块 | 当前状态 | 已有成果 | 仍缺少 |
| --- | --- | --- | --- |
| 核心契约与治理内核 | 已完成（本地） | Actor/Scope、权限、预算、审计、幂等、Runtime State、Port/Adapter 边界 | 真实生产身份和完整运行证据 |
| Connector / Output | 部分完成 | AstrBot + NapCat + OneBot 已连通；结构化事件、Delivery、受控 Rollout 已实现 | Agent 自动回复仍关闭；近期群聊 Projection、附件和真实 Canary 未完成 |
| 静态 Model Router | 已完成（静态范围） | Haiku/Sonnet/Opus、Endpoint Registry、资格过滤、流量/容量、fallback | 真实多 Endpoint 质量/成本数据与动态优化 |
| 语义理解与难度判断 | 部分完成 | Rule/Model/Merger、Intent/Entity/Reference、Complexity/TierPolicy、合成 Eval 和 Silver 样本 | 类别均衡人工 Gold、当前 Bot 流量校准、多轮和附件质量 |
| Memory | 已完成（离线边界） | Scope、删除/tombstone、导出/恢复、M0/M1/M2、CJK BM25、合成 Eval | 生产 Context Builder 消费、真实 Iris/Hybrid 检索、人工质量和受控写入 |
| MCP / Capability | 已完成（离线框架） | Unified Client、Server Registry、长 Session、Capability Runtime、Fake 扩展契约 | 唯一真实 MCP 仍是 iCourse；新真实 Server 和 Console 执行链接入未完成 |
| 回答档位与 Persona | 机制完成、体验待校准 | SHORT/MEDIUM/LONG、动态预算、Persona 同次生成、最终 Validator | 真实中文群聊风格、长度边界和 QQ 分片体验的人工校准 |
| 主动消息与推送 | 部分完成（no-send） | 授权契约、Scheduler、Source Port、Digest/Probe Shadow 和固定 fixture | 真实校园/arXiv/行业来源、生产 Projection/Output、逐行为授权和发送 |
| Bandit Learning | 离线基础完成 | Decision/Feedback、action support、propensity 校验、IPS/SNIPS/DR/ESS | 真实同档候选、before-action 日志、可归因反馈、Shadow/在线训练与探索 |
| Bot Control Plane / WebUI | 工程纵切完成并运行 | 群服务初值、六项策略、插件四态、动态 Catalog、消息浏览、人工评价 | 多项配置尚未被生产 AstrBot Runtime 消费；不能把配置成功视为能力已执行 |
| 插件 | 部分在线 | Sub2API 已在线；自动复读已恢复源码、配置面和 Compose 装配 | 自动复读仍缺 Web Policy Adapter；iCourse、图片能力尚未进入 Console Capability 链 |
| 真实群测试 | 暂停、部分完成 | 历史语料离线 Demo、Provider no-send、内测 Console | 实时单群 Shadow、明确 @ Canary、日报、Probe 和分层放量均未开始 |

## 四、已经形成的可见成果

### 1. 私有历史群聊离线链路

- 输入：1,402 个聊天记录文件，约 410 MB。
- 处理结果：155,567 条唯一群消息，137,026 个 past-only Conversation Window。
- Teacher：Terra 对 600 个分层窗口生成预标注，得到 464 条可编译 Silver。
- Student：按群隔离训练/测试，并完成全部 137,026 个窗口的本地预测。
- Web 展示：300 个脱敏窗口，可查看语义难度、回答档位和静态 Tier 预览。

这些数据证明处理链可以运行，但 Silver 类别明显失衡，不能代表真实中文质量。
原独立 Demo 已生成，不过截至本次检查，`127.0.0.1:8766` 的静态服务未启动。

### 2. Bot Control Plane 与内测工作台

当前 `http://127.0.0.1:5173/` 可访问，主要具备：

- QQ 会话、联系人、群管理和实时事件展示；
- Agent 候选回答和人工评价；
- 模型 Tier、推理深度、回答长度、回复强度、上下文长度、群聊风格六项配置；
- `adaptive / preferred / locked` 和插件 `off / auto / on / locked`；
- 管理员初值与本轮 Agent 实际选择的区分；
- 插件安装、配置、Runtime online 和本轮调用状态的分层展示。

消息链已经修复初始加载覆盖实时事件、断线补放、超大 sequence 精度和显示乱序问题。
当前 SSE 仍只保留最近 512 条事件，属于有限断线恢复，不是持久事件日志。

### 3. 三档模型候选

- Luna / Haiku、Terra / Sonnet、Sol / Opus 均完成 Responses 和 Chat Completions
  的一次性可达性抽样。
- 三档各完成一次隔离 Provider no-send，均为
  `provider_calls=1 / output_calls=0`。
- 固定 AstrBot 4.26.2 候选曾在无网络、临时数据、无 NapCat 环境启动。
- 请求级输出上限、Endpoint 固定思考深度和健康 TTL 工程路径已经实现。

这些结果不等于运行中 AstrBot 已注册三模型，也不等于 Provider Conformance、持续健康
或真实群 Runtime Shadow。

### 4. Sub2API

`/sub2api overview` 已完整复用原插件查询逻辑，并以四节点 QQ 合并转发输出：

1. 今日用量与用户排名；
2. 当前计费轮累计与排名；
3. 历史累计与排名；
4. 上游账号状态。

插件版本为 v0.6.3，27 项聚焦测试通过，并已使用 AstrBot 单插件 API 热重载；
AstrBot 容器没有因此重启。旧 Dududa 1.0 AstrBot 容器已经不存在，当前 NapCat 是
2.0 正在复用的唯一 QQ Connector。

## 五、当前运行现场

2026-08-24 只读检查结果：

| 服务 | 状态 | 说明 |
| --- | --- | --- |
| Dududa AstrBot | 运行中 | `http://127.0.0.1:6185/` 返回 HTTP 200 |
| Dududa Web | 运行中 | `http://127.0.0.1:5173/` 返回 HTTP 200 |
| NapCat | 运行中 | 当前唯一 QQ Connector，不能按旧项目名误停 |
| Sub2API 及 Postgres/Redis/Proxy | 运行且依赖健康 | 保留 `/sub2api` 查询能力 |
| Dududa 1.0 AstrBot | 不存在 | 已经处于关闭状态 |
| 历史语料独立 Demo | 文件已生成、服务未启动 | `127.0.0.1:8766` 当前未监听 |

代码现场：工作树干净；S23 分支尚未配置 upstream，也尚未合并到控制分支。

## 六、当前最关键的未完成问题

1. **真实 Agent 仍未在线接管回复。** 当前被动回复是 `rollout_mode=off`，delivery
   关闭且 kill switch 开启；Web 候选为 no-send。
2. **生产群聊上下文仍不完整。** 当前生产 `CurrentMessageContextBuilder` 主要看到当前消息，
   尚未消费受限的近期群聊历史，因此还不能称为群体情境适应 Runtime 成品。
3. **Web 配置与真实执行尚未完全闭合。** Sub2API 已接 Scope Policy；自动复读尚未接入；
   iCourse 和图片能力尚不能从当前 Console Capability 链执行。
4. **语义和风格缺人工 Gold。** 当前主要是合成 Eval 与类别失衡的 Silver，不能据此判断
   会不会自然插话、回答长短是否合适、人格是否真正融入群聊。
5. **主动推送只有离线框架。** 校园、arXiv、行业资讯没有真实 Source Adapter；定时发送、
   quiet hours、退订和 Probe 也没有真实群证据。
6. **Bandit 还没有在线学习条件。** 缺少同 Role+Tier 的多个合法 Endpoint、选择前 propensity、
   可归因反馈与稳定 reward；当前不能学习 Reply/Ignore 或主动发送。

## 七、建议会议确认的事项

本次会议最好只确认以下产品决策，不再重新设计核心模块：

1. 第一版内测的完成定义：是否以“单授权群、明确 @ 可真实回答”为第一个成品边界。
2. 第一批开放能力：普通回答、iCourse、图片理解/生成、Sub2API、自动复读分别是否进入内测。
3. 群聊策略初值：回复强度、SHORT/MEDIUM/LONG 比例、上下文档位、Persona 风格和 quiet hours。
4. 人工评价安排：从现有样本中建立 150–300 条类别均衡 Gold，并由第二人复核关键样本。
5. 主动行为授权顺序：手动日报、定时日报、低频 Probe 必须分开决定，不能一次全部开启。
6. 数据来源责任：校园、arXiv、行业资讯各自选择真实公开来源、更新频率和引用要求。
7. Bandit 的首个合法目标：建议只优化同档模型的质量/延迟/成本，不学习发送权限、
   主动打扰或 AnswerProfile。

## 八、建议的下一阶段顺序

按单开发者 `WIP=1` 推进：

1. 接通近期群聊 Projection 与当前消息 Context Builder，先完成真实 no-send Runtime Shadow。
2. 在运行 AstrBot 注册 Luna/Terra/Sol，完成 Provider Conformance、Evidence 绑定和持续健康。
3. 让 Web Policy 被真实 Runtime 消费，闭合模型、上下文、群聊风格和插件的 Desired/Effective。
4. 接通 iCourse；明确图片理解与图片生成分别使用的模型和 Capability。
5. 使用人工 Gold 与单群 Shadow 校准语义、回复意愿、Persona 和回答档位。
6. 在独立授权下开启“明确 @ Canary”，验证后再考虑普通自动回复。
7. 最后依次验证手动日报、定时日报和低频 Probe；真实反馈稳定后才进入 Bandit Shadow。

## 九、会议口径

可以声明：Dududa 2.0 的本地/离线工程主链、历史语料处理 Demo、静态 Router、统一 MCP、
Memory 边界、短中长回答、主动 no-send 框架、离线 Bandit 和 Bot Control Plane 已形成。

不能声明：S23 已完成、真实群聊已经验证、三档模型已经由运行时自动路由、Memory/Tool
已在生产使用、校园/arXiv/行业 MCP 已存在、主动推送已上线或 Bandit 已开始在线学习。

当前阶段最准确的定位是：**内测工程版已经形成，下一步是把真实运行链闭合并用人工评价
证明效果，而不是继续扩张模块数量。**
