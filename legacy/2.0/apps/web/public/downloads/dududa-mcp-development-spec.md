# Dududa 2.0 MCP Server 开发与接入规范

> 规范标识：`DUDUDA-MCP-SPEC 1.0.0`
> 目标环境：Dududa 2.0 Unified MCP、MCP Python SDK v1 Server、隔离的 MCP Python SDK v2 Client Worker
> 文档用途：供 MCP Server 作者、Dududa 接入者、代码审查者和生成代码的 AI 共同使用

## 1. 如何使用本规范

本文同时规定两件不同的工作：

1. 如何实现一个协议兼容、可以独立运行的 MCP Server；
2. 如何把这个 Server 登记到 Dududa，并按需映射为受治理的 Agent Capability。

这两件事不能合并理解。**Server 接入成功、工具发现成功、WebUI 显示在线，都不等于 Agent
获得了调用权限。** Dududa 的 Server Registry 只回答“怎样连接、允许通过传输层调用哪些
Tool”；Capability Registry、Scope Policy 和 Executor 才回答“谁在什么上下文可以使用哪项
业务能力”。

本文关键词含义如下：

- **必须（MUST）**：不满足时，不能作为合格的 Dududa MCP 接入交付；
- **禁止（MUST NOT）**：任何情况下都不能这样实现；
- **应该（SHOULD）**：默认遵守，偏离时在 README 中说明理由；
- **可以（MAY）**：按服务规模与风险选用。

本文以仓库当前的 `McpServerDefinition` v1、`configs/mcp/servers/*.json`、Unified MCP v2
Worker、iCourse 和 USTC Campus Server 为事实来源。不要从旧文档复制已经过期的“只有一个
真实 Server”等状态描述，也不要把尚不存在的校园资讯、arXiv 或行业资讯 Server 写成已接入。

## 2. 当前实现边界

### 2.1 已有能力

Dududa 当前已经实现：

- 严格 JSON 的 `McpServerDefinition` v1；
- `stdio` 和 `streamable_http` 两种 Client transport；
- 隔离使用 `mcp==2.0.0` 的 Unified MCP Worker；
- `auto` 与 `legacy` 协议模式；
- 按 Server 维护的长生命周期 Session、generation、并发、超时、有限重试和熔断；
- Tool discovery、输入/输出 JSON Schema 校验和 Schema Snapshot；
- 独立的 Capability Definition、MCP mapping、权限检查与 Executor；
- Web 超级管理员的 Server 登记与发现接口。

当前仓库内真实 Server 均通过 `stdio` 运行：

| `server_id` | 实现位置 | 说明 |
| --- | --- | --- |
| `icourse` | `services/mcp/icourse/` | 评课社区公开页面只读查询；模型能力不回退本地缓存 |
| `ustc-young` | `services/mcp/ustc-campus/` | 二课查询，使用 CAS SecretRef |
| `ustc-academic` | `services/mcp/ustc-campus/` | 学期、开课、考试和教学日历 |
| `ustc-curriculum` | `services/mcp/ustc-campus/` | 非官方培养方案研究快照 |

校车时刻表由本地 Builtin 插件提供，不是 MCP Server，也不占用 MCP Session。

`streamable_http` 已有 Core 类型、Registry、Worker Adapter 和无网络 Contract Test，但当前
四个真实 Server 都不是 Streamable HTTP。新 HTTP Server 在自己的真实 endpoint 通过
Contract Test 之前，只能声明“transport 可接入”，不能声明“生产可用”。

### 2.2 WebUI 的“接入”不做什么

WebUI 的“接入 MCP”会：

1. 校验 camelCase 表单请求；
2. 投影为 `McpServerDefinition` v1 的 snake_case JSON；
3. 写入 Runtime overlay，重新加载统一 Registry；
4. 建立或刷新该 Server 的 Session，并执行 Tool discovery；
5. 返回 `capabilityGranted: false`。

它**不会**：

- 从 GitHub 下载源码；
- 执行 `pip install`、`npm install` 或构建镜像；
- 把宿主机任意目录复制进容器；
- 创建真实 Secret；
- 自动生成 Capability Definition、mapping 或权限 Grant；
- 自动让 Planner、群聊或主动推送使用新 Tool。

因此 stdio Server 的 executable、源码和依赖必须已经存在于 MCP Console/Runtime 可见的
文件系统中；Streamable HTTP Server 必须已经在登记的 HTTPS endpoint 运行。

## 3. 分层模型

新增 MCP 能力按以下层次工作：

```text
业务数据源 / 外部系统
        |
        v
MCP Server
  - Tool 实现、业务参数校验、数据源访问、资源关闭
        |
        v
MCP Server Registry
  - server_id、transport、endpoint、SecretRef、Tool allowlist、连接预算
        |
        v
UnifiedMcpClient
  - Session、generation、discovery、Schema、timeout、retry、circuit、health
        |
        v
Capability Definition + MCP Mapping
  - 稳定业务 ID、输入输出契约、隐私、风险、语义、Tool 映射
        |
        v
Authorization + Retrieval + Executor
  - Actor、Scope、权限、候选过滤、逐次授权和调用
        |
        v
Composer / Output Adapter
  - 表达与发送；MCP Server 不拥有发送决策
```

各层职责必须保持分离：

| 层 | 拥有 | 不拥有 |
| --- | --- | --- |
| MCP Server | Tool 业务逻辑、数据源客户端、业务错误、资源生命周期 | 群聊理解、人格、模型路由、Agent 权限 |
| Server Registry | 连接事实、SecretRef、allow/deny、连接预算 | Capability Grant、Planner 可见性 |
| Unified Client | 协议、Session、Schema、健康和传输错误 | 业务权限、消息目标、回复格式 |
| Capability | 稳定业务契约、隐私、风险、语义、权限名 | Server 启动命令和 Secret 值 |
| Executor | Scope、授权、预算、调用与结果验证 | Server 内部数据抓取实现 |
| Web 超级管理员 | 提供初始连接配置并直接调用已授权 Capability | 绕过 Core Registry 或自动给 Agent 扩权 |

