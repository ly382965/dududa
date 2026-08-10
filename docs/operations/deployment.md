# 部署设计

## 1. 状态与目标

- 状态：S16 离线运维核心已实现；真实部署 Driver 与生产演练未完成
- 当前兼容入口：根目录 `./manage.sh`
- 目标：把部署拆成可观察、幂等、可单独失败和可验证的阶段

本文定义嘟嘟哒 Bot Runtime 的部署边界和目标编排。S16 已在
`scripts/dududa_ops.py` 实现版本化 Release/State/Receipt、只读 Health、SQLite Backup、
Restore Plan 和 Upgrade/Rollback 状态机；根 `manage.sh` 已增加转发并保持旧入口兼容。
这些离线证据不授权操作生产环境，也不表示真实 Compose/HTTP/MCP 探针已经配置。

## 2. 部署边界

本仓库部署：

- AstrBot 派生镜像
- NapCat 容器
- 四套自研 AstrBot 插件
- 锁定的第三方 AstrBot 插件
- 嘟嘟哒 Agent package
- iCourse MCP Server
- Persona 与 MCP 安全模板

外部依赖：

- OpenAI-compatible 模型 Provider 及其凭据
- QQ 网络和 NapCat 交互式登录
- 可选的 `mmdustc-edge` Docker 网络及受保护网关
- 可选的 Sub2API 管理站点及只读查询凭据
- 宿主机防火墙、磁盘、备份介质和监控

部署不得创建、复制或提交 Provider Key、QQ 登录态和真实用户数据。首次启动后，Provider 配置和 QQ 登录只能在私有运行环境完成。

## 3. 当前链路

当前 `./manage.sh up` 实际执行：

```text
init
  -> 创建 .env 和运行目录
  -> 合并 icourse MCP 模板
plugins
  -> 安装锁定第三方插件
ensure_edge_network
docker compose up -d --build
seed
  -> 更新 Persona 数据库和默认 Persona
restart astrbot
```

当前链路的已知限制：

- 初始化、准备、构建、启动和 seed 被一个命令隐式串联。
- 没有容器或应用健康检查，`depends_on` 只保证启动顺序。
- seed 在每次 `up` 时执行，会覆盖同名 Persona 并重设默认 Persona。
- 任一后置步骤失败时，已启动容器不会自动回滚。
- 插件安装直接面向活动运行目录，没有发布级事务。
- 没有内建 backup、restore 和版本化部署记录。

无参数 `./manage.sh upgrade` 为兼容仍保留上述旧链路；传入 Manifest、Driver Plan 和明确
参数时才进入 S16 受保护流程。真实 Driver 接入前，旧链路仍只能作为开发辅助命令。

### 3.1 S16 已实现边界

- `bootstrap` 幂等创建私有运行/发布目录，不创建或覆盖 `.env`；旧 `init` 继续负责兼容初始化。
- Release Manifest 固定源码、digest-pinned image、组件/Compose Contract 与前一 Release；
  mutable state 和逐阶段 Receipt 独立原子写入。
- Backup 拒绝路径逃逸与符号链接，SQLite 使用 Backup API；Restore 默认只输出确定性 Plan，
  Apply 只接受显式空目标。
- Upgrade 在健康成功后才提升 current pointer；切换后失败只回滚一次并保留失败 Release、
  Backup 和 Receipt。
- 实际 Compose 渲染已抽样验证 loopback 端口、只读源码挂载、可写数据挂载和
  `bot_net`/`edge`。NapCat 共享挂载未在无证据时收窄。

## 4. 目标阶段模型

目标 Python CLI 负责复杂逻辑，根级 Shell 只负责定位仓库、读取兼容参数和转发退出码。

| 阶段 | 职责 | 主要输出 | 幂等要求 |
| --- | --- | --- | --- |
| `bootstrap` | 创建私有目录、权限和部署元数据；兼容 `init` 单独处理初始 `.env` | 可用的运行根和部署元数据目录 | 不创建或覆盖 `.env` 和运行数据 |
| `prepare` | 校验配置、解析第三方 manifest、合并受管模板、准备插件 staging | 可审计的 release plan 和 staging 内容 | 同一输入产生相同计划 |
| `build` | 构建并标记 AstrBot 派生镜像 | 含 Agent package 与 MCP 依赖的镜像 | 源码和 lock 不变时可复现 |
| `start` | 创建或验证网络，启动或重建容器 | 运行中的 AstrBot、NapCat | 不执行 seed，不修改业务数据 |
| `seed` | 在服务启动后执行显式、版本化且幂等的配置/数据初始化 | seed 记录 | 每个 seed 版本至多成功一次 |
| `health` | 检查容器、HTTP、插件、Persona 和 MCP | 机器可读报告与明确退出码 | 只读，不修复状态 |
| `upgrade` | 编排 preflight、backup、prepare、build、activate、离线 migration、start、post-start seed、health | 已验证的新 release 或回滚结果 | 失败必须保留恢复点 |
| `backup` | 一致性备份和 manifest | 私有备份集 | 不修改源数据 |
| `restore` | 校验备份并恢复匹配 release | 已恢复的数据和配置 | 破坏性覆盖前必须确认 |

