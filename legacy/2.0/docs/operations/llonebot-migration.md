# LLOneBot 协议层迁移

默认协议客户端为 LLOneBot（LuckyLilliaBot）8.1.10，AstrBot 与 Web 共用现有 OneBot v11
接口。NapCat 留在 `legacy-napcat` Compose profile，供已有部署回退使用。
本次不更改人设、Agent 权限、意图路由、回复审查或插件安装列表。

## 配置与登录

1. `.env` 中配置 `LLBOT_IMAGE`、`LLBOT_DATA_DIR` 和 `LLBOT_WEBUI_PORT`；默认数据目录
   为 `STACK_DATA_ROOT/llbot`，WebUI 只监听本机 `127.0.0.1:3080`。
2. 启动 `llbot`，在 WebUI 设置密码、填写官方 Auth Token 并扫码登录 QQ。
   [官方安装说明](https://www.llonebot.com/)提供 Token 获取与登录入口。
3. 在账号的 OneBot 11 设置中添加 AstrBot 反向 WS：容器部署为 `ws://astrbot:6199/ws`。
   若 AstrBot 配置了 Token，使用该连接原有凭据。
4. 执行 `bash manage.sh web-connect-llbot` 添加 Web 连接，随后重启 LLOneBot。
   默认目标为 `ws://web:8000/onebot/v11/ws`，Token 来自现有 Web 私密文件。
5. 登录完成后可在私密 `.env` 中填写 `LLBOT_ACCOUNT`，供重启恢复该账号。

CLI/Desktop 安装可设置 `LLBOT_DATA_DIR` 指向其 `bin/llbot/data`，并使用
`DUDUDA_WEB_ONEBOT_WS_URL=ws://127.0.0.1:5173/onebot/v11/ws`。连接容器内 AstrBot
时可使用映射到本机的 6199 端口。

两个客户端共用 `ops/cli/configure_onebot_web.py`。它默认预览，使用 `--apply` 才写入；
写入前备份，只更新受管 Web 连接，保留 AstrBot 及其他网关，并可重复执行。
LLOneBot 账号配置中的 `ob11.enable` 会随接入开启。不要让同一个 QQ 账号的 NapCat 和
LLOneBot 同时向正式 AstrBot/Web 上报消息。

## 验证范围

- 网关识别客户端实现；未知实现不开放操作能力。
- 账号、联系人、群及标准消息收发使用同一个网关；LLOneBot 不执行 NapCat 的 packet 探针。
- LLOneBot 的 `reverseOrder` 只改变返回顺序。网关按其包含边界的反向序号接口转换前后分页，
  并处理消息序号空缺，避免请求新消息时返回旧消息。
- 当前工作台为 LLOneBot 开放 25 项能力，8 项扩展尚未对接或不可用：QQ 同步置顶、好友申请
  历史、群文件夹改名、群文件管理、单条转发、自定义表情市场、精华消息和群公告。
  服务端也会拒绝这些入口，不仅在界面禁用。
- 群成员权限、操作来源校验、私密 Token、Agent 群授权与注入防护沿用主线。

自动测试使用模拟 OneBot 端验证消息接收与发送 action，不向真实 QQ 群发送测试消息。
线上验收需另行确认 QQ 登录、两条反向 WS、联系人/历史读取及 Agent 预览；仅容器启动或
单元测试通过不能证明真实群收发正常。

## 已有部署切换与回退

保留原 NapCat 镜像、配置和 QQ 数据。先部署支持 LLOneBot 的 Web，准备 LLOneBot 独立数据
目录并完成登录；确认新客户端就绪后停用原 NapCat，再启用 LLOneBot 的两条正式连接。
LLOneBot 只读挂载 AstrBot 数据，用于读取机器人生成的附件。

需要回退时，先停止 LLOneBot，再用原部署清单启动原 NapCat。不要运行 `down -v`，也不要
用首次安装的 `up`/`seed` 流程覆盖已有模型、人设或群配置。
