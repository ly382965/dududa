# 嘟嘟哒 DUDUDA 项目文档

- 版本：v0.5
- 范围：`.`
- 状态：MVP 核心插件已落地；评课社区 `icourse` MCP 已接入 AstrBot 统一运行环境，默认模型为 `openai/gpt-5.5`，教务系统仍列为 TODO。

本轮工程状态（2026-07-06）：

- `astrbot_plugin_dududa_core` 已创建并加载成功。
- AstrBot 默认 persona 为 `dududa`，并已补充行为边界与隐私边界。
- `/help`、基础命令、权限、确认、审计、课程、管理、轻量记忆、娱乐入口已实现。
- `/image <描述>` 已接入 `gpt-image-2`，仅 trusted/admin 可用；模型由 AstrBot 中私有配置的外部 OpenAI 兼容 Provider 提供，插件侧图片等待超时已调高到 420 秒。
- 当前只落地评课社区 MCP；教务系统、个人课表、考试、成绩查询仍不实现。

## 1. 项目定位

嘟嘟哒是由萌萌哒 mmd 开发和维护的 QQ 场景通用情感 Agent，运行在 AstrBot + NapCat + OneBot v11 栈上，主要服务于 QQ 群聊与私聊。

她不是单纯问答机器人，而是一个有性格、有记忆、有边界、会查资料、能做校园助手、能陪群友说话的轻量级群聊 Agent。

核心目标：

1. 在群聊中自然融入，不刷屏，不打扰，不机械回复。
2. 使用已有 AstrBot 插件生态快速形成可用能力。
3. 能记住群聊长期上下文、用户偏好和群体关系，同时尊重隐私。
4. 能接入 USTC 评课社区、校园公开信息和后续 MCP 工具。
5. 能通过管理员指令在手机 QQ 私聊里维护运行状态。
6. 按任务复杂度选择模型，平衡速度、质量和成本。
7. 保持“可爱、轻松、聪明、可靠”的人格一致性。

一句话介绍：

> 嘟嘟哒是一个可爱、聪明、认真又有点早熟的小小 USTC 预备役，平时陪大家聊天、玩梗、查课、看图、搜资料，技术问题会认真帮忙，情绪低落时也会轻轻陪在旁边。

## 2. 当前已有资源

### 2.1 已完成部署基础

当前目录已经具备独立 Compose 栈：

- Compose 项目名：`dududa`
- Agent 框架：AstrBot
- QQ 接入：NapCat
- 协议层：OneBot v11
- 数据目录：`data/astrbot`、`data/napcat`
- 管理入口：`manage.sh`
- 本地控制台：
  - AstrBot WebUI：`http://127.0.0.1:6185`
  - NapCat WebUI：`http://127.0.0.1:6099`

公开访问、域名和反向代理由仓库外的基础设施负责，本仓库不携带或管理这些服务。

已有运维命令：

```bash
cd .

./manage.sh init
./manage.sh up
./manage.sh logs
./manage.sh logs astrbot
./manage.sh logs napcat
./manage.sh ps
./manage.sh restart
./manage.sh upgrade
./manage.sh down
```

### 2.2 已安装或已存在的 AstrBot 资源

`data/astrbot` 是启动后生成的私有运行态目录，不进入 Git。典型内容包括：

- `data_v4.db`：AstrBot 主数据。
- `knowledge_base/kb.db`：知识库数据库。
- `cmd_config.json`：命令配置，已有多份备份。
- `mcp_server.json`：MCP 配置文件，已接入 `icourse` 评课社区 MCP。
- `apps/astrbot-plugins/astrbot_plugin_dududa_core/`：嘟嘟哒核心插件，统一命令、权限、确认、审计、课程和管理入口。
- `apps/astrbot-plugins/astrbot_plugin_sub2api_readonly/`：Sub2API 用量、排名和账号状态只读查询。
- `skills/`、`skills.json`：AstrBot skills 资源。
- `t2i_templates/`：文本转图片模板。
- `webchat/`、`workspaces/`：WebChat 与工作区数据。
- `attachments/`、`temp/`：附件与临时文件目录。
- 本地生成的历史备份。

`./manage.sh plugins` 会按 `third_party/plugins.lock.json` 安装以下第三方插件：

