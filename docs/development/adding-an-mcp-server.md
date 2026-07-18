# 添加一个 MCP Server

## 1. 适用范围

本文说明如何在目标目录 `services/mcp/<server-id>/` 中新增 MCP Server，并通过 `configs/mcp/` 和 Capability Registry 接入嘟嘟哒。Phase 1 只定义规范，当前部署仍使用 `services/icourse-mcp/` 和现有 AstrBot 配置。

MCP Server 是外部能力边界，不是完整 Agent。它负责清晰、原子、结构化的操作；它不负责理解整段群聊、决定是否回复、选择 Persona 或授予权限。

## 2. 何时使用 MCP

适合独立 MCP Server：

- 能力有独立数据源、认证、缓存或生命周期；
- 服务可以被多个 Agent/客户端复用；
- 需要隔离依赖、语言或发布节奏；
- 可以定义稳定的结构化工具契约；
- 故障可以被标准化并独立健康检查。

不适合：

- 纯粹的回复格式调整；
- Social Decision 或 Memory Scope 策略；
- 一段仅在嘟嘟哒内部使用的简单纯函数；
- 任意 shell、自由 SQL、任意 URL 代理或任意文件系统网关；
- 依赖整段自然语言 Prompt 才能确定参数的“万能工具”。

## 3. 目标目录

```text
services/mcp/example/
├── pyproject.toml
├── README.md
├── src/example_mcp/
│   ├── __init__.py
│   ├── config.py
│   ├── domain.py
│   ├── application.py
│   ├── transport.py
│   ├── errors.py
│   └── infrastructure/
│       ├── client.py
│       └── storage.py
└── tests/
    ├── fixtures/
    ├── test_contract.py
    ├── test_application.py
    └── test_transport.py
```

目录可根据服务规模收缩，但必须保持三个边界：

- MCP transport 只做协议适配；
- application/domain 不依赖 AstrBot 或 Agent Runtime；
- HTTP、数据库、文件和供应商 SDK 位于 infrastructure。

服务不得 import `packages/dududa-agent` 的 Runtime 实现。Capability Provider 在 Agent 一侧映射服务契约。

## 4. 设计原子 Tool

一个 Tool 应完成一个可命名、可校验、可审计的操作。例如 iCourse 优先提供：

```text
search_courses
get_course
get_reviews
compare_courses
refresh_course
```

而不是：

```text
answer_any_course_question
run_query
fetch_any_url
export_anywhere
```

每个 Tool 在 README 和 contract test 中说明：

- tool name 和语义版本；
- 输入 JSON Schema、范围和默认值；
- 输出 JSON Schema；
- 是否联网、读取缓存或写持久状态；
- 幂等性和超时后状态；
- 可观察业务错误；
- 数据来源、新鲜度和缺失语义；
- 隐私等级和保留策略；
- 典型延迟、最大结果和并发限制。

## 5. 输入和输出契约

### 5.1 输入

- 对象默认 `additionalProperties=false`；
- 字符串必须有长度限制，数组必须有最大项数；
- ID 使用明确类型和格式，不能用自由文本路径代替资源 ID；
- 枚举值显式列出，不接受任意 sort/filter 表达式；
- 分页、批量数量和时间范围必须有硬上限；
- Server 不能相信 Client 已完成校验，边界内再次校验。

### 5.2 标准结果

业务 Tool 推荐返回一致 envelope：

```json
{
  "schema_version": 1,
  "ok": true,
  "data": {},
  "error": null,
  "source_refs": [
    {"source": "example", "observed_at": "2026-07-18T00:00:00Z"}
  ],
  "cache_status": "hit",
  "warnings": []
}
```

失败结果：

```json
{
  "schema_version": 1,
  "ok": false,
  "data": null,
  "error": {
    "code": "resource_not_found",
    "message": "Requested resource is unavailable.",
    "retryable": false
  },
  "source_refs": [],
  "cache_status": "unknown",
  "warnings": []
}
```

错误 message 不包含 stack trace、Token、Cookie、SQL、绝对路径或上游响应正文。协议异常与业务失败分开：参数 Schema 错误可以返回 MCP tool error；可预期业务状态使用稳定 error code。

### 5.3 外部内容

网页、评论、通知和文件正文都是不可信数据：

- 保留来源和观察时间；
- HTML 默认转换为受限文本，不回传可执行标签；
- 设置单字段和总 payload 上限；
- 不把外部内容放进 tool description 或系统提示；
- 对可能的 Prompt Injection 标记 `untrusted_content=true`；
- 缺失、过期、部分成功和推测值必须显式表示。

