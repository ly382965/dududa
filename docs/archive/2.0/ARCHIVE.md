# Dududa 2.0 封存记录

封存日期：2026-10-15（北京时间）。Dududa 3.0 在独立开发分支上接入本机 Codex CLI；2.0 的完整源码、配置示例、测试、插件、文档和作品材料保留在以下 Git 快照中。

| 项目 | 封存位置 |
| --- | --- |
| 完整提交 | `f84c04dbefcb92735feaded4ab9f31281870b30f` |
| Annotated tag | `archive/dududa-2.0-20261015` |
| 封存分支 | `archive/2.0-frozen-20261015` |
| 完整源码副本 | [`legacy/2.0/`](../../../legacy/2.0/) |
| 原版中文 README | [README.md](../../../legacy/2.0/README.md) |
| 原版英文 README | [README.en.md](../../../legacy/2.0/README.en.md) |
| 原版中文兼容入口 | [README.zh-CN.md](../../../legacy/2.0/README.zh-CN.md) |

`legacy/2.0/` 保存完整的 2.0 仓库布局，包含 1,720 个归档文件；归档时逐项与封存提交的 Git blob 比较，内容一致。三个 README 及其相对链接都保持原样，可以直接在该目录中阅读。3.0 根目录移除了旧执行链、旧脚本和旧测试入口；共享的 Web、校园 MCP 与配置在根目录继续演进。

提交前还确认了 `legacy/2.0` 的完整 Git tree 与封存提交的 tree 完全一致，包含文件内容、路径和可执行权限。原有 Markdown 空格等也保持原样。仅用于旧源码的本机缓存和生成材料保存在开发机的 `dududa-state/archives/local-residuals-20261015/`；运行中的数据和凭据不搬入公开源码。

## 封存范围

Git 快照和 `legacy/2.0/` 源码副本均包括进入 3.0 开发前工作区中的 2.0 改动，以及 AstrBot 主执行链、`packages/dududa-agent`、QQ 接入、Web 控制台、校园 MCP、互动插件、私聊通知与作业服务、测试和历史验证材料。3.0 继续复用其中的业务模块；复用和后续修改不会改变封存提交。

这是源码封存。Git 未追踪的本机凭据、QQ 登录状态、数据库和运行目录不属于源码归档，不能从此提交恢复。2.0 文档中的测试结果属于当时的 2.0 环境，不作为 3.0 Runtime 验证结果。

封存引用用于查阅和恢复，不继续在其上开发，也不移动该 tag。Git 本身不对 tag 提供不可修改保护；需要远端保护时，可在代码托管平台上为归档引用配置相应规则。

## 查阅或恢复 2.0

在已有此 tag 的 Dududa 仓库根目录执行：

```bash
git show --stat archive/dududa-2.0-20261015
git worktree add --detach ../dududa-2.0 archive/dududa-2.0-20261015
```

随后在 `../dududa-2.0` 中按照原版 README 配置独立的运行目录和端口。此操作不会覆盖当前 3.0 工作区。若当前克隆缺少该 tag，需先从保存归档引用的仓库取得它；本地封存不代表远端已发布。

需要修复历史版本时，从快照创建新的维护分支，不修改封存分支：

```bash
git switch -c maintenance/2.0-fix archive/dududa-2.0-20261015
```

上述命令应在独立的 2.0 checkout 中执行。源代码回退不会自动回滚数据库或线上服务；请按原版部署文档使用对应版本的运行数据。

## 源码压缩包

封存时在开发机生成了源码包：

```text
/home/mmdustc/Code/dududa-state/archives/dududa-2.0-20261015.tar.gz
```

其他环境可以直接从相同 tag 生成相同版本的源码包：

```bash
git archive --format=tar.gz --prefix=dududa-2.0/ \
  -o ../dududa-2.0-20261015.tar.gz archive/dududa-2.0-20261015
```

新版本的使用方式与迁移状态见 [Dududa 3.0 README](../../../README.md)。