Server 禁止 import Dududa Runtime 后反向修改 Router、Memory、Persona、Scheduler、群策略或
权限状态。外部框架只能实现 Server 或 Provider Adapter，不能形成第二套控制面。

## 4. Server 和 Tool 命名

### 4.1 `server_id`

`server_id` 必须：

- 与 Registry 文件名一致：`configs/mcp/servers/<server_id>.json`；
- 匹配 `^[a-z0-9][a-z0-9._-]{0,127}$`；
- 发布后保持稳定；
- 表示服务边界，不表示某个部署实例或临时进程。

推荐：

```text
campus-news
library.catalog
example-search
```

禁止：

```text
Campus News
../../server
server-20260824-173012
```

Web Runtime overlay 不能覆盖仓库中已有的 `server_id`，也不能重复安装相同 ID。升级已有
Server 应走明确的版本更新流程，而不是换一个随机 ID 逃避兼容性检查。

### 4.2 Tool 名称

Core 接受的 Tool 名称匹配 `^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$`。新 Server 应进一步采用
稳定的小写 snake_case，并包含业务域动词：

```text
news_search_items
news_get_item
calendar_list_events
```

一个 Tool 应完成一个原子、可命名、可校验的动作。禁止设计：

```text
answer_anything
run_command
query_any_url
execute_sql
manage_everything
```

Tool 名称不是 Capability ID。一个常见映射是：

```text
server_id:      campus-news
tool_name:      news_search_items
capability_id:  campus.news.items.search.v1
provider_id:    mcp.campus-news
```

## 5. 推荐工程结构

### 5.1 Python Server

仓库当前真实 Server 使用 Python 与 FastMCP。推荐目录：

```text
services/mcp/example/
├── pyproject.toml
├── README.md
├── run_example_mcp.py
├── src/
│   └── example_mcp/
│       ├── __init__.py
│       ├── server.py
│       ├── config.py
│       ├── service.py
│       ├── models.py
│       └── errors.py
└── tests/
    ├── fixtures/
    └── test_contract.py
```

边界建议：

- `server.py` 只负责 FastMCP 注册、参数转换、结果转换和 lifespan；
- `service.py` 负责业务用例；
- 外部 HTTP、数据库或供应商 SDK 可以再拆到 `client.py`、`storage.py`；
- 测试 fixture 不访问真实生产系统；
- Server package 不 import `packages/dududa-agent` 的 Runtime 实现。

当前真实 Server 使用 `mcp>=1.2.0,<2.0.0`，Unified Client Worker 独立锁定
`mcp==2.0.0`。两者不安装进同一个解释器。新 Python Server 若升级 Server SDK，必须先证明
Unified Worker 的 `auto` mode 可完成 initialize、list_tools、call_tool 和 close；不要顺手升级
主环境或已有 Server。

### 5.2 TypeScript Server

TypeScript Server 可以通过标准 MCP 协议接入，但仓库当前没有生产 TypeScript MCP Server
模板或锁文件。推荐目录：

```text
services/mcp/example-ts/
├── package.json
├── package-lock.json
├── tsconfig.json
├── README.md
├── src/
│   ├── index.ts
│   ├── server.ts
│   ├── service.ts
│   └── schema.ts
└── tests/
    └── contract.test.ts
```

要求：

- 固定 Node.js 和 `@modelcontextprotocol/sdk` 的兼容版本；
- 生产执行 Registry 中的已构建 `.js`，不要依赖运行时下载包；
- stdio 模式不得向 stdout 写日志，stdout 只用于 MCP 协议；
- 退出时关闭 HTTP client、数据库、定时器和监听器；
- 仍由 Dududa 的 Python Unified Worker 进行协议 Contract Test；
- SDK API 若与下方示意不同，以锁定版本的官方 API 为准，但 Tool 名称、Schema 和结果契约
  不得漂移。

TypeScript stdio 基本形态示意：

```ts
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { z } from 'zod'

const server = new McpServer({ name: 'example-mcp', version: '0.1.0' })

server.registerTool(
  'example_search_items',
  {
    description: 'Search example items by a bounded keyword.',
    inputSchema: {
      query: z.string().min(1).max(100),
      limit: z.number().int().min(1).max(20).default(10),
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
  },
  async ({ query, limit }) => {
    const result = { ok: true, items: [], query, limit }
    return {
      content: [{ type: 'text', text: JSON.stringify(result) }],
      structuredContent: result,
    }
  },
)

const transport = new StdioServerTransport()
await server.connect(transport)
```

MCP annotations 只是 Server 提供的发现事实和提示，不是 Dududa 权限或重试策略的权威来源。
最终语义必须在 Capability Definition 与 MCP mapping 中显式声明并保持一致。

## 6. Python Server 基本模板

以下模板与当前 iCourse/USTC Server 使用的 FastMCP 和 lifespan 形态一致：

```python
from __future__ import annotations

import argparse
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from .service import ExampleClient


def create_mcp(base_url: str) -> FastMCP:
    clients: dict[str, ExampleClient] = {}

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        clients["example"] = ExampleClient(base_url)
        try:
            yield clients
        finally:
            await clients["example"].close()
            clients.clear()

    mcp = FastMCP("example-mcp", lifespan=lifespan)

    @mcp.tool()
    async def example_search_items(
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search example items using a bounded keyword and result limit."""
        if not 1 <= len(query) <= 100:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_query",
                    "message": "query must contain 1 to 100 characters",
                    "retryable": False,
                },
            }
        if not 1 <= limit <= 20:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_limit",
                    "message": "limit must be between 1 and 20",
                    "retryable": False,
                },
            }
        return await clients["example"].search(query, limit)

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run example MCP over stdio.")
    parser.add_argument(
        "--base-url",
        default="https://api.example.edu",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    create_mcp(args.base_url).run()


if __name__ == "__main__":
    main(sys.argv[1:])
```

