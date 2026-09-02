# PR #10 选择性整合报告

## 1. 报告范围

本报告记录 2026-09-02 对 `ly382965/dududa#10` 的选择性整合。PR #10 基于嘟嘟哒旧目录、
旧 Core 和旧部署方式，整体合并会重新引入重复插件、重复 MCP、直接模型调用和第二套 Compose。
本次因此把 PR 作为候选实现来源，只吸收当前 Dududa 2.0 尚未覆盖、能够独立运行且边界清晰的
社交策略与校园信息资产。

整合后的主线仍只有一个 `astrbot_plugin_dududa_core` 负责 Dududa 2.0 Runtime。Web Bot
Control Plane、Unified MCP Client、MCP Console、Compose 服务集合和既有五个生产 Registry
Server 均保持原有所有权。新增内容以独立插件和默认关闭的可选 MCP Server 交付。

## 2. 选择结果

| PR #10 资产 | 结果 | 主线判断 |
| --- | --- | --- |
| 旧 `astrbot_plugin_dududa_core` | 不整合 | 与主线使用同一插件 ID、命令和事件入口，会重复注册并争夺事件所有权 |
| `academic-calendar-mcp` | 不整合 | `ustc-academic` 已拥有学期、开课、考试和教学日历能力 |
| `ustc-notice-mcp` | 不整合 | `notifai` 已拥有校园通知搜索、详情、日历、截止日期、来源和分类能力 |
| 旧根目录 `plugins/`、`config/`、`docker/` 与 Compose | 不整合 | 主线 canonical 目录和四服务 Compose 已经建立，旧布局会形成第二套发布面 |
| 直接 MCP Client、直接模型/API 调用与饭点自动推送 | 不整合 | 绕过 Unified MCP、Runtime 授权、调度和 Output Adapter |
| 地图搜索脚本与凭据 | 不整合 | 本轮不引入外部地图查询，也不提交任何地图服务凭据 |
| 生日、睡眠、投票、互动、情绪、夸奖、关键词规则 | 独立插件整合 | 主线没有同等的纯规则资产；自动监听和自动回复部分被剥离 |
| `local-recs-mcp` | 可选 MCP 整合 | 提供仓库种子驱动的餐饮、活动和学习推荐缓存 |
| `training-plan-mcp` | 可选 MCP 整合 | 提供公开本科专业、院系和年度设置一览，不等同于培养方案审核 |
| `campus-events-mcp` | 可选 MCP 整合 | 提供中国科大主页公开通知缓存，与 NotifAI 的来源不同 |
| `college-notice-mcp` | 可选 MCP 整合 | 提供已配置学院官网的公开通知缓存和学院筛选 |
| `library-mcp` | 可选 MCP 整合 | 提供图书馆各校区公开开放时间缓存 |

## 3. 社交策略插件

### 3.1 模块结构

插件位于 `apps/astrbot-plugins/astrbot_plugin_dududa_social/`，插件 ID 为
`astrbot_plugin_dududa_social`，与 Core 完全独立。

| 模块 | 职责 |
| --- | --- |
| `policy.py` | 日期解析、睡眠聚合、投票状态转换、无碰撞用户对编码、情绪/夸奖/关键词分类 |
| `storage.py` | 独立 SQLite 状态、会话 Scope 隔离、投票权限和有限睡眠记录保留 |
| `main.py` | `/dududa-social` 显式命令适配、配置读取和脱敏展示 |
| `_conf_schema.json` | 总开关、群 allowlist、私聊开关、逐功能开关和状态路径 |

### 3.2 运行边界

- 总开关默认 `false`，所有 feature 默认 `false`，群 allowlist 默认为空，私聊默认关闭。
- 只注册 `/dududa-social` 命令组，不注册 `ALL` 或其他普通消息监听器。
- 不创建 scheduler，不调用模型或 MCP，不自动发送生日祝福、安慰、投票提示或互动调侃。
- 本次不提供 PR #10 的旧顶级短命令兼容。未来若增加兼容入口，它必须是显式配置、默认关闭的
  独立变更，不能恢复全局消息 Handler。