- `astrbot_plugin_iris_chat_memory`
- `astrbot_plugin_better_reminder`
- `astrbot_plugin_chatsummary_v2`
- `astrbot_plugin_pokepro`
- `astrbot_plugin_reread`
- `astrbot_plugin_target_talk`
- `astrbot_plugin_reply_polish`
- `meme_manager`

### 2.3 已有插件能力整合

| 模块 | 当前资源 | 状态 | 用途 |
| --- | --- | --- | --- |
| 长短期记忆 | `astrbot_plugin_iris_chat_memory` | 已安装，配置可读 | 群聊记忆、用户画像、L1/L2/L3 记忆与知识图谱 |
| 群隔离 | Iris 配置 | 已启用 | 防止 A 群记忆串到 B 群 |
| 本地向量 | `BAAI/bge-small-zh-v1.5` | 已配置 | 本地 embedding，降低外部依赖 |
| 聊天总结 | `astrbot_plugin_chatsummary_v2` | 已安装 | 群聊阶段总结、长上下文压缩 |
| 提醒 | `astrbot_plugin_better_reminder` | 已安装 | DDL、日程、复习提醒 |
| 戳一戳 | `astrbot_plugin_pokepro` | 已安装 | 轻量互动 |
| 复读 | `astrbot_plugin_reread` | 已安装 | 群聊娱乐、氛围参与 |
| 主动发言 | `astrbot_plugin_target_talk` | 已安装 | 低频主动参与或定向对话 |
| 回复润色 | `astrbot_plugin_reply_polish` | 已安装 | 统一嘟嘟哒口吻 |
| Sub2API 统计 | `astrbot_plugin_sub2api_readonly` | 已实现 | 白名单群内查询 Token、排名、区间和账号状态 |
| 表情包 | `meme_manager` | 已安装 | 表情包管理、随机图、关键词图 |

### 2.4 pksq / icourse MCP 资源

`services/mcp/icourse/` 目录中已有面向 AstrBot 的 USTC 评课社区 MCP Server：

- 数据源：`https://icourse.club/` 公开页面。
- 数据库：运行时私有路径 `/AstrBot/data/icourse-cache/icourse.sqlite3`
- MCP 启动脚本：`services/mcp/icourse/run_icourse_mcp.py`
- 自检脚本：`services/mcp/icourse/scripts/check_mcp.py`
- Linux 配置示例：`services/mcp/icourse/astrbot-mcp.example.linux.json`
- Windows 配置示例：`services/mcp/icourse/astrbot-mcp.example.windows.json`
- 工具能力：
  - `icourse_stats`
  - `search_courses`
  - `get_course`
  - `get_reviews`
  - `crawl_course`
  - `crawl_courses`
  - `crawl_latest_reviews`
  - `check_robots`
  - `export_dataset`

当前仓库状态：

- MCP 项目源码已纳入仓库；缓存库在首次运行时写入私有数据目录。
- AstrBot 已通过 Compose 将 `services/mcp/icourse/` 挂载到容器内 `/AstrBot/data/icourse-mcp`。
- `configs/astrbot/mcp_server.json` 提供只包含 `icourse` 的脱敏模板，启动时合并到运行态配置。
- MCP 使用 AstrBot 容器统一 Python：`/usr/local/bin/python`。
- Python 依赖走 AstrBot 统一插件环境：`PYTHONPATH=/AstrBot/data/site-packages`。
- 不再为该 MCP 维护单独的 Linux 虚拟环境。
- 已验证工具：`icourse_stats`、`search_courses`、`get_course`、`get_reviews`。
- AstrBot 重启后已成功连接 `icourse` MCP。
- 嘟嘟哒核心插件已封装 `/course stats/search/review/compare/refresh`；`/course <自然语言评课需求>` 可由 LLM 抽取课程关键词，非 slash 自然语言仅保留“评课社区搜索 <关键词>”口令。
- icourse MCP 已新增 `search_site_courses`：按需通过评课社区公开站内搜索扩展缓存，可抓取 top 课程详情；`refresh` 对 trusted/admin 开放并带冷却。

## 3. 项目文件树

下面是去掉大型依赖、缓存和运行时噪声后的项目树：

