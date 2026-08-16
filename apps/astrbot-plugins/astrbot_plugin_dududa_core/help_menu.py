from __future__ import annotations


def user_help() -> str:
    return """嘟嘟哒指令菜单

基础：
/help [模块]
/about
/ping
/status
/privacy

聊天与记忆：
/remember <内容>
/forget <关键词>
/memory [export|on|off]
/style <简洁|详细|可爱|认真>

课程：
/course <自然语言评课需求>
/course stats
/course search <关键词>
/course review <课程/老师>
/course compare <A> | <B>
/course refresh <课程ID>

工具：
/remind <时间> <内容>
/reminders
/summary [today|数量]
/sub2api help
/help plugins

娱乐：
/image <描述>
/fortune
/draw <主题>

管理员发送 /help admin 查看管理指令。"""


def admin_help() -> str:
    return """嘟嘟哒管理指令

/admin status
/admin plugins
/admin group mode <quiet|normal|active>
/admin group reply-rate <0-100>
/admin memory summary
/admin memory clear-short
/admin user mute <QQ>
/admin user unmute <QQ>
/admin permission grant <QQ> <role>
/admin permission revoke <QQ> <role>
/admin mcp list
/admin mcp test icourse
/admin logs errors
/admin logs tail <行数>
/admin backup create
/admin restart astrbot
/admin restart napcat
/admin model set <default|image> <模型ID>
/admin broadcast <内容>

高风险操作会返回 /confirm <token>。"""


def module_help(module: str) -> str:
    key = (module or "").strip().lower()
    if key in {"admin", "管理"}:
        return admin_help()
    if key in {"course", "课程"}:
        return """课程指令

/course <自然语言评课需求>
/course stats
/course search <关键词>
/course review <课程/老师>
/course compare <A> | <B>
/course refresh <课程ID>

例子：
/course 推荐一个数学分析老师
/course 数据结构A哪个老师好
/course 查一下复变函数课程评价

非 slash 自然语言只保留一个触发口令：
评课社区搜索 数据结构A

当前只使用评课社区公开页面；会通过站内搜索扩展缓存，教务系统仍是 TODO。"""
    if key in {"memory", "记忆"}:
        return """记忆指令

/remember <内容>
/forget <关键词>
/memory
/memory export
/memory on
/memory off
/style <简洁|详细|可爱|认真>"""
    if key in {"plugins", "插件"}:
        return """Dududa 2.0 插件状态

当前路径：
Dududa Core：AstrBot Adapter
Sub2API Readonly：显式只读查询

过渡期兼容：
Iris Chat Memory、Better Reminder、ChatSummary v2：保留数据与兼容入口
Reply Polish：Dududa 1.0 LONG-only 输出兼容层，默认关闭

已退出默认路径：
Meme Manager：不再默认安装，不再自动发表情
PokePro：不再默认安装，不再自动戳一戳
Reread：不再默认安装，不再概率复读
Target Talk：不再默认挂载，由受治理的 Probe/主动 Runtime 方向取代"""
    return user_help()
