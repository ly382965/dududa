# Sub2API 只读统计插件

这个 AstrBot 插件复用 Sub2API 管理网页自身调用的 JSON API，查询用量、排名、
模型分布和上游账号状态。它不是数据库客户端，也不模拟点击页面。

## 命令

```text
/sub2api overview
/sub2api today
/sub2api total
/sub2api range 2026-07-01 2026-07-24
/sub2api trendtotal [天数d]
/sub2api trenduser [天数d]
/sub2api trenduser sum [天数d]
/sub2api users [开始日期] [结束日期]
/sub2api models [开始日期] [结束日期]
/sub2api accounts
/sub2api account <账号ID>
/sub2api status
/sub2api help
```

`overview` 固定生成一条 QQ 合并转发消息，包含四个节点：

1. 今日用量与 Token 用户排名；
2. 当前计费轮累计、已发生的 Pro 重置次数与时间点、Token 用户排名；
3. 从 2026-07-13 至今的历史累计与 Token 用户排名；
4. 上游账号状态。

当前计费轮的起止时间和 Pro 额度观测来自费用分摊网站的只读快照，成员
明细继续使用原插件的 Sub2API 管理员只读用量接口，按照网站给出的精确
起点聚合。重置次数与时间点依据本轮起点、既有 Bot 查询日志和当前上游
窗口估算，并在消息中明确标为估算值。`overview` 之外的命令、权限、缓存、客户端和错误处理保持原插件
行为；`total` 仍展示服务记录的全历史累计数据。

命令组别名为 `/sub2` 和 `/用量`，子命令也提供对应中文别名。日期范围包含首尾
两天，默认单次最多查询 90 天。

`trendtotal` 展示全站每日 Token 总量，`trenduser` 展示区间 Token 前 10 名用户
各自的每日变化。两者默认查询最近 7 天，也可使用 `/sub2api trenduser 30d` 指定
天数；最大天数与 WebUI 中的 `max_range_days` 一致。趋势图复用管理网页的
`snapshot-v2` 数据，通过 Pillow 生成 PNG 并直接发送，不保存到磁盘。旧命令
`/sub2api trend 30d` 继续作为 `trendtotal` 的兼容别名。

`/sub2api trenduser sum 30d` 将每日用量转换为从区间起始日开始的逐日累计值；
每条曲线的最后一个点等于该用户的 30 天区间总 Token。累计图使用从 0 开始的
标准线性 Token 坐标轴；省略天数时默认 7 天。

两类趋势图均使用经过每日真实点的保形平滑曲线；Y 轴采用 `sqrt(Token)`，
兼容零用量日期，并动态保留 10% 上下余量，使数据覆盖约 90% 的绘图高度。

## 配置

在 AstrBot WebUI 的插件配置中填写：

- `base_url`：Sub2API 根地址；
- `admin_email`、`admin_password`：管理员登录信息；
- `group_whitelist`：允许调用命令的 QQ 群号；
- `exclusive_groups`：只允许使用 Sub2API、静默屏蔽其他功能的 QQ 群号；
- `private_user_whitelist`：允许私聊调用的 QQ 号；
- 其余字段控制缓存、排名数量、脱敏和日期上限。

群聊和私聊白名单均为默认拒绝。用户邮箱和账号注册邮箱默认脱敏；打开
`reveal_user_identifiers` 后才显示完整地址。凭据只应存在于 AstrBot
私有运行数据中，不能写入这个仓库。也可以在容器运行环境中提供
`SUB2API_BASE_URL`、`SUB2API_ADMIN_EMAIL` 和 `SUB2API_ADMIN_PASSWORD`，环境变量优先。

## 只读边界

业务客户端只允许以下固定 GET 路径：

- `/api/v1/admin/dashboard/stats`
- `/api/v1/admin/dashboard/snapshot-v2`
- `/api/v1/admin/dashboard/user-breakdown`
- `/api/v1/admin/usage`
- `/api/v1/admin/usage/stats`
- `/api/v1/admin/accounts`
- `/api/v1/admin/accounts/{id}/today-stats`
- `/api/v1/admin/system/version`

唯一的 POST 是 `/api/v1/auth/login`，用于取得内存中的短期访问令牌。插件不保存
token，不跟随重定向，不调用任何 PUT、PATCH、DELETE 或业务 POST。账号列表响应中
即使包含凭据字段，客户端也会立即丢弃，只把状态字段交给格式化层。原始账号响应
不会进入缓存；短期缓存中只保存已剔除凭据的状态字段。

插件明确不调用 `/admin/accounts/{id}/usage`、配额探测、凭据导出、刷新、测试、
清错、启停或合规确认等接口，因为其中一些看似查询的接口会探测上游或持久化状态。
