# 主动搭话上下文策略

这是嘟嘟哒 2.0 Runtime 的可选策略扩展。它只检查 Core 已读取并脱敏投影的群聊历史，
在以下场景建议保持沉默：

- 最近消息主要是相同内容、`+1` 或接龙；
- 最近消息主要是打卡、签到、抽签、点歌等其他机器人互动。

插件不监听群消息，不保存聊天记录，不调用 LLM 或 MCP，也不直接发送消息。消息接收、历史读取、
触发频率、模型路由和最终发送均由 `astrbot_plugin_dududa_core` 的 2.0 Runtime 负责。

主动搭话的启用状态、概率、冷却时间、上下文长度和每小时上限在嘟嘟哒管理后台按群配置，
因此本扩展没有独立配置项。

策略函数位于 `policy.py`：

```python
from astrbot_plugin_proactive_chatter.policy import proactive_context_skip_reason

reason = proactive_context_skip_reason(("成员1：+1", "成员2：+1", "成员3：+1"))
```

返回 `None` 表示允许 2.0 Runtime 继续判断；返回 `echo_flood` 或 `bot_interaction`
表示本轮不应主动插话。
