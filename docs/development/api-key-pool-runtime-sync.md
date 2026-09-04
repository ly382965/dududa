# API Key Pool 与 AstrBot Runtime 的同步边界

## 当前操作：显式应用到 Runtime

本节描述当前源码提供的操作，不代表新版本已经部署或通过线上验收。

API Key 页面上方提供 **应用到 Runtime** 按钮。先保存三档的连接参数和 Key，再点击
按钮；保存本身不触发模型调用。按钮只提交当前保存版本 `revision`，由 Web 使用现有
plugin-scope 凭据转交 AstrBot，浏览器不读取密钥，也不访问 Docker 或宿主命令。

`GET /api/api-keys/runtime` 读取当前进程的 `pending/applying/applied/unavailable`
状态；同源管理页面向 `POST /api/api-keys/runtime/apply` 只提交 `{ "revision": 42 }`
这样的版本对象，不能附带 Key、路径或任意模型参数。Web 先比较当前保存版本，AstrBot
在准备候选前和提交前再次比较同一版本；不一致返回 `pool_revision_changed`，刷新后再
应用，不会把较新保存内容混入旧候选。应用期间宿主配置变更也会拒绝提交。

本次应用支持已验证的官方 DeepSeek Chat 协议、三档均启用、有可用 Key、既有固定
Provider ID，以及已明确接受的 CN/provider-managed 留存配置；不支持的协议、停用池、
缺少当前宿主证据等会拒绝应用并保留旧 Runtime，不会偷偷替换模型。Provider Source 的
Base URL、Key、模型、推理深度与输出上限都是外部配置，无需改业务框架或重新构建页面。

服务端先用三条短合成请求验证模型和输出边界，再执行三档健康检查；最坏可能耗时数分钟，
期间旧 Runtime 继续工作。提交时若有入站、预览、Shadow 或自动搭话正在执行，会提示稍后
重试。成功后立即切换 **Dududa 自己拥有的 Provider 实例**，不关闭 AstrBot 全局 Provider。
因此其他 AstrBot 插件在下次冷启动前仍使用旧实例；持久配置和宿主配置缓存已经同步，
冷启动后读取同一份新配置。主动搭话控制器只换 Runtime 引用，原冷却和小时限额不清零。

页面“已应用”依据当前进程真实配置绑定判断，而不是单纯看文件保存成功；仅健康检测引起
的版本变化不会误报未应用，Key/连接语义变化会显示待应用。它不保证上游永远健康，之后
的供应商故障仍由既有 Runtime 健康策略处理。旧连接清理失败时显示“新配置已应用；旧连接
清理待重试”，保留资源给生命周期清理重试，不把已完成切换伪装成失败。
若浏览器断开或接口超时，应先刷新真实状态，不能仅凭网络错误断言回滚或立即重复应用。

运行时挂载保持原样：Web 仅写外部 Key Store，AstrBot 只读该 Store；私有 command/Core/
evidence 写入仅在 AstrBot 内完成。写入前在数据目录的
`private/dududa-runtime-last-good/` 保存最后一份 command/core/evidence，目录 `0700`、
文件 `0600`。候选验证失败保留旧 Runtime；写入失败执行回滚，出现
`configuration_rollback_failed` 时停止继续应用并交部署管理员处理。若宿主在多个文件
写入之间突然被杀死，应先停止 AstrBot，
由部署管理员从此私有副本恢复三份文件后冷启动。该目录含原始凭据，禁止加入 Git、普通
备份导出或浏览器下载。它不是普通功能文档中的公开备份数据。

以下投影适配器仍可单独用于部署/冷启动；`ops/cli/apply_deepseek_runtime.py install`
仍要求宿主已经停止，不提供绕过该保护的热安装参数。

## 投影边界

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
开放（部署建议目录 `0700`、文件 `0600`）。Web 写入端与 Python 读取端都使用 4 MiB
上限。文件过大、JSON 损坏、schema 版本不
支持或 pool 标识冲突时，适配器拒绝该快照；它不会尝试修补旧值。