- 状态按 `platform + bot_id + conversation_id + group_id` 隔离；私聊与群聊不会共享记录。
- 投票仅允许发起人或管理员结束；群内账号以脱敏标识展示。
- 情绪危机分类只返回需要人工支持的结构化信号，不把危机文本转成普通自动安慰。

显式命令面如下：

```text
/dududa-social help
/dududa-social birthday set MMDD|list|delete
/dududa-social sleep record|rank
/dududa-social vote start <主题>|join|status|end
/dududa-social cp rank
```

插件已加入 `ops/cli/install_plugins.py` 的 owned-plugin 清单，因此正常插件安装流程会把它复制到
AstrBot 插件目录；复制并不代表启用，实际行为仍由默认关闭的插件配置决定。

## 4. 可选 MCP Server

### 4.1 统一形态

五个服务都位于 canonical `services/mcp/<server-id>/`。每个服务由一个 stdio MCP 适配层、一个
领域/SQLite 层和一个独立运维 CLI 组成。MCP 进程只暴露一个有界的 `public_query` 工具，工具
调用只读取本地缓存；抓取、robots 检查、详情刷新和推荐数据写入只存在于运维 CLI 或被完全
排除，不是 MCP Tool。

| Server | 唯一 MCP Tool | 输入与结果边界 | 缓存来源 |
| --- | --- | --- | --- |
| `local-recs` | `local_recommendations_public_query(query, kind, campus, meal_time, price_level, limit, exclude_ids)` | 查询最长 120 字符，最多返回 10 条，排除 ID 最多 50 个；查询不更新推荐计数 | 仓库 JSONL 种子和运维 CLI 维护的数据 |
| `training-plan` | `training_programs_public_query(query, year, college, limit)` | 查询最长 160 字符，年份限 2010–2100，最多返回 30 条 | `www.teach.ustc.edu.cn` 公开专业设置一览缓存 |
| `campus-events` | `campus_events_public_query(query, category, limit)` | 查询最长 200 字符，类别限定为综合/教学/科研/管理，最多返回 20 条 | `www.ustc.edu.cn` 通知公告缓存 |
| `college-notice` | `college_notices_public_query(query, college_key, limit)` | 查询最长 200 字符，学院限定为配置清单，最多返回 20 条 | 数学、计算机、物理学院 HTTPS 官网缓存 |
| `library` | `library_hours_public_query(query, campus, limit)` | 查询最长 120 字符，校区最长 32 字符，最多返回 30 条 | `lib.ustc.edu.cn` 开放时间缓存 |

返回值统一包含 `schema_version`、`ok`、查询条件、`items`、`returned` 和 `source`。通知类服务还
投影 `observed_at`；其他服务没有伪造统一的新鲜度字段。实时新鲜度由运维缓存更新记录决定，
当前没有 Capability mapping 对它作生产级 freshness 判断。

### 4.2 URL、文本与状态边界

- Campus Events 只输出 `https://www.ustc.edu.cn` URL；College Notice 只输出 USTC HTTPS
  子域名；Training Plan 和 Library 固定为各自官方 HTTPS origin。
- 标题、正文摘要、地点、附件名和其他上游文本都经过长度投影；通知附件最多十个。
- 通知类来源 URL 只接受配置的 HTTPS 同源地址并限制为 2048 字符；格式非法或外部链接在解析、
  运维详情和 MCP 投影边界均被舍弃。
- SQLite 数据库文件权限设为 `0600`，父目录设为 `0700`。数据库属于运行数据，不进入仓库。
- `local-recs` 启动时仅在空库中导入仓库种子；对外 MCP 查询没有写副作用，也没有任意地图搜索。

### 4.3 Registry-only 决策

新增配置位于 `configs/mcp/servers/`，全部满足：