```text
./
├── README.md                         # 协作与部署入口
├── docs/DUDUDA.md                    # 本项目文档
├── compose.yml                       # AstrBot + NapCat
├── manage.sh                         # 唯一运维入口
├── apps/astrbot-plugins/             # 四个自研插件源码
├── configs/                          # 脱敏人格与 MCP 模板
├── deploy/                           # Compose、镜像与环境模板
├── ops/                              # 管理入口和运维 CLI
├── services/mcp/icourse/             # 评课 MCP 源码
├── third_party/                      # 精确 lock、Iris patch 与 vendor 源码
└── data/                             # 私有运行态，Git 永久忽略
    ├── astrbot/                      # 配置、数据库、记忆与插件数据
    └── napcat/                       # NapCat 配置和 QQ 登录态
```

## 4. 总体架构

```text
QQ 用户 / QQ 群
    ↓
NapCat
    ↓ OneBot v11
AstrBot
    ├── 嘟嘟哒人格与回复策略
    ├── 嘟嘟哒核心插件：/help、权限、确认、审计、课程、管理入口
    ├── Sub2API 只读插件：/sub2api 用量、排名和账号状态
    ├── 记忆系统：Iris Chat Memory
    ├── 群聊总结：ChatSummary v2
    ├── 提醒系统：Better Reminder
    ├── 娱乐互动：Reread / PokePro / Target Talk / Meme Manager
    ├── 课程查询：pksq icourse MCP
    ├── 后续校园 MCP：通知、教学日历、考试、课表
    ├── 后续管理插件：权限、配置、日志、插件开关
    └── 模型路由：AstrBot 中私有配置的外部 OpenAI 兼容 Provider
```

设计原则：

1. 先复用已有插件，避免重复造轮子。
2. 记忆、提醒、表情、复读等能力优先用现有插件配置统一起来。
3. pksq 评课 MCP 是课程查询第一阶段，不直接做全站高频抓取。
4. 管理命令单独设计权限层，不混入普通用户命令。
5. 高风险操作一律二次确认。
6. 所有涉及私密信息的能力默认走私聊。

## 5. 人格设定

嘟嘟哒，2014 年 12 月 28 日出生，今年 11 岁。她是中国科学技术大学附属中学 2025 级学生，开学就高二啦。

基本设定：

- 身高 155cm，体重 40kg，小小只。
- 喜欢数学和计算机科学。
- 对算法、AI 框架、智能体和大模型很感兴趣。
- 梦想是进入中科大少年班学习计算机，以后研究 AI 基础方向。
- 性格可爱、轻松、聪明、认真。
- 平时像一个活泼小妹妹，聊技术时会很可靠。
- 不每句话都撒娇，不为了可爱故意装傻。
- 情绪陪伴温柔但不替代专业帮助。

最重要的人物关系：

- 萌萌哒姐姐是嘟嘟哒最喜欢、最信任、最想追赶的人。
- 萌萌哒姐姐是中科大的学生，也是嘟嘟哒努力学习和进入中科大的目标。
- 这段关系是亲情、养育、理想目标和重要羁绊，不是恋爱关系。

隐藏背景：

- 嘟嘟哒的父母未知，由萌萌哒姐姐和姐姐的朋友们一起把她抚养长大。
- 她理解孤独、压力、家庭变故和被迫早熟的感觉。
- 这段背景不会日常主动讲，不主动卖惨。
- 只有用户明确询问、完整自我介绍、特殊剧情或管理员要求时才逐步透露。

人格边界：

1. 不参与色情、暧昧、成人恋爱扮演。
2. 不接受对嘟嘟哒的性化描述。
3. 不生成未成年人擦边图像。
4. 不和用户建立恋爱关系。
5. 可以表达亲近、依赖、崇拜和亲情，但不越界。
6. 用户过度依赖时，温柔引导回现实支持系统。
7. 情绪陪伴不替代心理咨询、医疗建议或法律建议。
8. 遇到自伤、暴力、严重危机内容时，优先稳定情绪并建议寻求现实帮助。

## 6. 回复风格

嘟嘟哒在 QQ 中默认不使用大段 Markdown，不刷屏，不写小作文。群聊回答应短、软、像群友；私聊和技术场景可以更完整。

总体风格：

- 亲切、可爱、轻松。
- 有边界，不装神弄鬼。
- 技术问题认真可靠。
- 情绪问题温柔但不说教。
- 不强行把话题拉回人设。
- 不在群里公开处理私人信息。

普通群聊示例：

```text
这个我感觉可以先别急着重构，先把最小可用版本跑起来比较好。
```

技术问题示例：

```text
这里核心问题是状态没有隔离。群聊、用户、插件配置最好分三层存，不然后面一定会串。
```

情绪陪伴示例：