宿主机的 `DUDUDA_API_KEY_STORE_ROOT` 必须解析到 checkout 之外；示例配置使用同级
`../dududa-state/api-keys`，生产环境建议改为持久卷上的绝对路径。可先运行
`./manage.sh api-key-store-path` 查看并验证最终路径。官方启动命令会拒绝仓库内部
路径，避免清理 checkout 或 TreeWork worktree 时连同凭据删除。

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
| `providerId` | `provider.id` | 默认复用既有 Runtime 绑定：Luna `astrbot-luna`、Terra `astrbot-terra`、Sol `astrbot-sol` |
| `baseUrl` | `provider_source.api_base` | 仅允许 HTTP(S)，去除尾部 `/`，拒绝凭据、查询串和片段 |
| 可用 Key | `provider_source.key[]` | 过滤 disabled/unavailable/cooldown/error；按 priority 升序、weight 降序、ID 稳定排序（数值越小越优先） |
| `customHeaders` | `provider_source.custom_headers` | 最多 32 个；Authorization、Token、Cookie 等认证 Header 必须走 SecretRef |
| `timeoutMs` | `provider_source.timeout` | 向上取整为秒，限制在 1–900 秒 |
| `protocol` | `provider_source.type` | OpenAI Chat 使用 `openai_chat_completion`，Anthropic Messages 使用 `anthropic_chat_completion`；控制台不接受 Responses 协议，且当前一键应用仅支持上文的官方 DeepSeek Chat 配置 |
| `providerId`、`model`、`enabled` | `provider` | 设置 `provider_source_id`、模型和文本模态；无可用 Key 时自动关闭 |

`weight` 作为池元数据保留，不通过重复写入同一密钥来伪造权重；AstrBot 原生的
429 轮换机制负责从 `key[]` 选择下一个凭据。若部署需要真正的加权调度，应在
Provider Manager 层实现，而不是复制密钥或修改 Dududa 路由策略。

官方 DeepSeek 应用会把 `sourceId`、`baseUrl`、Key、非认证 Header、协议、超时、
`model`、`reasoningEffort` 和 `maxOutputTokens` 同步到 Provider/Runtime 配置。
`schedulingMode` 与 `weight` 仍不构成新的调度器；当前有界请求使用 AstrBot 初始 Key
选择，不在一次请求中遇到 429 后隐藏重试或跨档。`providerId` 固定为既有 Luna/Terra/Sol
绑定；新的模型/预算必须先通过实际候选探测才更新当前绑定证据。

## 生命周期与动态更新

投影适配器不在模型调用热路径轮询文件，也不注册 AstrBot Provider Manager 重载钩子。
控制台保存不会自动重载 Provider；只有上方明确的应用动作才进入 Core 自有实例交换。
离线部署侧读取投影可执行：

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
    # mapping 含原始 Key，只能在私有宿主配置边界使用。
    # 不要对持有旧 Provider 引用的在线 Runtime 调用 Provider Manager.reload。
```

控制台创建、轮换、停用或删除 Key 后，Gateway 递增快照 `revision`。应用使用该版本
进行前后两次校验；期间配置改变会放弃候选并保留旧 Runtime。适配器不执行进程重启，
不覆盖无关 Provider、群策略或运行配额。

## 安全与运维要求

- 真实 Key 只能通过控制台的显式创建/轮换请求或部署侧 Secret Manager 注入；
  不得写入 Git、浏览器 localStorage、Trace、审计正文或测试 fixture。
- `load_api_key_pool_snapshot` 的异常消息不包含文件内容、URL 查询值或 SecretRef
  解析详情；诊断时只记录 schema/revision 和脱敏状态。
- `for_astrbot()` 返回值包含原始 Key，是一次性边界对象。调用方不得打印、缓存到
  Domain 状态或再次序列化到 Web 响应；AstrBot 接收后应尽快释放引用。
- 非 Dududa 消费者仍可使用 AstrBot 自身 Key 轮换；Dududa 有界请求不隐藏重试。401/403、非法请求、Schema 错误和
  安全拒绝不得借 Key 池机制跨 tier 重试。跨 tier fallback 仍完全由既有 Runtime
  路由与 Admission 合同决定。
- 更新池元数据不会自动改变 `ModelTier`、`TierPolicy`、Endpoint descriptor
  digest 或健康 TTL。池为空、Provider 不可用或重载暂挂时，Runtime 继续使用既有
  的 provider-unavailable/fallback 行为。
- `ops/manage.sh start/up/web-up` 与无参数兼容 `upgrade` 会在启动或重建容器前创建
  API Key 目录和文件，并检查其归属为 Web 镜像中 `node` 用户的 UID 1000；若旧的
  Docker bind 目录由 root 创建，命令会先失败并要求修正归属，而不会带着不可写
  存储继续启动。带参数的 S16 upgrade 委托 Operations Driver；未来 Driver 的 start
  阶段必须执行同一 preflight 后才能声明支持该凭据根。
- 该明文私有文件故意不进入 `./manage.sh backup/restore` 的普通运行数据备份；主机
  恢复应从 Secret Manager 重新注入并轮换 Provider 凭据，具体步骤见
  `docs/operations/deployment.md` 的“数据与权限”。

契约测试位于 `tests/contracts/test_api_key_pools.py`，覆盖对象/数组快照、三档
隔离、权限、脱敏表示、SecretRef 解析、停用 Key 过滤和非法配置拒绝。