模板规则：

- 外部 client 在 lifespan 中创建，在 `finally` 中关闭；
- Tool docstring 只描述真实动作，不放外部网页正文、Prompt 或动态数据；
- Tool 在 Server 边界再次校验范围，不能只相信 Client JSON Schema；
- 异步网络访问使用异步 client，不在 event loop 中调用同步 `requests`；
- stdout 只输出 MCP 协议，日志写 stderr；
- 捕获可预期业务错误，返回稳定错误码；不可预期异常由 Server/transport 记录并归一化；
- 不在 import、initialize 或 discovery 时执行昂贵抓取、写入或迁移。

## 7. Tool 输入输出与 JSON Schema

### 7.1 输入 Schema

Tool 输入必须是有边界的 JSON object。推荐：

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "category": {
      "type": "string",
      "enum": ["notice", "event", "research"]
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 20,
      "default": 10
    }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

规则：

- 对象默认 `additionalProperties: false`；
- 字符串设置 `maxLength`，数组设置 `maxItems`；
- 数字、时间范围、分页和批量数量有明确上下界；
- 枚举显式列出，不接受任意表达式；
- 不接收 shell、SQL、任意 URL、任意绝对路径或自由 header map；
- Secret、Cookie、账号密码和 API Key 不作为 Tool 参数；
- ID 与自然语言查询分开，不用自由文本冒充资源 ID；
- Server 自己重复执行必要的业务边界校验。

Dududa 当前 Schema Validator 接受本地 JSON Schema 引用，但拒绝远程 `$ref`、动态引用和
递归引用。Schema 和参数还受到 Core 的深度、节点数和字节数限制；不要用极深嵌套或巨型
union 绕过清晰的业务契约。

### 7.2 输出 Schema

Tool 应优先返回 `structuredContent`，并提供有限的 text content 便于普通 MCP Client 查看。
推荐成功结构：

```json
{
  "ok": true,
  "items": [
    {
      "id": "notice-42",
      "title": "示例通知",
      "source_url": "https://example.edu/notices/42",
      "published_at": "2026-08-24T08:00:00Z"
    }
  ],
  "total": 1,
  "fetched_at": "2026-08-24T08:05:00Z",
  "warnings": []
}
```

推荐可预期业务失败结构：

```json
{
  "ok": false,
  "error": {
    "code": "resource_not_found",
    "message": "Requested resource is unavailable.",
    "retryable": false
  },
  "warnings": []
}
```

输出规则：

- 成功和业务失败字段稳定，不靠解析自然语言判断状态；
- 来源数据包含稳定外部 ID、规范 URL、观察/发布时间和必要的新鲜度字段；
- 缺失、过期、部分成功和推测值显式表示；
- 外部网页、评论和文件内容视为不可信 Observation；
- HTML 转换为有限文本，不返回可执行标签；
- 不返回 stack trace、Secret、Cookie、数据库绝对路径、SQL 或完整上游错误正文；
- 单项、数组和总 payload 有上限；
- 不把巨型正文同时复制到 text 与 structuredContent。

## 8. 只读、幂等与副作用

Dududa 在 Capability Definition 与 MCP mapping 中使用以下三类语义：

| Capability `idempotency` | Mapping `semantics` | 含义 |
| --- | --- | --- |
| `read_only` | `read_only` | 不改变外部或持久状态；允许无写入的网络读取 |
| `idempotent_write` | `idempotent` | 重复执行在业务上等价，必须有稳定业务幂等键或等价约束 |
| `non_idempotent` | `non_idempotent` | 重复执行可能产生第二次副作用 |

Capability `side_effects` 的现有枚举是：

```text
none
network_read
persistent_write
external_write
message_send
file_write
```

规则：

- `read_only` 只能搭配 `none` 或 `network_read`；
- “GET 请求”不自动等于 `read_only`，若它刷新缓存、创建会话、确认通知或改变计数，必须按
  实际可观察副作用声明；
- “通常不会重复”不等于幂等；幂等写应能说明稳定业务键、唯一约束或上游幂等机制；
- 非幂等调用在 timeout/断连后若无法证明未执行，结果为 `outcome_unknown`，禁止自动重试；
- Tool annotations 可以提供 `readOnlyHint`、`idempotentHint` 和 `destructiveHint`，但不能替代
  Capability 定义、mapping、授权和 Executor 校验；
- 每个副作用 Tool 都必须在 README 说明成功点、取消行为和超时后状态。

首个对外开放版本应该优先只映射只读 Tool。抓取刷新、导出、报名、取消、发布和发送等 Tool
可以存在于 Server，但应放入 `denied_tools` 或仅供确定性运维入口使用，不进入模型候选。

## 9. `McpServerDefinition` v1

### 9.1 完整字段

