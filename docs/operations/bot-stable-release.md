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
Web、AstrBot/MCP、自有插件统一使用同一已验证 Git revision 的发布副本，
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

## 2026-09-04 部署实测（部分完成）

- 已切换四个现有 Bot 容器：Web `791eede`、AstrBot/MCP `4068977`（AstrBot 4.27.5）、NapCat 4.18.19。两次代码提交间 AstrBot、插件、Agent 包和 MCP 源码无差异；仅 Web 补充无模型路由的错误提示。
- 旧镜像、精确私密 Compose 清单和停写后的业务数据备份均已保留；登录态、策略和三档 Key 池未清空。活动部署挂载独立发布副本。日常操作以私密发布清单为准，不运行会创建第二个 NapCat 的通用全栈启动命令。
- Web/QQ 连接正常，Runtime 实时状态就绪，MCP 目录可用（10 个 Server、21 个 Capability）；公网 HTTPS 未登录请求仍返回 Auth 跳转。27 个范围外服务的容器 ID、镜像和启动时间未变。
- 验证通过：前端 90、服务端 107、E2E 7、相关 Python 17、生产装配/源码守卫 36 项，类型检查和构建通过。构建保留既有 bundle 大小警告。
- 未解决：当前 Luna Provider 的合成调用返回上游 HTTP 503 `api_error`，虽然其模型 ID 仍在上游目录中。实际 Runtime 预览无可用模型路由；已改为明确报错，不能宣称模型回复验收通过。没有修改范围外 LLM 代理，也没有伪造健康证据。
- 兼容性例外：旧 Arc 暂保留，等待操作者确认是否移除第三方 QQ 查分命令；不能声称所有旧插件已冻结。已保存的 DeepSeek Key 池仍未应用到 Runtime。
