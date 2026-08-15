# Luna / Terra / Sol 候选配置样板

## 目的

样板文件位于
`configs/astrbot/luna-terra-sol.candidate.example.json`，用于给三档静态模型路由提供一组
**无真实凭据、默认关闭**的初值：

| Endpoint | Dududa Tier | AstrBot Provider ID | 模型 ID |
| --- | --- | --- | --- |
| Luna | `haiku` | `astrbot-luna` | `gpt-5.6-luna` |
| Terra | `sonnet` | `astrbot-terra` | `gpt-5.6-terra` |
| Sol | `opus` | `astrbot-sol` | `gpt-5.6-sol` |

它不是可直接覆盖 AstrBot 全量配置的文件。`astrbot_config_additions` 表示需要追加到私有
AstrBot 配置中的 Source 和 Provider；`dududa_plugin_config` 表示插件配置初值。不要用样板覆盖
现有 `provider_sources`、`provider` 或 `provider_settings`。

## 配置分层

AstrBot Source 保存 OpenAI-compatible 传输配置和 Secret 引用；三个 AstrBot Provider 分别绑定
模型 ID；Dududa Runtime 再把 Provider 映射为 Haiku、Sonnet、Opus，并独立声明上下文、输出、
并发、RPM 和 TPM 初值。这样更换中转、凭据或单个模型时，不需要修改 Dududa Domain 或路由
策略。

样板使用 `https://example.invalid/v1` 和环境变量引用 `$DUDUDA_GPT56_API_KEY`，仓库中没有真实
Base URL 或 Key。实际接入时只在 AstrBot 私有配置或 Secret Store 中替换，不把 Secret 写回
Git。

## 当前边界

- 三个 AstrBot Provider 均为 `enable=false`。
- `runtime_enabled=false`、`rollout_mode=off`、实际投递关闭、kill switch 开启，工具、Memory 和
  群白名单也保持关闭。
- 本样板没有配置主动出站能力，不会发送 QQ 消息。
- 每个 Endpoint 都有独立的 `reasoning_depth` 字段；Runtime 会将其映射为唯一的
  `provider-default` reasoning profile。样板初值为 Luna=`light`、Terra=`balanced`、Sol=`deep`，
  这是静态 Endpoint 初值，不是同一 Endpoint 的请求级动态切换。当前只抽样验证过 `low` 参数，
  `medium/high` 仍须由真实 AstrBot Provider conformance 证明；证据不满足时 Builder 会拒绝启用。
- 样板中的上下文、输出和流量值只是保守的 pilot 初值，不代表模型公开能力、真实配额、质量或
  生产可用性；应根据 Provider 合同与短时吞吐测量调整。
- 候选样板不填写 `runtime_provider_evidence_path`，因为该值必须指向部署机上的仓库外私有文件。
  若 AstrBot Context 没有 Evidence resolver，则实际部署必须在私有插件配置中补充该路径。
- Evidence 文件顶层为 `schema_version=1` 和 `providers` 数组；每条记录绑定
  `astrbot_provider_id`、`verified_model_id`、Conformance revision、输出上限、residency、
  retention 和现有验证 flags。不得写入 Key、Base URL、QQ ID 或聊天正文。
- Builder 按 Context resolver 优先、私有文件 fallback 的顺序解析 Evidence。Provider/model
  不匹配或验证 flags 不完整时拒绝装配。可解析文件本身不构成真实 Conformance 证据。
- Builder 装配后健康仍为 `UNKNOWN`。外部健康采集器必须显式发布有 TTL 的
  `ModelHealthEvidence`；到期未刷新时 Router 自动停止使用该 Endpoint。

## 最短使用顺序

1. 把 Source 和三个 Provider 追加到私有 AstrBot 配置，保留 `enable=false`。
2. 在私有环境中设置 Base URL 和 `DUDUDA_GPT56_API_KEY`，不要改仓库样板。
3. 在实际 AstrBot 路径验证 Provider ID、模型绑定、参数透传、输出上限、residency、retention、
   日志、deadline 和 cancellation。
4. 将结果写入仓库外 Evidence 文件，并在私有插件配置中设置
   `runtime_provider_evidence_path`。
5. 配置 `runtime_models_json`，接入持续健康采集；确认
   `UNKNOWN -> HEALTHY -> TTL 到期 UNKNOWN`。
6. Preflight 完成前继续保持 Runtime、rollout、投递和主动出站关闭。

聊天数据的 4--5 小时抽样预算见 `docs/operations/s23-real-group-validation.md` 第 1.2 节；首轮按
分层小样测量吞吐，不把约 410 MB 原始记录一次性提交给模型。

私有 Evidence 解析和 TTL 健康发布工程纵切已经完成；真实运行 AstrBot Provider 注册、真实
Conformance、持续健康采集、部署切换和单群 Shadow 仍未完成。S23 保持 `paused/partial`。
