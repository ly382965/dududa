# 嘟嘟哒私聊通知

定时通过 [SeminarRadar](https://github.com/ly382965/SeminarRadar) 查询科大研究生学术报告，
将可报名场次发到明确配置的 QQ 私聊。默认每 3 分钟检查一次，只推送 B 站直播和高新校区。
首次成功查询发送订阅确认和当前可报名报告，后续只发送此前未成功通知的报告。

同时可读取研究生系统“培养 > 我的作业”，向唯一指定收件人发送新作业和草稿文件。
学校作业入口为 `https://yjs1.ustc.edu.cn/gsapp/sys/wdzyappustc/*default/index.do`。

## 安装

将此目录安装到 AstrBot 的 `data/plugins/astrbot_plugin_dududa_notify`。
插件主体只使用标准库和 AstrBot API；查询与 PDF 渲染使用 Python 3.12 和 uv 的隔离环境：

```bash
docker exec dududa-astrbot-1 bash \
  /AstrBot/data/plugins/astrbot_plugin_dududa_notify/install_worker.sh
```

该命令将 SeminarRadar 固定版本及 pyustc 1.2.0 安装在
`data/plugin_data/astrbot_plugin_dududa_notify/worker-venv`，不更改宿主的 pyustc。
非 Docker 部署可以把虚拟环境路径作为脚本的第一个参数，并在配置中填写 `worker_python`。

PDF 使用 ReportLab 和 Markdown-it，嵌入中文字体。将 AR PL UMing 字体放在
`data/plugin_data/astrbot_plugin_dududa_notify/fonts/uming.ttc`，或设置
`DUDUDA_HOMEWORK_FONT` 指向可嵌入的中文 TrueType 字体。Linux 上也会读取
`/usr/share/fonts/truetype/arphic/uming.ttc`（`fonts-arphic-uming` 包）。
没有字体时会明确报错，不生成中文缺字的 PDF；PDF 渲染不进行学校认证或下载远程图片。

## 配置

在 AstrBot 插件设置中填写 OneBot 平台 ID 和收件人 QQ 号，再开启 `enabled`。
平台 ID 是 AstrBot 的连接标识，不能填写机器人 QQ 号。收件人与开关默认留空或关闭。

认证复用 `USTC_CAS_USR`、`USTC_CAS_PWD`；未设置时读取 `credentials_file` 或
`USTC_CAS_CREDENTIALS_FILE` 指向的 TOML 文件，字段为 `username` 和 `password`。
正式 Docker 部署已经挂载 `/run/secrets/ustc-cas.toml`，无需复制密码到插件配置。
查询子进程会为 `.ustc.edu.cn` 增加 `NO_PROXY`，通过本机网络直连校内站点，保留 HTTPS 证书校验。

认证适配包含学校 `analytics.ustc.edu.cn` 的 SSO 网关跳转，区分网关票据与研究生系统票据。
仅跟随已知学校认证端点，HTTP 回调地址统一使用 HTTPS 传输；不更改共享 pyustc 安装或保存登录票据。
`request_timeout_seconds` 同时应用于门户和 CAS 客户端，避免 CAS 默认的 5 秒超时提前中断登录。

查询器沿用 SeminarRadar 的登录、分页与筛选逻辑，不提交报名或退课请求。
讲座分页使用唯一报告编号 `BGBM` 排序，避免相同报告时间造成跨页重复；保留完整性检查，
通知展示仍按时间排序。
配置 `preferred_only=false` 可以通知全部地点的可报名报告。

## 作业草稿与提交

开启 `homework_enabled`，将 `homework_recipient` 设为 `recipients` 中的本人 QQ，
并填写 `homework_provider_id`（AstrBot 已配置的模型提供商 ID）；留空使用该私聊的当前模型。
默认每 3 分钟检查，可通过 `homework_interval_minutes` 调整。读取范围不限制学期。
轮询间隔计入本轮耗时，不再额外等待完整间隔；单轮超过间隔时完成后尽快再次检查。

- 冷启动发送全部未完成作业列表；日常轮询只通知新作业或要求更新。已提交作业不会重复起草。
- 作业摘要明确限定为研究生系统“培养 > 我的作业”，不代表 BB 或课程主页待办总数。
  逐条详情核实已提交记录，展示学校记录总数、已提交数及核验时间；重载后不重复发送不变的空摘要。
  学校业务错误或总数与核验结果不符时保留缓存，不发送“0 份”。
- 默认 PDF 只包含作业标题、课程和最新答案，不附系统提示或冗长问答包装。
  只有作业明确要求问答记录或个人评论时才附真实记录；完整调用记录仍保存在本地。
- 小测、测验、随堂和课堂练习使用简答风格，每个小问通常 2 至 4 句、约 100 字，尽量不超过 150 字。
  题目的明确字数、证明与步骤要求优先，不截断答案来凑字数。
- 作业附件支持文本、文本型 PDF、DOCX、HTML 和包含可读文件的 ZIP。
  不支持的格式、扫描图片或无法解析的附件需要人工阅读，不生成忽略这些附件的草稿。
- 私聊与学校提交均使用 PDF；本地保留 Markdown。未提交的旧 ZIP 会生成新版本 PDF，旧文件不被改写。
- “我的评论”留给本人填写。QQ 评论或改稿命令会产生新版本；本地文件修改不会自动同步。
- 模型不能调用提交工具。默认仍需指定 QQ 在指定平台私聊中明确确认。
- 本人明确授权后可开启 `homework_auto_submit_enabled`，在距离截止
  `homework_auto_submit_minutes`（默认 3）分钟内自动提交最新 PDF，不再逐份要求确认。
  独立任务每 10 秒检查已发现作业的截止时间；临近截止时重新查询学校，再提交并核对回执。
  不等待 QQ 文件发送成功才能自动提交；成功后尝试发送实际提交的 PDF。
  可关闭自动提交开关并重载插件，恢复逐份确认。
- 提交前重新核对本人身份、最新作业要求、是否可编辑及是否已有提交，不覆盖已有答案。
  上传使用保存版本的相同 PDF 字节，并读取学校作业详情核对结果。
- 未到自动提交窗口、已过期、附件不可读或学校关闭提交时不强行上传。
  已过期作业仍列出，但不自动起草。网络中断、认证故障或过晚发现作业仍可能导致错过截止。
- 提交超时或响应不明确时不自动重传，再次确认只读取学校记录进行核实。
  自动检查也只读取记录核实不确定结果，不会盲目重复上传；作业移出未交列表或截止之后，
  未核实记录仍每 3 分钟只读核对一次。
  如仍无法核实，需在学校页面检查处理，不能用反复确认覆盖不确定状态。

私聊命令（编号与版本以实际通知为准）：

```text
作业 列表
作业 要求 H1
作业 草稿 H1
作业 评论 H1 1 我的评论内容
作业 改稿 H1 修改意见
作业 确认 H1 v2
```

作业状态、实际问答和版本文件保存在插件数据目录 `homework-<QQ>/` 中，不进入仓库。
可将人工核对过的参考资料放在该目录 `H<编号>-sources.md`，起草时会随题目提供给模型。
默认不自动联网检索：没有原文或检索证据的引用必须标为待核实。
读取学校使用现有 pyustc 凭据，生成草稿会将作业题目及可读附件发给所配置的模型提供商。

## 助教空周汇报自动提交

明确授权后开启 `weekly_enabled`，沿用 `homework_recipient` 作为唯一通知收件人。
从[助教系统周汇报页面](https://tam.cmet.ustc.edu.cn/ustcta-pc/#/stu-week-report-student/index)
读取本人当前学期的全部分页，使用已有 CAS 凭据，不保存登录票据或 token。

- 默认 `weekly_report_day=first`：系统列出的首个汇报日，北京时间 `weekly_submit_hour=20` 点执行。
  不是把每周六写死；目前学校公布的汇报日为周六、周日，因此选择周六。
- 平时默认每 3 分钟检查，可通过 `weekly_interval_minutes` 调整；接近 20:00 时提前唤醒到该时点，
  不因常规轮询间隔延后提交计划；实际提交受学校认证和网络耗时影响。
  当天 20:00 后恢复运行且入口仍开放时可补尝试，不跨日补交，不提交过期记录。
- 只走页面原有的提交前检查、空汇报确认和提交接口，只发送记录编号及学期编号。
  不填写正文、不上传附件、不调用模型、不修改学生学业信息。
  网站的空汇报确认含义为“没有学生学业信息需要汇报”；发现已有学业信息时不自动提交，并私聊提醒人工确认。
- 已提交记录跳过；已撤回记录不自动重新提交。提交后重新读取学校记录，确认状态与提交时间。
  学校会更换提交后的记录编号，因此以学期、课堂、助教和汇报周保存唯一提交记录。
- 请求超时、进程中断或学校回执不明确时，只读核对，不重复发送提交请求。
  核对成功后私聊通知；仍无法确认时需人工查看页面。
- 本人可私聊 `周汇报 状态` 查看本期状态和下次计划。关闭 `weekly_enabled` 并热重载插件即可停止。

状态保存在插件数据目录 `weekly-<QQ>/state.sqlite3`；独立于讲座、作业自动提交和课程日报。

## 全课程任务与课件日报

开启 `courses_enabled`，沿用 `homework_recipient` 指定的唯一私聊所有者。
课程检查默认每 3 分钟一次，每日北京时间 **20:00** 发送当天新增/更新课件的摘要。
`courses_interval_minutes` 和 `courses_summary_hour` 可调整；`course_sources` 为空时使用七门课程的默认登记表：

- 算法设计与分析：指定课程主页的作业区和课件区。
- 计算机应用数学、机器学习、计算机系统：指定 BB 课程资源、子文件夹与课程通知。
- 高级人工智能：读取原作业插件已经成功同步的数据，保留原有 PDF/自动提交流程；尚无课件来源。
- 高级计算机网络：[课程主页](https://acn-2026.github.io/)的论文汇报、选做实验与课件区。
  线上/线下汇报标注为二选一，不把其他同学的汇报日期当成本人 DDL；只读 PPT 列的课件，不混入参考论文。
- 组合数学：待补充入口，不把未接入显示成“没有作业”。

BB 使用已有 CAS 凭据和官方登录回调，仅访问这些课程的资源与通知。
新课程功能不注册提交工具、不打开测验启动页面，不继承原作业插件的自动提交授权。
可在 `course_sources` 增加/替换 BB 的 `blackboard` 入口；其他网站需增加对应读取器。

- 新任务/要求更新主动私聊；明确到时分的 DDL 在提前 24、6、1 小时分别提醒一次。
  轮询首次发现已进入更紧迫阶段时只发送当前阶段，不补发全部旧阶段。
- 只有日期时提醒核对具体时刻，不伪造 23:59；相对期限、冲突日期或没有明确日期时标为待确认。
  高网省略年份的日期使用主页注明的课程年份；实验起止区间取结束时间，明确跨年的日期保留原年份。
- BB/网站不能可靠核实完成状态时明确标注未知，提供本地完成标记以停止提醒。
- HTTP ETag/Last-Modified 用于避免重复下载。首次连接的旧课件只建存量，不冒充今日新增。
  首次连接时源修改日期就是今天的课件会纳入今日日报；之后按实际发现的新增/修改记录。
  GitHub Pages 的发布时间不能代表文件上传时间，因此高网首批课件仅登记存量；后续按文件内容判断更新，整站重建不触发重复摘要。
- 每份课件按实际正文生成 3 至 5 条要点。长材料分段阅读再合并，不只读文件名、不静默截取开头。
  PDF 字体映射损坏、扫描件、解析失败或文件过大时明确标注限制，不编造内容。
- 日报为同一份数据生成的课程 **list + PNG 图片**，文字带原文链接。20:00 后有新增内容会补充汇报。
  已投递进度、摘要与提醒保存在 `courses-<QQ>/state.sqlite3`，重启不会重发不变内容。
  若日报生成时有课程同步失败，当天该来源恢复后会补发 list + PNG 修正版；
  以已送达修正版为准去重，图片发送失败只重试图片，不重复生成全文。
  插件重载后先完成本轮课程查询，再执行定时日报，避免把上次运行的状态当作新核验结果。
- 单一来源失败保留缓存并标注异常，连续 3 次失败后通知一次，恢复后通知。
  本插件只能覆盖已配置入口，QQ群公告、口头布置、未提供的网站不在自动读取范围。

私聊命令：

```text
课程 列表
课程 今日
课程 状态
课程 完成 C1
课程 恢复 C1
课程 截止 C1 2026-09-29 23:59
```

“列表”发送待办 list 与图片，“今日”再加入当天课件摘要，“状态”提供快速文字结果。
“完成”只停止课程提醒，不代表学校已经收到作业，也不取消原作业助手的自动提交设置。
“截止”只保存本人提供的北京时间，不修改学校原始数据。

课件依赖在 worker 环境安装；旧版 PPT 使用无界面 LibreOffice 转 PPTX 后提取正文：

```bash
docker exec dududa-astrbot-1 bash /AstrBot/data/plugins/astrbot_plugin_dududa_notify/install_worker.sh
docker exec dududa-astrbot-1 bash /AstrBot/data/plugins/astrbot_plugin_dududa_notify/install_course_readers.sh
```

第二条命令针对 Debian 13 容器安装 `catdoc` 和 `libreoffice-impress-nogui`。
容器重建后需重新安装这些系统依赖或加入部署镜像。PDF/PNG 共用前文配置的中文字体。
课件正文会发送到已配置的模型提供商进行总结，但不把 CAS 凭据、cookie 或登录票据发给模型。

## 投递与运行

- 通知使用 OneBot `send_private_msg` 和纯文本消息段，只向配置的收件人发送。
- 本插件不向 LLM 注册发信工具，也不新增群聊权限。
- 报告按来源、平台、收件人和报告编号保存在 `deliveries.sqlite3` 中。
  收到 OneBot 的 `message_id` 后才记为成功；失败会在下次检查重试，重启后保留发送记录。
- 默认每轮每位收件人最多 5 条消息，未投递且仍可报名的报告会在后续轮次发送。
- 同一报告成功通知后不会因剩余名额或其他字段变化再次提醒。此前满员、后来有名额且未通知过的报告会提醒。
- 关闭 `enabled` 并重载此插件即可停止。插件退出会取消计时任务并终止正在运行的查询进程。
- AstrBot 日志中的 `SeminarRadar poll complete` 包含查询数和发送数；错误日志不包含凭据或登录票据。
- 作业或讲座检查连续失败 3 次后私聊告警一次，持续失败不刷屏，成功恢复后再通知。
  `作业 状态` 显示本次启动后的最近成功时间；检查异常时会明确标记列表为缓存结果。
- 学校可能以 HTTP 200 返回数据库异常页。插件识别 `Could not get JDBC Connection` /
  `PoolDisabledSQLException`，明确报告学校数据库不可用，不误当作正常登录或缺失身份。
  作业入口退回本地登录页时明确报告会话失效；空值身份不会被转换为字符串 `None` 后继续查询。
- 异常响应仅记录时间、固定路径、HTTP 状态、学校节点号、响应大小和白名单错误特征，
  保存在 worker 环境旁的 `portal-diagnostics/`，每类最多两份 128 KiB 日志。
  不保存响应正文、cookie、票据、学号或请求参数。学校写入之后发生数据库异常仍按结果不明核对，不重传。

QQ 的发送与本地 SQLite 写入无法构成同一事务。如果消息已被 QQ 接收，但进程在落盘前终止，
或 QQ 回执丢失，下次检查可能重复发送该条消息。

## 本地验证

```bash
uv run --locked --with lxml --with python-pptx python -m unittest tests.test_private_notifications tests.test_homework_notifications tests.test_notification_auth tests.test_course_notifications tests.test_weekly_reports tests.test_install_plugins
```

测试使用模拟 QQ、合成作业和学校接口，不登录学校、不发送真实消息、不提交真实作业。
PDF 渲染测试需要 `reportlab`、`markdown-it-py`、`pypdf` 和上述中文字体；缺少时仅跳过渲染测试。
