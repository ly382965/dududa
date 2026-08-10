# 仓库布局设计

## 1. 状态与范围

- 状态：S17 三批路径迁移、旧 marker 兼容和代表性验证均已完成，并已通过 protected
  completion 合入控制分支
- 基线提交：`2767cc9768d4bce63d4b4ee811add951ebce6870`
- 适用范围：嘟嘟哒 Bot Runtime Monorepo
- S17 不执行：业务行为重写、运行数据迁移、Manifest v2 无证据切换和兼容面删除

下面的目录现在是主仓权威布局。旧路径仅为一 Release 兼容链接，由 S22 基于消费者和上一
Release 恢复证据删除。S17 保持容器内路径、插件 ID、包名、MCP Server ID 和根操作入口不变。

本仓库继续作为完整的 Bot Runtime Monorepo，统一管理 AstrBot、NapCat、嘟嘟哒 Agent、AstrBot 适配插件、MCP Server、第三方插件、部署工具、测试和文档。模型网关、反向代理、通用数据库、主站服务和宿主机基础设施不进入本仓库。

## 2. 布局目标

目标布局需要同时满足以下要求：

1. Agent 核心可以脱离 AstrBot 导入和单元测试。
2. AstrBot 插件保持其真实加载契约，不因目录整理而失效。
3. 运行编排、业务代码、配置模板、第三方代码和私有运行数据有明确边界。
4. 根级兼容入口在迁移期间持续可用。
5. 每次路径切换可以独立 Review、验证和回滚。

依赖方向固定为：

```text
apps/adapters
    -> packages/dududa-agent runtime/application
        -> packages/dududa-agent domain/interfaces
            <- infrastructure implementations injected at composition time
```

`packages/dududa-agent` 不得 import AstrBot Event、NapCat、OneBot、Compose、具体 MCP Server 或模型供应商 SDK。`services/mcp/*` 只实现外部能力，不反向依赖 Agent Runtime。

## 3. 已验证的现状约束

### 3.1 AstrBot 插件加载

当前三套自研插件分别挂载为：

```text
/AstrBot/data/plugins/astrbot_plugin_dududa_core
/AstrBot/data/plugins/astrbot_plugin_reply_polish
/AstrBot/data/plugins/astrbot_plugin_target_talk
```

每个目录是独立加载单元，插件名、`main.py`、`metadata.yaml`、`_conf_schema.json` 和 `@register` 标识共同构成运行契约。Core 还使用包内相对 import。容器内插件目录名和深度不能在未迁移路径推导逻辑前改变。

Core 当前通过 `Path(__file__).resolve().parents[2]` 推导 `/AstrBot/data`。Target Talk 直接 import AstrBot 的 aiocqhttp 内部实现。二者都要求先建立兼容测试，再修改加载结构。

### 3.2 Python 包可见性

当前容器只将各插件目录单独挂载到 AstrBot 插件目录。未来放在 `packages/dududa-agent` 的代码不会因此自动进入 `sys.path`。AstrBot 派生镜像必须安装该 package，插件才能稳定执行 `import dududa`。不得依赖开发机当前目录或隐式 `PYTHONPATH`。

### 3.3 构建与运行路径

当前 Compose、Dockerfile、管理脚本、CI 和 Dependabot 都引用根级固定路径。`compose.yml` 的构建上下文是仓库根，Dockerfile 从根上下文复制 iCourse 服务。`manage.sh` 也假设自身位于仓库根。

因此目标目录不能一次性启用。每次移动必须同时更新消费者，并在切换前加入路径契约测试。

### 3.4 私有运行数据

`data/`、`.env`、数据库、记忆、附件、审计日志、QQ 登录态和 Provider 凭据不是源码布局的一部分。它们必须继续位于 Git 之外。配置模板属于 `configs/`，运行配置属于 `STACK_DATA_ROOT`，二者不得混用。

## 4. 目标目录

目标结构采用 `apps/astrbot-plugins` 复数目录，而不是把三套加载单元立即合并成一个插件：

```text
dududa/
├── .github/
│   ├── workflows/
│   ├── dependabot.yml
│   └── CODEOWNERS
├── apps/
│   └── astrbot-plugins/
│       ├── astrbot_plugin_dududa_core/
│       │   ├── main.py
│       │   ├── adapters/
│       │   ├── commands/
│       │   ├── metadata.yaml
│       │   ├── _conf_schema.json
│       │   └── README.md
│       ├── astrbot_plugin_reply_polish/
│       └── astrbot_plugin_target_talk/
├── packages/
│   └── dududa-agent/
│       ├── pyproject.toml
│       └── src/dududa/
│           ├── domain/
│           ├── runtime/
│           ├── memory/
│           ├── capabilities/
│           ├── models/
│           ├── responses/
│           ├── persona/
│           ├── proactive/
│           ├── security/
│           ├── config/
│           └── infrastructure/
├── services/
│   └── mcp/
│       ├── icourse/
│       └── README.md
├── configs/
│   ├── personas/
│   ├── models/
│   ├── capabilities/
│   ├── proactive/
│   ├── sources/
│   ├── policies/
│   └── mcp/
├── deploy/
│   ├── compose/compose.yml
│   ├── docker/astrbot/Dockerfile
│   └── env/.env.example
├── ops/
│   ├── manage.sh
│   ├── cli/
│   ├── migrations/
│   └── README.md
├── third_party/
│   ├── plugins.lock.json
│   ├── patches/
│   ├── vendor/
│   └── README.md
├── tests/
│   ├── unit/
│   ├── contracts/
│   ├── integration/
│   ├── evals/
│   ├── fixtures/
│   └── smoke/
├── docs/
│   ├── architecture/
│   ├── design/
│   ├── operations/
│   ├── development/
│   ├── refactor/
│   ├── adr/
│   └── roadmap/
├── manage.sh
└── compose.yml
```

