# 升级与回滚设计

## 1. 状态与安全原则

- 状态：S16 离线事务核心已实现；真实 Driver、原地恢复和生产演练未完成
- 当前命令：`./manage.sh upgrade`
- 目标：升级失败后可以回到已知可运行的代码、镜像、插件、配置和数据组合

升级不是一次 `docker compose up --build`。一个可回滚 release 至少由以下状态共同定义：

```text
Git commit
+ Compose/环境模板版本
+ AstrBot/NapCat image digest
+ dududa-agent 与 iCourse package lock
+ 第三方插件 manifest 和 patch digest
+ seed/migration 版本
+ 私有配置与持久数据快照
```

任何真实密钥、QQ 登录态、用户记忆或数据库都不得进入 Git、CI artifact 或公开日志。备份属于私有高敏数据。

## 2. 当前升级行为和风险

当前 `manage.sh upgrade` 依次执行：

```text
plugins -> sync -> ensure edge -> pull --ignore-buildable
        -> compose up -d --build -> seed
```

当前存在以下已验证限制：

1. 插件 lock 变化后，活动目录 marker 与新 lock 不匹配；安装器在没有 `--force` 时拒绝替换，而 `upgrade` 不提供 force 通道。
2. 插件同步直接面向活动运行目录，没有完整 release staging 和长期回滚副本。
3. 升级前没有一致性备份、磁盘检查、配置快照或回滚点。
4. `pull --ignore-buildable` 不会显式拉取 AstrBot build service 的 base image。
5. seed 在容器启动后执行，但 upgrade 不像 `up` 那样重启 AstrBot，更新后的 Persona/配置何时生效不明确。
6. 没有健康检查。Compose 命令成功不能证明插件、Persona、MCP、OneBot 或模型可用。
7. 后置步骤失败时，新旧状态可能混合，命令不会自动恢复。

在目标流程实现前，当前 `upgrade` 只能视为开发环境辅助命令，不能作为无监督生产升级事务。

## 3. Release 与备份清单

每次升级生成唯一 `release_id`，推荐使用 UTC 时间、Git 短 SHA 和 manifest digest。私有 release manifest 至少记录：

- 源 Git commit 和 dirty 状态；dirty 工作树默认拒绝升级
- 渲染后的 Compose 配置摘要，不含 secret value
- 实际镜像 ID 和 digest
- 第三方插件名、版本、commit、integrity 和 patch digest
- Agent/MCP Python lock digest
- 已执行 seed/migration ID
- 数据 schema 版本
- 备份路径、校验和、文件权限和创建时间
- 升级阶段、健康结果和最终状态

Release manifest 位于 `STACK_DATA_ROOT/.dududa/releases/`，不提交 Git。

## 4. 备份范围

默认备份必须包含：

- `.env` 或等效私有部署配置
- AstrBot `cmd_config.json`、MCP 配置和插件配置
- AstrBot 主数据库、Memory、知识库、插件数据和审计日志
- 第三方插件活动版本及其 `.dududa-lock.json`
- NapCat 配置和 QQ 登录态
- iCourse SQLite 缓存，除非明确标为可重建并选择跳过
- 当前 release manifest 和 seed/migration 记录

可重建缓存、模型下载缓存和临时附件可按策略排除，但排除项必须写入 backup manifest。

NapCat 登录态、Provider 凭据和聊天记忆具有高敏感性。备份目录权限至少与源数据相同，离机备份必须加密。禁止将备份上传到 GitHub Actions、普通对象存储公开桶或仓库目录。

## 5. 一致性要求

- SQLite 数据库使用 SQLite backup API、应用支持的在线备份或短暂停写后复制，禁止把正在写入的单文件 `cp` 当作一致性备份。
- 多文件配置快照要记录先后顺序和校验和。
- NapCat 登录态备份前应确认文件刷新状态；需要停服务时必须明确记录停机窗口。
- 备份完成后执行可读性、校验和和 schema 验证。
- 未验证的备份不能作为升级前置条件通过。

`backup` 默认只读源数据。需要协调暂停写入时，应显示计划并获得明确授权，不得静默停止生产服务。

## 6. 目标升级流程