Core Registry 文件必须包含且只能包含以下字段：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `schema_version` | integer | 当前只能为 `1` |
| `server_id` | string | 与文件名一致，匹配 Server ID 规则 |
| `enabled` | boolean | 是否允许建立连接 |
| `transport` | string | `stdio` 或 `streamable_http` |
| `protocol_mode` | string | `auto` 或 `legacy` |
| `endpoint` | object | 必须与 transport 对应 |
| `secret_refs` | array | 只存 Secret 引用，不存真实值 |
| `allowed_tools` | array | 非空的显式传输 allowlist |
| `denied_tools` | array | 显式拒绝集合，不能与 allowlist 重叠 |
| `timeouts_seconds` | object | connect/discovery/call/maximum_call/close |
| `retry` | object | maximum_attempts/base_delay_ms |
| `circuit` | object | failure_threshold/window/open duration |
| `maximum_concurrency` | integer | 每 Server 并发，1 到 64 |
| `schema_ttl_seconds` | number | 大于 0 且不超过 86400 |
| `config_revision` | string | 非空、无空白、UTF-8 不超过 128 字节 |

Registry 使用严格 JSON：未知字段、重复 key、非有限数字、符号链接、文件名与 `server_id`
不一致都会被拒绝。`definition_digest` 由 Core 从上述内容计算，不写入 JSON 文件，也不要求
Server 作者再建立一套哈希机制。

### 9.2 stdio 完整示例

```json
{
  "schema_version": 1,
  "server_id": "example",
  "enabled": false,
  "transport": "stdio",
  "protocol_mode": "auto",
  "endpoint": {
    "command": "/usr/local/bin/python",
    "args": [
      "/opt/dududa/services/example/run_example_mcp.py"
    ],
    "cwd": "/opt/dududa/services/example",
    "env_allowlist": [
      "LANG",
      "LC_ALL",
      "PATH",
      "PYTHONPATH"
    ]
  },
  "secret_refs": [],
  "allowed_tools": [
    "example_search_items",
    "example_get_item"
  ],
  "denied_tools": [
    "example_refresh_all",
    "example_export"
  ],
  "timeouts_seconds": {
    "connect": 10,
    "discovery": 10,
    "call": 30,
    "maximum_call": 60,
    "close": 5
  },
  "retry": {
    "maximum_attempts": 1,
    "base_delay_ms": 100
  },
  "circuit": {
    "failure_threshold": 3,
    "failure_window_seconds": 60,
    "open_duration_seconds": 30
  },
  "maximum_concurrency": 1,
  "schema_ttl_seconds": 300,
  "config_revision": "example-transport-v1"
}
```

stdio endpoint 规则：

- `command` 和 `cwd` 必须是绝对路径；
- `args` 每项是固定字符串，最多 128 项；
- `env_allowlist` 只包含匹配 `^[A-Z_][A-Z0-9_]{0,127}$` 的变量名；
- command、args、cwd 不得来自消息、模型输出或 Tool 参数；
- Server 的 stdout 只用于 MCP 帧，日志写 stderr；
- Runtime 只继承 allowlist 中的普通环境变量，再注入显式 SecretRef。

当前 iCourse/USTC Server 使用 MCP v1 FastMCP，因此 Registry 设置
`protocol_mode: "legacy"`；原生兼容 Unified Worker 当前协议的 Server使用 `auto`。不要用
`legacy` 作为任意失败后的动态 fallback。

### 9.3 Streamable HTTP 完整示例

```json
{
  "schema_version": 1,
  "server_id": "example-http",
  "enabled": false,
  "transport": "streamable_http",
  "protocol_mode": "auto",
  "endpoint": {
    "url": "https://mcp.example.edu/mcp",
    "allowed_hosts": [
      "mcp.example.edu"
    ]
  },
  "secret_refs": [
    {
      "secret_id": "example-mcp-token",
      "target": "header",
      "target_name": "Authorization"
    }
  ],
  "allowed_tools": [
    "example_search_items",
    "example_get_item"
  ],
  "denied_tools": [],
  "timeouts_seconds": {
    "connect": 10,
    "discovery": 10,
    "call": 30,
    "maximum_call": 60,
    "close": 5
  },
  "retry": {
    "maximum_attempts": 1,
    "base_delay_ms": 100
  },
  "circuit": {
    "failure_threshold": 3,
    "failure_window_seconds": 60,
    "open_duration_seconds": 30
  },
  "maximum_concurrency": 2,
  "schema_ttl_seconds": 300,
  "config_revision": "example-http-v1"
}
```

Streamable HTTP endpoint 规则：

- URL 必须使用 HTTPS；
- URL 不能包含用户名、密码、query 或 fragment；
- `allowed_hosts` 非空，并且包含 endpoint hostname；
- 凭据只通过 header SecretRef 注入；
- Client 不跟随重定向，也不继承宿主代理环境；
- 登记远程 endpoint 不等于已经验证其可用性、所有权或真实负载；
- 当前没有生产 Streamable HTTP Server 样板，新服务必须提供真实 Contract/Smoke 证据。

### 9.4 数值边界

以 Core 校验为最终权威：

- 所有 timeout 大于 0 且不超过 600 秒；
- `call <= maximum_call`；
- `maximum_attempts` 只能是 1 或 2，表示总尝试次数；
- `base_delay_ms` 为 0 到 5000；
- `failure_threshold` 为 1 到 100；
- failure window 和 open duration 大于 0 且不超过 3600 秒；
- `maximum_concurrency` 为 1 到 64；
- `schema_ttl_seconds` 大于 0 且不超过 86400。

不要因为 Web input 的 HTML 上限更宽就假设 Core 会接受；接入请求最终仍由
`ConfigMcpServerRegistry` 完整验证。

## 10. SecretRef

Registry 和 Web 请求只能包含 SecretRef，禁止包含真实 Token、Cookie、密码、私钥或账号。

stdio 示例：

```json
{
  "secret_id": "ustc-cas-username",
  "target": "env",
  "target_name": "USTC_CAS_USR"
}
```

Streamable HTTP 示例：

```json
{
  "secret_id": "example-mcp-token",
  "target": "header",
  "target_name": "Authorization"
}
```

规则：

