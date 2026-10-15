# 嘟嘟哒 · 智能体／可部署程序文件

本包用于提交材料第 3 项。包含完整程序源码、可安装的智能体 wheel、Web 前后端产物、Docker Compose、一键启动脚本，以及本次构建的 **Linux amd64 Docker 镜像**。

## 三步启动

1. 安装并启动 [Docker Desktop](https://docs.docker.com/get-started/get-docker/)；Linux 也可以使用 Docker Engine + [Docker Compose 插件](https://docs.docker.com/compose/install/)。选择 Linux 容器。建议给 Docker 分配至少 8 GB 内存，预留 20 GB 磁盘空间。
2. **完整解压 ZIP**，进入 `dududa` 文件夹。
3. Windows 双击 **`start.cmd`**；Linux / macOS 在该文件夹打开终端执行：

   ```bash
   bash start.sh
   ```

首次启动会自动导入随包镜像、创建数据卷、安装预置插件、初始化人格和内部连接，再等待四项服务启动。**无需在电脑上安装 Python、Node.js、uv 或 Git，也无需手动建目录和修改文件权限。** 随包镜像齐全时，安装依赖不需要联网；实际 QQ 登录、模型调用、校园查询仍需网络。

成功后打开同目录的 **`initial-login.txt`**，查看初始登录信息。每次新安装自动生成随机凭据。已修改的密码不会被再次启动重置。

| 页面 | 默认地址 | 用途 |
| --- | --- | --- |
| 嘟嘟哒 WebUI | http://127.0.0.1:5173 | 群工作区、Agent、模型、插件与运行记录 |
| AstrBot 管理页 | http://127.0.0.1:6185 | 模型 Provider、Dududa Core 和目标群配置 |
| NapCat | http://127.0.0.1:6099 | 用自己的 QQ 扫码登录 |

如果端口被占用，修改自动生成的 `quickstart.env` 中三个端口，再运行启动脚本。控制台 `status` 显示的映射端口为准；登录文件中的地址标注了默认端口。

## 首次使用智能体

1. 打开 NapCat，用 `initial-login.txt` 中的 Token 登录，再用自己的 QQ 扫码。到 AstrBot 和 WebUI 的 OneBot 连接已预配置，无需运行旧版 `web-connect` 命令。
2. 配置自己的模型 API 与 Dududa Core。源码的 Runtime 初始为关闭，首次还需建立三档 Provider、对应的 Runtime 端点配置和 Provider 验证记录；**仅在 WebUI 保存 Key 不等于已完成首次模型接入**。详细字段和现有接入工具见 [程序使用说明第 5 节](docs/operations/submission-program.md#5-配置真实智能体)与 [Runtime 配置说明](docs/development/api-key-pool-runtime-sync.md)。这些配置工具和 Python 均已包含在 AstrBot 镜像内，脚本位于 `/opt/dududa/repository/ops/cli/`。
3. 选择自己的测试群，按上述说明启用群回复。之后可以在 WebUI 调整插件、路由和主动参与，并检查运行记录。

校园公开数据服务可以先不配置 CAS；二课认证等功能需要时在 `quickstart.env` 填入自己的 `USTC_CAS_USR` 和 `USTC_CAS_PWD`，再运行启动脚本。程序包不含任何已登录 QQ、作者的 API Key、校园账号或聊天数据。

## 日常操作

| 操作 | Windows | Linux / macOS |
| --- | --- | --- |
| 启动或继续使用 | 双击 `start.cmd` | `bash start.sh` |
| 停止，保留账号和配置 | `start.cmd down` | `bash start.sh down` |
| 查看状态 | `start.cmd status` | `bash start.sh status` |
| 查看日志 | `start.cmd logs` | `bash start.sh logs` |
| 查看初始登录信息 | `start.cmd credentials` | `bash start.sh credentials` |
| 从源码重新构建并启动 | `start.cmd build` | `bash start.sh build` |

数据保存在名称以 `dududa-quickstart_` 开头的 Docker 数据卷中。正常停止不会删除数据。后续使用保留 `quickstart.env` 中的项目名，即可继续使用相同账号和配置。镜像已导入后，可删除 `images/dududa-images-amd64.tar.gz` 节省硬盘；重新构建会联网下载构建依赖。

## 程序文件位置

| 内容 | 位置 |
| --- | --- |
| 一键启动 | `start.cmd` / `start.ps1` / `start.sh` |
| Docker Compose 和初始化程序 | `deploy/quickstart/` |
| 预构建镜像（AstrBot + MCP、Web、NapCat） | `images/dududa-images-amd64.tar.gz` |
| 智能体安装包 | `dist/wheels/dududa_agent-0.1.0a1-py3-none-any.whl` |
| 智能体源码 | `packages/dududa-agent/` |
| Web 源码及构建结果 | `apps/web/` |
| 插件与校园服务 | `apps/astrbot-plugins/`、`services/mcp/` |
| 构建与启动验证 | `validation/一键部署验证.md` |

核心应用来自 [GitHub 2b52593](https://github.com/ly382965/dududa/tree/2b525935fb2d6977e19765cc4283c73ec01b72ec)，本包在该源码上增加便携部署入口。原有 `manage.sh` 和生产 Compose 保留；本包请从 `start.cmd` / `start.sh` 启动。

随包镜像的架构为 Linux amd64，已在 x86-64 Linux Docker 环境实测；Windows / macOS 使用 Docker Desktop 的 Linux 容器，启动入口已提供，但未在这两种系统上实际运行。Apple Silicon 需要 Docker 的 amd64 仿真支持，本次没有实测。实际模型效果与 QQ 登录由部署者的账号、模型服务和网络决定。
