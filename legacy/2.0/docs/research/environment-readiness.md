# 开发环境就绪报告

## 1. 结论

截至 2026-08-09，Dududa 主仓的 Python 与 Web 开发环境已经具备锁定、干净重建和双版本
验证能力。当前结论只覆盖本地开发和离线测试，不代表 Agent 已装配进运行中的 AstrBot。

| 项目 | 修复前 | 当前状态 | 判定 |
| --- | --- | --- | --- |
| TreeWork | `tw` 不在 PATH；0.1.6 Map 仍运行 | PATH 指向 0.1.7；旧 Map 已停止；0.1.7 已重渲染 | ready |
| Python 声明 | 两个子项目范围依赖，无根 lockfile | 根 uv workspace、`.python-version`、`uv.lock` | ready |
| Python 3.10 | 仅 uv 解释器；未覆盖新增脚本 | 3.10.20 干净环境 375 项通过 | ready |
| Python 3.12 | 系统 3.12.3，SQLite 3.45.1 | uv 3.12.13，SQLite 3.53.1，375 项通过 | ready |
| Web 依赖 | `node_modules` 不完整 | Node 22.18.0 下 `npm ci` 可重建 | ready |
| npm 安全 | `nanoid 3.3.16` 高危公告 | lockfile 固定 3.3.18；production audit 为 0 | ready |
| Playwright | 浏览器缓存缺失 | Chromium 1234、FFmpeg 1011 已安装，6 项 E2E 通过 | ready |
| Compose | 旧 Bot 栈和新 Web 栈并存 | 只读形态已确认；完整主仓 Compose 仍禁止并行启动 | guarded |
| Agent production shape | 库级测试通过但纵向链未闭合 | 三个 P0 断点及部署差距已记录 | not ready |

## 2. 依赖契约

根 `pyproject.toml` 只承担 monorepo 的开发/测试环境，不发布产品包。工作区成员仍由各自
`pyproject.toml` 声明运行依赖；插件测试所需的 `httpx`、`jsonschema` 和 Pillow 在根
`dev` group 中作为直接依赖列出，避免偶然借用其他 package 的传递依赖。

`scripts/setup_dev.sh` 使用：

```text
uv python install 3.12.13
uv sync --locked --python 3.12.13
```

因此“裸 Python 缺模块”不再是正常开发路径。CI 同样以 `uv.lock` 为输入，并在 3.10.20、
3.12.13 上分别构建 wheel、编译源码和运行完整测试。

## 3. 实际验证证据

| 验证 | 结果 |
| --- | --- |
| `uv lock --check` | pass，39 packages |
| Python 3.10.20 干净 `uv sync --locked` | pass，SQLite 3.53.1 |
| Python 3.10.20 全仓 unittest | pass，375 tests，2 skipped |
| Python 3.12.13 干净 `uv sync --locked` | pass，SQLite 3.53.1 |
| Python 3.12.13 全仓 unittest | pass，375 tests，2 skipped |
| `npm ci` | pass，306 packages，0 vulnerabilities |
| `npm test` | pass，66 frontend + 42 server |
| `npm run typecheck` | pass |
| `npm run build` | pass |
| `npm run test:e2e` | pass，6 Playwright tests |
| `npm audit --omit=dev --audit-level=high` | pass，0 vulnerabilities |
| `docker compose --env-file .env.example config --quiet` | pass；未启动服务 |
| TreeWork `tw version` / `tw graph render` | `tw 0.1.7` / pass |

第一次 Python 3.10 干净运行发现 `scripts/configure_napcat_web.py` 导入 3.11 才提供的
`datetime.UTC`。改用等价的 `timezone.utc` 后，针对性测试和 3.10 全仓测试均通过。这是
兼容性门禁发现并修复的代码问题，不是通过放宽版本范围规避。

MCP 1.29.0 与解析到的 `pydantic-settings 2.15.0` 组合还会产生 `lifespan` 前向引用警告。
隔离对照证明 2.14.2 可在 `-W error` 下完成相同离线握手，因此 v1 过渡期显式限制为
`>=2.14.2,<2.15.0`；迁移 MCP v2 时必须重新验证并删除该临时上界。

## 4. SQLite 安全约束

SQLite 官方在 2026 年披露 WAL-reset corruption bug：3.7.0 至 3.51.2 在同一 WAL 数据库
存在多个连接并同时写入/checkpoint 的特定竞态下可能损坏；3.51.3 修复。来源：
[SQLite WAL 文档](https://www.sqlite.org/wal.html#walresetbug)，访问日期 2026-08-09。

本机事实：

- Ubuntu Python 3.12.3：SQLite 3.45.1，不可作为并发 WAL 验证环境；
- uv Python 3.10.20/3.12.13：SQLite 3.53.1，可用于本地门禁；
- 运行中上游 AstrBot 镜像：Python 3.12.13、SQLite 3.46.1，仍处受影响范围。

当前 `SQLiteRolloutLedger` 和 iCourse storage 都启用 WAL。不得因为单进程单元测试通过就
声称生产并发安全。下一阶段必须在派生镜像固定 SQLite 3.51.3+，或先改用 rollback journal
配合 `BEGIN IMMEDIATE`/CAS 并验证双 Worker；本 Goal 不修改运行容器或数据库。

## 5. Web 环境说明

`vue-router 5.2.0` 依赖 Babel 8，其 engine 要求 Node `^22.18.0 || >=24.11.0`。旧 Node
20.20.2 虽能通过当前测试，却会产生真实 `EBADENGINE`，因此开发基线升级到 22.18.0。
运行中的 Web 镜像仍是旧构建的 Node 20.20.2；它健康且有 1/1 NapCat 账号在线，本 Goal
没有重建、替换或重启该容器。

Playwright 配置已改为显式 `chromium`，避免把系统安装的 Chrome 当作隐式依赖。测试前后
4174/8180 均无残留监听进程。

## 6. 剩余非阻断项

- Vite 报告主 JS chunk 约 923 kB；这是 Web 性能工作，不影响测试工具环境。
- npm 输出 `glob@10.5.0` 弃用提示；当前 audit 为 0，后续随上游升级处理，不执行强制升级。
- `docs/research/production-shape-preflight.md` 的断点仍阻止 Agent 生产切流。
- 当前 Web 与旧 AstrBot/NapCat 属于两个 Compose 项目；只能在明确迁移窗口内调整所有权。
