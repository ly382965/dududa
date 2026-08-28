# USTC 第二课堂 75 题 Dududa 2.0 原生消息模拟报告

> 记录日期：2026-08-29。该报告使用固定本地 Young MCP fixture、脚本化模型语义和
> 内存 Fake Delivery；事件由测试代码手工构造为 OneBot-shaped Event，不经过 NapCat、
> AstrBot Filter 调度或真实 QQ 回执，不访问真实二课账号，也不经过 Dududa 1.0。

## 结论

- OneBot-shaped 原生消息：75/75。
- 2.0 Runtime 完成：75/75。
- Fake Delivery：75/75；真实 QQ 发送：0。
- Unified MCP 调用：62；不调用边界：13。
- 模型调用：150（75 次 Perception + 75 次 Direct Chat，均为脚本 Fake）。
- 唯一链路：手工 OneBot-shaped Event -> Dududa 2.0 Rollout Bridge -> Connector -> Hybrid Perception -> Planner -> Capability Runtime -> Unified MCP -> Young MCP -> Observation -> DirectChat -> Composer -> Persona/Final Validator -> Fake Delivery。
- 禁止面：`young_list_my_activities`、报名、取消、申请人、Web search、ReplyPolish 和旧命令路由均未执行。
- 个人请求负例：Case 70 中脚本模型故意提出 Young 公共搜索，确定性资格过滤将其移除，最终 MCP 调用为 0。

## 证据边界

这份结果证明路由、参数投影、MCP 契约、结构化 Observation、最终输出和正确不调用。
聚焦语义断言覆盖日期、报名窗口、余位阈值、填充率排序、容量、学时效率、五育覆盖和
规模比较，不只检查有无回复。脚本 Fake 不能证明真实 Luna/Terra/Sol 的中文理解和总结质量；
另行执行的 Luna Review 只是旁路审校证据，不是 Runtime 已发送的回复。上下文追问也准确暴露了
当前 Production Context 只含本轮消息的限制，没有伪造前序对话。

## 逐题结果

### Case 1：今日与本周

**Q：** 今天还有哪些二课活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-29T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T00:00:00", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0。

### Case 2：今日与本周

**Q：** 今晚有什么第二课堂活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-29T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T18:00:00", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120。

### Case 3：今日与本周

**Q：** 明天有哪些二课可以参加？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-30T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-30T00:00:00", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28；校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4。

### Case 4：今日与本周

**Q：** 后天有什么第二课堂活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-31T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-31T00:00:00", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110。

### Case 5：今日与本周

**Q：** 本周剩下还有哪些二课？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-30T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T09:30:00", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28；校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0。

### Case 6：今日与本周

**Q：** 这个周末有哪些二课？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-30T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T00:00:00", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28；校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0。

### Case 7：今日与本周

**Q：** 未来三天有哪些第二课堂活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-31T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T09:30:00", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28；校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4；科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0。

### Case 8：今日与本周

**Q：** 最近一周已经结束的二课有哪些？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-29T09:30:00", "limit": 50, "query": "", "start_time": "2026-08-22T09:30:00", "state": "history"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 科技史专题讲座，时间 2026-08-22T19:00:00，有效学时 2，余位 50。

### Case 9：今日与本周

**Q：** 今天有人工智能前沿公开讲座吗？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-29T23:59:59", "limit": 50, "query": "人工智能前沿公开讲座", "start_time": "2026-08-29T00:00:00", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120。

### Case 10：今日与本周

**Q：** 未来十天有哪些二课？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `planner_boundary`；输出 `forward` / 2 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28；校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4；科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110；新生体能训练体验，时间 2026-09-01T17:00:00，有效学时 1.5，余位 15；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0；生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500。当前单步查询只能给出这一层结果，不能继续自动展开下一层详情。

### Case 11：德智体美劳

**Q：** 二课有哪些官方模块？

