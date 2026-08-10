# astrbot_plugin_dududa_core

嘟嘟哒核心插件，负责统一命令入口、权限、审计、课程查询和管理骨架。

当前已实现：

- `/help`、`/dududa help`
- `/about`、`/ping`、`/status`、`/privacy`
- `/course stats/search/review/compare/refresh`
- `/admin status/plugins/mcp/logs/group/user/memory/model/backup/restart/permission/broadcast`
- `/confirm`、`/cancel`
- `/remember`、`/forget`、`/memory`、`/style`
- `/meme`、`/image`、`/fortune`、`/draw`、`/poke`、`/reread`

边界：

- 当前只接入评课社区 `icourse` MCP。
- 教务系统、成绩、个人课表、考试查询仍为 TODO。
- gpt-image-2 已接入 `/image <描述>`，仅 trusted/admin 可用，默认等待超时 420 秒。
- `/admin restart` 与 `/admin broadcast` 只进入确认和审计，不在 QQ 命令内直接重启容器或群发。
