# 嘟嘟哒：录制操作单

配音与剪辑由你完成。完整分镜和可直接朗读的旁白见 [五分钟稿](demo-video-runtime-validation-2026-09-05.md)。本页供录制时操作。

## 打开这些页面

| 页面 | 本机地址 | 用途 |
| --- | --- | --- |
| 录制控制台 | http://127.0.0.1:8786 | 重置并播放固定的四人讨论，查看实测结果。 |
| WebUI | http://127.0.0.1:5174 | 录制群聊、Agent 对话、配置和 MCP 工作台。 |
| 宣传海报 | http://127.0.0.1:8786/poster | 开场与收尾。 |
| 插件实测素材 | http://127.0.0.1:8786/plugins | 已生成的合成表情、曲目信息、谱面，以及复读和统计样例。 |
| 架构图 | http://127.0.0.1:8786/design | 最后 45 秒的设计介绍。 |

页面运行在准备这份材料的机器上。浏览器建议 1920 × 1080、100% 缩放。使用控制台的「WebUI 工作台」链接打开录制页面，便于重录时一并清理该页面的缓存。

## 从头启动

在项目根目录运行以下命令。准备命令复用本机已有的 AstrBot 模型配置、校园凭据和公开数据，创建独立的 `dududa-recording-astrbot` 实例。

```bash
uv run --locked python ops/cli/prepare_recording_environment.py --restart
uv run --locked python ops/cli/warm_recording_plugins.py
uv run --locked python ops/cli/prepare_recording_plugin_samples.py
cd apps/web
npm run build
npx tsx scripts/recording.ts
```

准备好的状态保存在项目旁的 `dududa-recording-state/`。若服务已经运行，直接打开页面即可。正常等待与查询过程可以在剪辑时缩短。

## 0—1：海报与 WebUI

1. 海报开场 15 秒，介绍「生活在 QQ 群里的 AI 群友」。
2. 进入 WebUI，选择「数学分析选课 · 四人模拟群」。
3. 展示联系人、消息区、Agent 对话、三档模型和配置页。
4. 使用下方任一已测问题完成一次 Agent 对话，再打开「运行」展示模型、耗时、能力与结果。

## 2：四人讨论与自适应插件

1. 在控制台点「重置场景」。评课初始关闭，自适应许可与主动搭话开启。
2. 回到 WebUI「配置」，拍清楚评课的关闭状态和自适应许可。
3. 在控制台点「播放20条讨论」，切回 WebUI 录制群聊。四名成员是小林、小周、小陈、小许，脚本逐条送入模拟 OneBot 通道。
4. 最后一句不 @ 嘟嘟哒。系统将这 20 条消息送入主动参与流程，并实际调用模型和 iCourse。
5. 等到回答出现，再打开配置查看「嘟嘟哒已启用」，拍摄四人的建议及对应评课链接。

第 20 条固定输入：

> 能查查评课社区的数学分析评价吗？请按我们四个人的需求各给一条选课建议，并附上对应的评课链接。

完整台词在 `tests/fixtures/recording/math-analysis-discussion.json`。控制台保留本次调用结果，包含 20 次状态变化、能力 ID 和最终答复。此段使用模拟群成员、真实模型与真实校园查询。

重录时重新点「重置场景」，从控制台链接重新进入 WebUI。不要在上一轮运行未结束时启动下一轮。

## 3：手动能力镜头

在当前群配置中开启要展示的插件，回到 Agent 对话，把回答长度选为「长」，粘贴固定问题。每段保留「开关 → 输入 → 完成结果」。

| 能力 | 固定输入 | 应出现的内容 |
| --- | --- | --- |
| 二课 | 二课里搜索英语角活动，列出活动名称和活动时间。 | English Corner 英语角、系列活动时间、报名状态。 |
| 教务 | 查询2026秋季学期数学分析的开课记录，列出课程名和任课教师。 | 数学分析(A1)/(B1)、任广斌、罗罗等实际返回的教师。 |
| 培养方案 | 查询2026级计算机科学与技术普通主修培养方案的总学分要求。 | 164 学分、2026 级、普通主修。 |
| 校园通知 | 查询最近三条校园通知，带标题、日期和来源链接。 | 三条通知及官网链接；内容随更新变化。 |
| 校车 | 列出工作日东校区到西校区上午的校车发车时刻。 | 东区→西区的工作日上午班次，保持始发站与经过站的区别。 |

完整的 26 项 MCP 原子查询清单和参数在 `tests/fixtures/recording/manual-capability-cases.json`，可在 MCP 工作台逐项演示。五分钟视频选上表代表功能即可。

插件镜头使用「插件实测素材」页：

- `/emoji 😀 😭`：真实 Emoji Kitchen 合成图片，已缓存。
- `/arc info Testify`：真实本地曲库信息与封面。
- `/arc chart Sayonara Hatsukoi ftr`：已生成的 Future 谱面。Testify 当前本地谱面文件为加密格式，因此谱面镜头选用已成功渲染的曲目。
- 复读：三个不同模拟成员发送「一起聊天，一起变好！」，真实处理器返回一次相同内容。
- `/sub2api status`：真实处理器处理固定统计样例，页面明确标为「统计样例」。

## 4：介绍设计

打开架构页，按 Context、Social Engine、Model Router、Capability/MCP、Persona 的顺序介绍。长期 Memory 接入、群友印象、多 OC 与 Skill 编排放在最后的持续建设部分。

## 复测命令

```bash
uv run --locked python ops/cli/run_recording_rehearsal.py --reset
uv run --locked python ops/cli/test_recording_answers.py
```

MCP 原子查询使用录制实例内的 Console：

```bash
recording_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dududa-recording-astrbot)
uv run --locked python ops/cli/test_recording_capabilities.py --url "http://${recording_ip}:8090"
```

实测报告存放于 `../dududa-recording-state/reports/`。录制配置的快速档保留轻量推理，标准档和深度档直接组织查询结果，回答篇幅独立设置。模型措辞会变化，验收重点是调用正确能力、回应四人的需求、引用真实来源。

## 本轮验证

验证日期：2026 年 9 月 6 日。

| 检查 | 结果 |
| --- | --- |
| 自适应群聊 | 四人 20 条消息；前 19 条评课关闭，第 20 条启用并实际查询，回答包含四人的建议和评课链接。 |
| MCP 原子查询 | 26 / 26 通过；包含 iCourse、二课、教务、培养方案、通知及五项可选校园服务。 |
| 自然语言问答 | 5 / 5 通过；实际模型调用预期能力，结果已逐项核对。 |
| 插件素材 | Emoji 合成、Arc 曲目信息与谱面已生成；真实复读和统计处理器的固定样例通过。 |
| Python 回归 | 60 项 Runtime / 社交测试、85 项插件测试、13 项最终 Runtime / 自适应 / 查询回归、2 项二课回归通过。 |
| Web | 114 项前端测试和 121 项服务端测试通过；类型检查与构建通过。 |
| 固定消息基准 | 100 条符合预期：94 条 Runtime 响应、6 条兼容入口；使用脚本模型和校园样例数据。 |

本轮修复了二课详情接口参数与院系树返回过大、通知查询误选来源字典、主动群聊上下文重复，以及配置页未及时显示自适应启用状态的问题。真实模型的句式与远端数据会变化；上面的固定问题、能力调用和结果是本次录制的实测依据。