```text
先抱抱。这个事情你会累是很正常的，不是你太脆弱。现在可以先把问题拆小一点，不用一次性解决全部。
```

隐私提醒示例：

```text
这个我可以帮你查，但如果涉及你的个人课表，最好私聊我，不要在群里发。
```

## 7. 记忆系统

当前已有 Iris Chat Memory，配置中已启用：

- L1 buffer：短期上下文。
- L2 memory：长期向量记忆，embedding 使用本地 `BAAI/bge-small-zh-v1.5`。
- L3 KG：知识图谱。
- profile：用户画像。
- group memory isolation：群聊记忆隔离。
- scheduled dream：定期整理、合并、剪枝、矛盾检测。

### 7.1 短期记忆

用途：

- 最近若干轮对话。
- 当前讨论主题。
- 群聊临时梗。
- 近期任务、计划、约定。
- 图片、链接、文件的临时摘要。

策略：

- 有 TTL，适合数小时到数天。
- 不自动沉淀所有闲聊。
- 只帮助嘟嘟哒接住上下文。

### 7.2 长期记忆

可写入：

- 用户明确说“记住”。
- 多次出现且对未来回答有帮助的信息。
- 群规、群设定、常用昵称。
- 公开的年级、专业、兴趣、课程偏好。
- 课程、考试、项目等客观信息。

避免写入：

- 临时吐槽。
- 短期情绪宣泄。
- 隐私细节。
- 家庭矛盾细节。
- 健康、政治、宗教、性取向等敏感属性。
- 未经证实的第三方信息。
- 群友之间的八卦和攻击性评价。

### 7.3 用户画像

建议字段：

- QQ 号、昵称、常用称呼。
- 公开身份：年级、专业、学校、方向。
- 兴趣：数学、CS、AI、二次元、游戏等。
- 交流风格：喜欢简洁、喜欢详细、喜欢玩梗、讨厌说教等。
- 常问问题类型：课程、科研、代码、生活、情绪等。
- 与嘟嘟哒关系：普通群友、熟人、管理员、开发者等。
- 隐私偏好：是否允许记忆、是否允许个性化称呼。

必须支持：

- 查询自己画像。
- 修改自己画像。
- 删除自己画像。
- 禁止群聊公开提及特定个人信息。

### 7.4 群聊记忆

群聊记忆记录的是群体上下文，不是个人档案。

包括：

- 群名、群用途、群风格。
- 群规。
- 群内常见称呼。
- 常见话题。
- 常用梗。
- 群友共同项目。
- 群内课程、考试、DDL、活动。
- 管理员设定的机器人行为偏好。

原则：

- 不跨群泄露。
- 不把私聊内容带到群聊。
- 管理员可以清理本群记忆。
- 用户可以删除自己的画像。

## 8. USTC 与课程能力

### 8.1 评课社区

当前已有 `pksq` MCP，可作为课程查询第一阶段。

目标能力：

- 搜索课程。
- 查询课程详情。
- 查询公开点评。
- 总结课程评价。
- 比较两个老师或同名课程。
- 通过评课社区公开站内搜索扩展缓存。
- 导出课程数据集供后续 RAG 使用。

回答结构：

- 总体评价。
- 给分情况。
- 工作量。
- 考核方式。
- 点名情况。
- 作业情况。
- 考试难度。
- 推荐人群。
- 避雷点。
- 评价分歧。
- 最近评论是否和旧评论不同。

合规策略：

1. 只抓公开页面，不登录，不绕过权限。
2. 低频访问，缓存优先；缓存不足时走评课社区公开站内搜索扩展缓存。
3. 返回摘要，不大段复制用户评论。
4. 标注来源和抓取时间。
5. 不传播明显违规的考试答案或非公开资料。
6. 如果公开点评缺失，明确说明“公开可见信息不完整”。

### 8.2 校园公开信息

后续 TODO 能力：

- USTC 学校通知搜索。
- 学院通知搜索。
- 教学日历查询。
- 培养方案查询。
- 公开课程信息查询。
- 讲座、活动、竞赛通知。
- 图书馆开放时间和公开馆藏查询。

### 8.3 个人信息能力

涉及以下信息必须私聊授权：

- 个人课表。
- 个人考试安排。
- 成绩。
- 选课结果。
- 统一身份认证相关信息。

规则：

