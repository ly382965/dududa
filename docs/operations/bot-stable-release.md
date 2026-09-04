# Bot 服务稳定版发布

本流程只覆盖 Dududa Web、AstrBot、已有 NapCat、MCP 和已安装的自有插件。
不重启其他站点、LLM 代理、Authentik、Caddy 或数据库，也不新增 QQ 发送权限。

## 前端与正式 Runtime

前端源码在 `apps/web`，API Key 页面为 `/#/api-keys`。每档的「配置 Base URL / 模型」
维护共同连接；添加 Key 对话框显示该连接并提供跳转。DeepSeek 使用
`https://api.deepseek.com` 和 OpenAI Chat Completions，模型 ID 按其控制台填写。
SecretRef 可以留空，真实 Key 只在明确写入时提交。

正式 Agent 使用 `/api/agent/status`、`catalog`、`config`、`respond`，不依赖
`DUDUDA_INTERNAL_TEST_DATA_ROOT`，也不会回退到个人 Codex 凭据。
历史内测 API 保留原边界。状态通过服务端 plugin-scope 凭据查询当前 AstrBot
进程的 `/api/v1/plugins/extensions/astrbot_plugin_dududa_core/runtime/status`。
装配就绪不等于模型调用健康，`NO BANDIT` 不是连接失败原因。
群聊预览调用现有 Runtime，保持 no-send/no-memory-write；当前不支持私聊预览。

群聊的 Agent「配置 → 运行行为 → 主动加入群聊」提供「在本群启用自动搭话」开关。
开启使用自动参与模式，关闭停用；修改后点击底部「保存配置」生效。概率、冷却、
每小时上限及其他群配置保持不变。私聊、策略加载中或保存中不可操作；会话 Agent
总开关和全局交付限制仍须满足，部署新开关不会自动启用任何群。

Web 不再挂载整个 AstrBot 敏感配置目录。部署必须让 Web 与 AstrBot 共享独立的
`DUDUDA_AGENT_POLICY_ROOT`，两端 `DUDUDA_AGENT_POLICY_PATH` 指向同一文件。
Web 挂载可写、AstrBot 只读；目录属 UID 1000、权限 0700，文件 0600。
迁移时先保留并复制原 `DUDUDA_AGENT_POLICY_PATH` 内容，不能用空策略覆盖已有群配置。
Web 使用串行化 read-modify-write 和同目录原子替换，Python 不会读到半份 JSON。

## 稳定版本与冻结

2026-09-04 核对上游稳定版：AstrBot 4.27.5、NapCat 4.18.19。
AstrBot 的 latest release 当时指向 4.28 beta，不能仅按 prerelease 标志选版。
镜像摘要固定在示例环境文件；镜像源可变，但摘要必须一致。
已有 OpenAI request-overrides 补丁在 4.27.5 仍需要，构建时验证应用。
AstrBot 主进程 MCP 1.x 与独立 worker MCP 2.x 保持隔离，不做跨主版本混装。

发布前按实际容器检查镜像 ID、挂载、端口和网络别名，不能只看 `:local` 标签。
Web、AstrBot/MCP、自有插件使用明确记录的已验证 Git revision 发布副本；
分阶段热修复可以保持其他服务不变，但必须逐项记录实际 revision，不能宣称统一版本。
不能继续挂载会变动的开发 worktree。仅更新已安装插件，不把历史/实验插件重新启用。

切换前私密保留旧镜像标签、精确容器配置、策略、QQ 登录数据和应用数据恢复点。
若旧镜像已从镜像存储移除，必须先保存仍运行容器的可恢复镜像，再重建容器。
这类镜像可能含私密 writable layer，绝不可上传公共 registry 或 GitHub。
对写入中的数据库进行一致性备份；升级后 schema 不兼容时不能仅回退代码。
旧版本退出活动部署，保留回滚，不删除业务数据。

使用原 Compose project 更新唯一 NapCat，不另建一个争抢 QQ 登录的实例。
每次使用精确服务名和 `--no-deps --pull never` 分批切换，验证 AstrBot API、
Runtime、MCP、NapCat 登录/双向连接、Web 和公网 auth 跳转，再处理下一服务。

## 尚未等同于 Runtime 应用的操作

API Key 的保存和显式探测不等于切换 Runtime 模型。现有池投影适配器不做
Provider Manager 热重载：AstrBot 会先终止旧 Provider，而已装配 Runtime 仍持有
旧对象。模型、Provider binding、conformance evidence 不一致时必须保持旧实例。
任何受控应用须先验证这些绑定、保留 last-known-good，并重新装配 Runtime。
不要复制旧模型证据给 DeepSeek 或把 pending 状态改成 synced。

## GitHub 边界

