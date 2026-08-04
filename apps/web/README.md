# Dududa Web

嘟嘟哒的真实 QQ 多账号工作台。浏览器不直连 NapCat：同源 Node 网关接收 NapCat 的 OneBot 11
反向 WebSocket，在服务端执行受限 action，再向 Vue 前端提供 HTTP + SSE。

生产代码不包含演示账号、虚构群聊或模拟 Agent 输出，也不把消息写入浏览器数据库。网关只在内存中
维护在线连接和短期媒体映射；账号、联系人、群、历史消息和发送结果均来自当前 NapCat 连接。

## Architecture

```text
Vue browser
  | same-origin HTTP + SSE
  v
Dududa Web Gateway
  | authenticated OneBot 11 reverse WebSocket
  v
NapCat account A ---- QQ account A
NapCat account B ---- QQ account B
```

每个 NapCat 进程只能承载一个当前登录 QQ。多账号必须使用多个 NapCat 容器，并为每个账号使用独立
的 `config` 和 `.config/QQ` 数据卷；它们可以同时反连同一个 Dududa Gateway。

## Start

只启动工作台，不修改或重启任何 NapCat/AstrBot：

```bash
./manage.sh web-up
```

命令会在 `${DUDUDA_WEB_DATA_ROOT}/secrets/`（默认 `./runtime/web/secrets/`）中创建权限为
`0600` 的 `onebot_access_token`。该凭据仅用于 NapCat 与服务端之间的 OneBot 连接，不进入浏览器。

默认入口：

```text
http://127.0.0.1:5173
```

然后在每个 NapCat 已登录账号的 WebUI 中新增一个 `WebSocket Client`：

```json
{
  "name": "dududa-web",
  "enable": true,
  "url": "ws://dududa-web-api:8000/onebot/v11/ws",
  "messagePostFormat": "array",
  "reportSelfMessage": true,
  "reconnectInterval": 5000,
  "token": "<DUDUDA_WEB_DATA_ROOT/secrets/onebot_access_token 的内容>",
  "debug": false,
  "heartInterval": 30000,
  "verifyCertificate": true
}
```

`reportSelfMessage` 必须启用，否则手机 QQ 或其他客户端发送的本账号消息不会完整同步到工作台。
现有 NapCat -> AstrBot 客户端应保留，此项作为第二个客户端并行存在。

如果 QQ 登录态属于本仓库当前 Compose，可使用以下命令幂等添加配置；它只扫描当前
`STACK_DATA_ROOT/napcat/config`，保留所有现有客户端，并在写入后重启当前栈的 NapCat：

```bash
./manage.sh web-connect
```

不要用这个命令操作其他生产栈。外部 NapCat 应在其 WebUI 中显式添加连接。

## Development

```bash
./manage.sh init
cd apps/web
DUDUDA_ONEBOT_TOKEN_FILE=../../runtime/web/secrets/onebot_access_token \
npm run dev
```

开发模式启动端口 `8000` 的 Gateway 和端口 `5173` 的 Vite UI。NapCat 必须能够访问 Gateway；
容器部署时使用上面的 `dududa-web-api` 网络别名。

## Supported QQ Surface

- `get_login_info`、`get_status`、`get_version_info`；
- `get_group_list`、`get_friend_list`、`get_recent_contact`；
- `get_group_msg_history`、`get_friend_msg_history`；
- `send_group_msg`、`send_private_msg`、`get_msg`；
- `message`、`message_sent` 与群/好友撤回事件；
- QQ 用户/群头像代理，以及允许的 QQ CDN 图片代理。

网关没有“任意 OneBot action”转发接口。Cookie、Credential、原始本地路径和 OneBot Token 不会下发
浏览器。浏览器 API 当前暂不启用登录，默认只应绑定本机回环地址；对外发布前必须在反向代理补充认证。
QQ 头像与历史图片是上游的短期数据，失败时前端使用明确降级状态。

NapCat 无法保证补齐 QQ 离线期间未同步到本机的全部消息；本工作台也不会伪造初始未读、置顶或免打扰
状态。未读数仅从当前页面收到的实时事件开始计算。

Agent Console 目前显示未连接状态，不会生成本地模拟结果。后续接入 Dududa Agent Runtime 时应复用
同一会话作用域与权限/审计边界。

## Verification

```bash
npm run test
npm run build
npm run test:e2e
```

服务端测试使用一个内存中的假 NapCat 传输端验证 OneBot 认证、账号初始化、历史读取、实时事件和实际 action
发送契约；这些 fixture 仅存在于测试代码，不会进入生产构建。

## Design Reference

布局密度、会话列表层级和移动端单页切换借鉴了
[USTC-XeF2/mew-ui](https://github.com/USTC-XeF2/mew-ui)。本实现为独立重写，没有复制其源码、
favicon、QQ 表情或腾讯视觉资产；调研时该仓库没有可识别的开源许可证。
