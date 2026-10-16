<div align="center">

# 嘟嘟哒 · Dududa 3.0

**生活在 QQ 群里的 AI 群友**

规则服务直接执行，复杂任务交给本机 Codex。

[简体中文](README.md) · [English](README.en.md) · [2.0 完整归档](legacy/2.0/README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-80b8a5)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-7ba9d6)](pyproject.toml)
[![Vue 3](https://img.shields.io/badge/Vue-3-8bc6b3)](apps/web/package.json)

[3.0 的变化](#30-的变化) · [功能与迁移状态](#功能与迁移状态) · [技术架构](#技术架构) · [快速开始](#快速开始) · [开发与验证](#开发与验证) · [2.0 封存](#20-封存与仓库布局)

</div>

## 群里，来了一个 AI 群友

嘟嘟哒是一个生活在 QQ 群里的 AI 群友。我们希望她像群里一个什么都会一点的人：能接住闲聊，能认真讨论问题，知道什么时候出现，也懂得什么时候闭嘴。聊到选课、活动、考试和出行时，她能调用相应服务，把事情说清楚。

项目探索的是 **AI 如何持续参与一个群体的日常生活**。科大校园是嘟嘟哒开始生活的地方；你也可以接入自己的服务，塑造适合不同群体的角色。

3.0 将 Agent 的理解、规划和多步工具循环交给本机 Codex CLI。Dududa 自己管理消息入口、规则服务、会话、权限和输出。**明确的规则命令不调用 LLM，整个规则执行过程也不需要 Codex 参与。**

当前默认服务模型固定为 **GPT‑5.6 Luna / MAX**（`gpt-5.6-luna`、`reasoning_effort=max`）。新建会话、恢复会话和每一轮请求都显式指定；聊天消息不能切换模型。运行记录和 Web 显示实际模型与推理强度。

本仓库包含可独立启动的 3.0 Runtime，以及完整封存的 2.0 源码。3.0 的运行入口、测试和下文安装步骤均围绕新 Runtime；已有服务保留情况和当前迁移边界在下表说明。代码接入不代表已有线上机器人已经切换版本。

## 3.0 的变化

| 方面 | 2.0 | 3.0 |
| --- | --- | --- |
| Agent 执行 | 自研感知、模型路由、单步能力计划、回答组织 | 本机 `codex app-server` 负责完整 Agent 循环 |
| 确定性服务 | 由对应插件或旧 Runtime 处理 | Host 先做规则匹配，直接执行业务并回复 |
| QQ / Web | 与 AstrBot 运行链集成 | 通过同一个 3.0 Host 接口调用新 Runtime |
| 校园业务 | AstrBot 适配器、原子能力、MCP | 复用业务实现，由规则或 MCP 两种入口调用 |
| 会话 | 由旧 Runtime 组织上下文 | Host 保存会话映射，Codex thread 保留执行历史 |
| 模型配置 | AstrBot Provider 与 Luna / Terra / Sol 三档 | 使用本机 Codex 的登录及模型配置 |
| 新版验收 | 历史脚本模型与 2.0 测试 | `tests/v3` 与实际本机 CLI 的 3.0 运行验证 |
| 历史版本 | 原仓库根目录 | `legacy/2.0/` 与独立 Git 封存引用 |

## 功能与迁移状态

### 像群友一样接话

3.0 的 Web 预览和 QQ 适配器调用同一个 Runtime。消息来源、会话与近期上下文由宿主提供；需要 Agent 的消息才进入 Codex。会话连续追问复用对应的 Codex thread。

2.0 已有近期群聊、引用与指代处理、按群自动搭话、参与概率、冷却、频率与上下文窗口设置；还支持管理员授权后按话题自适应启用查询能力。**这些 Social Engine 策略及旧控制台配置保存在 2.0 中，不能把旧页面上的配置等同于 3.0 已生效的策略。** 3.0 当前 QQ 接入使用明确触发和白名单范围；Host 另外支持显式配置主动参与范围及冷却时间，旧的参与概率和自适应插件启用逻辑等待迁移。

### 规则服务不经过 LLM

Host 在 Agent 路径之前匹配明确命令。规则处理器负责解析参数、调用业务服务和生成确定性回复；普通聊天与需要推理的请求交给 Codex。

同一个业务服务可以由规则处理器直接调用，也可以被包装成 MCP 工具。服务实现与调用方式分开，避免维护两份查询逻辑。规则失败直接返回服务结果，不会切换到旧 Runtime。

| 命令 | 行为 |
| --- | --- |
| `/help`、`/帮助` | 查看当前规则帮助 |
| `/ping` | 返回 3.0 连通性与零 LLM 调用标记 |
| `/status` | 查看 Runtime 版本、本机 Codex 可用性和活动任务数 |
| `/校车 查询条件`、`/shuttle 查询条件` | 直接读取版本化校车时刻表 |
| `/remember 内容`、`/记住 内容` | 显式保存当前会话记忆；Web 预览不写入 |
| `/memory 关键词`、`/记忆 关键词` | 搜索当前会话记忆，省略关键词时列出最近记录 |
| `/forget 编号`、`/忘记 编号` | 删除本人在当前会话写入的记忆；Web 预览不删除 |
| `/cancel` | 取消当前会话正在执行或排队的任务 |
| `/new` | 取消当前会话任务并开启新的 Codex 对话，保留显式记忆 |

还可通过配置中的 `rules` 添加精确文本匹配与固定回复。以上规则均由 3.0 Host 执行，即使未安装或登录 Codex，也可独立使用不依赖模型的服务。

### 做最懂科大的 AI 群友

2.0 已积累的校园服务全部保留，公共业务组件继续放在 `services/mcp/`。以下是已有能力目录，**不是“3.0 已逐项完成真实环境验收”的清单**；每项是否可用仍取决于新 Runtime 的工具暴露、对应服务和部署端凭据。

| 能力 | 已有业务范围 | 资料与实现 |
| --- | --- | --- |
| 评课社区 | 找课程、教师和评论；区分同名课程；查看评价与统计 | [iCourse MCP](services/mcp/icourse/README.md) |
| 第二课堂 | 搜索活动、查看详情；按类别、时间和数量筛选 | [科大校园 MCP](services/mcp/ustc-campus/README.md) |
| 教务信息 | 学期、全校开课、考试、教学日历 | [科大校园 MCP](services/mcp/ustc-campus/README.md) |
| 培养方案 | 年级、专业方案资料；比较课程与方案变化 | [培养方案 MCP](services/mcp/training-plan/README.md) |
| 校园通知 | 通知搜索、详情、日历与截止日期 | [NotifAI MCP](services/mcp/notifai/README.md) |
| 校车出行 | 按校区、路线、日期与时间查询常规班次；3.0 已同时接入规则和 MCP | [共享校车服务](services/builtin/shuttle/service.py) · [资料版本说明](legacy/2.0/apps/astrbot-plugins/astrbot_plugin_ustc_shuttle/README.md) |

培养方案和校车资料保留版本信息；校车静态时刻表需要随学校公告更新。需要认证的校园服务仍由部署端管理 USTC CAS 凭据；当前 3.0 校园工具仅开放显式启用的公开能力，不开放私人 CAS 数据。课程比较等多步需求可以由 Codex 连续调用获准工具，工具返回资料来源后再组织回答。

3.0 原生 MCP 当前提供六个工具：

| 工具 | 作用 |
| --- | --- |
| `shuttle_query` | 查询本地校车资料，无需网络 |
| `memory_search` | 搜索当前会话显式保存的记忆 |
| `context_recent` | 读取当前会话近期聊天记录 |
| `conversation_history` | 按当前 QQ 会话分页读取历史，最多 1000 条，返回实际数量和完整时间范围 |
| `services_list` | 列出本地工具和允许调用的公开校园能力及参数 |
| `campus_query` | 通过 MCP Console 调用白名单内的公开校园查询 |

校园查询需要同时配置 `mcp_console_url` 和 `campus_capabilities`；Host 还会核对能力目录中的 `privacy=public`、当前会话类型和可用状态。默认不连接 Console、不启用外部校园能力。本地校车、上下文和记忆查询可以先独立运行。模型不能通过工具参数修改账号、用户或会话身份。

仓库还保留 [图书馆](services/mcp/library/README.md)、[校园活动](services/mcp/campus-events/README.md)、[学院通知](services/mcp/college-notice/README.md)和[附近推荐](services/mcp/local-recs/README.md)等服务，后续可按相同方式接入。

### 私聊学术报告与作业：完整封存，尚未迁移至 3.0

以下功能保存在 [2.0 私聊通知插件](legacy/2.0/apps/astrbot-plugins/astrbot_plugin_dududa_notify/README.md)，供历史部署继续使用和后续迁移参考。启动 3.0 Host 不会自动启用这些通知或提交任务。

- **学术报告通知**：对接 SeminarRadar，默认每 3 分钟查询科大研究生学术报告，将 B 站或高新校区可报名场次推送给指定 QQ；首次发送订阅确认，后续按报告去重，认证复用部署端凭据，查询依赖运行在独立环境中。
- **研究生作业通知与草稿**：默认每 3 分钟读取“培养 > 我的作业”，冷启动列出未完成作业，新作业生成 PDF 草稿，小测采用简答风格；本人私聊补充评论或要求改稿后生成新版。
- **作业提交**：旧版支持确认指定版本后提交，或明确开启截止前 3 分钟自动提交；提交后核对学校记录，避免覆盖已交答案、强行提交过期作业或重复上传结果不确定的文件。这些提交权限不会随 3.0 启动继承。
- **全课程监控**：监控算法、高级计算机网络课程主页及指定 BB 课程的作业、实验与课件，默认每 3 分钟检查，在明确 DDL 前 24 / 6 / 1 小时提醒；每日北京时间 20:00 用列表和 PNG 汇总新增、更新课件。组合数学仍有待补充项；新课程只通知，不继承自动提交权限。
- **助教空周汇报**：可独立开启，按学校列出的首个汇报日北京时间 20:00 执行，不填写正文、不上传附件；提交后核对记录并私聊通知，已有提交或结果不明时不重复操作。

### 有性格，也有玩心

`configs/personas/` 保留 Dududa 人格描述和多 Persona 资产。技术问题认真说清楚，日常交流跟随群里的语气，是 3.0 提供给 Codex 的表达方向。

2.0 的 Emoji Kitchen 表情合成、复读与互动插件保存在 `legacy/2.0/apps/astrbot-plugins/`。Memory v2 已有中文 BM25、会话检索、记忆写入和生命周期模块，源码保存在 `legacy/2.0/packages/dududa-agent/`。3.0 已提供会话隔离的轻量显式记忆：用户通过规则命令写入和删除，Codex 只通过 MCP 查询。**Codex 的 thread 历史不等同于长期群记忆；完整 Memory v2 接入、多 OC 切换、群友印象和互动插件仍需分别迁移。**

### 看得见，也调得动

Web 控制台保留群聊、Agent 对话、运行记录、配置和 MCP 工作台。3.0 复用 Agent 预览入口并返回 Runtime 版本标记，QQ 适配器也调用相同 Host。

原有三档模型 Key 池、旧 Persona / 群参与配置及 AstrBot 插件管理属于 2.0 功能，它们不会修改本机 Codex 的配置。当前预览返回完整结果；专门的 3.0 流式进度与取消按钮尚未接入。客户端超时会请求取消对应的 Runtime 任务。

## 技术架构

下图采用 **4:3 画布，左侧输入、右侧输出**。上方规则路径不经过 Codex，下方 Agent 路径交给本机 CLI；业务服务由两条路径共享。

<p align="center">
  <img src="docs/assets/dududa-3.0-architecture.svg" alt="Dududa 3.0 架构图：左侧 QQ、Web 和事件输入，中央 Host 分流规则与 Codex Agent，右侧统一投递输出；共享业务服务位于底部" width="960">
</p>

| 层 | 职责 |
| --- | --- |
| QQ / Web 适配器 | 接收平台消息，补充可信身份、会话与上下文，投递结果 |
| Dududa Host | 规则分流、会话映射、任务管理、权限范围及执行结果 |
| 规则处理器 | 明确命令和参数匹配、业务调用、模板回复，不调用 LLM |
| 本机 Codex App Server | 理解需求、多步规划、工具调用、线程历史及最终回答 |
| 业务 MCP | 暴露获准的业务能力，使用服务端绑定的访问范围 |
| 共享业务服务 | 校园查询、已有插件与其他业务实现，不依赖某一种聊天入口 |
| SQLite | 保存 3.0 会话和任务数据，与 2.0 运行数据分开 |

Codex 由 Python 子进程直接启动，通过 stdio JSON-RPC 通信。程序调用本机可执行文件，继承其登录和配置，不从 QQ 消息拼接 shell 命令，不把 Codex 当作一次性的文本生成函数。Agent 的中间工具结果留在执行循环中，最终答复才进入投递路径。同一会话串行执行，不同会话受并发数限制；Web 预览与真实 QQ 会话使用独立的线程和状态。

Host 为 Codex 关闭 Shell、个人 MCP、App、插件等通用入口，只注入绑定当前会话的 Dududa MCP，使用只读沙箱与不自动批准的策略。业务查询由 MCP 服务自身检查范围。QQ 发送由平台适配器完成，先取得投递权，再记录结果；发送结果不明确时不会自动重发。

架构图中的定时事件标为预留入口；外部校园服务按配置启用。已有 2.0 调度器尚未迁移，不能通过启动 3.0 自动获得旧通知任务。实现边界见 [3.0 Runtime 设计](docs/design/dududa-3.0-runtime.md)。

## 快速开始

### 1. 准备本机环境

以下命令面向 Linux / WSL。准备 Python 3.12、[uv](https://github.com/astral-sh/uv)，以及已经可以正常运行和登录的本机 Codex CLI。Web 需要 Node.js 22.18.0 或兼容版本，具体范围见 [package.json](apps/web/package.json)。

```bash
git clone https://github.com/ly382965/dududa.git
cd dududa
uv sync --locked --python 3.12
codex --version
codex login status
```

3.0 使用本机 Codex 的认证，模型与推理强度由 Runtime 配置固定。原来的 AstrBot Provider、DeepSeek Chat Completions 端点和 Luna / Terra / Sol 档位不参与新执行链；管理员需要调整模型时，应修改 Runtime 的 `model`、`reasoning_effort`，而非旧 Web 模型池。

### 2. 运行 3.0 Runtime

```bash
uv run --locked dududa-v3 --config configs/runtime-v3.example.json check
uv run --locked dududa-v3 chat '/ping'
uv run --locked dududa-v3 chat '/校车 工作日东区到西区'
uv run --locked dududa-v3 chat '你好，介绍一下你自己。'
```

规则命令与 Agent 问答由同一个入口分流。Agent 问答需要可用的本机 Codex 登录与模型服务，会产生对应账号的真实调用；规则服务不会产生模型调用。

配置示例见 [`configs/runtime-v3.example.json`](configs/runtime-v3.example.json)。`--config` 放在子命令前；省略时使用内置默认值，不会自动读取示例文件。HTTP Host 默认使用 `127.0.0.1:8783`，首次启动自动生成 `runtime/v3/token`，终端只显示文件路径，不输出令牌内容。

```bash
uv run --locked dududa-v3 --config configs/runtime-v3.example.json serve
```

Host 通过 Bearer token 认证适配器；Web 直接读取同一个令牌文件即可。也可显式设置 `DUDUDA_V3_TOKEN` 覆盖自动文件模式。完整配置与 HTTP 示例见 [3.0 启动说明](docs/operations/v3.md)。

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

打开 <http://127.0.0.1:5173>，在 Agent 预览中发起请求。Web 默认选择版本 `3`；新 Runtime 不可达时直接报错，不会回退到 2.0 来产生看似正常的结果。

| 配置 | 默认值 / 用途 |
| --- | --- |
| `DUDUDA_RUNTIME_VERSION` | `3`；显式 `2` 仅用于历史兼容，不用于 3.0 验收 |
| `DUDUDA_V3_URL` | `http://127.0.0.1:8783`；Web 后端连接的 Host 地址 |
| `DUDUDA_V3_TOKEN` | 可选；Host 与 Web 后端显式共享的访问令牌，优先于文件 |
| `DUDUDA_V3_TOKEN_FILE` | Web 后端读取令牌的路径；从 `apps/web` 启动时默认读取仓库的 `runtime/v3/token` |
| `DUDUDA_V3_QQ_SCOPES` | 默认空；允许新 Runtime 处理的 QQ 会话白名单 |

### 4. 接入 QQ 测试群

保留的 OneBotHub 负责连接 LLOneBot / NapCat、接收消息与发送回复。QQ 连接的历史操作可参考 [2.0 LLOneBot 迁移说明](legacy/2.0/docs/operations/llonebot-migration.md)，但 3.0 的 Agent 执行入口改为本节启动的 Host。

先在 Web 工作区连接 QQ 账号，再用账号与会话的真实 ID 设置白名单。格式为 `accountId/conversationId`，多个范围以逗号分隔，例如：

```bash
export DUDUDA_V3_QQ_SCOPES='qq-100001/qq-100001:group:200001'
```

Host 和 Web 后端都要获得相同的 `DUDUDA_V3_QQ_SCOPES`：在两个启动终端分别设置后重启两者；也可在 Host JSON 中填写同一范围的 `allowed_scopes`。空白名单不会自动处理或发送 QQ 回复。请确保测试群只有一个版本负责同一触发消息，避免旧 AstrBot 插件和 3.0 同时回复。

`legacy/2.0/manage.sh` 和旧 Docker Compose 属于封存环境；它们不是 3.0 启动入口。3.0 的本地调试先使用上述 Host 与 Web 两个进程。

## 开发与验证

**3.0 的测试必须通过 3.0 Runtime。** 旧的 100 条脚本模型基准、26 项 MCP 查询和历史真实模型问答只说明 2.0 当时的行为，不作为 3.0 验收证据。

```bash
uv sync --locked --python 3.12
uv run --locked python -m unittest discover -s tests/v3 -v
uv run --locked python ops/cli/verify_dududa_v3.py --output runtime/v3/verification.json
```

两种验证的用途不同：

| 验证 | 覆盖范围 | 需要真实模型 |
| --- | --- | --- |
| `tests/v3` | 3.0 Host 的规则分流、会话和执行行为；App Server 协议、错误、取消等边界 | 协议单元测试使用明确标识的测试进程，不冒充真实模型 |
| `verify_dududa_v3.py` | 从新 Runtime 入口调用本机 Codex CLI，验证真实 Agent 执行 | 是；使用本机已配置的认证 |
| Web 测试与构建 | 适配器路由、版本标记、QQ 范围及 UI / 服务端构建 | 不依赖真实模型；真实链路另由上项验证 |

Web 检查：

```bash
cd apps/web
npm test
npm run build
```

本次已通过真实本机 Codex 验证：同一次 Agent 运行调用记忆和校车两个 MCP 工具，并在进程重建后恢复同一 thread。详细环境、耗时、自动化检查及未测范围见 [2026-10-15 验证记录](docs/operations/v3-validation-2026-10-15.md)。

没有可用的 Codex 登录或模型服务时，真实链路验证应明确失败或说明缺少环境，不能改用 2.0、脚本模型或固定答案后宣称 3.0 通过。本次未发送真实 QQ 消息，也未部署生产环境。

## 2.0 封存与仓库布局

2.0 的完整源码已保存在 [`legacy/2.0/`](legacy/2.0/)，并固定到 Git 提交 `f84c04dbefcb92735feaded4ab9f31281870b30f`：

- Tag：`archive/dududa-2.0-20261015`
- 封存分支：`archive/2.0-frozen-20261015`
- 完整范围、恢复方式和源码包位置：[2.0 封存记录](docs/archive/2.0/ARCHIVE.md)

源码副本保持原始内容和目录结构；旧的中文、英文 README、测试、插件、启动脚本、部署文件及作品材料都可以在其中找到。Git 未追踪的本机凭据和运行数据不进入源码归档。

```text
README.md                         3.0 使用与开发入口
packages/dududa-runtime/           3.0 Host 与本机 Codex 传输
apps/web/                         共享 Web 控制台、OneBotHub、3.0 适配器
services/mcp/                     继续复用的校园 MCP 与 Console
services/builtin/shuttle/         独立提取的本地校车业务与资料
configs/                          3.0 示例及共享业务、人格配置
tests/v3/                         3.0 Runtime 的独立测试
ops/cli/verify_dududa_v3.py         真实本机 Codex 验证入口
docs/                             3.0 文档、架构图、归档索引
legacy/2.0/                       完整冻结的 2.0 源码与文档
```

旧 AstrBot 主执行链、`dududa-agent`、旧脚本、旧测试和部署入口已收进 `legacy/2.0/`。根 Python workspace 只安装 `dududa-runtime` 与开发检查工具，不安装旧 `dududa-agent`。校车已独立提取为共享业务服务；MCP Console 和其他历史校园服务仍需各自的运行环境及依赖，根目录的 `uv sync` 不会启动它们。旧配置文件保留用于业务兼容，也不表示所有旧控制台配置都已接入 3.0。

## 开发路线

- [x] 完整封存 2.0 源码、README、测试与部署材料
- [x] 建立独立的 3.0 Runtime 和测试目录
- [x] 通过本机 Codex App Server 接管 Agent 执行
- [x] 规则服务与 Agent 服务双路径
- [x] 本地校车、会话上下文与显式记忆的原生 MCP 接入
- [x] Web 与 QQ 适配器连接 3.0 Host
- [ ] 逐项迁移校园能力并完成真实服务验证
- [ ] 迁移按群参与、冷却、频率与自适应启用策略
- [ ] 完整长期记忆、群友印象与共同经历
- [ ] 多 OC、互动插件与表情风格
- [ ] 迁移通知、日报及需要独立授权的提交服务
- [ ] 3.0 任务进度、流式展示与取消交互

## 文档与历史作品材料

| 想了解什么 | 从这里开始 |
| --- | --- |
| 3.0 的运行和验证 | [启动说明](docs/operations/v3.md) · [Runtime 配置示例](configs/runtime-v3.example.json) |
| 3.0 代码边界与接口 | [Runtime 设计](docs/design/dududa-3.0-runtime.md) |
| 3.0 本次实际测试证据 | [2026-10-15 验证记录](docs/operations/v3-validation-2026-10-15.md) |
| 2.0 完整功能与原版说明 | [2.0 中文 README](legacy/2.0/README.md) · [英文 README](legacy/2.0/README.en.md) |
| 版本封存与恢复 | [封存记录](docs/archive/2.0/ARCHIVE.md) |
| 2.0 作品定位与技术设计 | [作品简介](legacy/2.0/docs/design/dududa-2.0-work-introduction.md) · [设计文档](legacy/2.0/docs/design/dududa-2.0-design-report.md) |
| 2.0 部署与演示 | [程序使用说明](legacy/2.0/docs/operations/submission-program.md) · [录制操作单](legacy/2.0/docs/operations/recording-runbook.md) |
| 已有业务接口设计 | [新增 Capability](legacy/2.0/docs/development/adding-a-capability.md) · [新增 MCP Server](legacy/2.0/docs/development/adding-an-mcp-server.md) |
| 人格与记忆设计 | [Persona](legacy/2.0/docs/design/persona.md) · [Memory](legacy/2.0/docs/design/memory.md) |
| 原版宣传海报 | [嘟嘟哒宣传海报](legacy/2.0/docs/assets/dududa-poster.png) |

历史材料保留其原有版本背景；其中的启动步骤、模型配置和测试结论不会自动适用于 3.0。

## 参与贡献

欢迎接入校园服务、补充真实使用场景、改善回答、设计角色或修复问题。

- 在 [Issues](https://github.com/ly382965/dududa/issues) 中描述场景、复现步骤和预期结果，并注明 Runtime 版本。
- 3.0 改动在新源码和 `tests/v3` 中完成验证；修改 Web 适配器后运行相关测试与构建。
- 新业务优先提供独立的输入、输出和使用示例，再选择规则入口、MCP 入口或两者同时接入。
- 保持 `legacy/2.0/` 与封存引用不变；需要维护旧版时从封存提交建立新分支。

请使用合成或脱敏的群聊样例，模型 Key、校园凭据和 QQ 登录数据留在部署端。历史贡献规范和安全联系说明保存在 [CONTRIBUTING](legacy/2.0/CONTRIBUTING.md) 与 [SECURITY](legacy/2.0/SECURITY.md)。

## 致谢与许可证

感谢 [OpenAI Codex](https://github.com/openai/codex)、[AstrBot](https://github.com/AstrBotDevs/AstrBot)、[NapCat](https://github.com/NapNeko/NapCat-Docker)、[pyustc](https://github.com/USTC-XeF2/pyustc) 及相关校园数据和开源项目。

嘟嘟哒原创代码和文档采用 [MIT License](LICENSE)。第三方组件保留各自许可证，历史引入说明见 [Third-Party Notices](legacy/2.0/THIRD_PARTY_NOTICES.md)。