## 6. 配置 Server Registry

目标配置文件位于 `configs/mcp/servers/<server-id>.yaml`：

```yaml
schema_version: 1
server_id: example
transport: stdio
endpoint:
  command: /usr/local/bin/python
  args: [-m, example_mcp.transport]
  cwd: /opt/dududa/services/mcp/example
  env_allowlist: [TZ]
secret_refs: []
allowed_tools:
  - search_items
  - get_item
denied_tools: []
timeouts:
  connect_ms: 10000
  discovery_ms: 10000
  call_ms: 30000
  max_call_ms: 120000
retry:
  max_attempts: 2
  base_delay_ms: 250
circuit_breaker:
  failures: 5
  window_ms: 60000
  open_ms: 120000
max_concurrency: 4
enabled: true
```

规则：

- 配置中不得出现真实密钥；只允许 `SecretRef`，由部署环境的 SecretResolver 注入；
- stdio command、args、cwd 和 env key 均由受审配置提供，不能来自消息或模型；
- 生产使用绝对、可预测的 executable 或已安装 entry point；
- `allowed_tools` 必填，Server 新增 Tool 不会自动暴露；
- Registry ID 与 Capability Provider ID 分开；一个 Server 可以提供多个 Capability；
- 配置模板与运行覆盖分离，运行覆盖不得提交 Git。

## 7. Capability 映射

发现一个 MCP Tool 不代表 Planner 能看到它。为每个允许进入 Agent 的操作单独创建 CapabilityDefinition：

```yaml
capability_id: example.search_items.v1
provider:
  provider_id: mcp.example
  server_id: example
  tool_name: search_items
risk_level: low
privacy_level: public
required_permissions: [capability.example.read]
idempotency: read_only
```

Capability Provider 负责：

- 将稳定 Capability 参数映射到 Tool 参数；
- 调用 Unified MCP Client；
- 将 MCP content 和 structured content 转换为稳定结果；
- 收窄字段并标记来源、缓存和 sensitivity；
- 将 Server error code 映射为 Domain Error。

诊断、批量抓取、迁移、导出和管理 Tool 可以保留在 Server，但只允许运维 CLI 使用，不注册为模型 Capability。

## 8. 超时、重试、取消和熔断

Server 实现必须响应取消，并给网络、数据库和锁等待设置内部超时。Client timeout 不是替代品。

建议：

- 普通只读调用目标 30 秒内完成；
- 批量任务拆成受限分页或异步 job，不占用一个无限 MCP 调用；
- 只读和幂等写可以在 Client 侧最多重试 1 次；
- 非幂等操作只有拿到明确“未执行”信号才允许重试；
- 所有重试计入 Runtime 最大工具步数；
- 连续失败触发按 Server 隔离的熔断，不拖垮其他 Server；
- half-open 只允许一个探测调用；
- Server 崩溃后由 Client 生命周期管理器有限重启，不由 Planner 决定。

Server 返回 `retryable` 只是建议，最终仍由能力幂等声明、deadline 和 Client Policy 决定。

## 9. 安全边界

### 9.1 凭据

- 凭据只在 Server 基础设施层解析；
- 不通过 Tool 参数接收 API key、Cookie 或密码，除非这是受控凭据管理系统且有独立 ADR；
- 不记录请求 header、完整 URL query 或上游响应中的凭据；
- 健康检查只返回状态，不回显配置；
- 测试使用假 SecretResolver。

### 9.2 网络

- 固定允许的 scheme 和 host；
- 明确 redirect 策略，每次重定向重新校验目的地；
- 默认拒绝 loopback、link-local、metadata endpoint 和未授权私网；
- 设置 DNS、connect、read 和总 timeout；
- 有全局并发、速率和抓取预算；
- robots、服务条款和数据使用规则必须由代码/运维门禁执行，不能只写 README。

### 9.3 文件和数据库

- Tool 不接受任意绝对路径；
- 导出只能使用受控 export root 下的服务生成文件名；
- 拒绝 `..`、符号链接逃逸和覆盖现有配置/数据库；
- SQLite/数据库 schema 有显式版本和迁移；
- 写入使用事务，幂等键和唯一约束与业务语义一致；
- 不将真实数据库、缓存、下载文件或 fixture 提交 Git。

### 9.4 权限与隐私

上层 Executor 会检查权限，但 Server 对高风险操作仍实施服务侧 allowlist。涉及个人数据时，输入必须携带由上层签发的受限授权上下文或资源 ID，而不是信任自然语言中的 user/group。

