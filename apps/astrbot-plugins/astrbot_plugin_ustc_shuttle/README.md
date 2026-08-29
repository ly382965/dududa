# 中国科大校车插件

该插件保存版本化静态时刻表，并实现 Dududa 通用 `BUILTIN` Capability
Provider。它不注册消息处理器；自然语言感知、权限、调用、总结和发送仍由
Dududa 2.0 Runtime 负责。

数据版本：

- 东区、西区、南区校园班车：2026-08-30
- 高新校区班车：2026-08-30
- 太湖路园区班车：2026-08-27

`holiday=true` 表示学期中节假日仍运行；`no_public_bus=true` 仅表示该趟
没有公交车辆运行，不表示班次取消。时刻表变更时应更新
`data/timetable.v1.json`，而不是在运行时抓取网页。