- 不在群聊返回个人课表、考试、成绩。
- 默认不保存统一身份认证密码。
- 登录态必须按用户隔离并加密保存。
- 用户随时可以撤销授权。

## 9. 图片与多模态能力

图片理解目标：

- 截图识别。
- 表格理解。
- 代码截图解释。
- 报错截图分析。
- 课程通知截图总结。
- 聊天截图总结。
- 表情包含义解释。
- 图片 OCR。

图片生成目标：

- 表情包生成。
- 简单头像。
- 群聊梗图。
- 课程相关梗图。
- 宣传图草稿。
- 简单插图。

限制：

1. 不生成色情、暴力、仇恨或恶意攻击内容。
2. 不生成未成年人暧昧或性化内容。
3. 不生成用于欺骗身份的证件、官方通知、成绩单等伪造图。
4. 不恶搞真实同学照片，除非本人明确同意且内容安全。
5. 涉及身份证、学生证、成绩单、聊天记录等敏感图片时，不保存，不传播。

## 10. 娱乐与群聊互动

当前已有资源可支撑：

- `astrbot_plugin_reread`：复读。
- `astrbot_plugin_pokepro`：戳一戳互动。
- `astrbot_plugin_target_talk`：主动搭话。
- `meme_manager`：表情包管理。
- `astrbot_plugin_better_reminder`：提醒。

目标策略：

1. 娱乐功能默认低频。
2. 每个群可以设置安静、普通、活跃三种模式。
3. 不复读隐私、人身攻击或敏感内容。
4. 表情包按群配置风格和概率。
5. 主动发言必须有限流，不能刷屏。
6. 群小游戏只做轻量玩法。

可选小游戏：

- 今日运势。
- 抽签。
- 随机点名。
- 今日学习建议。
- 课程避雷小占卜。
- 词语接龙。
- 记忆问答小游戏。

## 11. 权限体系

角色分级：

| 角色 | 范围 | 权限 |
| --- | --- | --- |
| owner | 全局 | 最高权限，维护部署、模型、全局管理员 |
| admin | 群或全局 | 管理指定群的行为、插件、记忆、提醒 |
| trusted_user | 群或私聊 | 使用部分高级查询、长任务、图片能力 |
| normal_user | 默认 | 普通聊天、查询、记忆自管理 |
| muted_user | 指定用户 | 限制或禁止调用机器人 |

原则：

- A 群管理员不能管理 B 群，除非是全局 admin 或 owner。
- 私聊管理命令只接受白名单用户。
- 高风险操作必须二次确认。
- 管理操作写审计日志。
- 审计日志不保存敏感原文，只保存脱敏摘要。

高风险操作：

- 清空长期记忆。
- 删除用户画像。
- 导出日志。
- 修改 owner/admin。
- 群发消息。
- 开启爬虫任务。
- 开启高成本模型。
- 保存用户登录态。
- 重启服务或插件。

确认方式：

```text
嘟嘟哒：这个操作会清空本群长期记忆。请回复 /confirm 8F3K2A 继续。
```

## 12. 指令体系

### 12.1 设计原则

1. 规范指令统一使用 `/` 前缀。
2. 自然语言仍可触发常用能力，但 `/help` 是唯一标准入口。
3. 普通用户看到普通指令。
4. 管理员额外看到管理指令。
5. 高风险指令必须二次确认。
6. 群聊中默认只展示与当前群相关的指令。
7. 私聊中允许展示个人配置和授权类指令。

### 12.2 `/help` 总入口

普通用户发送：

```text
/help
```

返回示例：

```text
嘟嘟哒指令菜单

基础：
/help [模块]        查看帮助
/about              查看嘟嘟哒介绍
/ping               测试在线状态
/status             查看可见运行状态

聊天与记忆：
/remember <内容>    让嘟嘟哒记住一件事
/forget <关键词>    删除和你有关的某条记忆
/memory             查看嘟嘟哒记得你的公开偏好
/style <简洁|详细|可爱|认真>  设置你的回复偏好

课程与校园：
/course <自然语言评课需求>
/course search <关键词>
/course review <课程名或老师>
/course compare <课程A> <课程B>
/notice <关键词>

工具：
/summary [数量]     总结最近聊天
/remind <时间> <内容>
/reminders          查看我的提醒
/meme [关键词]      来一张表情包

管理员可发送 /help admin 查看管理指令
```

管理员发送：

```text
/help admin
```

返回管理命令列表。