提交代码、测试、示例环境和脱敏操作记录；不提交 `.env`、密钥库、真实策略、
容器完整 inspect、镜像导出、数据库备份、QQ 登录态、密码或 auth 会话。

## 外部连接配置的受控应用

Key、Base URL、模型名与推理设置属于外部配置，不是 Runtime 框架代码。
网页写入独立 Key store；AstrBot 用 Source/Provider 注册连接；Runtime 在装配时
通过 Provider ID 获取实例，只处理模型调用接口。过去缺少前两者的应用桥接，
所以保存池不会更新已运行实例。换 Key/Base URL 本身不应要求重新构建镜像。
应用后真实 Key 也会存在 AstrBot 私有数据目录的 `cmd_config.json` 中，供 Source
创建客户端使用；并非整个服务端只存 SecretRef。两处凭据文件和备份均不得公开。
当前网页没有一键应用或自动热更新链路，仍需下面的显式应用和冷启动。

`ops/cli/apply_deepseek_runtime.py` 为本次明确授权的 DeepSeek 迁移提供两步操作：
在已验证 AstrBot 镜像内用 `prepare --data <只读数据目录> --store <私有池文件>
--candidate <新的私密目录> --expected-revision <池revision> --source-revision <代码提交>
--accept-provider-retention` 生成候选；验证真实三档 Provider、参数、输出与健康探针，
并保存原配置。候选只替换指定三档 Provider/Source，保留其他配置和并发/速率限制。

停止唯一 AstrBot 宿主后，以可写数据挂载执行同一工具的 `install --data ...
--store ... --candidate ... --host-stopped`，随后冷启动。配置在准备后若被改动，
安装会拒绝覆盖。回退使用候选目录的 `command.before.json`、`core.before.json`、
`evidence.before.json` 和发布前镜像/插件清单；不要在运行中的宿主覆盖配置。
不把私密候选或证据提交到 Git，也不把一次 Provider 成功等同于 Runtime 预览验收。

镜像内的 `verify_astrbot_request_boundary.py` 使用 MockTransport，不访问真实服务，
验证单请求、参数、异常脱敏、超时和取消。对应 AstrBot 补丁只绕过显式单次非流式
调用的隐式重试，不改变其他调用默认策略。默认预算保持不变；配置较大推理预算时，
Runtime 总输出额度同时覆盖感知与回答两份预留，避免在发请求前因固定额度被拒绝。

## 2026-09-04 当前部署：DeepSeek 已应用

- AstrBot 当前镜像为 `dududa/astrbot:0ef2a18-4.27.5`，镜像摘要为 `sha256:2fb56b38ca111c315b111957b0b0c9b52378cd550c1e26bfa2fb6bcbc1cf6bdd`。挂载的独立 Runtime/插件源为 `5e243fd`；后续提交只修改构建依赖，不改变该运行时代码。Web 和 MCP Console 保持 `cdbc5f0`，NapCat 保持 4.18.19。
- 外部池 revision 14 已实际应用，三池均启用：Haiku/Luna 为 Flash `low` / 8192，Sonnet/Terra 为 Flash `high` / 16384，Opus/Sol 为 Pro `max` / 32768。数字为每次输出上限，不是每次必定消耗量。操作者明确同意 CN / provider-managed 默认留存策略；没有继续声称零留存，也没有复制旧 GPT 证据。
- 三档均通过真实 AstrBot Provider 请求及非思考健康探针。线上 Agent 状态显示 `providerConfigured=true`，模型映射为 `deepseek-v4-flash`、`deepseek-v4-flash`、`deepseek-v4-pro`。普通问候的实际 Runtime 预览生成非空回答，用时 10.732 秒，路径为 `dududa_2_preview`，QQ 输出、Memory 写入、工具调用均为 0。
- 一次含“测试”的固定输出合成提示返回 `conflicting_evidence_without_clarification`，不是模型路由缺失。静态规则支持验证关键词与模型分类冲突这一解释，但当次具体冲突字段未被捕获；未放宽冲突策略，也不据成功问候宣称所有输入都通过。尚未重新验收真实主动群发和人工质量。
- 本次只重建 AstrBot；Web/MCP/NapCat 的容器 ID、镜像 ID、启动时间均未改变，27 个范围外容器也与原基线一致。Web/QQ connected，MCP 目录 10 个 Server / 26 个 Capability，公网 HTTPS 未登录仍跳转 Auth。现有群策略、概率、冷却和限额没有改变。
- 验证：迁移/模型单测 26 项通过，新增 CLI lint 通过；完整生产装配运行 32 项，其中 30 项通过、两项旧重试次数断言失败，更新断言后两项及新增配置用例共 3 项定向重跑通过。最终镜像的 9 项真实 SDK/Provider MockTransport 边界验证全部通过，不访问外网。先前 Web 类型/构建/测试结果仍为前一阶段证据，本次没有改动前端代码。
- 冻结的旧镜像、切换前精确清单、私密配置候选及恢复副本均保留在仓库外。Arc 仍保留旧命令实现；镜像已内置其现有 OpenCV 4.14.0.94 / pyparsing 3.1.4 公共发行包，避免首次启动下载。不复制旧私密配置，也不发布冻结容器的私密根文件系统。
- 更广的“旧插件全部冻结/替换”仍受 Arc 兼容选择约束，TreeWork 发布分支保持 partial，不把本次 DeepSeek 成功当成整个分支验收完成。

