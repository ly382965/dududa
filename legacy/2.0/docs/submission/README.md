# 嘟嘟哒提交报告

本轮完成第 1 项设计文档与第 4 项作品简介，使用 LaTeX 编写并编译为 PDF。材料采用技术报告语体，统一了当前实现、独立组件、历史原型和后续研究的状态说明。

| 文件 | 用途 |
| --- | --- |
| [01_设计文档.pdf](pdf/01_设计文档.pdf) | 完整架构、场景、功能、模型 API、独立 WebUI 设计章节、技术难点、部署与验证 |
| [04_作品简介.pdf](pdf/04_作品简介.pdf) | 独立介绍背景、问题、功能、架构、WebUI、创新点、模型与 API、成果与边界 |
| [本地文档汇总.md](本地文档汇总.md) | 所有相关本地技术资料的主题归纳、条目和采用方式 |
| [source-inventory.json](source-inventory.json) | 446 个逻辑条目及 8,944 份文档/副本的位置；441 份当前或独立来源 |
| [latex/design-report.tex](latex/design-report.tex) | 设计文档主文件，正文分章维护 |
| [latex/work-introduction.tex](latex/work-introduction.tex) | 作品简介主文件 |
| [validation/benchmark-summary.json](validation/benchmark-summary.json) | 本轮复跑 100 条离线流程的实际结果 |
| [validation/检查记录.md](validation/检查记录.md) | 编译、版面、内容及交付检查结果 |

## 编译

在本目录运行：

```bash
bash build_reports.sh
```

脚本优先使用 `tectonic`，也支持已安装的 `latexmk`/`xelatex`。Tectonic 可通过 `TECTONIC=/绝对路径/tectonic` 指定。首次运行需要网络下载 TeX 宏包；后续可使用本地缓存。

本次实际使用 Tectonic 0.17.0。重要的是显式传入 `-Z search-path=vendor`，使编译器使用随材料提供的 ElegantPaper v0.12，而不是发行版中可能较旧的模板。脚本已经包含该参数。XeLaTeX 路径通过 `TEXINPUTS` 实现相同效果。

XeLaTeX 环境需要 CTeX、Fandol 字体、TikZ、BibLaTeX、fvextra、booktabs、tabularx、longtable、fancyhdr 等常用宏包。文献采用手工编号的本地来源与官方链接，模板加载 BibLaTeX 时使用兼容的 BibTeX 后端。编译产物写入 `latex/build/`，最终两份 PDF 写入 `pdf/`。

## 模板与内容维护

实际采用 [ElegantPaper](https://github.com/ElegantLaTeX/ElegantPaper) v0.12（2026-02-27），上游类文件和 LPPL 许可证在 `latex/vendor/`。模板保持原样，项目风格在 `latex/preamble.tex`：A4 单栏、Fandol 宋体/黑体、深灰正文、藏蓝标题、三线表和 TikZ 矢量图。选择时同时对照 ElegantBook 与 CTeX 官方资料，详见 [模板说明](latex/README.md)。

本轮没有修改应用代码、运行配置、QQ 状态、演示视频或可部署程序包。源码开始核对时 HEAD 为 `2b52593`，主仓已有其他任务的在途改动；报告不把当前工作树与所有历史运行实例等同。

作品名称统一为“嘟嘟哒”，封面、页眉、正文与 PDF 元数据同步更新。设计文档第 10 节“WebUI 设计”独立介绍信息架构、工作台布局、数据同步、Agent 交互、模型和工具管理、异常反馈与典型操作；部署、验证和资料整合依次为第 11、12、13 节。作品简介另有“WebUI 工作台设计”专节。原始资料索引保留其历史标题与文件名。

## 文档汇总口径

主仓设计/研究/ADR/开发/运行/评测文档与阶段记录、历史原型与插件、旧 PDF/Word、嘟嘟哒文档站、外部试用与部署记录均在清单中。工作树和发布副本按逻辑路径归并，历史版本不覆盖当前源码事实。凭据、聊天数据库、私有运行配置、第三方依赖文档和批量数据条目不纳入正文。

`build_source_inventory.py` 是本次文档清单的整理脚本，默认以主仓旁的 Code 目录为相关资料根。清单是报告准备阶段的资料快照；除非需要重新整理资料，不必在每次编译时重跑，也不要将新生成报告重新计入原材料。

提交目录中的旧设计文档和作品简介已保留在历史版本目录，新提交请使用本轮 PDF。两份 PDF 可独立阅读；评审者不需要 LaTeX 环境。源码链接指向 GitHub 仓库，PDF 与程序附件可独立提交。

创新点已按“自适应插件选择、任务驱动的自适应路由、自适应群聊参与与表达、WebUI 工作台设计”组织，摘要和模型路由说明同步更新。当前成稿为设计文档 36 页、作品简介 5 页。
