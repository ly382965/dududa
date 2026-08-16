# astrbot_plugin_dududa_core

嘟嘟哒核心插件，负责统一命令入口、权限、审计、课程查询和管理骨架。

当前已实现：

- `/help`、`/dududa help`
- `/about`、`/ping`、`/status`、`/privacy`
- `/course stats/search/review/compare/refresh`
- `/admin status/plugins/mcp/logs/group/user/memory/model/backup/restart/permission/broadcast`
- `/confirm`、`/cancel`
- `/remember`、`/forget`、`/memory`、`/style`
- `/image`、`/fortune`、`/draw`
- `/meme`、`/poke`、`/reread` 仅保留停用兼容提示，不调用旧插件

边界：

- 当前只接入评课社区 `icourse` MCP。
- 教务系统、成绩、个人课表、考试查询仍为 TODO。
- gpt-image-2 已接入 `/image <描述>`，仅 trusted/admin 可用，默认等待超时 420 秒。
- `/admin restart` 与 `/admin broadcast` 只进入确认和审计，不在 QQ 命令内直接重启容器或群发。
- Meme Manager、PokePro、Reread 已退出 Dududa 2.0 干净安装默认集合。
- Target Talk 源码和配置保留，但不再由默认 Compose 挂载；主动参与由受治理的 Probe/主动 Runtime 承担。
- Reply Polish 是默认关闭、仅处理显式 LONG 回答的 Dududa 1.0 输出兼容层，不属于 2.0 正式输出链路。
- 上述迁移不删除已有插件目录、配置、图库、数据库或历史数据，也不代表当前运行实例已经被修改。
- `/image` 是显式图片生成 Capability，与自动发表情包无关，继续保留。
