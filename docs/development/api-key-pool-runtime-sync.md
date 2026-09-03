# API Key Pool 与 AstrBot Runtime 的同步边界

## 目的

Web 控制台的 `/api-keys` 页面负责维护 Luna（`haiku`）、Terra
（`sonnet`）和 Sol（`opus`）三个相互独立的 Provider Key 池。Key 池不是新的
模型路由器，也不修改 Dududa Core 的 `TierPolicy`、Endpoint Admission 或
健康快照。它只决定某个已被 Runtime 选中的 Provider 从哪里取得凭据。

AstrBot 已经提供了稳定的 Provider Source 边界：Source 保存 OpenAI-compatible
的 `api_base`、`key[]`、自定义 Header 和超时，Provider 条目保存模型 ID 和
`provider_source_id`。本仓库新增的
`astrbot_plugin_dududa_core.adapters.api_key_pools` 是一个只读部署适配器，
把 Web Gateway 的外部快照校验后投影成这两个 AstrBot 配置片段。适配器不写
`cmd_config.json`，不触碰 Domain DTO，也不把凭据放进 Endpoint descriptor、
digest、receipt、Trace 或普通日志。

## 外部文件

Web Gateway 通过原子替换把快照写到仓库之外的私有 JSON 文件。Python 侧按下列
顺序读取路径：

1. `DUDUDA_API_KEY_STORE_PATH`；
2. 兼容旧部署的 `DUDUDA_API_KEYS_FILE`。

路径必须是绝对路径、非符号链接的普通文件。默认要求文件权限不向 group/other
开放（部署建议目录 `0700`、文件 `0600`）。文件过大、JSON 损坏、schema 版本不
支持或 pool 标识冲突时，适配器拒绝该快照；它不会尝试修补旧值。

文件顶层契约如下。`pools` 既可以是按 tier 索引的对象（Gateway 内部写入形状），
也可以是包含 `tier` 字段的数组（便于导出和迁移）：

```json
{
  "schemaVersion": 1,
  "revision": 42,
  "pools": {
    "haiku": {
      "tier": "haiku",
      "provider": "openai-compatible",
      "providerId": "astrbot-luna",
      "sourceId": "dududa-haiku-source",
      "baseUrl": "https://provider.example/v1",
      "model": "gpt-5.6-luna",
      "protocol": "openai_chat_completions",
      "reasoningEffort": "low",
      "timeoutMs": 120000,
      "maxOutputTokens": 2048,
      "enabled": true,
      "schedulingMode": "priority",
      "customHeaders": [],
      "revision": 42,
      "keys": [
        {
          "id": "luna-primary",
          "name": "primary",
          "secretRef": "DUDUDA_LUNA_PRIMARY",
          "secret": "<only in the private store, never in Git>",
          "priority": 10,
          "weight": 1,
          "enabled": true,
          "status": "active"
        }
      ]
    }
  }
}
```

上面的 `secret` 仅表示 Gateway 私有文件中的内部字段；不要把示例值替换成真实
凭据后提交仓库。也可以省略 `secret`，由显式传入的 `secret_resolver` 依据
`secretRef` 从环境变量或部署侧 Secret Manager 解析。适配器不会把 `key`、`value`
等不明确字段当作凭据，以免误读脱敏 API 响应。

缺失的 tier 会被投影为关闭的空池。这样在控制台尚未配置某一档时，现有 Runtime
仍按原有 TierPolicy 运行；它不会因为 Key 池为空而自动跨档、放宽能力或改变回答
档位。

## 投影规则

调用 `load_api_key_pool_snapshot()` 后，对目标池调用
`project_pool_to_astrbot(pool, secret_resolver=...)`。返回对象的
`for_astrbot()` 方法才会物化 AstrBot 需要的敏感 `key[]`：

| Key Pool 字段 | AstrBot 字段 | 规则 |
| --- | --- | --- |
| `sourceId` | `provider_source.id` | 默认 `dududa-{tier}-source` |
| `baseUrl` | `provider_source.api_base` | 仅允许 HTTP(S)，去除尾部 `/`，拒绝凭据、查询串和片段 |
| 可用 Key | `provider_source.key[]` | 过滤 disabled/unavailable/cooldown/error；按 priority 降序、ID 稳定排序 |
| `customHeaders` | `provider_source.custom_headers` | 最多 32 个；Authorization、Token、Cookie 等认证 Header 必须走 SecretRef |
| `timeoutMs` | `provider_source.timeout` | 向上取整为秒，限制在 1–900 秒 |
| `protocol` | `provider_source.type` | 当前统一投影为 `openai_chat_completion`/`chat_completion` |
| `providerId`、`model`、`enabled` | `provider` | 设置 `provider_source_id`、模型和文本模态；无可用 Key 时自动关闭 |

`weight` 作为池元数据保留，不通过重复写入同一密钥来伪造权重；AstrBot 原生的
429 轮换机制负责从 `key[]` 选择下一个凭据。若部署需要真正的加权调度，应在
Provider Manager 层实现，而不是复制密钥或修改 Dududa 路由策略。

## 生命周期与动态更新

当前适配器是显式的启动/重载边界，不在模型调用热路径轮询文件。部署侧应在
AstrBot Provider Manager 初始化或受控重载钩子中执行：

```python
from astrbot_plugin_dududa_core.adapters.api_key_pools import (
    load_api_key_pool_snapshot,
    project_pool_to_astrbot,
)

snapshot = load_api_key_pool_snapshot()
for tier in ("haiku", "sonnet", "opus"):
    pool = snapshot.pool(tier)
    if pool is None:
        continue
    projection = project_pool_to_astrbot(pool)
    astrbot_provider_manager.apply(
        projection.for_astrbot()
    )  # 仅在 AstrBot Source 边界内使用，随后丢弃 mapping
```

控制台创建、轮换、停用或删除 Key 后，Gateway 会递增快照 `revision`。部署编排
应检测该版本并对 AstrBot 执行一次受控 Provider 重载；在重载完成前，页面显示
`pending`，旧 Provider 继续提供服务。重载失败时保留旧的 last-known-good
Provider，并把错误状态反馈给控制台。适配器本身不执行进程重启，也不会覆盖无关
Provider。

## 安全与运维要求

- 真实 Key 只能通过控制台的显式创建/轮换请求或部署侧 Secret Manager 注入；
  不得写入 Git、浏览器 localStorage、Trace、审计正文或测试 fixture。
- `load_api_key_pool_snapshot` 的异常消息不包含文件内容、URL 查询值或 SecretRef
  解析详情；诊断时只记录 schema/revision 和脱敏状态。
- `for_astrbot()` 返回值包含原始 Key，是一次性边界对象。调用方不得打印、缓存到
  Domain 状态或再次序列化到 Web 响应；AstrBot 接收后应尽快释放引用。
- 429 可在同一 tier 的 Source Key 列表中轮换；401/403、非法请求、Schema 错误和
  安全拒绝不得借 Key 池机制跨 tier 重试。跨 tier fallback 仍完全由既有 Runtime
  路由与 Admission 合同决定。
- 更新池元数据不会自动改变 `ModelTier`、`TierPolicy`、Endpoint descriptor
  digest 或健康 TTL。池为空、Provider 不可用或重载暂挂时，Runtime 继续使用既有
  的 provider-unavailable/fallback 行为。

契约测试位于 `tests/contracts/test_api_key_pools.py`，覆盖对象/数组快照、三档
隔离、权限、脱敏表示、SecretRef 解析、停用 Key 过滤和非法配置拒绝。