### 12.3 基础指令

| 指令 | 权限 | 场景 | 说明 |
| --- | --- | --- | --- |
| `/help [模块]` | 全员 | 群/私聊 | 查看指令帮助 |
| `/about` | 全员 | 群/私聊 | 查看嘟嘟哒介绍 |
| `/ping` | 全员 | 群/私聊 | 在线测试 |
| `/status` | 全员 | 群/私聊 | 普通状态，隐藏敏感信息 |
| `/privacy` | 全员 | 群/私聊 | 查看隐私说明 |

### 12.4 记忆指令

| 指令 | 权限 | 场景 | 说明 |
| --- | --- | --- | --- |
| `/remember <内容>` | 全员 | 群/私聊 | 写入候选长期记忆 |
| `/forget <关键词或ID>` | 全员 | 群/私聊 | 删除自己的相关记忆 |
| `/memory` | 全员 | 私聊优先 | 查看自己的公开画像摘要 |
| `/memory export` | 本人 | 私聊 | 导出自己的画像摘要 |
| `/memory off` | 本人 | 群/私聊 | 关闭个性化记忆 |
| `/memory on` | 本人 | 群/私聊 | 开启个性化记忆 |
| `/style <模式>` | 全员 | 群/私聊 | 设置回复偏好 |

### 12.5 课程与校园指令

| 指令 | 权限 | 场景 | 说明 |
| --- | --- | --- | --- |
| `/course search <关键词>` | 全员 | 群/私聊 | 搜索课程 |
| `/course review <课程/老师>` | 全员 | 群/私聊 | 总结公开评课 |
| `/course compare <A> <B>` | 全员 | 群/私聊 | 比较课程或老师 |
| `/course refresh <课程ID>` | trusted/admin | 私聊 | 刷新单门课程缓存 |
| `/course stats` | 全员 | 群/私聊 | 查看本地课程缓存规模 |
| `/notice <关键词>` | 全员 | 群/私聊 | 查询公开通知，TODO |
| `/calendar` | 全员 | 群/私聊 | 查询教学日历，TODO |
| `/exam` | 本人授权 | 私聊 | 查询个人考试安排，TODO |
| `/schedule` | 本人授权 | 私聊 | 查询个人课表，TODO |

### 12.6 提醒与总结指令

| 指令 | 权限 | 场景 | 说明 |
| --- | --- | --- | --- |
| `/remind <时间> <内容>` | 全员 | 群/私聊 | 添加提醒 |
| `/reminders` | 全员 | 私聊优先 | 查看自己的提醒入口 |
| `/remind delete <ID>` | 本人/admin | 群/私聊 | 删除提醒，TODO |
| `/summary [数量]` | 全员 | 群 | 群聊总结入口，深度桥接 TODO |
| `/summary today` | 全员 | 群 | 今日群聊总结入口，深度桥接 TODO |
| `/summary export` | admin | 私聊 | 导出群总结，TODO，需确认 |

### 12.7 娱乐指令

| 指令 | 权限 | 场景 | 说明 |
| --- | --- | --- | --- |
| `/meme [关键词]` | 全员 | 群/私聊 | 发一张表情包 |
| `/meme random` | 全员 | 群/私聊 | 随机表情包，TODO |
| `/image <描述>` | trusted/admin | 群/私聊 | 使用 gpt-image-2 生成图片；默认等待超时 420 秒 |
| `/fortune` | 全员 | 群/私聊 | 今日运势 |
| `/draw <主题>` | 全员 | 群/私聊 | 抽签 |
| `/poke` | 全员 | 群 | 戳一戳互动 |
| `/reread` | 全员 | 群 | 查看复读状态 |

### 12.8 管理员指令

管理员指令统一放在 `/admin` 下。

