# ADR 0007：删除根路径别名，保留稳定操作入口

- 状态：已接受，S22 已实施
- 日期：2026-08-10
- 决策范围：S17 路径迁移后的根入口、环境模板和兼容 symlink

## 背景

S17 将源码和配置权威迁至 `apps`、`configs`、`services/mcp`、`deploy`、`ops` 和
`third_party`，同时保留十个一 Release symlink。根 `manage.sh`、`compose.yml` 和
`.env.example` 的用途不同：前两者是有意稳定的操作入口，环境模板只是可被 canonical 路径
直接替代的文件别名。

S19 已生成消费者清单、完整离线候选和回滚证据。S22 进一步迁移了字符串扫描遗漏的分段路径
和 Python import 消费者，因此无需继续维护两组可见路径。

## 决策

1. 保留根 `manage.sh` 和 `compose.yml`，它们只转发到 `ops/manage.sh` 和
   `deploy/compose/compose.yml`，不形成第二份实现。
2. 删除根 `.env.example`；唯一可提交模板为 `deploy/env/.env.example`，`.env` 仍是本机私有
   覆盖。
3. 删除 `config`、`docker`、`plugins`、`scripts`、`patches`、`vendor`、根
   `plugins.lock.json`、`services/icourse-mcp` 和 `services/unified-mcp-worker` symlink。
4. 当前代码、CI、测试和操作文档只使用 canonical 路径。历史 baseline、旧 Verification 和
   S19 immutable catalog 可以保留旧名称，但必须属于明确的历史证据。
5. 已持久化第三方 lock marker 中的旧 patch/vendor 字符串继续由读取时归一化兼容；这不是文件
   系统别名，也不能重新创建 symlink。

## 后果

- 仓库只有一组源码、配置和第三方 v1 authority，路径扫描与 import 不再依赖 symlink。
- 旧外部脚本若直接读取根 `.env.example` 或旧目录必须升级；上一 S19 Release 仍可独立恢复。
- 容器内 `/AstrBot/data/plugins`、`/AstrBot/data/icourse-mcp`、`/opt/dududa/config` 和
  `/opt/dududa/scripts` 是部署 API，不受主机源码目录清理影响。

## 回滚

不在当前 Release 临时重建 symlink。需要回滚时恢复精确 S19 candidate 及其 source archive、
环境模板和 Compose contract，避免产生当前代码加旧路径的混合状态。

## 复审条件

- 根 operator wrapper 不再有外部消费者；
- Compose 入口需要跨仓或已安装发行物；
- Manifest v2 取得完整 integrity、lock、SBOM 和许可证证据并准备替换 schema v1。