根级 `manage.sh` 和 `compose.yml` 是稳定操作入口。S22 按 ADR 0007 删除根级
`.env.example` 和其余路径别名；唯一可提交环境模板是
`deploy/env/.env.example`。

## 5. 目录职责

| 目录 | 拥有内容 | 不应拥有 |
| --- | --- | --- |
| `apps/astrbot-plugins` | Event 转换、命令注册、AstrBot 生命周期、回复适配 | Agent 决策、Memory Scope、MCP 路由主体 |
| `packages/dududa-agent` | Domain、Runtime、接口、策略和可测试核心 | AstrBot 类型、Compose 路径、具体 Provider SDK |
| `services/mcp` | 原子化外部能力和自己的存储实现 | 群聊决策、Persona、上层权限判断 |
| `packages/dududa-agent/src/dududa/responses` | AnswerProfile、ResponsePlan Policy 与最终 Profile Validator | Provider 选择、Persona 文案或平台分片实现 |
| `packages/dududa-agent/src/dududa/proactive` | Trigger、Subscription、Scheduler/Dispatch Protocol、主动 Policy 与 Orchestrator | 具体 MCP SDK、AstrBot Event、平台发送实现或私人来源 |
| `configs` | 可提交、无密钥、带 schema 的模板 | 运行时覆盖、真实 ID、Token、Cookie |
| `deploy` | 镜像与 Compose 声明 | 复杂迁移逻辑、运行数据 |
| `ops` | 幂等编排 CLI、迁移、备份和恢复工具 | Agent 业务规则 |
| `third_party` | 唯一 v1 lock、patch、必要 vendor；未来 v2 需另过供应链门禁 | 自研插件、运行时安装结果、无证据的许可证/hash |
| `tests` | 分层测试、fixture、eval 和 smoke | 真实聊天、真实账号、生产数据库 |

## 6. 当前路径到目标路径

| 当前路径 | 目标路径 | 迁移约束 |
| --- | --- | --- |
| `plugins/astrbot_plugin_dududa_core` | `apps/astrbot-plugins/astrbot_plugin_dududa_core` | 容器目标、插件名和配置名不变；先安装核心 package |
| `plugins/astrbot_plugin_reply_polish` | `apps/astrbot-plugins/astrbot_plugin_reply_polish` | 先保留独立 output hook，不立即并入 Core |
| `plugins/astrbot_plugin_target_talk` | `apps/astrbot-plugins/astrbot_plugin_target_talk` | 先保留独立 Event filter 和配置 schema |
| `services/icourse-mcp` | `services/mcp/icourse` | 同步更新镜像 COPY、MCP 命令、CI、Dependabot 和文档 |
| `config` | `configs` | 运行数据路径不变；迁移 sync/seed 的模板路径 |
| `docker` | `deploy/docker` | 构建上下文保持仓库根，避免 COPY 失效 |
| `compose.yml` | `deploy/compose/compose.yml` | 根文件保留为稳定转发入口 |
| `scripts` | `ops/cli` | 根 `manage.sh` 转发；Python CLI 承担复杂逻辑 |
| `plugins.lock.json`、`patches`、`vendor` | `third_party` | 已移动现有 v1 authority；Manifest v2 因 hash/lock/license 证据不足延期 |
| `docs/DUDUDA.md`、`docs/ROADMAP.md` | 分主题文档 | 先建立内容映射，后合并，禁止直接删除 |

## 7. 兼容入口

迁移期间必须维持：

- `./manage.sh init|plugins|sync|seed|up|down|restart|logs|ps|pull|upgrade|config`
- `docker compose --env-file deploy/env/.env.example -f compose.yml ...`
- 三个现有 AstrBot 插件名、配置文件名和运行数据目录
- `STACK_DATA_ROOT` 的相对路径仍以仓库根解析
- 现有 MCP Server 名 `icourse` 和数据库路径

新的阶段化命令为 `bootstrap`、`prepare`、`build`、`start`、`seed`、`health`、`upgrade`、`backup` 和 `restore`。旧命令先转发到新 CLI；在文档、遥测和生产验证证明无旧调用后，才讨论弃用。

## 8. 路径变更验收

每次路径 PR 至少验证：

1. 根兼容入口仍可解析配置。
2. 派生镜像可构建并已安装 `dududa-agent` 与 iCourse 依赖。
3. 三套插件可由真实 AstrBot loader import 和注册。
4. 插件数据仍写入 `/AstrBot/data/plugin_data/<plugin-name>`，源码挂载保持只读。
5. MCP 握手和 `icourse_stats` 成功，数据库仍位于私有数据目录。
6. 第三方插件可从空运行目录安装，patch 实际应用成功。
7. `.env`、数据库、QQ 登录态和真实用户数据不进入 Git 或构建上下文。
8. 回滚到上一个 Git 提交后，旧路径和旧数据仍可启动。

## 9. 实施顺序

1. Phase 1 只落设计、ADR、迁移映射和基线证据。
2. Phase 2 创建可安装的 `dududa-agent`，但不切换生产插件。
3. Phase 3 抽离安全和配置逻辑，保留旧 import 兼容层。
4. Phase 4 在三个现有插件根内逐步改成薄适配层。
5. Phase 5 至 Phase 7 完成 Memory、Runtime 和 Capability/MCP 边界。
6. Phase 8 最后移动 `apps/astrbot-plugins`、deploy、ops、services、configs 和 third_party，并切换路径。
7. Phase 9 增加 Eval、Tracing、完整 CI 分层和新目录契约门禁。
8. Phase 10 仅在无旧 import、无旧路径消费者且回滚验证通过后清理兼容层。