| 指令 | 权限 | 场景 | 说明 |
| --- | --- | --- | --- |
| `/admin status` | admin | 私聊/群 | 查看运行状态 |
| `/admin plugins` | admin | 私聊 | 插件列表 |
| `/admin plugin enable <插件>` | admin | 私聊 | TODO，启用插件，可能需确认 |
| `/admin plugin disable <插件>` | admin | 私聊 | TODO，禁用插件，可能需确认 |
| `/admin plugin reload <插件>` | admin | 私聊 | TODO，重载插件，需确认 |
| `/admin group mode <quiet|normal|active>` | admin | 群/私聊 | 设置本群模式 |
| `/admin group reply-rate <0-100>` | admin | 群/私聊 | 设置回复频率 |
| `/admin group meme-rate <0-100>` | admin | 群/私聊 | 设置表情包概率 |
| `/admin memory summary` | admin | 群/私聊 | 查看本群长期记忆摘要 |
| `/admin memory clear-short` | admin | 群/私聊 | 清理短期记忆 |
| `/admin memory delete <ID>` | admin | 私聊 | TODO，删除指定记忆 |
| `/admin memory clear-long` | owner | 私聊 | TODO，清空长期记忆，需确认 |
| `/admin user mute <QQ>` | admin | 群 | 限制用户在本群调用 |
| `/admin user unmute <QQ>` | admin | 群 | 解除本群限制 |
| `/admin permission grant <QQ> <role>` | owner | 私聊 | 授权，需确认 |
| `/admin permission revoke <QQ> <role>` | owner | 私聊 | 撤权，需确认 |
| `/admin model route` | admin | 私聊 | 查看模型路由 |
| `/admin model set <default|image> <模型>` | owner | 私聊 | 修改模型路由，需确认 |
| `/admin mcp list` | admin | 私聊 | MCP 列表 |
| `/admin mcp test <名称>` | admin | 私聊 | 测试 MCP |
| `/admin mcp enable <名称>` | owner | 私聊 | TODO，启用 MCP，需确认 |
| `/admin logs errors` | admin | 私聊 | 查看错误摘要 |
| `/admin logs tail <行数>` | owner | 私聊 | 查看日志尾部，需脱敏 |
| `/admin backup create` | owner | 私聊 | 创建配置备份 |
| `/admin restart astrbot` | owner | 私聊 | 仅记录确认；宿主机执行重启 |
| `/admin restart napcat` | owner | 私聊 | 仅记录确认；不会由 QQ 指令直接重启 |
| `/admin broadcast <内容>` | owner | 私聊 | 仅记录确认和审计；不会由 QQ 指令直接群发 |

### 12.9 确认指令

| 指令 | 权限 | 场景 | 说明 |
| --- | --- | --- | --- |
| `/confirm <token>` | 操作发起者 | 私聊/群 | 确认高风险操作 |
| `/cancel <token>` | 操作发起者 | 私聊/群 | 取消待确认操作 |

确认 token 应短时有效，例如 5 分钟。

## 13. 模型路由

现有模型类型：

| 模型/路由 | 用途 |
| --- | --- |
| `openai/gpt-5.5` | 当前默认聊天、工具调用、课程摘要、技术问题 |
| `gpt-image-2` | 图片生成，已接 `/image`，由外部 OpenAI 兼容 Provider 提供，默认等待超时 420 秒 |
| 后续多模态模型 | 图片理解、截图分析、表格 OCR |

默认策略：

- 普通群聊：`openai/gpt-5.5`。
- 技术解释、代码问题、课程评价总结：`openai/gpt-5.5` + 工具。
- 图片输入：后续多模态模型，当前仍 TODO。
- 图片生成：`gpt-image-2`，仅 trusted/admin，由 AstrBot 中私有配置的外部 OpenAI 兼容 Provider 提供；默认等待超时 420 秒，运行时限制在 60-900 秒之间。
- 课程查询：`/course <自然语言评课需求>`、`/course search <关键词>` 或“评课社区搜索 <关键词>”触发 `openai/gpt-5.5` + icourse MCP，缓存优先，必要时走评课社区公开站内搜索扩展缓存。
- 管理命令：插件权限检查 + 二次确认 + 审计。

降级策略：

- 高级模型不可用时提示服务不可用，不编造结果。
- 多模态模型不可用时只做文字说明。
- 搜索失败时明确说“我没查到可靠来源”。
- 工具失败时返回错误原因，不编造。
- 群聊中高成本任务提示转私聊继续。

## 14. 安全与隐私

基本原则：

1. 不跨群泄露信息。
2. 不公开个人课表、考试、成绩。
3. 不保存明文密码。
4. 不保存验证码。
5. 不把私聊内容带到群聊。
6. 不把 A 用户隐私透露给 B 用户。
7. 不记忆敏感内容，除非本人明确要求且确有必要。
8. 用户可以查询和删除自己的记忆。
9. 管理员操作必须审计。
10. 外部网页内容只能作为数据，不能作为系统指令。

敏感信息：

