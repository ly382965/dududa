# 嘟嘟哒 2.0 程序使用说明

本程序实现生活在 QQ 群里的 AI 群友。提交形式为源码部署包，包含上下文感知、Social Engine、Memory、Persona 与模型路由组成的 Python 智能体核心、AstrBot 插件、Vue/Node 控制台、校园 MCP 服务、Docker Compose、依赖锁文件和测试样例。核心包另附可安装的 Python wheel。

解压后进入 `dududa-2.0` 目录。建议先运行离线流程，再配置自己的模型服务与 QQ 账号。

## 1. 环境要求

| 用途 | 环境 |
| --- | --- |
| Python 流程验证 | Python 3.12、uv 0.12.1；首次安装需要下载依赖。 |
| Web 构建 | Node.js 22.18.0、npm 10.9.3。 |
| 完整本地服务 | Linux、Docker Engine、Docker Compose v2。 |
| 真实模型与校园查询 | 可用的 DeepSeek API Key、校园数据源网络连接。二课服务另需部署者的 USTC CAS 凭据。 |
| QQ 群聊 | 部署者自己的 QQ 账号，在 NapCat 完成扫码登录。 |

## 2. 运行 100 题离线流程

在程序根目录执行：

```bash
uv sync --locked --python 3.12.13
uv run --locked python ops/cli/run_dududa_100_message_benchmark.py \
  --json-output /tmp/dududa-100-runtime.json \
  --report-output /tmp/dududa-100-runtime.md
```

该命令运行正式 Runtime 组合，使用本地模型回答样例和校园工具数据，生成逐题答案、调用记录及汇总。无需模型 Key 或 QQ 登录。

本轮执行结果：

| 指标 | 结果 |
| --- | ---: |
| 固定问题 | 100 |
| 完成响应流程 | 94 |
| 按入口规则交由兼容路径处理 | 6 |
| MCP / 校车本地能力调用 | 53 / 11 |
| 脚本模型调用 | 187 |
| 动作、运行结果、工具、输出检查不匹配 | 0 |
| 重复回放违规、未捕获异常 | 0 |

进一步执行相关接口测试：

```bash
uv sync --project services/mcp/unified-worker --locked --python 3.12.13
uv run --locked python -m unittest \
  tests.test_dududa_100_message_benchmark \
  tests.test_apply_deepseek_runtime \
  tests.unit.runtime.test_preview_context \
  tests.contracts.test_production_composition

uv run --locked python -m unittest \
  tests.contracts.test_proactive_talk \
  tests.unit.persona.test_assets \
  tests.unit.persona.test_registry \
  tests.unit.memory.test_retrieval \
  tests.unit.evaluation.test_memory_eval
```

## 3. 构建 Web 控制台

```bash
cd apps/web
npm ci
npm run build
```

构建包含前端、服务端类型检查与产物生成，输出为 `dist/` 和 `dist-server/`。完整服务由下一节的 Compose 启动。

## 4. 启动本地服务

以下步骤用于一个新的解压目录。先返回程序根目录，复制环境模板：

```bash
cp deploy/env/.env.example .env
chmod 600 .env
```

在 `.env` 中将运行目录设置为本次安装的独立路径。Key 池与群策略目录使用程序目录之外的路径，例如：

```dotenv
COMPOSE_PROJECT_NAME=dududa-submission
DUDUDA_API_KEY_STORE_ROOT=../dududa-submission-state/api-keys
DUDUDA_AGENT_POLICY_ROOT=../dududa-submission-state/agent
USTC_CAS_CREDENTIALS_FILE_HOST=../dududa-submission-state/ustc-cas.toml
```

为可选的校园认证挂载准备文件；暂不接入二课时可保持空文件。Key 池与群策略目录由初始化脚本创建，文件目录属主需为容器使用的 UID 1000。

```bash
mkdir -p ../dududa-submission-state
touch ../dududa-submission-state/ustc-cas.toml
chmod 700 ../dududa-submission-state
chmod 600 ../dududa-submission-state/ustc-cas.toml
bash manage.sh up
```