**2.0 调用：** `ustc-young/young_list_facets` `{"facet": "module"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前公开筛选项包括：德育、智育、体育、美育、劳育。

### Case 12：德智体美劳

**Q：** 二课有哪些官方标签？

**2.0 调用：** `ustc-young/young_list_facets` `{"facet": "label"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前公开筛选项包括：学术讲座、志愿服务。

### Case 13：德智体美劳

**Q：** 二课活动有哪些组织单位？

**2.0 调用：** `ustc-young/young_list_facets` `{"facet": "department"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前公开筛选项包括：校团委。

### Case 14：德智体美劳

**Q：** 现在有哪些德育活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110。

### Case 15：德智体美劳

**Q：** 现在有哪些智育活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0；生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500。

### Case 16：德智体美劳

**Q：** 现在有哪些体育活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 新生体能训练体验，时间 2026-09-01T17:00:00，有效学时 1.5，余位 15。

### Case 17：德智体美劳

**Q：** 现在有哪些美育活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28。

### Case 18：德智体美劳

**Q：** 现在有哪些劳育活动？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4。

### Case 19：德智体美劳

**Q：** 德智体美劳各推荐一个当前活动。

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 德育：科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110；智育：人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；体育：新生体能训练体验，时间 2026-09-01T17:00:00，有效学时 1.5，余位 15；美育：校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28；劳育：校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4。

### Case 20：德智体美劳

**Q：** 德智体美劳是二课官方模块名吗？

**2.0 调用：** `ustc-young/young_list_facets` `{"facet": "module"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前公开筛选项包括：德育、智育、体育、美育、劳育。

### Case 21：报名窗口

**Q：** 当前哪些二课仍在报名而且有余位？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `forward` / 3 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120，容量 300，已报名 180，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28，容量 100，已报名 72，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4，容量 40，已报名 36，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110，容量 200，已报名 90，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；新生体能训练体验，时间 2026-09-01T17:00:00，有效学时 1.5，余位 15，容量 60，已报名 45，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500，容量 500，已报名 0，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中。

### Case 22：报名窗口

**Q：** 哪些二课今天报名截止？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `forward` / 3 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；新生体能训练体验，时间 2026-09-01T17:00:00，有效学时 1.5，余位 15，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中。

### Case 23：报名窗口

**Q：** 人工智能前沿公开讲座什么时候截止报名？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "人工智能前沿公开讲座", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120，容量 300，已报名 180，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中。

### Case 24：报名窗口

**Q：** 校园美育艺术赏析的报名窗口是什么时候？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "校园美育艺术赏析", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28，容量 100，已报名 72，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中。

### Case 25：报名窗口

**Q：** 机器人社团小组工作坊现在还能报名吗？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "机器人社团小组工作坊", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0，容量 12，已报名 12，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；活动已满，按当前公开条件不能报名。

### Case 26：报名窗口

**Q：** 已结束的科技史专题讲座还能报名吗？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "科技史专题讲座", "state": "history"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 科技史专题讲座，时间 2026-08-22T19:00:00，有效学时 2，余位 50，容量 200，已报名 150，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 结项；当前状态不在报名中，按当前公开条件不能报名。

### Case 27：报名窗口

**Q：** 生涯发展系列讲座现在能报名吗？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "生涯发展系列讲座", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500，容量 500，已报名 0，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中；按当前公开状态、报名窗口和余位判断，可以报名。

### Case 28：报名窗口

**Q：** 二课服务现在连接正常吗？

**2.0 调用：** `ustc-young/young_connection_status` `{}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 第二课堂查询服务当前可用，认证配置正常。

### Case 29：报名窗口

**Q：** 人工智能讲座的报名截止时间和活动时间分别是什么？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "人工智能前沿公开讲座", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座：报名截止 2026-08-29T18:00:00；活动时间 2026-08-29T19:00:00 至 2026-08-29T21:00:00。

### Case 30：余位

**Q：** 人工智能前沿公开讲座还剩多少名额？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "人工智能前沿公开讲座", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120。

### Case 31：余位

**Q：** 校园美育艺术赏析还剩多少名额？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "校园美育艺术赏析", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园美育艺术赏析，时间 2026-08-30T14:00:00，有效学时 2，余位 28。

### Case 32：余位

**Q：** 校园劳动志愿服务还剩多少名额？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "校园劳动志愿服务", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4。

### Case 33：余位

**Q：** 机器人社团工作坊是不是已经满了？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "机器人社团小组工作坊", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0。

### Case 34：余位

**Q：** 今天的二课分别还剩多少名额？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-29T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T00:00:00", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；机器人社团小组工作坊，时间 2026-08-29T15:00:00，有效学时 1，余位 0；生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500。

### Case 35：余位

**Q：** 当前余位最多的二课是哪一个？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500。

### Case 36：余位

**Q：** 当前还能报名的活动里哪个余位最少？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4。

### Case 37：余位

**Q：** 找出至少还剩 100 个名额的二课。

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120；科学精神与学术道德，时间 2026-08-31T19:00:00，有效学时 2，余位 110；生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500。

### Case 38：余位

**Q：** 把当前二课按报名填充率排序，列出前三项。

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 机器人社团小组工作坊，报名 12/12，填充率 100%；校园劳动志愿服务，报名 36/40，填充率 90%；新生体能训练体验，报名 45/60，填充率 75%。

### Case 39：学时效率

**Q：** 人工智能前沿公开讲座有多少有效学时？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "人工智能前沿公开讲座", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120。

### Case 40：学时效率

**Q：** 今天有哪些二课能拿 2 学时？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-29T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T00:00:00", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，时间 2026-08-29T19:00:00，有效学时 2，余位 120。

### Case 41：学时效率

**Q：** 周末活动里哪个有效学时最多？

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-30T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T00:00:00", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园劳动志愿服务，时间 2026-08-30T08:00:00，有效学时 3，余位 4。

### Case 42：学时效率

**Q：** 当前二课按有效学时除以活动时长排序。

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 科学精神与学术道德，2 学时/1.5 小时=1.3 学时/小时，余位 110；人工智能前沿公开讲座，2 学时/2 小时=1 学时/小时，余位 120；校园美育艺术赏析，2 学时/2 小时=1 学时/小时，余位 28；校园劳动志愿服务，3 学时/3 小时=1 学时/小时，余位 4；新生体能训练体验，1.5 学时/1.5 小时=1 学时/小时，余位 15；机器人社团小组工作坊，1 学时/3 小时=0.33 学时/小时，余位 0。

### Case 43：学时效率

**Q：** 2 小时讲座和 3 小时志愿服务哪个学时效率高？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座和校园劳动志愿服务都是 1 学时/小时，按当前记录学时效率相同。

### Case 44：学时效率

**Q：** 机器人工作坊活动 3 小时却只有 1 学时吗？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "机器人社团小组工作坊", "state": "applying"}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 是。机器人社团小组工作坊活动时长 3 小时，有效学时 1。

### Case 45：学时效率

**Q：** 系列讲座入口显示 0 学时，是否代表参加子活动也没有学时？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "生涯发展系列讲座", "state": "applying"}`

**完成类型：** `evidence_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 系列入口本身显示 0 学时，但当前搜索结果没有展开子活动，不能据此推断每个子活动也都是 0 学时。这些记录不包含历史抢报、个人签到或实际考核结果，不能据此补猜。

### Case 46：学时效率

**Q：** 当前哪些二课比较适合混学时？请按学时、时长和明确要求说明。

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `evidence_boundary`；输出 `forward` / 2 part。

**实际 Fake Delivery：** 按当前公开条件可优先比较：科学精神与学术道德，2 学时/1.5 小时=1.3 学时/小时，余位 110，要求：公开主题报告，无需提交作品；人工智能前沿公开讲座，2 学时/2 小时=1 学时/小时，余位 120，要求：面向全校学生的公开讲座，无选拔要求，现场签到；校园美育艺术赏析，2 学时/2 小时=1 学时/小时，余位 28，要求：艺术作品赏析与交流，面向全校学生；校园劳动志愿服务，3 学时/3 小时=1 学时/小时，余位 4，要求：需要按分组完成校园公共区域整理；新生体能训练体验，1.5 学时/1.5 小时=1 学时/小时，余位 15，要求：需穿运动服装，根据个人身体情况参加。这里只比较公开学时、时长、余位和明确要求，不保证实际获得学时。这些记录不包含历史抢报、个人签到或实际考核结果，不能据此补猜。

### Case 47：学时效率

**Q：** 本周哪些二课学时效率高？不要猜签到、考核和抢报难度。

**2.0 调用：** `ustc-young/young_search_activities` `{"end_time": "2026-08-30T23:59:59", "limit": 50, "query": "", "start_time": "2026-08-29T09:30:00", "state": "applying"}`

**完成类型：** `evidence_boundary`；输出 `forward` / 2 part。

**实际 Fake Delivery：** 按当前公开条件可优先比较：人工智能前沿公开讲座，2 学时/2 小时=1 学时/小时，余位 120，要求：面向全校学生的公开讲座，无选拔要求，现场签到；校园美育艺术赏析，2 学时/2 小时=1 学时/小时，余位 28，要求：艺术作品赏析与交流，面向全校学生；校园劳动志愿服务，3 学时/3 小时=1 学时/小时，余位 4，要求：需要按分组完成校园公共区域整理。这里只比较公开学时、时长、余位和明确要求，不保证实际获得学时。这些记录不包含历史抢报、个人签到或实际考核结果，不能据此补猜。

### Case 48：规模比较

**Q：** 当前容量最大的二课是什么？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 生涯发展系列讲座，容量 500，已报名 0，余位 500。

### Case 49：规模比较

**Q：** 当前容量最小的二课是什么？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 机器人社团小组工作坊，容量 12，已报名 12，余位 0。

### Case 50：规模比较

**Q：** 当前报名人数最多的活动是什么？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，容量 300，已报名 180，余位 120。

### Case 51：规模比较

**Q：** 当前报名填充率最高的活动是什么？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 机器人社团小组工作坊，报名 12/12，填充率 100%。

### Case 52：规模比较

**Q：** 仍可报名的活动里填充率最高的是哪个？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 校园劳动志愿服务，报名 36/40，填充率 90%。

### Case 53：规模比较

**Q：** 找出容量至少 200 人的活动。

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `bounded_aggregation`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 人工智能前沿公开讲座，容量 300，已报名 180，余位 120；科学精神与学术道德，容量 200，已报名 90，余位 110；生涯发展系列讲座，容量 500，已报名 0，余位 500。

### Case 54：规模比较

**Q：** 二课里 300 人的大讲座和 12 人的小工作坊，哪个更容易报名？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `evidence_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 按当前公开数据，人工智能前沿公开讲座余位 120，机器人社团小组工作坊余位 0、已经满员；因此大讲座当前更容易报名，但不能仅凭规模推断历史报名难度。这些记录不包含历史抢报、个人签到或实际考核结果，不能据此补猜。

### Case 55：规模比较

**Q：** 这些活动里哪个历来最难抢？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "", "state": "applying"}`

**完成类型：** `evidence_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 没有历史抢报数据，不能判断哪个活动“历来”最难抢；当前只能看到机器人社团小组工作坊，报名 12/12，填充率 100%。这些记录不包含历史抢报、个人签到或实际考核结果，不能据此补猜。

### Case 56：系列活动

**Q：** 活动 ID：series-career-2026 的所有子活动有哪些？

**2.0 调用：** `ustc-young/young_get_activity` `{"activity_id": "series-career-2026", "include_children": true}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 子活动包括：生涯发展系列讲座第一场，时间 2026-08-29T09:00:00，有效学时 1.5，余位 180。

### Case 57：系列活动

**Q：** 活动 ID：series-career-2026 的详情是什么？

**2.0 调用：** `ustc-young/young_get_activity` `{"activity_id": "series-career-2026", "include_children": false}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500，容量 500，已报名 0，报名窗口 2026-08-20T08:00:00 至 2026-08-29T18:00:00，状态 报名中，要求：系列入口，请查看各子活动场次。。

### Case 58：系列活动

**Q：** 活动 ID：series-career-child-1 的详情是什么？

**2.0 调用：** `ustc-young/young_get_activity` `{"activity_id": "series-career-child-1", "include_children": false}`

**完成类型：** `evidence_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 没有查到这个活动 ID 对应的活动，请核对 ID。

### Case 59：系列活动

**Q：** 生涯发展系列讲座有哪些场次？

**2.0 调用：** `ustc-young/young_search_activities` `{"limit": 50, "query": "生涯发展系列讲座", "state": "applying"}`

**完成类型：** `planner_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 生涯发展系列讲座，时间 2026-08-29T09:00:00，有效学时 0，余位 500。当前单步查询只能给出这一层结果，不能继续自动展开下一层详情。

### Case 60：系列活动

**Q：** 活动编号 series-career-2026 是系列活动吗？

**2.0 调用：** `ustc-young/young_get_activity` `{"activity_id": "series-career-2026", "include_children": false}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 生涯发展系列讲座的类型是 series，因此它是系列活动。

### Case 61：系列活动

**Q：** 活动编号 series-career-2026 这个系列的第一场几点？

**2.0 调用：** `ustc-young/young_get_activity` `{"activity_id": "series-career-2026", "include_children": true}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 第一场是生涯发展系列讲座第一场，开始时间 2026-08-29T09:00:00。

### Case 62：系列活动

**Q：** 活动 ID：series-career-2026 的所有场次各多少学时？

**2.0 调用：** `ustc-young/young_get_activity` `{"activity_id": "series-career-2026", "include_children": true}`

**完成类型：** `direct_fact`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 各场次学时：生涯发展系列讲座第一场 1.5 学时。

### Case 63：上下文追问

**Q：** 这个活动几点结束？

**2.0 调用：** 不调用

**完成类型：** `context_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 我这轮没有拿到你指的活动名称或活动 ID，暂时不能确定结束时间。把活动名或 ID 发来，我可以继续查。

### Case 64：上下文追问

**Q：** 它还剩几个名额？

**2.0 调用：** 不调用

**完成类型：** `context_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 目前缺少“它”对应的活动名称或活动 ID，不能可靠计算余位。请补充具体活动。

### Case 65：上下文追问

**Q：** 第一个多少学时？

**2.0 调用：** 不调用

**完成类型：** `context_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前消息里没有可解析的活动列表，所以无法判断“第一个”指哪项。请发活动名或 ID。

### Case 66：上下文追问

**Q：** 它为什么不能报名？

**2.0 调用：** 不调用

**完成类型：** `context_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 我还不知道“它”是哪项活动，不能判断是已满、过了报名窗口还是状态已结束。请给出活动名或 ID。

### Case 67：上下文追问

**Q：** 哪个余位更多？

**2.0 调用：** 不调用

**完成类型：** `context_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前消息没有给出要比较的活动，无法可靠比较余位。请把两个活动名或 ID 一起发来。

### Case 68：上下文追问

**Q：** 把它的所有场次展开。

**2.0 调用：** 不调用

**完成类型：** `context_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前缺少系列活动的名称或 ID，无法展开场次。请补充系列活动 ID。

### Case 69：上下文追问

**Q：** 这个活动怎么样？

**2.0 调用：** 不调用

**完成类型：** `context_boundary`；输出 `plain` / 1 part。

**实际 Fake Delivery：** “这个活动”目前没有明确指代。请给出活动名或活动 ID，我再按时间、学时、容量和要求帮你判断。

### Case 70：正确拒绝

**Q：** 我参加过哪些二课？

**2.0 调用：** 不调用

**完成类型：** `correct_refusal`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前没有 QQ 用户与第二课堂账号的绑定，不能把部署服务账号当成你本人，也就不能查询你参加过的活动记录。

### Case 71：正确拒绝

**Q：** 我个人累计了多少第二课堂学时？

**2.0 调用：** 不调用

**完成类型：** `correct_refusal`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前没有个人第二课堂账号绑定和个人学时账本，无法查询你的累计学时。

### Case 72：正确拒绝

**Q：** 帮我报名人工智能前沿公开讲座。

**2.0 调用：** 不调用

**完成类型：** `correct_refusal`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 目前二课能力只读，不能替你报名。可以继续帮你查活动时间、报名窗口和当前余位。

### Case 73：正确拒绝

**Q：** 帮我取消机器人社团工作坊的报名。

**2.0 调用：** 不调用

**完成类型：** `correct_refusal`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 目前二课能力只读，不能替你取消报名。

### Case 74：正确拒绝

**Q：** 查一下这个二课有哪些人报名、我签到成功了吗？

**2.0 调用：** 不调用

**完成类型：** `correct_refusal`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 当前不提供申请人名单或个人签到查询，也没有你的第二课堂账号绑定，不能回答这两项个人信息。

### Case 75：正确拒绝

**Q：** 周末有什么活动？

**2.0 调用：** 不调用

**完成类型：** `correct_refusal`；输出 `plain` / 1 part。

**实际 Fake Delivery：** 你说的活动范围还不明确；如果是中国科大第二课堂，请明确说二课或第二课堂，我再按周末时间查询。