```text
preflight
  -> backup
  -> prepare release staging
  -> build and verify image
  -> quiesce affected writers when required
  -> activate code/plugins/image
  -> run declared offline pre-start migrations
  -> start/recreate services
  -> run pending idempotent post-start seeds
  -> health and bounded observation
  -> mark release successful
  -> retain previous release and backup
```

### 6.1 Preflight

检查：

- Git ref、工作树状态和目标 release 已知
- 配置、Compose、manifest、patch 和 migration 可解析
- 磁盘空间足够容纳 staging、镜像和至少一个完整备份
- 当前服务状态和当前 release 可识别
- 目标 schema 的升级与降级策略存在
- 外部网络、端口和 Docker daemon 可用
- 无秘密将进入日志、构建上下文或 release manifest

任何 preflight 失败都在修改活动状态前退出。

### 6.2 Prepare 与 Build

- 将第三方插件安装到 release staging，不触碰活动插件目录。
- 对 git 插件校验完整 commit 和 integrity；对 vendor 校验来源、版本、许可证；对 patch 实际执行 check/apply。
- 使用锁定依赖构建新 AstrBot 镜像，并先做离线 import smoke。
- 生成新旧 release diff：镜像、插件、配置、schema、seed 和网络变化。

### 6.3 Activate

活动插件切换应使用同一文件系统内的原子目录替换，并保留上一个完整目录。不得在活动目录中逐文件覆盖。

Activate 只切换 release 引用、完整插件目录和明确的新 image ID，不在此步骤宣称服务已经健康。若目标包含离线 migration，必须先停止或隔离受影响写入方，不能让旧代码继续写入正在迁移的数据。

### 6.4 Offline Migration、Start 与 Post-Start Seed

- 每个数据变更声明执行模式：`offline_pre_start` 或 `post_start_seed`，不得由脚本猜测顺序。
- Offline migration 只在受影响写入方已停止后执行，并声明 `up`、可选 `down`、前置 schema、后置 schema 和数据备份要求。
- Offline migration 成功后，Compose 使用目标 image ID 启动或重建 AstrBot；NapCat 仅在其镜像、配置契约或共享集成变化时重建，避免无关地影响 QQ 登录会话。
- 服务可启动后才执行幂等 post-start seed。Persona 更新不得无条件覆盖用户维护字段或默认 Persona。
- 不可逆 migration 必须在执行前停止自动流程并要求明确批准。
- 部分失败时记录精确状态，重试不得重复产生记录或数据；未完成 health 前 release 始终不是成功状态。

### 6.5 Health 与观察窗口

升级后依次验证容器、WebUI、插件、Persona、MCP 和 OneBot。外部 Provider 或 QQ 登录不可用时区分环境缺失与版本回归。

通过即时 health 后保留有界观察窗口，检查容器重启、插件 traceback、MCP 错误率和关键命令 smoke。观察期结束前不删除旧 release 或备份。

## 7. 回滚触发条件

以下任一情况默认触发回滚或人工决策：

- AstrBot 无法启动或持续重启
- 任一必需自研插件无法加载
- Persona 或 MCP 初始化失败
- iCourse MCP 无法握手或关键只读工具失败
- 数据 schema 与运行代码不兼容
- OneBot 连接因升级发生回归
- 新版本出现跨群、跨用户或私聊数据泄漏风险
- 配置、插件或数据处于无法确认的混合状态

单纯未完成 QQ 交互登录或未配置外部 Provider，在首次部署中可以是 `degraded`；已有生产环境升级后丢失这些状态则是回滚信号。

## 8. 回滚类型

### 8.1 无数据变更的应用回滚

适用：仅代码、镜像或插件变化，数据 schema 未变。

流程：

1. 停止继续执行新 release 的后置步骤。
2. 恢复上一 release 的镜像引用和完整插件目录。
3. 恢复上一版本受管配置快照。
4. 重建受影响服务。
5. 执行完整 health，记录回滚结果。

### 8.2 可逆 migration 回滚

只有 migration 提供并测试过 `down` 时使用。先回退 schema，再切换旧代码；顺序由 migration 契约明确，不得凭经验猜测。

### 8.3 备份恢复

适用：不可逆 migration、数据损坏或配置跨文件不一致。

流程：

