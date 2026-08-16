# Dududa Web

嘟嘟哒的真实 QQ 多账号工作台。浏览器不直连 NapCat：同源 Node 网关接收 NapCat 的 OneBot 11
反向 WebSocket，在服务端执行受限 action，再向 Vue 前端提供 HTTP + SSE。

生产代码不包含演示账号、虚构群聊或模拟 Agent 输出。账号、联系人、群、历史消息和发送结果均来自
当前 NapCat 连接；浏览器 IndexedDB 只缓存 NapCat 返回的规范化消息、历史覆盖范围、会话和操作员草稿，
不作为另一个 QQ 数据源。清理浏览器缓存不会修改 QQ 数据。

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
npm ci
npx playwright install chromium
DUDUDA_ONEBOT_TOKEN_FILE=../../runtime/web/secrets/onebot_access_token \
npm run dev
```

开发模式启动端口 `8000` 的 Gateway 和端口 `5173` 的 Vite UI。NapCat 必须能够访问 Gateway；
独立启动默认只监听 `127.0.0.1`。NapCat 位于容器或其他主机时，应在受保护网络内显式设置
`DUDUDA_WEB_BIND=0.0.0.0`；Compose 部署使用上面的 `dududa-web-api` 网络别名，同时宿主发布端口仍默认
绑定 `127.0.0.1`。

## S23 Web 人工内测页

该页面用于浏览既有脱敏样本、生成一次真实 Provider 的候选回答并追加人工评价，不要求连接 NapCat
或登录 QQ。启动前配置数据根和仓库外的反馈文件绝对路径：

```bash
cd apps/web
export DUDUDA_INTERNAL_TEST_DATA_ROOT=/绝对路径/脱敏测试数据根
export DUDUDA_INTERNAL_TEST_FEEDBACK_PATH=/绝对路径/internal-test-feedback.jsonl
npm run dev
```

打开 `http://127.0.0.1:5173/#/internal-test`。未设置有效的数据根时，页面会明确显示不可用，不会回退到
仓库内演示数据。

如果本机已有连接 NapCat 的正式 Web Gateway，可让人工内测页复用它的 QQ 工作区，同时保留本地
`no-send` 内测 API。例如正式 Gateway 在 `5173`、本地开发 Gateway 在 `8000` 时：

```bash
export VITE_PORT=5174
export DUDUDA_API_TARGET=http://127.0.0.1:5173
export DUDUDA_INTERNAL_TEST_API_TARGET=http://127.0.0.1:8000
npm run dev
```

这样普通 `/api` 请求使用已经完成 OneBot 认证的 Gateway，`/api/internal-test` 仍只进入本地内测
Gateway，无需复制 Token 到浏览器，也无需为开发进程新增 NapCat 连接。

真实 Provider 为可选配置：

```text
DUDUDA_INTERNAL_TEST_BASE_URL
DUDUDA_INTERNAL_TEST_API_KEY
DUDUDA_INTERNAL_TEST_PROVIDER
DUDUDA_INTERNAL_TEST_CODEX_CONFIG
DUDUDA_INTERNAL_TEST_AUTH_FILE
DUDUDA_INTERNAL_TEST_HAIKU_MODEL
DUDUDA_INTERNAL_TEST_SONNET_MODEL
DUDUDA_INTERNAL_TEST_OPUS_MODEL
```

三级默认模型映射为 `haiku -> gpt-5.6-luna`、`sonnet -> gpt-5.6-terra`、
`opus -> gpt-5.6-sol`，可通过上述变量覆盖。页面仅执行操作员显式触发的候选生成：不发送 QQ、
不写 Memory、不调用 Tool、不连接 Bandit；它是人工评价入口，不构成 AstrBot Runtime Shadow 或真实群验证。

本入口已运行的聚焦验证命令：

```bash
npm run typecheck
npx vitest run src/views/InternalTestView.spec.ts src/App.spec.ts
npx vitest run --config vitest.server.config.ts server/internal-test.spec.ts
npm run build
```

## Supported QQ Surface

- `get_login_info`、`get_status`、`get_version_info`；
- `get_group_list`、`get_friend_list`、`get_recent_contact`；
- `get_group_msg_history`、`get_friend_msg_history`；
- 绑定账号和会话的签名历史游标，以及前后方向分页；
- `send_group_msg`、`send_private_msg`、`get_msg`，当前安全发送段包括文本、回复、提及和 QQ face；
- `message`、`message_sent` 与群/好友撤回事件；
- 有序规范化文本、回复、提及、QQ/市场表情、图片、语音、视频、文件、合并转发、Markdown、
  Light App 和未知消息段；
- 每账号能力文档，明确区分已实现、协议缺失、权限不足和暂时不可用；
- QQ 用户/群头像代理，以及允许的 QQ CDN 媒体映射。

网关没有“任意 OneBot action”转发接口。Cookie、Credential、原始本地路径和 OneBot Token 不会下发
浏览器。浏览器 API 当前暂不启用登录，默认只应绑定本机回环地址；对外发布前必须在反向代理补充认证。
QQ 头像与历史图片是上游的短期数据，失败时前端使用明确降级状态。

缓存主键均包含 `accountId` 与会话 ID。Blob URL、Data URL、`base64://`、`file://` 和原始本地路径
不会写入 IndexedDB。当前 NapCat 没有 QQ 同步置顶、群文件夹重命名和完整普通好友申请历史 action，
这些能力会明确显示为不支持，不使用本地假成功补齐。

NapCat 无法保证补齐 QQ 离线期间未同步到本机的全部消息；本工作台也不会伪造初始未读、置顶或免打扰
状态。未读数仅从当前页面收到的实时事件开始计算。

Agent Console 已接入本机内测 Runtime。页面通过独立状态接口判断 Runtime 是否可用，
不再把“是否已建立 Session”误当成连接状态。操作员可以在当前 QQ 会话上创建临时内测
Session，选取最近最多 30 条消息作为上下文，并调用现有三档 Provider 生成候选回答。

候选仅留在浏览器临时会话中；该链路固定为 `NO SEND / NO MEMORY WRITE / NO TOOL CALL /
NO BANDIT`，不会调用 QQ 发送接口。`answerProfile` 可分别路由到 `haiku / sonnet / opus`，
当前控制台默认使用中等长度。这是人工内测 Adapter，不代表 AstrBot 中的正式 Agent Runtime 已完成接入。

## Verification

```bash
npm audit --omit=dev --audit-level=high
npm run test
npm run typecheck
npm run build
npm run test:e2e
```

服务端测试使用一个内存中的假 NapCat 传输端验证 OneBot 认证、账号初始化、历史读取、实时事件和实际 action
发送契约；这些 fixture 仅存在于测试代码，不会进入生产构建。

## Design Reference

布局密度、会话列表层级和移动端单页切换借鉴了
[USTC-XeF2/mew-ui](https://github.com/USTC-XeF2/mew-ui)。本实现为独立重写，没有复制其源码、
favicon、QQ 表情或腾讯视觉资产；调研时该仓库没有可识别的开源许可证。