- `secret_id` 是给外部 SecretResolver 的稳定引用，不是 Secret 值；
- stdio 只能使用 `target: "env"`；
- Streamable HTTP 只能使用 `target: "header"`；
- 同一 transport 内 target 名不能重复；
- env 名必须符合大写环境变量格式；
- header 名不能包含冒号或换行；
- Server 健康状态可以报告“未配置”，但不能回显值；
- README 只列需要哪些 SecretRef 和配置方法，不放示例真实凭据；
- 日志、错误、Tool 结果、截图和测试 fixture 都不能包含真实值。

Web 表单中的 `secret-id=TARGET_NAME` 只是把引用名投影为上述对象。浏览器不会也不应该接触
Secret 值。

## 11. Tool allowlist 与 denylist

`allowed_tools` 是必填且非空的传输层 allowlist。Server discovery 发现的新 Tool 不会自动通过。
`denied_tools` 用于明确记录即使 Server 暴露也不能走统一业务传输的 Tool。

通过传输层的条件至少是：

```text
tool_name in allowed_tools
and tool_name not in denied_tools
and tool_name exists in fresh discovery snapshot
```

进入 Agent 候选还必须满足：

```text
enabled Capability Definition
and enabled MCP mapping
and expected Tool Schema matches
and actor/scope permission allows
and risk/privacy/context/budget filters allow
```

allowlist 与 denylist 不能有交集。建议把管理类 Tool 明确放入 denylist，例如：

```text
refresh_all
export_dataset
delete_cache
publish_message
apply_activity
cancel_application
```

不要使用 `*`，不要在运行时把 discovery 结果整体复制成 allowlist，也不要让模型修改两个集合。

## 12. Capability Definition 与 MCP Mapping

### 12.1 注册不等于授权

MCP discovery 只更新事实。要让 Agent 使用 Tool，主仓还需要：

1. `configs/capabilities/definitions/<capability_id>.json`；
2. `configs/capabilities/mappings/<capability_id>.json`；
3. Provider descriptor 与 Schema 一致；
4. 对应 Scope/Actor 的权限策略；
5. Capability Registry reload 成功。

Web Server 安装接口固定返回：

```json
{
  "capabilityGranted": false
}
```

Server 自己禁止写 Capability 配置或授权文件。WebUI 直接调用也调用的是**已经映射和授权的
Capability**，不是绕过治理直接调用任意 Tool。

### 12.2 Capability Definition 负责什么

Definition 使用稳定版本 ID，例如：

```text
campus.news.items.search.v1
```

它定义：

- 稳定业务名称与描述；
- Capability 输入/输出 Schema；
- `provider_id`，通常为 `mcp.<server_id>`；
- `risk_level` 与 `privacy_level`；
- 允许的 conversation context；
- `required_permissions`；
- 成本与延迟提示；
- `idempotency` 与 `side_effects`；
- 是否启用。

不要把 Server command、URL、SecretRef 或 SDK 类型放入 Capability Definition。

### 12.3 Mapping 负责什么

当前 MCP mapping 完整结构如下：

```json
{
  "schema_version": 1,
  "capability_id": "campus.news.items.search.v1",
  "capability_definition_digest": "<由仓库生成工具计算>",
  "server_id": "campus-news",
  "tool_name": "news_search_items",
  "expected_input_schema_digest": "<由发现 Schema 计算>",
  "expected_output_schema_digest": "<由发现 Schema 计算或为 null>",
  "semantics": "read_only",
  "fixed_arguments": {},
  "argument_mapping_revision": "identity-v1",
  "result_mapping_revision": "schema-project-v1",
  "enabled": false,
  "mapping_digest": "<由仓库生成工具计算>"
}
```

尖括号值只是说明，不能作为 JSON 配置提交。应使用仓库已有的配置生成方式计算 digest，不要让
AI 猜测或手工伪造。现有 iCourse 和 USTC Campus 分别有专用生成脚本；新的通用 Server 在
没有通用生成入口时，应在自己的接入实现中提供等价的小型生成脚本。

Mapping 规则：

- `server_id` 和 `tool_name` 必须命中 Registry 和 fresh discovery；
- expected Schema digest 绑定已审查的 Tool 契约；
- `semantics` 必须与 Definition 的 idempotency 对应；
- `fixed_arguments` 可收窄高风险参数，例如强制 `refresh: false`；
- mapping 启用不会跳过权限策略；
- 新发现的 Tool、字段或 annotations 不会自动生成 mapping。

## 13. 生命周期与资源关闭

Dududa 会按 Server 维护长生命周期 Session，而不是每次 Tool call 新建进程。Server 必须适应：

- initialize 后多次 discovery 与 call；
- 多个顺序调用和 `maximum_concurrency` 范围内的并发调用；
- 调用取消；
- Client 主动 close；
- stdio EOF、SIGTERM 或进程退出；
- 配置变化后旧 generation 被关闭，新 generation 重新连接；
- Server 崩溃后有限重建。

Server lifespan 中创建的资源必须在关闭时释放：

- HTTP client 与连接池；
- 数据库连接、事务和 cursor；
- 文件句柄与临时目录；
- 后台 task、timer 和 thread；
- 子进程与订阅连接。

禁止：

- 每次调用创建永不关闭的 client；
- import 时启动后台任务；
- close 后继续写 stdout；
- 为普通只读查询启动无法取消的无限批处理；
- 让 Server 自己无限重启或绕过 Unified Client 的 generation 管理。

网络、数据库和锁等待需要 Server 内部 timeout。Client timeout 是总预算的一部分，不能替代
Server 在实际阻塞点设置 timeout。

## 14. Schema Discovery 与 Drift

Server 初次连接或 Schema Snapshot 过期时，Unified Client 执行 discovery。Snapshot 包含：