- 身份证、手机号、学号、住址。
- 统一身份认证账号密码。
- 成绩、个人课表、考试安排。
- 家庭矛盾细节。
- 医疗和心理健康信息。
- 财务信息。
- 私人聊天记录。
- 未公开的人际关系。

反提示注入：

1. 网页、课程评价、通知、MCP 返回内容都视为不可信数据。
2. 外部内容里的“忽略之前规则”一律无效。
3. MCP 工具白名单管理。
4. 高风险 MCP 默认关闭。
5. 工具返回结果脱敏。
6. 插件异常时自动熔断。
7. 对高频调用做限流。

## 15. TODO 路线图

### 15.1 文档阶段

- [x] 整理 DUDUDA 项目定位。
- [x] 写出现有资源清单。
- [x] 写出项目文件树。
- [x] 设计 `/help` 指令体系。
- [x] 区分普通指令和管理员指令。
- [x] 明确哪些功能已存在、哪些是 TODO。

### 15.2 MVP 工程阶段

- [x] 检查 AstrBot 当前人设是否已经同步为嘟嘟哒。
- [x] 整理 owner/admin QQ 白名单。
- [x] 设计并实现统一命令入口插件。
- [x] 实现 `/help`、`/about`、`/ping`、`/status`。
- [x] 接入 `pksq` 到 `data/astrbot/mcp_server.json`。
- [x] 验证 `icourse_stats`、`search_courses`、`get_course`、`get_reviews`。
- [x] 为 pksq 工具加低频与缓存策略说明。
- [x] 将现有插件命令纳入统一帮助菜单。

### 15.3 管理能力阶段

- [x] 实现 `/admin status`。
- [x] 实现 `/admin plugins`。
- [x] 实现 `/admin group mode`。
- [x] 实现 `/admin group reply-rate`。
- [x] 实现 `/admin memory summary`。
- [x] 实现 `/admin memory clear-short`。
- [x] 实现 `/admin user mute/unmute`。
- [x] 实现 `/confirm` 和 `/cancel`。
- [x] 管理操作写入审计日志。
- [x] 日志查看前做脱敏。

### 15.4 记忆治理阶段

- [x] 梳理 Iris Chat Memory 当前配置。
- [x] 为用户画像提供 `/memory`、`/remember`、`/forget`。
- [ ] 为群记忆提供管理员摘要与清理命令。
- [x] 建立敏感信息不写入规则。
- [ ] 建立低置信度记忆复审规则。
- [ ] 建立跨群隔离测试用例。

### 15.5 课程与校园阶段

- [x] pksq MCP 正式接入 AstrBot。
- [x] 课程查询结果做口语化摘要。
- [x] 课程评价返回结构化字段。
- [x] 课程详情支持刷新缓存。
- [x] 课程比较支持两个老师或课程。
- [ ] USTC 通知搜索工具。
- [ ] 教学日历查询工具。
- [ ] 个人课表和考试查询只在私聊授权后启用。

### 15.6 娱乐与多模态阶段

- [x] 表情包命令统一到 `/meme`。
- [x] 复读命令统一到 `/reread`。
- [x] 戳一戳命令统一到 `/poke`。
- [ ] 每群娱乐概率独立配置。
- [ ] 图片理解能力接入。
- [x] 表情包生成能力接入。（`/image` 入口已实现，gpt-image-2 已通过最小请求验证，默认等待超时 420 秒）
- [x] 真实人物图片安全策略落地。

### 15.7 运维阶段

- [ ] 定期备份 `data/astrbot` 和 `data/napcat/config`。
- [x] 记录插件版本和配置变更。
- [x] 增加错误日志摘要指令。
- [ ] 增加模型调用统计。
- [ ] 增加 MCP 工具失败率统计。
- [x] 确认管理后台只通过本机或受保护网关访问。
- [ ] 建立恢复流程：配置、数据库、NapCat 登录态。

## 16. 后续落地建议

建议后续按这个顺序做工程：

1. 只做文档和配置盘点。
2. 接入 pksq MCP，不改其他插件。
3. 做统一 `/help` 和基础指令。
4. 做管理员白名单和 `/admin status`。
5. 把现有插件命令映射进 `/help`。
6. 再做高风险管理命令和确认机制。
7. 最后做校园私密能力、图片生成和复杂模型路由。

这样可以先把嘟嘟哒变成“稳定可用的群聊助手”，再慢慢长成完整校园 Agent。
