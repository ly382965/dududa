# MCP 工作台：公开缓存查询

管理员进入会话配置中的「MCP 工作台」。刷新仅读取状态；每张卡的「检测连接」
只执行 MCP 握手和工具发现，不查询业务数据、不刷新缓存。成功显示「连接正常」
不等于数据实时；检测时间来自真实检查，未检测的服务不再显示绿色“可调用”。

选择下方 Capability，`query` 留空可浏览，输入关键词可过滤。结果保留官方来源、
缓存更新时间和时效说明。某次搜索无匹配记录不等于缓存为空；未初始化的缓存
返回 `ok:false`。仅已登记的只读能力可调用，浏览器不提交任意 URL 或工具名。

| 服务 | 数据边界 |
| --- | --- |
| campus-events | 中国科大官网首页及教学、科研、管理公告列表；正文以来源链接为准 |
| college-notice | 数学、计算机、物理学院综合通知，不代表所有学院 |
| library | 官网日常开放时间，假期、考试周和临时调整以专项公告为准 |
| training-plan | 官网分年份本科专业设置一览，不是个人培养计划；停招需查原表 |
| local-recs | 历史人工整理的校园生活参考；营业时间、价格与评分未实时核验 |

这五项定义与映射单独存放在 `configs/console-capabilities`，仅由 Console 加载。
共享 Runtime Capability Catalog、自动规划类别和群权限不变。服务只开放一个
只读查询工具，不开放 refresh/crawl/write。需 Bot 自动调用时须另行配置权限和路由。

## 首次数据初始化和刷新

使用已安装依赖的 Python，在发布副本运行：

```sh
python ops/cli/refresh_console_caches.py --cache-root /absolute/private/mcp-public-caches
```

可用 `--service library` 只更新一项。工具只抓取固定公开列表页，不抓附件、不进行
历史全站爬取，局部移除代理环境变量。失败返回非零；空解析不会替换已有表。
local-recs 仅在空库导入仓库种子，不能把导入时间当作营业信息的核验时间。

把每个服务目录映射到 `/AstrBot/data/<service>-cache`，源码发布副本映射到
`/AstrBot/data/<service>-mcp`，配置映射到 `/opt/dududa/config`。缓存目录需要可写，
因为 SQLite 初始化/WAL 会写文件；这并不授予模型刷新或修改数据的工具权限。
不要把数据、凭据、私人部署 manifest 或镜像导出提交到 Git。

## 验证与回退

运行生成器 `python ops/cli/generate_console_capability_config.py --check`，再运行
Console、公共来源、Web 类型/单元测试。部署后实际检测五项，并执行空 query、
limit=1 的只读调用，核对非空条目和数据时间。仅检查容器存活不算查询验证。
更新 exact Compose 服务，保留前一镜像/配置；不得创建第二个 NapCat 或改其他站点。
回退使用保存的上一 manifest，只恢复此次修改的 Web/MCP 镜像与挂载，不删除缓存。

## DeepSeek 迁移边界

官方 V4 支持 `low/high/max`；Dududa 三档建议 Flash low、Flash high、Pro max。
`maximum` 在 GPT 仍映射 `xhigh`，在 DeepSeek 映射 `max`。见
[官方参数说明](https://api-docs.deepseek.com/guides/thinking_mode/)。
保存 Key 池不会自动更新 Runtime。当前源码提供「应用到 Runtime」按钮：校验同一
保存版本、实际 Provider 请求和独立证据后，只交换 Dududa 自有实例，不热重载其他
AstrBot 消费者；失败保留旧 Runtime。部署侧 CLI 冷安装仍要求停止宿主。应用后还需
独立验证 no-send preview，不能把探测成功等同于对话成功。详见
[API Key Pool 同步边界](../development/api-key-pool-runtime-sync.md)；此处不声明
新版已部署或已通过线上验收。

DeepSeek 官方启用自动缓存，不能声称零留存。`runtime_allow_provider_retention`
默认 false；使用 `provider_managed` 必须取得管理员知情确认，不能复制旧模型的
零留存证据。参见[官方缓存说明](https://api-docs.deepseek.com/news/news0802/)。
额外推理 token 预算与可见短/中/长回答限制分开；健康探针使用非思考模式的有界
合成内容，不把“只有推理、没有最终答案”当成可用。