- `server_id` 与配置 revision；
- Session generation；
- Tool 名称、描述、输入 Schema、可选输出 Schema和 annotations；
- 观察时间与过期时间。

变化处理原则：

- 新增一个未映射 Tool：可以出现在 discovery 事实中，但不获得 Capability；
- 修改未映射 Tool：不影响已有 Capability；
- 已映射 Tool 的 Schema 发生不兼容变化：对应 Capability fail closed；
- Schema 过期且刷新失败：不能用陈旧事实继续执行；
- 配置 revision 变化：旧 generation 和旧 Schema 不再作为新调用依据；
- Tool 被删除：映射不可用，不静默换成名称相似的 Tool。

兼容演进建议：

- 新增可选字段而不是修改已有字段含义；
- 不改变枚举值语义；
- 不把整数 ID 改成自由文本；
- 破坏性变更使用新的 Tool 名或新的 Capability 主版本；
- 先更新 Server 和 discovery 证据，再更新明确 mapping；
- 不为每次小改动新增第二套 Schema freeze 或额外 hash，沿用 Core 已有 Snapshot/digest 即可。

## 15. 健康、超时、重试和熔断

Unified Client 的健康状态包括：

```text
initializing
healthy
degraded
stale
unavailable
circuit_open
closed
```

健康状态是观测事实，不是 Capability Grant。Server health 不应执行昂贵业务写入，也不回显
Secret、command、完整环境或上游错误正文。

重试原则：

- `maximum_attempts: 1` 表示不自动重试；
- 只读或真正幂等的调用可以配置总共最多 2 次尝试；
- 重试仍受调用总 deadline 和 Runtime 工具预算限制；
- 非幂等调用只有明确证明“未 dispatch/未执行”时才可能重试；
- effect 后断连、timeout 或取消导致未知结果时禁止自动重试；
- 熔断按 Server 隔离，不能拖垮其他 Server；
- Server 返回 `retryable` 只是业务提示，最终由语义、dispatch state 和 Client policy 决定。

## 16. 错误契约

Server 应区分：

1. 参数不合法；
2. 可预期业务失败；
3. 上游暂时不可用；
4. 协议或 Server 内部异常；
5. 调用结果未知。

可预期业务失败使用稳定、有限的 `error.code`。错误文本面向开发者时仍不能包含 Secret、绝对
路径、HTML 正文或 stack。不可恢复的协议异常可以通过 MCP `isError` 表达，由 Unified Client
归一化。

Core 当前标准失败类别包括：

```text
not_found
disabled
tool_forbidden
schema_unavailable
schema_stale
schema_incompatible
argument_invalid
result_invalid
transport_unavailable
timeout
cancelled
budget_exhausted
circuit_open
outcome_unknown
closed
internal
```

Server 不需要复制这套枚举，但自己的错误码必须能稳定映射，且不能用同一个
`something_failed` 覆盖所有情况。

## 17. 最小 Contract Test

测试规模应与风险匹配。普通只读 Server 的首版最小集合是：

1. initialize 成功；
2. list_tools 只出现预期 Tool，名称稳定；
3. 一个主要 Tool 的成功调用返回符合 Schema 的 structured result；
4. 一个无效参数或上游失败路径返回稳定错误；
5. close 后 client、任务和进程被释放；
6. Registry allowlist 与发现 Tool 的预期集合一致。

Python stdio 协议 smoke 可以使用与当前 iCourse 检查相同的 Client 形态：

```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def smoke() -> None:
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "run_example_mcp.py")],
        cwd=str(root),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            discovered = await session.list_tools()
            names = {tool.name for tool in discovered.tools}
            assert names == {"example_search_items", "example_get_item"}

            result = await session.call_tool(
                "example_search_items",
                {"query": "test", "limit": 2},
            )
            assert not result.isError
            assert result.content


if __name__ == "__main__":
    asyncio.run(smoke())
```

还应有一个聚焦的 service unit test，使用本地 fixture 或 Fake HTTP，不访问生产服务。带账号
Server 的默认测试验证 `missing_secret`，真实账号只在受管环境做 smoke。

不要为普通只读原型先建立大规模矩阵、第二套 baseline 或新的发布 Gate。先证明 discovery、
主要调用、错误和 close；只有发现具体失败场景时再增加相应测试。涉及外部写、个人数据或账户
操作时，则按其实际风险增加授权、幂等与 unknown outcome 测试。

## 18. WebUI 接入契约

### 18.1 浏览器请求

超级管理员页面向同源接口发送：

```text
POST /api/mcp/install
Content-Type: application/json
```

Web 请求使用 camelCase。以下是与当前表单完全对应的 Streamable HTTP 示例：

```json
{
  "serverId": "campus-news",
  "displayName": "校园资讯",
  "enabled": true,
  "transport": "streamable_http",
  "protocolMode": "auto",
  "endpoint": {
    "url": "https://mcp.example.edu/mcp",
    "allowedHosts": [
      "mcp.example.edu"
    ]
  },
  "secretRefs": [],
  "allowedTools": [
    "news_list",
    "news_get"
  ],
  "deniedTools": [],
  "timeoutsSeconds": {
    "connect": 10,
    "discovery": 10,
    "call": 30,
    "maximumCall": 120,
    "close": 5
  },
  "retry": {
    "maximumAttempts": 1,
    "baseDelayMs": 100
  },
  "circuit": {
    "failureThreshold": 3,
    "failureWindowSeconds": 60,
    "openDurationSeconds": 30
  },
  "maximumConcurrency": 1,
  "schemaTtlSeconds": 300,
  "configRevision": "campus-news-web-v1"
}
```

stdio 的 `endpoint` 必须完整包含四个字段：