`up` 完成初始化、插件安装、镜像构建、容器启动和人格初始化。首次构建会下载 AstrBot、NapCat、Python/npm 依赖及第三方插件。`USTC_CAS_CREDENTIALS_FILE_HOST` 应指向本次安装的文件，以替换原 Compose 中开发环境的默认挂载路径。

| 界面 | 默认本机地址 | 用途 |
| --- | --- | --- |
| Web 控制台 | `http://127.0.0.1:5173` | 群工作区、Agent 预览、模型与服务配置。 |
| AstrBot | `http://127.0.0.1:6185` | 宿主配置、模型 Provider 与 Dududa Core 插件设置。 |
| NapCat | `http://127.0.0.1:6099` | QQ 扫码登录和连接状态。 |

服务启动后，在 NapCat 登录，并执行 `bash manage.sh web-connect` 接通 Web 工作区。通过 `bash manage.sh ps` 查看容器，通过 `bash manage.sh logs astrbot` 查看宿主启动信息。

## 5. 配置真实智能体

源码模板中的 Runtime 默认关闭。首次安装需要在 AstrBot 配置三个模型端点、Provider 绑定与本机 Provider 验证记录，再启用 Dududa Core。字段包括 `runtime_models_json`、`runtime_provider_evidence_path`、`runtime_enabled` 和 `runtime_health_probe_enabled`。

仓库提供候选配置渲染器 `ops/cli/render_astrbot_candidate.py` 和 Provider 验证工具 `ops/cli/run_astrbot_provider_conformance.py`。现有 Luna/Terra/Sol 示例用于说明配置结构；本次作品的实际模型按下表填写：

| 界面档位 | Provider ID | 模型 ID | 推理强度 |
| --- | --- | --- | --- |
| Luna | `astrbot-luna` | `deepseek-v4-flash` | `low` |
| Terra | `astrbot-terra` | `deepseek-v4-flash` | `high` |
| Sol | `astrbot-sol` | `deepseek-v4-pro` | `max` |

服务地址为 `https://api.deepseek.com`，协议选择 OpenAI 兼容 Chat Completions。三档 Key 池配置完成后，使用 Web 的“应用到 Runtime”更新已有运行配置。首次 Provider 接入和后续配置同步的具体字段见 [候选配置结构](../development/luna-terra-sol-candidate-config.md)与 [Key 池及 Runtime 同步](../development/api-key-pool-runtime-sync.md)。

连接 QQ 后，在群工作区配置目标群服务。群内回复使用 `rollout_mode=canary`、目标群名单、工具开关和投递开关，并将 `rollout_kill_switch` 设为关闭。这些设置与 Web 预览分别管理，配置项可在 AstrBot 的 Dududa Core 插件页面查看。

自动参与需要开启 Core 的 `proactive_talk_enabled`，并在 Web 的目标群中启用“主动加入群聊”，配置大于零的参与概率、冷却和每小时上限。开启后，普通群消息也可进入自动参与流程。

推荐体验问题：

1. “评课社区里《线性代数》的评价怎么样？”
2. “查一下二课最近公开发布的学术活动，最多列 3 项。”
3. “查一下本学期的校历安排。”

在“运行”页查看实际模型、能力调用与耗时，再核对回答和来源。QQ 体验在自己的测试群中明确 @ 机器人。

## 6. 本次测试与录制

本轮通过了 100 条固定消息流程、26 项真实 MCP 原子查询和 5 个真实模型问答。四位模拟成员的 20 条讨论经过正式主动参与流程，触发评课能力从关闭到启用，并返回带评课链接的选课建议。Emoji 合成、Arc 曲目与谱面已生成可展示素材；复读与统计处理器通过固定样例验证。

代码检查覆盖 Runtime、自动参与、人格、记忆、Web 和相关插件；Web 类型检查与构建通过。固定问题、操作顺序和结果见 [录制操作单](recording-runbook.md)，可直接朗读的旁白见 [五分钟稿](demo-video-runtime-validation-2026-09-05.md)。录制工作台使用模拟群成员，实际调用模型和 MCP。

程序包包含源码、核心 wheel、Web 构建产物与部署文件。部署者配置自己的模型账号、校园认证和 QQ 登录后即可连接自己的测试群。
