# astrbot_plugin_dududa_social

这是从 PR #10 选择性提取的 Dududa 2.0 社交策略扩展。它与
`astrbot_plugin_dududa_core` 使用不同的插件 ID，并且默认关闭、默认拒绝空群白名单。

## 设计边界

- 只注册 `/dududa-social ...` 显式命令；不注册 `ALL` 消息处理器。
- 不调用模型、MCP、Scheduler，不监听普通消息，也不自动发送祝福、安慰、投票提示或 CP 调侃。
- `policy.py` 是无 I/O 的确定性策略资产，供 Core/Runtime 在获得授权后消费。
- `storage.py` 是独立的 SQLite 状态仓库，所有记录按 `platform + bot + conversation` Scope 隔离。
- 状态文件使用私有目录和 SQLite 事务；睡眠日志自动保留有限天数，群内展示使用脱敏标识。
- 投票结束只允许发起人或管理员，不能由任意成员结束他人投票。
- 情绪 `CRISIS` 只产生结构化人工支持信号，不生成医疗判断或自动安慰文本。

## 纯策略 API

```python
from astrbot_plugin_dududa_social import (
    apply_vote_action,
    classify_compliment,
    classify_mood,
    match_keyword,
    parse_birthday,
)

assert parse_birthday("3/15") == "03-15"
assert classify_mood("最近有点难受").severity.value == "support"
assert classify_compliment("嘟嘟哒好可爱").target.value == "bot"
```

`canonical_pair`/`record_interaction` 使用结构化 `UserPair`，不会把两个用户 ID 用
下划线拼接，因此 ID 中含下划线时仍不会发生碰撞。关键词策略默认关闭 PR #10 中单字
`区`、`猪` 规则；调用方可以显式传入自己的 `KeywordRule`。

## 显式命令

```text
/dududa-social help
/dududa-social birthday set 0315
/dududa-social birthday list|delete
/dududa-social sleep record|rank
/dududa-social vote start <主题>|join|status|end
/dududa-social cp rank
```

启用命令需要在 AstrBot 配置中同时设置 `enabled=true`、具体 feature 为 `true`，并把
目标群加入 `group_allowlist`。私聊默认拒绝。关闭插件或移除群白名单即可回滚，不会触碰
嘟嘟哒 Core、Web 控制台、MCP Registry 或既有状态文件。

## 与 PR #10 的差异

PR #10 的生日检查、睡眠关键词监听、自然语言投票提示、CP 检测、情绪自动回复、接龙跟读、
夸奖自动回复和关键词自动回复都位于一个 Core `ALL` Handler 链中。本扩展只保留可测试的
规则和显式命令状态 API；接龙跟读不在本插件中实现，因为当前 `astrbot_plugin_reread` 和
`astrbot_plugin_proactive_chatter` 已分别拥有复读能力与接龙静默策略，新增自动 Handler 会
造成重复或抢占事件。

## 验证

```bash
PYTHONPATH=packages/dududa-agent/src:apps/astrbot-plugins \
  uv run --with pytest python -m pytest -q tests/test_social_plugin.py
```