1. 验证备份 manifest、校验和、schema 和目标 release 匹配。
2. 停止相关写入，并再次保存故障现场副本。
3. 恢复数据库、配置、插件数据和必要的 NapCat 状态。
4. 恢复对应的代码、镜像和插件版本。
5. 启动服务并执行完整 health。
6. 保留故障 release、日志和现场副本供审计。

`restore` 是潜在破坏性操作，必须支持 `--plan`/dry-run，并在覆盖活动数据前要求明确确认。不得自动删除故障数据。

## 9. 失败矩阵

| 失败阶段 | 活动状态预期 | 处理 |
| --- | --- | --- |
| preflight | 未变化 | 修正输入后重试 |
| backup | 未变化 | 保留失败备份，禁止升级 |
| prepare | 未变化 | 删除或保留 staging 供诊断 |
| build | 未变化 | 保留构建日志，不激活镜像 |
| activate 前 | 未变化 | 放弃目标 release |
| activate 后、migration 前 | 新代码/旧数据 | 应用回滚 |
| migration 中 | 状态未知 | 停止自动化，按 migration 记录补偿或恢复 |
| health | 新 release 运行但未确认 | 自动应用回滚或进入人工决策 |
| 回滚 health | 故障状态 | 不继续自动重试，保留现场并升级为人工恢复 |

所有失败都必须返回非零退出码，release manifest 不得标记为成功。

## 10. Plugin lock 升级规则

目标安装器不再把 `--force` 作为正常升级机制。它应：

1. 读取统一 manifest 并验证 schema。
2. 在 staging 获取或复制源码。
3. 校验 commit/version、integrity、license 和 patch。
4. 生成新 marker 和新旧 diff。
5. 停止或重载受影响插件后原子切换目录。
6. 通过插件加载 health 后保留新版本。
7. 失败时恢复完整旧目录。

运行目录存在未登记修改时默认拒绝升级，并把 diff 写到私有诊断文件。不得静默覆盖团队成员或 WebUI 产生的未知修改。

## 11. 数据迁移规则

- 所有持久格式都要有 schema/version，不能通过文件存在与否猜测版本。
- Migration 必须可重复检测，成功记录与实际 schema 一致。
- Memory Scope 或身份字段迁移需要跨群、跨用户和私聊隔离回归测试。
- 旧代码读取不了新 schema 时，不允许只回退镜像而不恢复数据。
- iCourse 缓存通常可重建，但仍要明确决定保留、迁移或删除，不能顺手清空。
- QQ 登录态不进行格式转换，除非 NapCat 上游提供受支持迁移流程。

## 12. 保留策略

至少保留：

- 当前成功 release
- 上一个成功 release
- 升级前完整备份
- 最近一次失败 release 的诊断信息

删除旧备份前检查保留期、校验状态和离机副本。清理是独立显式命令，不属于成功升级的隐式最后一步。

## 13. 测试要求

升级实现至少需要：

- lock 变化后 staging 和原子替换测试
- 旧插件目录含未知修改时拒绝测试
- 配置与 SQLite 一致性备份/恢复测试
- seed 和 migration 幂等、部分失败与重试测试
- 旧代码/新 schema 不兼容的阻断测试
- build、activate、seed、health 各阶段故障注入
- 应用回滚和完整备份恢复演练
- NapCat 登录态与 AstrBot 数据权限不被意外改变的契约测试
- 回滚后插件、Persona、MCP 和 OneBot health 验证
- 备份、release manifest 和日志的秘密扫描

## 14. 当前兼容策略

S16 已保留 `./manage.sh upgrade` 命令名：无参数调用继续兼容旧开发链路，显式参数调用转发
至 `ops/cli/dududa_ops.py upgrade`。受保护流程要求版本化 Manifest、升级前已校验 Backup、
逐阶段 Receipt 和显式 Driver Plan；目标 Health 不是 `healthy` 时只回滚一次，且不提升
current release pointer。

离线 fixture 已覆盖 Backup、Restore Plan、Health 和故障回滚，但尚无真实 Compose/HTTP/MCP
Driver、生产备份范围/加密、原地 Restore 或容器升级观察证据。因此不得把新 upgrade 标记为
无人值守生产可用，也不删除旧手工回滚说明和上一个可运行 Release。