## 5. 推荐调用链

### 5.1 首次部署

```text
bootstrap
  -> prepare
  -> build
  -> start
  -> seed
  -> health
```

`bootstrap` 只负责主机和目录基线。`prepare` 不连接生产模型，不登录 QQ，不启动容器。`build` 不读取 `.env` 中的秘密，也不把运行数据加入构建上下文。

### 5.2 日常启动

```text
start -> health
```

日常启动不得重复安装插件、重写 Persona 或迁移数据库。检测到尚未完成的 migration 时，`start` 应拒绝并提示执行明确的 `seed` 或 `upgrade`。

### 5.3 配置或源码变更

```text
prepare -> build（需要时）-> start -> health
```

纯模板变更是否需要 seed，由版本化 migration 明确声明。不能依靠重启碰运气加载配置。

## 6. 阶段契约

### 6.1 Bootstrap

输入：仓库根、`.env.example`、可选 `.env`、Docker 可用性。

必须执行：

- 如果 `.env` 不存在，使用安全权限创建；存在时绝不覆盖。
- 解析 `STACK_DATA_ROOT`，拒绝空路径、根目录和明显危险路径。
- 创建 AstrBot、NapCat、插件 staging、备份和部署元数据目录。
- 设置运行根及敏感父目录的最小宿主权限。
- 检查 Docker Compose 版本、磁盘空间和必需端口。
- 检查外部 edge 网络策略；自动创建行为必须可配置并记录。

失败时不得启动容器或写业务数据库。

### 6.2 Prepare

输入：配置模板、第三方 manifest、patch、vendor、目标 release ID。

必须执行：

- 结构化解析并校验所有配置，不使用字符串猜测。
- 验证第三方 commit/version、license、integrity 和 patch 列表。
- 将插件安装到 staging，实际执行 patch check。
- 合并 MCP 时保留非受管 Server，只更新明确受管的 `icourse` 项。
- 输出不含秘密的 release plan，包含即将变化的镜像、插件和 seed。

Prepare 不得直接替换活动插件目录。失败时删除 staging 即可，活动运行态保持不变。

### 6.3 Build

AstrBot 镜像必须：

- 以 digest 固定的 AstrBot base image 为基础。
- 安装锁定依赖的 `dududa-agent` package。
- 安装锁定依赖的 iCourse MCP package。
- 不包含 `.env`、运行数据库、QQ 登录态、备份或真实配置。
- 记录源码 commit、依赖 lock digest 和构建时间标签。
- 通过 package import 和插件 import smoke test。

正式实现前应为 Python 依赖增加可审核 lock 和 hash；当前 `>=` 依赖范围不能支持完全可复现构建。

### 6.4 Start

Start 只负责容器和网络状态：

- 验证或创建项目私有 `bot_net`。
- 按策略验证外部 `edge`，不得静默加入未知网络。
- 以明确 release image 启动 AstrBot。
- 挂载四个插件到稳定的 `/AstrBot/data/plugins/<plugin-name>`。
- 挂载私有运行数据，并保持源码、模板和运维脚本只读。
- 启动 NapCat，但不清理或重置 QQ 登录态。

Start 不执行 Persona seed、插件下载、数据库迁移或备份。

### 6.5 Seed

每个 seed 必须具有稳定 ID、适用版本、前置 schema 和回滚说明。执行记录保存在私有部署元数据中。

Persona seed 应区分：

- 首次创建嘟嘟哒 Persona
- 更新仓库受管字段
- 用户在 WebUI 中维护的字段
- 是否将其设为默认 Persona

默认 Persona 变更必须显式配置，不能在每次启动时强制发生。数据库修改与配置文件修改无法形成单一事务时，应记录补偿步骤并保证重试安全。

### 6.6 Health

Health 必须只读并输出 JSON 及人类可读摘要。至少分层检查：