## 历史部署记录（下列旧阻塞已由上述迁移更新）

### 2026-09-04 首次切换

- 已切换四个现有 Bot 容器：Web `791eede`、AstrBot/MCP `4068977`（AstrBot 4.27.5）、NapCat 4.18.19。两次代码提交间 AstrBot、插件、Agent 包和 MCP 源码无差异；仅 Web 补充无模型路由的错误提示。
- 旧镜像、精确私密 Compose 清单和停写后的业务数据备份均已保留；登录态、策略和三档 Key 池未清空。活动部署挂载独立发布副本。日常操作以私密发布清单为准，不运行会创建第二个 NapCat 的通用全栈启动命令。
- Web/QQ 连接正常，Runtime 实时状态就绪，MCP 目录可用（10 个 Server、21 个 Capability）；公网 HTTPS 未登录请求仍返回 Auth 跳转。27 个范围外服务的容器 ID、镜像和启动时间未变。
- 验证通过：前端 90、服务端 107、E2E 7、相关 Python 17、生产装配/源码守卫 36 项，类型检查和构建通过。构建保留既有 bundle 大小警告。
- 未解决：当前 Luna Provider 的合成调用返回上游 HTTP 503 `api_error`，虽然其模型 ID 仍在上游目录中。实际 Runtime 预览无可用模型路由；已改为明确报错，不能宣称模型回复验收通过。没有修改范围外 LLM 代理，也没有伪造健康证据。
- 兼容性例外：旧 Arc 暂保留，等待操作者确认是否移除第三方 QQ 查分命令；不能声称所有旧插件已冻结。已保存的 DeepSeek Key 池仍未应用到 Runtime。

### 同日 MCP 与推理挡位更新（迁移前历史）

- Web 和 MCP Console 已切换到 `cdbc5f0`，使用独立发布副本；AstrBot Runtime/插件仍为 `4068977`，NapCat 仍为 4.18.19，本次未重启这两者。分阶段发布使用精确私密清单，不能用共享镜像变量的通用全栈命令覆盖当前混合版本。
- 五个新增 MCP 仅接入控制台目录，不扩大群聊自动调用权限。线上目录为 10 个 Server、26 个 Capability；五项连接检测及五次各取一条的查询均 HTTP 200、成功且非空。
- 仓库外缓存为校园活动 65、学院通知 36、图书馆 28、培养方案 326、本地推荐 108 条。本地推荐是历史整理数据，没有虚构抓取时间；图书馆为官网常规安排，不保证临时开放变化。页面显示检测状态、来源和缓存时间。
- 公网未登录仍跳转 Auth，Web/QQ 状态 connected；27 个范围外容器的 ID、镜像 ID、启动时间未变。前一版 Web/MCP 镜像和切换前私密清单已保留，未删除数据。
- 最新验证：前端 100、服务端 107、E2E 7、Console 14、来源/仓库 18、模型适配器 21、生产装配 31 项通过，类型检查和构建通过。另有模型/Key/MCP client 合并 48 项通过；这些测试集合部分重叠，不相加声称总数。
- DeepSeek 池 revision 11：Haiku/Luna 使用 `deepseek-v4-flash` / `low` / 8192，Sonnet/Terra 使用 Flash / `high` / 16384，Opus/Sol 使用 `deepseek-v4-pro` / `max` / 32768（末项为输出 token 上限）。三池均启用，每池保留一个启用 Key；三次有界合成 API 请求均 HTTP 200 且有可见输出。
- **保存和探测不等于 Runtime 切换。** Runtime 此时仍绑定 GPT 三档。用户已同意迁移及启用 Sonnet，但是否接受服务商默认留存仍待独立确认；现有零留存要求未放宽。DeepSeek [推理参数](https://api-docs.deepseek.com/guides/thinking_mode/)支持上述挡位；[自动缓存说明](https://api-docs.deepseek.com/news/news0802/)不能作为零留存证据。新适配代码已提交，尚未在 AstrBot 激活，不复制旧 GPT 验证记录。
- 目标群的主动搭话策略原已开启，近期失败原因是 `model_route_not_found`，不是开关关闭。本次未改变群概率、冷却、限额或发送权限，也未发送 QQ 测试消息。实际模型回复及旧 Arc 兼容选择仍未验收。
