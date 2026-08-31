# 嘟嘟哒 2.0

**嘟嘟哒是一个受治理的群体情境适应 Agent Runtime。** 它保留不可卸载的最小治理内核，
在外围组合可逆、可观察、分作用域的能力资产。当前仓库定位为**内部 Canary**，不是生产就绪版本。

仓库包含框架无关 Runtime、AstrBot/NapCat 适配器、校园 MCP 服务、Bot 控制台和可复现的离线测试。
仓库不包含 Provider 凭据、QQ 登录态、运行数据库或生产聊天数据。

## 设计哲学

```text
QQ / 群消息
      |
 NapCat OneBot v11
      |
 AstrBot Connector
      |
 MessageEnvelope -> 分作用域上下文 -> 语义理解
                    （规则 + Haiku Schema 候选）
      |
 确定性资格过滤 / 授权 / 预算
      |
 静态 Model Router（Haiku / Sonnet / Opus）
      |
 Capability Retrieval -> 有界 Planner -> Executor -> Validator
                              |
                         Unified MCP 或 Builtin Provider
      |
 Observation -> Direct Chat -> ResponsePlan -> Persona -> 最终校验
      |
 Output Adapter -> DeliveryReceipt
```

模型只提出类别、实体、工具候选和表达草案，不拥有身份、Scope、权限、预算、Capability 授权、
路由资格或副作用。确定性代码拥有这些决策。MCP 只是传输边界，不授予 Capability，不负责调度、
目标选择或发送消息。

模型的三个维度彼此正交：

- `Tier`：`haiku`、`sonnet`、`opus`，表示能力与成本档位；
- `Reasoning`：`off`、`light`、`balanced`、`deep`、`maximum`；
- `AnswerProfile`：`short`、`medium`、`long`，表示可见输出预算。

内部部署通常把 Luna/Terra/Sol 映射到 Haiku/Sonnet/Opus。模型 ID、Endpoint 和凭据属于私有运行配置，
不是仓库承诺。静态路由器先做资格过滤，再在合法候选中考虑质量和成本。

## Runtime 与控制台

`packages/dududa-agent` 是框架无关的 2.0 核心。AstrBot、MCP SDK、模型 SDK 以及 Vue/Node Web 应用
都只能实现外围 Port。Web 是 Bot Control Plane（管理员超级工作台），不是第二套 Agent Runtime；
所有写操作都转换为类型化 Core Command，读取的是 Runtime 投影状态。

Bot 进入群聊后，授权管理员可以选择版本化 `GroupServiceProfile` 初值。`adaptive` 和 `preferred` 允许
Agent 只在管理员批准的范围内按轮次调整，`locked` 才会禁止调整。Web 设置不会创建模型、授予能力或绕过
Core 授权。

## 能力与 MCP

每个服务都有独立的 Server 身份、Session 生命周期、Schema 快照、健康状态和 Capability mapping。
未来新增 MCP 应只增加配置和 mapping，不修改 Domain 或 Runtime。

| 服务 | 类型 | 当前范围 |
| --- | --- | --- |
| iCourse / 评课社区 | Unified MCP | 匿名公开查询课程、教师、评价、排行榜和统计，是当前主要真实 MCP 路径。 |
| USTC Young / 二课 | Unified MCP | 复用 `pyustc` 查询活动、筛选项、详情和连接状态；报名、取消报名、申请人等操作不作为公开能力。 |
| USTC Academic / 教务处 | Unified MCP | 公开学期、开课、考试和教学日历查询。 |
| USTC Curriculum / 培养方案 | Unified MCP | 查询 `docs.mmdustc.top/curriculum` 的研究快照，不是实时毕业审核。 |
| USTC Shuttle / 校车 | Builtin Capability | 版本化本地时刻表，不建立 MCP Session，不联网抓取。 |
| Weather | 候选 Source/Capability Adapter | 已有 `WttrWeatherSource` 和 Provider 契约，但尚未接入生产组合或日报订阅。 |
| 校园资讯、arXiv、行业来源 | 预留接口 | 只有来源契约和 fixture，不能宣称存在实时 Server 或实时日报。 |

Web MCP 控制台只接受批准的 Capability ID 和输入 Schema，不提供任意 `server/tool` 透传。Discovery 只更新事实，
不会自动授予权限。

## 插件与本地能力

| 组件 | 2.0 状态 |
| --- | --- |
| `astrbot_plugin_dududa_core` | 唯一 2.0 Agent Runtime 的 AstrBot 适配器，负责命令边界、Runtime 组合和投递。 |
| `astrbot_plugin_sub2api_readonly` | 仅超级管理员可用的只读命令；`overview` 生成一条四段合并转发（今日、当前计费轮、历史、上游账号）。它是宿主独立插件，不是 Agent 自动工具路由。 |
| `astrbot_plugin_proactive_chatter` | 由 Core 在 Bridge 前消费的无副作用策略扩展，识别复读/机器人互动并建议静默；不监听、不调用模型、不发送，默认关闭。 |
| `astrbot_plugin_reply_review` | 保守审校策略资产，不拦截消息、不自行调用 Provider；接入 Runtime secondary-review Port 前保持 `production_wired=false`。 |
| `astrbot_plugin_weather` | 只读天气 Source/Provider 资产，默认关闭，未注册到生产 Composition。 |
| `astrbot_plugin_arc_proxy` | 受治理的本地 B50 渲染/Provider 资产；调用者提供结构化成绩，Core 拥有授权和投递权。默认关闭，未接生产 Composition。 |
| `astrbot_plugin_ustc_shuttle` | Runtime 使用的本地校车时刻表 Capability Provider。 |
| `astrbot_plugin_reread` | 兼容性的独立复读插件，默认关闭、独立 Scope；不是 Agent 的社会决策层。 |
| `astrbot_plugin_reply_polish` | 旧版 LONG-only 合并转发兼容层，默认关闭；2.0 Output 自己负责合并转发判断。 |