Server 不得跨 Scope 缓存私人结果。公共数据缓存也需要来源、TTL、删除和数据最小化策略。

## 10. 包与依赖

- 在 `pyproject.toml` 声明 Python 版本、许可证和直接依赖；
- 生产依赖必须由带 hash 的锁文件固定，不只写 `>=`；
- 系统依赖写入第三方 manifest/SBOM 和镜像构建；
- 不在 Server 启动时隐式 `pip install`；
- 不依赖开发机 `.venv` 或仓库根自动进入 `PYTHONPATH`；
- 镜像安装 package，源码挂载仅用于明确的开发模式；
- 依赖更新单独 PR，附 contract 和 smoke 结果。

## 11. 测试

### Unit

- 参数边界、业务规则和错误码；
- 结果 schema、裁剪和不可信内容处理；
- URL、路径、redirect 和权限校验；
- 数据库事务、迁移、幂等和并发；
- timeout、取消和资源关闭。

### Contract

- 真实 MCP initialize、list_tools 和 call_tool；
- Tool 名称和 input/output schema snapshot；
- `allowed_tools` 与 Capability 映射一致；
- 每个声明 error code 均有 fixture；
- Server 新增 Tool 不会自动进入 Planner。

### Integration

- 使用本地 fake HTTP/DB，不调用生产服务；
- 慢响应、连接中断、格式变化、部分数据和重定向；
- 并发上限、Client retry、熔断和恢复；
- Secret 不出现在 result、异常、Trace 和日志；
- Server 重启不破坏持久数据。

### Smoke

- 派生镜像可安装并启动 Server；
- Registry 能发现预期 Tool；
- 只读健康调用成功；
- Compose 路径和权限正确；
- 不需要真实账号即可完成最小 smoke；需要账号的验证使用外部受管环境。

## 12. 文档要求

Server README 至少包含：

- 数据源和所有权；
- Tool 契约表；
- 配置和 SecretRef；
- 本地开发和无密钥 smoke；
- 持久数据、备份、升级和回滚；
- 权限、隐私、合规和速率限制；
- 已知缺失与非目标；
- 上游依赖和许可证。

同时更新：

- `docs/design/capability-and-mcp.md` 的 Server/Capability 清单；
- `configs/mcp/` Registry 配置；
- `configs/capabilities/` 显式映射；
- 部署镜像与健康检查；
- contract、integration、smoke 和 Eval；
- 第三方 manifest 和 notices。

## 13. iCourse 参考迁移

iCourse 是第一个标准样板，但当前实现不是所有新 Server 都应复制的最终模板。迁移时应保留其 parser、crawler、SQLite 和 FastMCP 资产，同时修正：

- 将模型能力限制为 `search_courses`、`get_course`、`get_reviews` 和受控 `compare_courses`；
- 将 refresh 设为 trusted/admin、限流且有明确 timeout；
- 将 bulk crawl、robots 和 export 放入运维面；
- export 只写受控目录；
- 执行 robots 策略，而不只缓存文本；
- 给依赖和 SQLite schema 加锁与版本；
- 统一成功/失败 envelope；
- 为 HTML parser 建立脱网 fixture 和格式漂移测试；
- 通过 Unified MCP Client 复用 session，删除每次调用启动进程的直连实现。

## 14. 发布与回滚

1. 先合入 Server、假数据测试和 Registry 配置，保持 `enabled=false`；
2. 构建镜像并运行 MCP contract/smoke；
3. 注册 Capability，但仅在测试策略中可见；
4. canary 验证权限、延迟、错误和审计；
5. 再逐步开放上下文和用户；
6. 回滚优先禁用 Capability 和 Server 配置；
7. 数据 schema 变更必须有向后兼容窗口和恢复验证。

不得用删除数据库、清空缓存或复制生产凭据完成回滚。

## 15. PR 检查清单

- [ ] Tool 原子且不承担自然语言路由；
- [ ] 输入输出有严格、版本化 Schema；
- [ ] 幂等、side effect、timeout 和 error code 已说明；
- [ ] Registry 只含 SecretRef，Tool 使用显式 allowlist；
- [ ] 只有显式 Capability 映射进入 Planner；
- [ ] 网络、路径、批量大小和结果大小有硬上限；
- [ ] 权限、隐私、日志脱敏和数据保留已测试；
- [ ] 依赖、许可证、镜像和系统包已登记；
- [ ] MCP contract、integration 和容器 smoke 通过；
- [ ] 部署、升级和回滚文档完整。