1. `container`：两个容器存在、运行且无重启循环。
2. `web`：AstrBot 和 NapCat 本地 HTTP 端点可响应。
3. `plugin`：四套自研插件和 manifest 中第三方插件均已加载。
4. `persona`：`dududa` 存在，默认选择符合部署策略。
5. `mcp`：完成 MCP initialize、list tools 和 `icourse_stats`。
6. `data`：数据库与配置可读写，源码挂载仍为只读。
7. `integration`：OneBot 连接、Provider 和 QQ 登录状态分别报告。

QQ 尚未交互登录或外部 Provider 尚未配置时，应返回明确的 `degraded`，不能与容器崩溃混为一谈。CI smoke 可跳过真实 QQ 和 Provider，但不能跳过插件 import 与 MCP 握手。

## 7. 配置层次

配置优先级设计为：

```text
安全默认值
  < 仓库内无密钥模板
  < 私有 .env
  < 运行态 AstrBot/NapCat 配置
  < 明确的命令行一次性覆盖
```

任何覆盖都必须在日志中记录字段名和来源，不能记录秘密值。模板 schema 应拒绝未知类型和危险路径。模型配置、工具权限和 Persona 配置分开管理，Persona 不得决定事实、权限或工具白名单。

## 8. 数据与权限

默认私有数据结构：

```text
STACK_DATA_ROOT/
├── astrbot/
├── napcat/
│   ├── config/
│   └── ntqq/
├── .dududa/
│   ├── releases/
│   ├── staging/
│   └── state.json
└── backups/
```

`.dududa` 和 `backups` 均为私有运行数据，必须加入 Git 和构建上下文排除规则。部署日志默认脱敏，不输出 QQ 标识列表、Token、Cookie、Provider Key 或完整 `.env`。

当前 NapCat 共享挂载整个 AstrBot 数据目录。收窄前必须确认 `MODE=astrbot` 的最低文件契约并建立联调测试。没有证据前不得直接删挂载；确认后应按最小权限拆为专用集成配置。

## 9. 网络边界

- WebUI 默认只发布到 `127.0.0.1`，远程管理使用 SSH 本地端口转发或受认证网关。
- 宿主 loopback 绑定不限制 Docker 网络内访问。加入 `edge` 的其他容器可通过别名访问服务端口。
- `edge` 接入应显式启用，默认部署可只使用 `bot_net` 时不应强制创建外部网络。
- 公网 TLS、认证和限流由仓库外网关负责，但仓库必须记录其依赖契约。
- 容器后续应评估非 root 用户、`cap_drop`、只读根文件系统、资源限制和容器 healthcheck。

## 10. 兼容命令映射

| 现有命令 | 目标行为 |
| --- | --- |
| `init` | 转发到 `bootstrap`，随后执行仅配置准备所需的兼容步骤 |
| `plugins` | 转发到 `prepare --plugins-only` |
| `sync` | 转发到 `prepare --config-only` |
| `up` | `bootstrap -> prepare -> build -> start -> seed（仅有 pending 版本时）-> health` |
| `seed` | 转发到版本化 `seed` |
| `upgrade` | 转发到受保护的 upgrade 流程 |
| `pull` | 保留当前拉取非 buildable 外部镜像的语义；只有提供迁移说明和兼容测试后才可并入 `prepare/build` |
| `config` | 只渲染和验证 Compose，不修改状态 |
| `ps/logs/restart/down` | 保持现有用户界面和服务参数 |

兼容 `up` 只有在检测到未执行 seed 时才执行 seed，不应在每次启动重复覆盖。

## 11. 失败语义

- 所有阶段使用非零退出码表示失败，并标明失败阶段。
- 日志使用 release ID、stage、duration 和 error code，不输出敏感值。
- `prepare/build` 失败不得影响活动容器。
- `start` 失败保留旧 release 和备份，不自动删除容器或数据。
- `seed` 失败禁止标记 release 成功，按 migration 定义补偿或回滚。
- `health` 失败触发 upgrade 的回滚决策，但独立执行 `health` 永不修改状态。

## 12. 测试与验收

部署实现至少需要：

- Bootstrap 路径和权限单测
- 配置合并、无效 JSON 和未知字段测试
- 第三方 staging、patch、完整性和原子切换测试
- Docker 构建 smoke
- 四套 AstrBot 插件真实 import/注册测试
- Persona seed 版本和用户字段保留测试
- MCP initialize/list/call 集成测试
- Health 的 healthy/degraded/failed 测试
- 各阶段故障注入和退出码测试
- 从旧 `manage.sh` 命令到新 CLI 的兼容契约测试
- 无密钥、运行数据和备份进入 Git/镜像的扫描