`third_party/` 中的 Better Reminder、ChatSummary、Iris 仅作为迁移或回滚证据保留。它们的旧消息监听、
SQLite 状态、独立调度和直接发送都不是 2.0 Runtime 能力，不应在文档中写成已启用功能，也不能形成第二套控制面。
旧的评课社区专用 Client 和 PR 中的旧 iCourse 实现不在本次集成结果内；评课社区统一走 Unified MCP。

独立的 `apps/b50-renderer` 只依赖 Pillow，不依赖 AstrBot 或网络。它从结构化数据或本地 fixture 生成
`1920x1750` PNG，不抓取成绩、不发送媒体。

## 目录结构

```text
packages/dududa-agent/       # 框架无关的 2.0 契约与 Runtime
apps/astrbot-plugins/        # AstrBot 适配器和能力资产
apps/b50-renderer/            # 离线 B50 渲染器
apps/web/                     # Vue/Node Bot Control Plane
services/mcp/icourse/         # 评课社区 MCP
services/mcp/ustc-campus/     # 二课、教务处、培养方案 MCP
services/mcp/console/         # MCP Registry/Capability 控制台
configs/                      # 不含凭据的 Server 与 Capability mapping
deploy/                       # Compose 与派生镜像
ops/                          # 初始化、安装和验证工具
third_party/                  # 锁定的兼容来源与补丁
docs/                         # 设计、研究和进度记录
```

## 快速开始

要求：Linux、Docker Compose v2、`uv 0.12.1`、Python 3.10/3.12、Node.js 22、npm 10，
以及在 AstrBot 私下配置的 OpenAI 兼容 Provider。

```bash
cp deploy/env/.env.example .env
chmod 600 .env
./manage.sh init
./manage.sh plugins
./manage.sh web-up
```

默认本机回环地址：

- Web 控制台：`http://127.0.0.1:5173`
- AstrBot：`http://127.0.0.1:6185`
- NapCat：`http://127.0.0.1:6099`

`./manage.sh up` 会构建完整本地栈，可能重建本地 AstrBot/Web 服务；不会把凭据或 QQ 登录态写进 Git。
NapCat 需要单独完成登录。只测试仓库自有 2.0 资产时使用：

```bash
python ops/cli/install_plugins.py --plugins-root ./runtime/astrbot-plugins --owned-only
```

`third_party/plugins.lock.json` 继续作为兼容与迁移输入保留；锁定来源不等于自动获得 Agent Capability。

## 验证

仓库优先运行代表性、可执行的检查，不为假设事故预先堆叠门禁：

```bash
uv lock --check
uv run --locked python -m compileall -q packages apps services ops tests
uv run --locked python -m unittest discover -s tests -t .
uv run --locked python ops/cli/check_secrets.py
cd apps/web && npm run typecheck && npm run test && npm run build
```

聚焦插件检查覆盖 2.0 主动搭话策略、保守审校、天气 Source、本地 B50 Provider、Sub2API overview 和 MCP
契约 fixture。真实 QQ 发送、实时来源新鲜度、人工质量标注、Bandit 在线探索和大规模群聊放量仍是外部验收工作。

## 数据、隐私与学习边界

不要提交 `.env`、API Key、Cookie、Token、QQ 登录目录、数据库、聊天导出、Memory 记录、运行生成物或私有
Provider evidence。运行数据必须放在被忽略的私有目录。Memory v2 已有离线生命周期、检索和删除边界证据，
但尚未作为生产 Context Builder 或自动写入器启用。

S20 只提供离线 Bandit 决策/反馈契约和合成 IPS、SNIPS、DR 评估，没有训练 Worker、在线探索或生产奖励回路。
未来学习只能在已经授权且安全等价的候选之间排序，并保持可观察、可撤销。

## 文档

- [Dududa 2.0 设计总览](docs/design/dududa-2.0-overview.md)
- [重构进度台账](docs/refactor/PROGRESS.md)
- [模型路由](docs/design/model-routing.md)
- [Capability 与 MCP 设计](docs/design/capability-and-mcp.md)
- [Bot Control Plane](docs/design/bot-control-plane.md)
- [本地开发环境](docs/development/local-environment.md)
- [English README](README.md)

`docs/refactor/PROGRESS.md` 是带证据的完成度和外部门禁台账。没有证据的部分不会被描述为生产就绪。

## 许可证

嘟嘟哒原创代码和文档采用 MIT 许可证。第三方组件保留其上游许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