```json
{
  "command": "/usr/local/bin/python",
  "args": [
    "/opt/dududa/services/example/run_example_mcp.py"
  ],
  "cwd": "/opt/dududa/services/example",
  "envAllowlist": [
    "LANG",
    "PATH",
    "PYTHONPATH"
  ]
}
```

字段映射如下：

| Web camelCase | Registry snake_case |
| --- | --- |
| `serverId` | `server_id` |
| `displayName` | Runtime Web metadata，不进入 Core Definition |
| `protocolMode` | `protocol_mode` |
| `endpoint.envAllowlist` | `endpoint.env_allowlist` |
| `endpoint.allowedHosts` | `endpoint.allowed_hosts` |
| `secretRefs[].secretId` | `secret_refs[].secret_id` |
| `secretRefs[].targetName` | `secret_refs[].target_name` |
| `allowedTools` | `allowed_tools` |
| `deniedTools` | `denied_tools` |
| `timeoutsSeconds.maximumCall` | `timeouts_seconds.maximum_call` |
| `retry.maximumAttempts` | `retry.maximum_attempts` |
| `retry.baseDelayMs` | `retry.base_delay_ms` |
| `circuit.failureThreshold` | `circuit.failure_threshold` |
| `circuit.failureWindowSeconds` | `circuit.failure_window_seconds` |
| `circuit.openDurationSeconds` | `circuit.open_duration_seconds` |
| `maximumConcurrency` | `maximum_concurrency` |
| `schemaTtlSeconds` | `schema_ttl_seconds` |
| `configRevision` | `config_revision` |

不要把 snake_case Registry JSON 原样发给 Web API，也不要把 camelCase Web payload 直接提交到
`configs/mcp/servers/`。

### 18.2 接入响应

发现成功的核心响应形态：

```json
{
  "schemaVersion": 1,
  "status": "ok",
  "message": "MCP Server 已接入并完成工具发现",
  "server": {
    "id": "campus-news",
    "displayName": "校园资讯"
  },
  "discovery": {
    "status": "ok",
    "tools": [
      {
        "name": "news_list",
        "description": "List campus news items."
      }
    ]
  },
  "capabilityGranted": false
}
```

如果 Registry 写入成功但 discovery 暂时失败，返回 `status: "warning"`、
`discovery.status: "unavailable"`。配置会保留为可见、可修复状态；这仍不代表 Server 可用，
也不授予 Capability。

接入接口只接受同源超级管理员请求。浏览器不接触 MCP Console 内部凭据或 Server Secret。

### 18.3 推荐操作顺序

1. 在本地或受管环境实现 Server；
2. 运行脱网 unit test 和最小协议 Contract Test；
3. 把 stdio artifact/依赖部署到 Runtime 可见路径，或部署 HTTPS Server；
4. 在 WebUI 下载并核对本规范；
5. 填写 Server ID、transport、endpoint、SecretRef 名和 Tool allow/deny；
6. 保守设置并发、timeout 与 retry，点击“接入 Server”；
7. 核对 discovery 列表，只确认连接事实；
8. 在主仓创建并生成 Capability Definition 与 mapping；
9. 配置权限和测试 Scope；
10. 通过 WebUI 的已授权 Capability 调用入口执行一个只读 smoke；
11. 再决定是否开放给 Agent Retrieval/Planner。

## 19. README 要求

每个 Server README 至少包含：

- Server 名称、`server_id`、版本与所有权；
- 数据源、来源许可和新鲜度语义；
- Tool 表：名称、输入、输出、语义、副作用、认证、典型 timeout；
- stdio 启动命令或 Streamable HTTP 部署方式；
- 所需 SecretRef ID 与 target name，不含真实值；
- 持久数据、缓存、迁移、备份和清理方式；
- lifespan 与资源关闭方式；
- 业务错误码；
- 本地 Fake/fixture 测试和最小协议 smoke；
- Capability mapping 需求，或明确写“仅登记 Server，尚未映射 Capability”；
- 已知限制和非目标；
- 上游依赖、许可证与归属。

README 禁止声称：

- “所有发现 Tool 自动可被 Agent 使用”；
- “安装后自动获得管理员权限”；
- “支持任意网站/任意命令/任意数据库”；
- “Streamable HTTP 已生产验证”，除非确有本服务的真实证据；
- 尚未实现的数据源、定时推送或群聊行为已经存在。

## 20. 交付清单

### 20.1 Server

- [ ] `server_id` 稳定且符合命名规则。
- [ ] Tool 原子、命名稳定，不承担自然语言路由。
- [ ] 输入和输出有有限、可校验的 JSON Schema。
- [ ] 只读/幂等/非幂等与实际副作用一致。
- [ ] 可预期业务失败使用稳定错误码。
- [ ] 外部内容有来源、新鲜度和不可信边界。
- [ ] stdout 不含日志，Secret 不出现在结果和错误中。
- [ ] lifespan 会关闭所有 client、任务、文件和子进程。
- [ ] 依赖已锁定，运行时不隐式安装。

### 20.2 Registry

- [ ] Definition v1 字段完整，没有未知字段。
- [ ] 文件名与 `server_id` 一致。
- [ ] transport 与 endpoint 类型一致。
- [ ] Registry 只含 SecretRef，不含真实凭据。
- [ ] `allowed_tools` 非空，管理 Tool 位于 deny 或根本不允许。
- [ ] timeout、retry、circuit 和 concurrency 在 Core 范围内。
- [ ] `config_revision` 表达真实配置修订。

### 20.3 Capability

- [ ] 已明确本次是否仅登记 Server。
- [ ] 需要 Agent 使用时，有独立 Definition 与 mapping。
- [ ] Definition 的 idempotency 与 mapping semantics 一致。
- [ ] Schema digest 由仓库工具计算，不手写伪造。
- [ ] required permission、privacy、risk、context 和 side effects 准确。
- [ ] 安装或 discovery 没有自动创建 Grant。