- `enabled: false`；
- `protocol_mode: legacy`，使用现有 MCP v1 进程边界；
- `allowed_tools` 只含对应的唯一 `public_query`；
- 固定命令、工作目录、超时、并发和环境变量 allowlist；
- 没有 SecretRef。

本轮没有把五个 Server 加入 `configs/astrbot/mcp_server.json`，也没有生成
`configs/capabilities/definitions/` 或 `configs/capabilities/mappings/`。因此它们是 Unified MCP
Registry 可识别的可选资产，但不会出现在 Planner 候选中，也不参与当前生产 Capability Provider
health 链。现有 iCourse、NotifAI、USTC Young、USTC Academic、USTC Curriculum 五个真实
Registry Server 以及校车 Builtin Capability 保持不变。

这条边界避免了“配置为 disabled 但仍创建 Provider descriptor 并触发健康探测”的当前组合行为。
后续若要让某个服务进入 Agent 规划面，需要在独立变更中完成来源审核、Capability
definition/mapping、可选 Provider 加载语义和生产 health 验证。

## 5. 构建与部署接线

派生 AstrBot 镜像复制并安装五个 MCP Python 包，同时保持主进程 `mcp==1.29.0` 与 Unified
worker `mcp==2.0.0` 的既有隔离。Compose 仍只有 `web`、`mcp-console`、`astrbot` 和 `napcat`
四个服务：

- `astrbot` 与 `mcp-console` 都以只读方式挂载五个服务源码；
- `mcp-console` 为五个 SQLite 缓存挂载独立可写目录，容器根文件系统继续只读；
- `astrbot` 沿用现有 `/AstrBot/data` 持久卷保存缓存；
- Web、MCP Console、Unified worker、`init`、`read_only`、网络和公网入口均未被替换；
- 新 Server Registry 项保持关闭，所以构建和挂载不会自动启动抓取或扩大 Agent 工具面。

## 6. 回滚方式

运行行为的第一层回滚是保持五个 Registry 项 `enabled=false`、保持社交插件 `enabled=false`。
完全移除时，删除五个可选 Registry 项与源码/镜像/Compose 挂载，并从 owned-plugin 清单移除社交
插件即可。此次变更没有修改 Core 状态格式，也没有迁移任何既有数据库；新增缓存和社交状态使用
独立目录，可按资产单独保留或删除。

## 7. 验证与已知边界

聚焦验证覆盖五个服务的唯一工具发现、输入上限、缓存查询、SQLite 权限、推荐查询无写副作用、
图书馆 rowspan/时间段解析、培养方案年份过滤、学院通知两种日期 URL、社交 Scope/权限/默认关闭、
owned-plugin 安装以及仓库 Registry/Compose/镜像合同。当前仓库聚焦集合为 `38 passed`；五个服务
按 CI 方式逐目录运行共 `14 passed`。因此本轮已重跑的 PR10 相关集合合计为 `52 passed`。五个服务测试改成唯一模块名后可以在一次 pytest 收集中
共同执行，不再发生同名 `test_contract.py` 的 import mismatch。

此外，五个 stdio 自检脚本均完成一次本地空缓存 discovery/query，所有工具名与 Registry allowlist
一致；五个 Python 包的 source distribution/wheel 均成功构建。Compose `config --format json`、
`compose-contract` 和 `check_secrets.py` 均通过，新增源码挂载为只读、缓存目录独立。

根仓库完整 `unittest discover` 在当前基线仍有既存失败/环境缺口（包括历史评测快照、joblib、
既有 Runtime/Schema 断言）；这些失败在未集成本分支的控制工作区也可复现，本分支没有扩大范围
修复它们。它们不改变上述 PR #10 聚焦证据，但也意味着不能把本次变更描述为“完整 CI 已全绿”。

本次证据是离线代码、fixture、Registry 和部署合同证据。它不代表五个服务已经启用，不代表网页
缓存实时更新，也不代表 Planner 已能调用它们；真实抓取调度、主动推送、QQ Delivery 和 S23
真实群验收仍是后续独立工作。
