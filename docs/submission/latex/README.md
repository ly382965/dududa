# 嘟嘟哒提交报告 LaTeX 源码

本目录采用 ElegantPaper v0.12（2026-02-27）中文工作论文模板，模板原文件放在 `vendor/`，排版调整集中在 `preamble.tex`。正文采用 Fandol 宋体，标题采用 Fandol 黑体，字体随 TeX 发行版提供；A4 单栏，深灰正文、少量藏蓝，不使用海报、角色插画或装饰性贴纸。

- 上游：https://github.com/ElegantLaTeX/ElegantPaper
- CTAN：https://ctan.org/pkg/elegantpaper
- 许可证：LPPL 1.3c 或更新版本，见 `vendor/LICENSE-ElegantPaper`。
- 对照模板：ElegantBook 适合较长书籍；本次两份技术材料选择结构较轻的 ElegantPaper，以便保持一致版式。
- 中文排版依据：https://ctan.org/pkg/ctex

完整编译方法和交付说明见上一级 README。模板来源及访问日期：2026-09-06。上游类文件保持原样，项目正文和附加样式与上游模板分开维护。

标题样式使用 CTeX 的 `heading=true` 与 `ctexset` 配置，选项依据 [CTeX 官方文档源码](https://github.com/CTeX-org/ctex-kit/blob/master/ctex/ctex.dtx)。封面不创建重复页码锚点，摘要使用独立锚点。具体编译、目录跳转和图表渲染结果见 `../validation/检查记录.md`。