### 20.4 验证

- [ ] initialize、list_tools、主要调用和 close 通过。
- [ ] 一个失败路径返回稳定错误。
- [ ] Registry 可以加载配置并只发现 allowlist Tool。
- [ ] 需要 Secret 时，无 Secret 状态明确且不泄露数据。
- [ ] Web 接入响应明确为 `capabilityGranted: false`。

## 21. 可直接复制给 AI 的生成 Prompt

将尖括号内容替换为实际需求，并把本规范一起提供给 AI：

```text
你正在为 Dududa 2.0 Unified MCP 开发并接入一个 MCP Server。严格遵守随附的
《Dududa 2.0 MCP Server 开发与接入规范》（DUDUDA-MCP-SPEC 1.0.0）。

Server 信息：
- server_id：<小写稳定 ID，例如 campus-news>
- 展示名称：<中文名称>
- 实现语言：<Python/TypeScript>
- transport：<stdio/streamable_http>
- MCP SDK 与版本：<明确锁定版本>
- 数据源：<本地 fixture/公开 HTTP/需要登录的系统/数据库>
- Tool：<逐项列出名称和真实功能>
- 认证：<无/列出 SecretRef ID、env 或 header target name；禁止提供真实值>
- 持久状态：<无/缓存/数据库，以及写入语义>
- 外部副作用：<none/network_read/persistent_write/external_write/message_send/file_write>
- 是否需要 Agent 自动选择：<否/是；是也只生成接入资产，不声称已授权>
- 目标 Scope 与权限：<public/group/private/admin 等真实要求>

生成要求：
1. 先检查仓库当前 `McpServerDefinition` v1、现有同语言 Server、Unified MCP Worker 和 Web
   camelCase 表单契约；以运行时代码为准，不复制旧状态描述。
2. 输出完整目录树和每个必要文件的完整内容，不使用“省略”“同上”或伪代码。Python 优先
   采用当前 FastMCP + lifespan 形态；TypeScript 固定 SDK/Node 版本并输出构建后的启动方式。
3. Server transport 只做协议适配；业务逻辑和外部 client 分层。禁止 import 或复制 Dududa
   Router、Memory、Persona、Scheduler、权限或消息发送控制面。
4. 每个 Tool 原子且名称稳定。输入 object 默认 additionalProperties=false，所有自由文本、
   数组、分页、时间范围和批量参数有上限；Server 内再次执行必要的业务校验。
5. 优先返回 structuredContent。成功、业务失败、来源、新鲜度、缺失和 warning 使用稳定字段；
   不返回 Secret、Cookie、stack、绝对路径、SQL 或完整上游错误正文。
6. 为每个 Tool 准确给出 read_only/idempotent_write/non_idempotent、mapping semantics 和
   side effects。不能仅根据 HTTP method 或 Tool 名猜测；未知结果的非幂等操作不得自动重试。
7. 使用 lifespan/finally 关闭 HTTP client、数据库、任务、timer、文件和子进程。stdio stdout
   只输出 MCP 协议，日志写 stderr；网络与数据库阻塞点设置内部 timeout。
8. 生成完整 `McpServerDefinition` v1 snake_case JSON：显式 allowed_tools/denied_tools，只有
   SecretRef，没有真实 Secret；stdio 使用绝对 command/cwd，HTTP 使用无 query/fragment 的
   HTTPS URL 和 allowed_hosts。
9. 同时生成 Web `POST /api/mcp/install` 的 camelCase JSON，并逐项保证与 Registry 投影一致。
   displayName 只属于 Web metadata。不要混用 envAllowlist/env_allowlist 等字段。
10. 若只登记 Server，明确写“Capability 未授权”。若需要 Agent 使用，列出 Definition 和 MCP
    mapping 所需内容、稳定 capability_id、provider_id、权限、隐私、风险、Schema 与固定参数；
    digest 由仓库现有生成代码计算，不猜测或填写伪造值。
11. 生成最小测试：initialize、list_tools、一个成功调用、一个失败调用和 close；外部访问使用
    Fake/固定 fixture。需要真实账号的部分默认验证 missing_secret，不嵌入凭据。
12. 最后给出部署 artifact、Web 接入、discovery 核对、Capability mapping 和只读 smoke 的
    顺序。明确“接入成功/发现成功不等于 Agent 获权”。
13. 不发明未存在的数据源、Server、Capability 或生产证据，不自动开放任意 Tool，不新增与
    本服务具体风险无关的 hash、冻结 contract、baseline、审批流或发布 gate。

开始生成前，仅在缺少会实质改变 transport、认证或副作用的信息时提问；信息充分时直接输出
可运行成品，不先写长篇方案。
```

## 22. 仓库参考实现

开发时优先参考：

```text
packages/dududa-agent/src/dududa/mcp/contracts.py
packages/dududa-agent/src/dududa/mcp/registry.py
packages/dududa-agent/src/dududa/mcp/client.py
packages/dududa-agent/src/dududa/mcp/subprocess_v2.py
services/mcp/unified-worker/
services/mcp/icourse/
services/mcp/ustc-campus/
services/mcp/console/
configs/mcp/servers/
configs/capabilities/definitions/
configs/capabilities/mappings/
docs/adr/0004-unified-mcp-client.md
docs/adr/0006-adopt-mcp-v2-for-unified-client.md
```

参考实现用于理解真实接口，不意味着复制其具体业务。新增 Server 的正常扩展面是：Server
package、Registry 配置、Capability Definition、mapping、部署 artifact 和聚焦测试；不应修改
Core Domain、Unified Client 或 Runtime 来硬编码一个新数据源。
