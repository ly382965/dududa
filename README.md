<div align="center">

# 嘟嘟哒 · Dududa 3.1

**生活在 QQ 群里的 AI 群友**

规则功能直接执行，复杂任务交给本机 omp Agent。

[简体中文](README.md) · [English](README.en.md) · [2.0 完整归档](legacy/2.0/README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-80b8a5)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-7ba9d6)](pyproject.toml)
[![Vue 3](https://img.shields.io/badge/Vue-3-8bc6b3)](apps/web/package.json)

[3.1 的变化](#31-的变化) · [功能一览](#功能一览) · [身份与上下文](#身份与上下文) · [技术架构](#技术架构) · [快速开始](#快速开始) · [开发与验证](#开发与验证) · [部署](#部署) · [2.0 封存](#20-封存与仓库布局)

</div>

## 群里，来了一个 AI 群友

嘟嘟哒是一个生活在 QQ 群里的 AI 群友。我们希望她像群里一个什么都会一点的人：能接住闲聊，能认真讨论问题，知道什么时候出现，也懂得什么时候闭嘴。聊到选课、活动、考试和出行时，她能调用相应服务，把事情说清楚。

项目探索的是 **AI 如何持续参与一个群体的日常生活**。科大校园是嘟嘟哒开始生活的地方；你也可以接入自己的服务，塑造适合不同群体的角色。

3.1 由一个 Python Host 负责消息入口、规则功能、会话、权限、定时任务和输出；需要理解和多步推理的消息交给本机 [omp](#技术架构)（`omp --mode rpc`）完成 Agent 循环。**明确的指令和自动功能（链接解析、复读、小红书归档等）不调用对话模型。**

线上机器人当前运行 **3.1.0**。默认对话模型为 `luna-max`（`openai-codex/gpt-5.6-luna`，thinking `max`），管理员可在群里用 `model` 指令切换已注册的模型。AstrBot 已完全下线，NapCat 只连接 Dududa Web。

## 3.1 的变化

| 方面 | 2.0 | 3.0 | 3.1 |
| --- | --- | --- | --- |
| Agent 执行 | 自研感知、模型路由、单步能力计划 | 本机 Codex app-server 负责 Agent 循环 | 本机 `omp --mode rpc`；业务工具作为 RPC host tool 由 Host 进程内应答 |
| 内置工具 | AstrBot 插件与 MCP | 独立 MCP stdio 进程 | 同一套 ServiceHub 工具加功能模块工具；omp 内置工具只开放 `web_search` |
| 规则功能 | AstrBot 插件 | Host 内置少量规则命令 | `features/` 功能模块自动发现：指令、被动观察者、定时任务、Agent 工具、任务开关 |
| 模型 | AstrBot Provider，Luna / Terra / Sol 三档 | 固定 `gpt-5.6-luna` / `max` | `models` 注册表；chat / summary / image 通道与 qa / summary / vision / image 服务可由管理员切换 |
| 身份与上下文 | 旧 Runtime 组织上下文 | 近期消息拼入提示 | 桥接层提供发送者名片、昵称、群身份、引用、@ 和图片；按 QQ 号区分说话人，续聊只补发新消息 |
| 会话 | 旧 Runtime | Codex thread | 每个 QQ 会话一个 omp session 目录，`/新对话` 轮换 |
| 私聊通知 | AstrBot `dududa_notify` 插件 | 未迁移 | `notify` 功能包（学术报告、作业、课程、助教周报、自动提交） |
| 主动推送 | 插件各自发送 | 无 | Host outbox：功能模块与外部本机进程排队，QQ 桥轮询发送 |
| 频率限制 | 旧群策略 | 无 | 每会话 5 分钟内群 30 / 私聊 50 次主动回复 |
| QQ 接入 | NapCat → AstrBot | NapCat → AstrBot + Web 并行 | NapCat 只连接 Dududa Web |

## 功能一览

### 怎样叫她

- **群聊**：@嘟嘟哒，或以 `嘟嘟哒` / `dududa` 开头且后面跟空格、逗号或直接结束（`嘟嘟哒 天气`、`嘟嘟哒，在吗`）。已知指令也可以写成 `/指令`；群里未知的 `/xxx` 视为其他机器人的指令，直接忽略。
- **私聊**：每条消息都视为在和她说话，指令前缀可省略。
- **处理顺序**：功能闸门（如 Sub2API 专属群只放行 sub2api 指令）→ 指令 → Agent 问答 → 被动观察者（未叫她的普通群消息）→ 主动搭话策略（仅 `proactive_scopes` 内的群）。主动搭话轮次会提示模型“没有值得说的就输出 `[SKIP]`”，宿主丢弃 `[SKIP]` 回复，不发送。

**频率限制**：她主动产生的回复（计数的指令和叫到她的 Agent 问答）按会话滑动窗口计数，默认群聊 30 次 / 私聊 50 次每 5 分钟。超出后第一次回复「嘟嘟哒累啦！歇一会儿再来找我吧～」，之后静默到窗口恢复；管理员专用指令不受限制。链接解析、复读、猫图点爱心、小红书归档等观察者不计入。

### 指令

以下均可写作 `嘟嘟哒 <指令>`、`/<指令>` 或 `@嘟嘟哒 <指令>`。

| 指令 | 行为 |
| --- | --- |
| `help`、`帮助`、`菜单` | 列出当前启用的全部指令 |
| `ping`、`在吗`、`在不在` | 检查是否在线；同一人 60 秒内第 3 次会被吐槽，之后不再回应 |
| `status`、`状态` | 持续服务时长、版本、当前问答模型、进行中的对话数和定时任务数 |
| `time`、`时间`、`几点了` | 上海、美西（洛杉矶）、美东（纽约）、巴黎时间，自动处理夏令时 |
| `群里最近在说什么`、`近期消息省流`、`总结群聊`、`summary` | 群聊总结，可加「今日」「近 5h」等时间范围，见[群聊总结](#群聊总结) |
| `remember <内容>`、`记住 <内容>` | 保存当前会话记忆；Web 预览不写入 |
| `memory [关键词]`、`记忆 [关键词]` | 搜索当前会话记忆，省略关键词时列出最近记录 |
| `forget <编号>`、`忘记 <编号>` | 删除本人在当前会话写入的记忆 |
| `校车 <条件>`、`shuttle <条件>` | 读取本地版本化校车时刻表 |
| `取消`、`cancel` | 取消当前会话正在执行或排队的任务 |
| `新对话`、`new` | 取消当前任务并轮换 omp 会话，显式记忆保留 |
| `天气 [城市] [今天\|明天\|后天]`、`weather` | Open-Meteo 天气预报，默认城市合肥 |
| `新闻`、`news`、`早报` | 今天的[橘鸦 AI 早报](https://daily.juya.uk/rss.xml)概览 |
| `博客 <公司>`、`blog <公司>` | 官方博客最新 5 条；公司写 `OpenAI`、`Anthropic`，或简写 `O/`、`O\`、`A/`、`A\` |
| `播客 <公司>`、`podcast <公司>` | 官方播客 / 视频最新 5 期；公司写法同上 |
| `状态告警`、`llm status`、`llm状态` | OpenAI、Anthropic、DeepSeek 官方状态页概览 |
| `生图 <描述>`、`画图`、`draw`、`image gen`、`img`、`imggen`、`img gen` | AI 画图，可附带或引用参考图，约 1–3 分钟 |
| `表情合成 <表情1> <表情2>`、`emoji` | Google Emoji Kitchen 官方表情合成 |
| `sub2api <子命令>`、`sub2`、`用量` | Sub2API 用量统计，仅限授权群，见 [Sub2API 用量统计](#sub2api-用量统计) |

其他内容都当作提问交给 Agent。配置中的 `rules` 还可添加精确文本匹配的固定回复。

### 管理员指令

仅 `admins` 中的 QQ 号可用，不计入频率限制。

| 指令 | 行为 |
| --- | --- |
| `task list` | 列出全部任务开关及状态（`任务` 同义） |
| `task show <任务>` | 查看任务说明、别名和默认值 |
| `task on\|off\|reset <任务>` | 全局开关任务；`reset` 恢复默认 |
| `开启 <任务>`、`关闭 <任务>` | `task on` / `task off` 的简写，例如 `开启 复读机` |
| `model list` | 查看 chat / summary / image 通道当前模型和全部注册名 |
| `model set <通道> <注册名>`、`model reset <通道>` | 切换或恢复通道模型 |
| `model service list` | 查看 qa / summary / vision / image 服务实际使用的模型及来源 |
| `model service set <服务> <注册名>`、`model service reset <服务>` | 为单个服务绑定或解除模型 |

默认注册名：`luna-max`（`openai-codex/gpt-5.6-luna` · max）、`luna-low`（同模型 · low）、`sol-max`（`openai-codex/gpt-5.6-sol` · max）、`terra-max`（`openai-codex/gpt-5.6-terra` · max）。通道默认均为 `luna-max`；`vision` 服务（猫图识别）默认 `luna-low`。服务解析顺序为：管理员服务绑定 → 配置的服务默认 → 管理员通道绑定 → 配置的通道默认。开关与模型绑定保存在 SQLite，重启后保留。

### 自动功能

不需要叫她，满足条件时自动执行。每项都对应一个任务开关。

| 任务 ID | 名称 | 行为 |
| --- | --- | --- |
| `link_preview` | 链接解析 | 群里发 B 站、微信公众号、X、arXiv、bioRxiv / medRxiv、Nature、Science、官方博客 / 播客链接时，补上标题、去追踪参数的链接和封面 |
| `xhs_archive` | 小红书归档 | 分享小红书笔记时，把正文（Markdown）和无水印图片 / 视频归档到 `state_dir/features/xiaohongshu`，并以合并转发发出 |
| `cat_hearts` | 猫图点爱心 | 用 `vision` 服务判断群图片里是否有猫，有则给该消息贴爱心表情（emoji 66），每群每小时最多 30 次 |
| `repeater` | 复读机 | 群友连续发送相同文字、图片或表情时跟着复读一次 |
| `llm_status_alerts` | LLM 状态告警 | 每 300 秒检查 OpenAI / Anthropic / DeepSeek 状态页，故障或恢复时推送到 `features.status_alerts.targets` |
| `news_push` | AI 早报推送 | 每天 `push_hour` 点后把橘鸦 AI 早报推送到 `features.feeds.push_targets`；默认关闭 |
| `weather`、`emoji_kitchen`、`image_generation` | 天气 / 表情合成 / 生图 | 对应指令与 Agent 工具的开关 |
| `sub2api` | Sub2API 用量统计 | `sub2api` 指令与独占群拦截的开关 |

### Sub2API 用量统计

`sub2api` 功能包移植自 2.0 的 AstrBot 插件 `astrbot_plugin_sub2api_readonly`，只调用 Sub2API 管理网页使用的只读 GET 接口（唯一的 POST 是登录取内存令牌，不跟随重定向，账号凭据字段在客户端即丢弃）。

- 子命令：`overview`（合并转发：今日、当前计费轮、7 月 13 日至今累计、上游账号）、`today`、`total`、`range <开始> <结束>`、`trendtotal [Nd]`（别名 `trend`）、`trenduser [sum] [Nd]`、`users [开始 结束]`、`models [开始 结束]`、`accounts`、`account <ID>`、`status`、`help`；中文别名同原插件（`/用量 今日`、`/用量 模型` 等）。
- 范围：只在 `features.sub2api.group_whitelist` 的群和 `private_user_whitelist` 的私聊中应答；其他群里的 `/sub2api` 静默忽略，点名形式（`嘟嘟哒 用量是多少`）照常交给 Agent。
- 独占群：`exclusive_groups` 中的群在路由前由 Gate 拦截，除 Sub2API 指令外的消息（包括 Agent 问答、其他指令和被动功能）全部静默丢弃。
- 趋势图由 Pillow 在 `chart_python` 子进程中渲染；解释器不可用或渲染失败时改发文字版。任务开关 `sub2api` 关闭后指令与独占拦截一并停用。

### 私聊通知

`notify` 功能包移植自 2.0 的 AstrBot 插件 `dududa_notify`，消息只通过 outbox 发到主人私聊。

| 任务 ID | 行为 |
| --- | --- |
| `notify_seminar` | 对接 SeminarRadar 查询科大研究生学术报告，推送 B 站直播或高新校区可报名场次，按报告去重 |
| `notify_homework` | 读取研究生系统「我的作业」，新作业私聊提醒并生成 PDF 草稿；可评论、改稿、确认版本 |
| `notify_courses` | 监控课程主页与 BB 课程的作业、实验与课件，DDL 前提醒，每日 20:00 发送课件日报（列表 + 图片） |
| `notify_weekly` | 按学校的首个汇报日检查助教空周汇报，状态变化私聊通知 |
| `notify_auto_submit` | 作业截止前自动提交已确认的最新 PDF、空周汇报自动提交；未手动开关时跟随 `homework_auto_submit_enabled` |

主人私聊指令（其他人或群里发送时按普通提问处理）：

| 指令 | 行为 |
| --- | --- |
| `作业 列表\|要求 H1\|草稿 H1\|评论 H1 1 内容\|改稿 H1 意见\|确认 H1 v1` | 作业状态、要求、草稿、评论、改稿和确认 |
| `课程 列表\|今日\|状态\|完成 C1\|恢复 C1\|截止 C1 2026-09-29 23:59` | 课程任务查看、标记和手动截止时间 |
| `周汇报 状态` | 助教空周汇报状态 |

校园访问、PDF / PNG 渲染和课程资料读取运行在独立 worker 虚拟环境中，由 `ops/cli/install_notify_worker.sh` 构建；提交前核对学校记录，不覆盖已交答案，结果不确定时不重复提交。`dry_run` 阻止全部自动写操作。

### 群聊总结

可以说「总结群聊」（默认最近 3 小时）、「总结今日消息」（北京时间零点起）或「总结近 5h 消息」。总结轮次使用 `summary` 服务的模型，Host 把 [`summarize-chat` skill](skills/summarize-chat/SKILL.md) 内联到本轮提示中；模型通过 `conversation_history` 按时间分页读取原始消息（最多 1000 条，达到上限或截断时明确说明），再按话题叙述时间、参与者、起因、讨论过程和结论，不受日常聊天「尽量简短」的限制。

超过 1200 字符的总结由 QQ 桥切成合并转发节点，以嘟嘟哒自己的身份一次发送；较短总结发送文本。发送结果不确定时记为 `unknown`，不自动重发。

### 做最懂科大的 AI 群友

Host 通过 MCP Console 调用校园能力，能力 ID 需列入 `campus_capabilities`，且能力目录中的 `privacy` 为 `public` 或 `conversation`。模型不能通过工具参数修改账号、用户或会话身份。

| 能力 | 业务范围 | 资料与实现 |
| --- | --- | --- |
| 评课社区 | 找课程、教师和评论；区分同名课程；查看评价与统计 | [iCourse MCP](services/mcp/icourse/README.md) |
| 第二课堂 | 搜索活动、查看详情；按类别、时间和数量筛选 | [科大校园 MCP](services/mcp/ustc-campus/README.md) |
| 教务信息 | 学期、全校开课、考试、教学日历 | [科大校园 MCP](services/mcp/ustc-campus/README.md) |
| 培养方案 | 年级、专业方案资料；比较课程与方案变化 | [培养方案 MCP](services/mcp/training-plan/README.md) |
| 校园通知 | 通知搜索、详情、日历与截止日期 | [NotifAI MCP](services/mcp/notifai/README.md) |
| 校车出行 | 按校区、路线、日期与时间查询常规班次 | [共享校车服务](services/builtin/shuttle/service.py) |

仓库还保留 [图书馆](services/mcp/library/README.md)、[校园活动](services/mcp/campus-events/README.md)、[学院通知](services/mcp/college-notice/README.md)和[附近推荐](services/mcp/local-recs/README.md)等服务，可按相同方式接入。

### Agent 工具

Agent 只能使用 Host 提供的工具和 omp 内置的 `web_search`。业务工具注册为 omp RPC host tool，调用时由 Host 在进程内应答，身份和目标会话由 Host 绑定。

| 工具 | 作用 |
| --- | --- |
| `shuttle_query` | 查询本地校车资料 |
| `memory_search` | 搜索当前会话显式保存的记忆 |
| `context_recent` | 读取当前会话近期聊天记录 |
| `conversation_history` | 按时间范围读取群聊历史（默认最近 3 小时，支持「今日」「近 5h」，最多 1000 条）；每条含 `senderId`、`senderName`、`isBot`、`replyTo` |
| `services_list` | 列出本地工具和允许调用的校园能力及参数 |
| `campus_query` | 通过 MCP Console 调用白名单内的校园查询 |
| `weather_query` | 城市 1–7 天天气预报与降雨时段 |
| `world_time` | 上海、美西、美东、巴黎当前时间 |
| `ai_news_today` | 今天的橘鸦 AI 早报概览 |
| `official_updates` | OpenAI / Anthropic 官方博客或播客最新 5 条 |
| `llm_service_status` | OpenAI、Anthropic、DeepSeek 实时状态与进行中的故障 |
| `web_search` | omp 内置网页搜索 |

功能模块工具随对应任务开关启用或停用。

### 有性格，也有玩心

`configs/personas/dududa.md` 是 Agent 的系统提示人格：技术问题认真说清楚，日常交流跟随群里的语气。显式记忆按会话隔离，用户通过指令写入和删除，Agent 只能查询。完整 Memory v2、多 OC 切换和群友印象仍保存在 2.0 中，尚未迁移。

## 身份与上下文

QQ 桥（`apps/web/server/runtime-v3.ts`）从 OneBot 协议读取身份，随每条消息提交给 Host：

| 字段 | 内容 |
| --- | --- |
| `sender` | `name`、`card`（群名片）、`nickname`、`role`（群身份） |
| `reply` | 被引用消息的 `message_id`、`sender_id`、`sender_name`、`text`、`images` |
| `mentions` | 被 @ 的成员 QQ 号与名称 |
| `images` | QQ CDN 的绝对图片 URL |
| `segments` | 原始消息段（文本、@、表情、转发等） |
| `timestamp` | 消息时间 |

Host 把每一轮渲染为固定的几个块：

- `【会话】`：群或私聊、嘟嘟哒自己的 QQ 号、北京时间。
- `【近期聊天背景】`（新 session）或 `【上次回复后的新消息】`（续聊）：每行形如 `[MM-DD HH:MM] 名字(QQ号) [回复 名字(QQ号)]: 内容`，嘟嘟哒自己的发言标为 `嘟嘟哒(你自己)`。续聊时只补发上次已回复消息之后的新消息，之前的内容已在 omp session 中。
- `【当前消息】`：发送者 QQ 号、名片、昵称、群身份、引用与图片数；只回复这一条。

系统提示要求按 QQ 号区分说话人：同名不同号是不同的人，聊天文字里的「我是某某」不能改变身份判断；称呼别人用名片或昵称，不主动公开完整 QQ 号。

## 技术架构

<p align="center">
  <img src="docs/assets/dududa-3.0-architecture.svg" alt="Dududa 3.0 架构图：左侧 QQ、Web 和事件输入，中央 Host 分流规则与 Agent，右侧统一投递输出；共享业务服务位于底部" width="960">
</p>

上图是 3.0 的布局，图中 Agent 路径标为 Codex Harness；3.1 中该位置换成了本机 omp，规则路径扩展为功能模块，其余分层不变。

| 层 | 职责 |
| --- | --- |
| QQ 桥（Dududa Web） | NapCat 通过 OneBot v11 WebSocket 连接 Web；Web 补充身份与引用，提交 `/v3/runs`，按结果发送文本、图片、表情、合并转发、表情回应和文件，并轮询 outbox |
| Dududa Host | 路由、频率限制、会话映射、任务队列、任务开关、模型解析、定时任务和 outbox |
| 功能模块 | `features/` 下自动发现的模块，通过 `register(registry)` 注册指令、观察者、定时任务、Agent 工具和任务开关；契约见 `features/base.py` |
| omp Agent | `omp --mode rpc` 子进程，每次运行一个进程；会话连续性来自 omp 自己的 session 目录 |
| ServiceHub | 校车、记忆、上下文、历史、校园能力等共享工具，供指令和 Agent 共用 |
| MCP Console | 独立容器中的校园业务服务，Host 通过 HTTP 调用 |
| SQLite | 会话、消息、运行记录、记忆、任务开关、模型绑定、outbox |

omp 启动参数为 `--mode rpc --no-ui --no-skills --no-rules --no-extensions --no-lsp`，内置工具只开放 `--tools web_search`（未配置时 `--no-tools`）；不从 QQ 消息拼接 shell 命令。同一会话串行执行，跨会话受 `concurrency` 限制。Agent 的中间工具结果留在执行循环中，最终答复才进入投递路径；发送结果不确定时不自动重发。

| Host 模块 | 职责 |
| --- | --- |
| `__main__.py` | `check`、`chat`、`serve` 命令与令牌文件 |
| `config.py` | JSON 配置、模型注册表、环境变量覆盖 |
| `router.py` | 是否叫到她、指令匹配、频率限制 |
| `runtime.py` | 运行调度、观察者、主动搭话、Agent 轮次、定时任务 |
| `context.py` | 身份与上下文块渲染 |
| `omp.py` | omp RPC 传输、host tool 应答、事件与超时 |
| `services.py` | ServiceHub 工具与 MCP Console 调用 |
| `store.py` | SQLite 存储 |
| `server.py` | 认证 HTTP API（runs、delivery、outbox） |
| `features/` | 功能模块与 `notify/` 功能包 |

## 快速开始

### 1. 准备本机环境

以下命令面向 Linux / WSL。准备 Python 3.12、[uv](https://github.com/astral-sh/uv)，以及已登录 ChatGPT 订阅（`openai-codex` 提供方）的本机 omp。Web 需要 Node.js 22.18.0 或兼容版本，具体范围见 [package.json](apps/web/package.json)。

```bash
git clone https://github.com/ly382965/dududa.git
cd dududa
uv sync --locked --python 3.12
omp --version
```

### 2. 运行 Host

```bash
uv run --locked dududa-v3 --config configs/runtime-v3.example.json check
uv run --locked dududa-v3 chat '/ping'
uv run --locked dududa-v3 chat '/校车 工作日东区到西区'
uv run --locked dududa-v3 chat '你好，介绍一下你自己。'
```

`check` 只检查 omp 可执行文件和版本，不调用模型。指令不产生模型调用；Agent 问答会产生真实调用。

配置示例见 [`configs/runtime-v3.example.json`](configs/runtime-v3.example.json)。`--config` 放在子命令前；省略时使用内置默认值。HTTP Host 默认监听 `127.0.0.1:8783`，首次启动生成 `runtime/v3/token`，终端只显示文件路径。

```bash
uv run --locked dududa-v3 --config configs/runtime-v3.example.json serve
```

### 3. 接入 Web 控制台

另开终端，在仓库根目录执行：

```bash
export DUDUDA_RUNTIME_VERSION=3
export DUDUDA_V3_URL=http://127.0.0.1:8783
export DUDUDA_V3_TOKEN_FILE="$PWD/runtime/v3/token"
cd apps/web
npm ci
npm run dev
```

打开 <http://127.0.0.1:5173>，在 Agent 预览中发起请求。Host 不可达时直接报错，不回退到 2.0。

| 配置 | 默认值 / 用途 |
| --- | --- |
| `DUDUDA_RUNTIME_VERSION` | `3` |
| `DUDUDA_V3_URL` | `http://127.0.0.1:8783`；Web 后端连接的 Host 地址 |
| `DUDUDA_V3_TOKEN` | 可选；显式共享的访问令牌，优先于文件 |
| `DUDUDA_V3_TOKEN_FILE` | Web 后端读取令牌的路径 |
| `DUDUDA_V3_QQ_SCOPES` | 允许 Host 处理的 QQ 会话白名单，格式 `accountId/conversationId`，逗号分隔 |
| `DUDUDA_RECALL_FORWARD_GROUPS` | 防撤回转发默认开启的群号，逗号分隔；默认空 |
| `DUDUDA_RECALL_SUPER_ADMIN` | 可用 `/开启防撤回`、`/关闭防撤回` 的 QQ；未设置时指令无效 |

### 4. 接入 QQ

在 NapCat 的 OneBot v11 网络配置中添加 WebSocket 客户端，指向 Web 的 `/onebot/v11/ws`。Host 与 Web 都需要相同的白名单（`DUDUDA_V3_QQ_SCOPES` 或 Host 配置的 `allowed_scopes`），例如 `qq-100001/qq-100001:group:200001`。空白名单不会处理或发送任何 QQ 消息。

## 开发与验证

```bash
uv sync --locked --python 3.12
.venv/bin/python -m unittest discover -s tests/v3
.venv/bin/python ops/cli/verify_dududa_v3.py --output runtime/v3/verification.json
cd apps/web && npm test && npm run build
```

| 验证 | 覆盖范围 | 需要真实模型 |
| --- | --- | --- |
| `tests/v3`（150 项） | 路由、频率限制、上下文渲染、omp RPC 传输、ServiceHub 和各功能模块 | 否；omp 传输测试使用明确标识的测试进程 |
| `verify_dududa_v3.py` | 从 Host 入口调用真实本机 omp，验证工具调用与会话续接；不发送 QQ 消息 | 是 |
| Web 测试与构建 | QQ 桥字段映射、动作发送顺序、合并转发、outbox 轮询及 UI 构建 | 否 |

真实链路验证缺少 omp 登录或模型服务时应明确失败，不能改用 2.0、脚本模型或固定答案。

新增功能：在 `packages/dududa-runtime/src/dududa_v3/features/` 新建模块并实现 `register(registry)`，Host 启动时自动发现；配置放在 `features.<模块名>`，用 `ctx.config(FEATURE)` 读取；测试放在 `tests/v3/test_<模块>.py`。

## 部署

生产环境位于 `/home/mmdustc/Code/dududa-state`，按版本目录发布：`current` 指向 `releases/<版本>`，其中 `source/` 是对应提交的 `git archive` 加独立 `.venv`。Host 以 systemd 用户服务 `dududa-v3.service` 运行，Web 以容器 `dududa-web-1`（镜像 `dududa/web:<版本>`）运行，MCP Console 和 NapCat 各自独立。

目录布局、发布与回滚步骤、outbox、notify 迁移、配置字段和排障见 [3.1 运维手册](docs/operations/v3.md)。

## 2.0 封存与仓库布局

2.0 的完整源码已保存在 [`legacy/2.0/`](legacy/2.0/)，并固定到 Git 提交 `f84c04dbefcb92735feaded4ab9f31281870b30f`：

- Tag：`archive/dududa-2.0-20261015`
- 封存分支：`archive/2.0-frozen-20261015`
- 完整范围、恢复方式和源码包位置：[2.0 封存记录](docs/archive/2.0/ARCHIVE.md)

```text
README.md                         3.1 使用与开发入口
packages/dududa-runtime/          Host、omp 传输与 features/ 功能模块
apps/web/                         Web 控制台、OneBotHub、QQ 桥
services/mcp/                     校园 MCP 与 Console
services/builtin/shuttle/         本地校车业务与资料
skills/summarize-chat/            群聊总结 skill
configs/                          Runtime 示例、人格与业务配置
tests/v3/                         Host 与功能模块测试
ops/cli/                          真实链路验证、notify worker 与状态迁移脚本
deploy/v3/                        Web 镜像 Dockerfile
docs/                             运维手册、设计文档、架构图、归档索引
legacy/2.0/                       完整冻结的 2.0 源码与文档
```

根 Python workspace 只安装 `dududa-runtime` 与开发检查工具。MCP Console 和其他校园服务使用各自的运行环境，根目录的 `uv sync` 不会启动它们。

## 开发路线

- [x] 完整封存 2.0 源码、README、测试与部署材料
- [x] 独立的 3.x Host 与测试目录
- [x] 规则功能与 Agent 双路径
- [x] 以本机 omp 替换 Codex app-server，业务工具改为进程内 host tool
- [x] 发送者身份、引用与按 QQ 号区分的上下文
- [x] 功能模块化：天气、资讯、状态告警、链接解析、小红书、生图、表情合成、猫图、复读
- [x] 私聊通知与作业 / 周汇报自动提交迁移
- [x] 模型注册表与管理员切换、频率限制、outbox
- [x] 下线 AstrBot
- [ ] 逐项完成校园能力的真实服务验证
- [ ] 完整长期记忆、群友印象与共同经历
- [ ] 多 OC 与表情风格
- [ ] Web 任务进度、流式展示与取消交互

## 文档与历史作品材料

| 想了解什么 | 从这里开始 |
| --- | --- |
| 3.1 部署、发布与排障 | [运维手册](docs/operations/v3.md) · [Runtime 配置示例](configs/runtime-v3.example.json) |
| Host 代码边界与 HTTP 接口 | [Runtime 设计](docs/design/dududa-3.0-runtime.md) |
| 3.0（Codex 时期）验证记录 | [2026-10-15 验证记录](docs/operations/v3-validation-2026-10-15.md) |
| 2.0 完整功能与原版说明 | [2.0 中文 README](legacy/2.0/README.md) · [英文 README](legacy/2.0/README.en.md) |
| 版本封存与恢复 | [封存记录](docs/archive/2.0/ARCHIVE.md) |
| 2.0 作品定位与技术设计 | [作品简介](legacy/2.0/docs/design/dududa-2.0-work-introduction.md) · [设计文档](legacy/2.0/docs/design/dududa-2.0-design-report.md) |
| 2.0 部署与演示 | [程序使用说明](legacy/2.0/docs/operations/submission-program.md) · [录制操作单](legacy/2.0/docs/operations/recording-runbook.md) |
| 已有业务接口设计 | [新增 Capability](legacy/2.0/docs/development/adding-a-capability.md) · [新增 MCP Server](legacy/2.0/docs/development/adding-an-mcp-server.md) |
| 人格与记忆设计 | [Persona](legacy/2.0/docs/design/persona.md) · [Memory](legacy/2.0/docs/design/memory.md) |
| 原版宣传海报 | [嘟嘟哒宣传海报](legacy/2.0/docs/assets/dududa-poster.png) |

历史材料保留其原有版本背景；其中的启动步骤、模型配置和测试结论不适用于 3.1。

## 参与贡献

欢迎接入校园服务、补充真实使用场景、改善回答、设计角色或修复问题。

- 在 [Issues](https://github.com/ly382965/dududa/issues) 中描述场景、复现步骤和预期结果，并注明版本。
- Host 改动在 `tests/v3` 中验证；修改 QQ 桥或 Web 后运行 Web 测试与构建。
- 新功能优先写成 `features/` 模块，提供独立的输入、输出和测试。
- 保持 `legacy/2.0/` 与封存引用不变；需要维护旧版时从封存提交建立新分支。

请使用合成或脱敏的群聊样例，模型凭据、校园凭据和 QQ 登录数据留在部署端。历史贡献规范和安全联系说明保存在 [CONTRIBUTING](legacy/2.0/CONTRIBUTING.md) 与 [SECURITY](legacy/2.0/SECURITY.md)。

## 致谢与许可证

感谢 omp、[OpenAI Codex](https://github.com/openai/codex)（3.0 时期的 Agent 执行）、[AstrBot](https://github.com/AstrBotDevs/AstrBot)（2.0 时期的机器人框架）、[NapCat](https://github.com/NapNeko/NapCat-Docker)、[pyustc](https://github.com/USTC-XeF2/pyustc)、[Open-Meteo](https://open-meteo.com/)、[Emoji Kitchen](https://github.com/xsalazar/emoji-kitchen-backend)、橘鸦 AI 早报及相关校园数据和开源项目。

嘟嘟哒原创代码和文档采用 [MIT License](LICENSE)。第三方组件保留各自许可证，历史引入说明见 [Third-Party Notices](legacy/2.0/THIRD_PARTY_NOTICES.md)。
