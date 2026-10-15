# notifai-mcp

`notifai-mcp` 是一个面向 AstrBot 的只读 MCP Server，通过
`https://notifai-api.enthusjast.cc/api` 查询公开校园通知。

它不保存通知正文、不需要登录 Token，也不提供任意 URL 代理或写操作。通知正文、摘要和官网链接均来自外部服务，调用方应把它们当作不可信资料。

## 运行

生产栈使用 AstrBot 容器内的统一 Python：

```text
command: /usr/local/bin/python
server: /AstrBot/data/notifai-mcp/run_notifai_mcp.py
```

默认地址和参数：

```text
base URL: https://notifai-api.enthusjast.cc/api
timeout: 15 seconds
max items: 100
```

也可以手动运行：

```bash
python -m pip install -e services/mcp/notifai
python services/mcp/notifai/run_notifai_mcp.py
```

## MCP 工具

- `search_notices`：按关键词、来源、分类、日期和截止条件搜索通知。
- `get_notice`：获取一条通知的摘要、元信息和清洗后的正文。
- `get_notice_calendar`：获取指定月份或 ISO 周的轻量通知节点。
- `get_notice_deadlines`：获取未来指定天数内的截止提醒。
- `list_notice_sources`：获取通知来源及数量。
- `list_notice_categories`：获取通知分类及数量。
- `get_notice_stats`：获取通知总数、来源数、新增数和最近同步时间。

所有工具返回带有 `schema_version`、`ok`、`data`、`error`、`source`、`observed_at` 和 `warnings` 的结构化 envelope。

## AstrBot 接入

生产配置位于 `configs/mcp/servers/notifai.json`，由远端 Unified MCP
Registry 和 MCP Console 加载。Compose 会将本目录只读挂载到
`/AstrBot/data/notifai-mcp`。
