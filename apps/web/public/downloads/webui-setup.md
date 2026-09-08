# 工作台管理入口配置指引

## QQ 离线

工作台网关在线不代表 QQ 已登录。请打开该账号实际部署的 NapCat WebUI，检查 QQ 登录态和连接到嘟嘟哒的 WebSocket Client；恢复后回到聊天页点击“重新检测”。NapCat WebUI 地址由部署管理员提供。

## 群服务

群服务依赖独立的 Bot Control Plane 后端。管理员需在 Web Gateway 环境中设置 `DUDUDA_CONTROL_PLANE_URL`，值为网关可以访问的该后端地址。不要将 QQ 网关或 Agent 预览地址当作群服务后端。

后端可用后，还需要其有效的操作员会话和群服务配置；连接成功不会自动授权 Bot 发送消息。配置应用后，点击“重新检测群服务”。后端尚未部署时，此入口保持不可用。

## 人工内测

管理员需要准备真实的脱敏样本，以及独立可写的人工评价存储。Web Gateway 使用以下环境变量，路径均为其运行环境内的绝对路径：

- `DUDUDA_INTERNAL_TEST_DATA_ROOT`：脱敏样本数据根，只读。
- `DUDUDA_INTERNAL_TEST_FEEDBACK_PATH`：评价 JSONL 文件，父目录需可写。

使用容器时需要挂载相应目录，不能直接使用宿主机路径代替容器路径。仓库 `deploy/compose/compose.internal-test.yml` 提供 Compose 配置示例；其中 `DUDUDA_INTERNAL_TEST_HOST_DATA_ROOT` 和 `DUDUDA_INTERNAL_TEST_HOST_FEEDBACK_DIR` 指定宿主机目录。Provider 配置另见仓库 `apps/web/README.md`，不应把密钥填入浏览器。

应用配置后，点击“重新检测内测数据”。没有可用脱敏样本时，请先准备样本；工作台不会生成虚构数据来填补空状态。

## 搜索历史

左侧筛选匹配会话名称、QQ 号和最新消息摘要。聊天页的“搜索聊天记录”仅查找当前浏览器缓存，可使用关键词、发送人和日期筛选；需要更早历史时，在账号在线后浏览聊天历史，或到“设置 → 历史补齐”读取指定日期。

“总结近期讨论”只处理本轮读取的近期窗口；实际条数和时间覆盖范围以运行结果为准。
