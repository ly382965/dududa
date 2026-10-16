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
- Builder 装配后健康仍为 `UNKNOWN`。仓库已提供可选的周期健康刷新，但
  `runtime_health_probe_enabled=false` 是默认值，候选样板和运行中的 AstrBot 都没有启用它。
  显式启用后，单次探测最多输出 8 Token、零重试，并按配置的 timeout/TTL 发布
  `ModelHealthEvidence`；成功转为 `HEALTHY`，超时、异常或空结果只转为脱敏 `UNKNOWN`，到期
  未刷新时 Router 自动停止使用该 Endpoint。默认 interval/timeout/TTL 为 45/15/90 秒。

## 已完成的隔离抽样

候选渲染器已经在隔离 AstrBot 数据目录抽样：它按 ID 合并 Source、Provider 和插件配置，不覆盖
无关配置；默认保持三个 Provider、Runtime 和投递关闭，kill switch 开启，群白名单为空。该抽样
没有修改、重启或替换运行中的 AstrBot/NapCat。

固定镜像 `dududa/astrbot:s23-candidate-local` 也已在 `--network none`、临时
`/AstrBot/data`、无 NapCat 和无端口暴露的容器中启动，AstrBot 4.26.2 成功加载 Dududa Core；
候选容器随后停止并清理。这是隔离启动证据，不是运行中部署或生产切换。

三个模型还各完成一次固定合成的 Provider-level no-send 请求：

| 模型 | Tier | 结果 | 延迟 | usage（输入/输出/总计） | Provider / Output 调用 |
| --- | --- | --- | ---: | ---: | ---: |
| `gpt-5.6-luna` | Haiku | 成功 | 1.980 秒 | 21 / 7 / 28 | 1 / 0 |
| `gpt-5.6-terra` | Sonnet | 成功 | 1.846 秒 | 21 / 7 / 28 | 1 / 0 |
| `gpt-5.6-sol` | Opus | 成功 | 2.503 秒 | 21 / 7 / 28 | 1 / 0 |

Runner 不导入 QQ Connector 或 Output Adapter，并丢弃 Prompt、回答和 Provider 错误正文；私有
Receipt 位于 `/home/mmdustc/temp/dududa-s23-provider-no-send-shadow.json`，权限为 `0600`。
这只证明三种模型的一次 Responses 请求可用和该隔离路径零 QQ Output，不是运行中 AstrBot 的
Provider Conformance、候选部署或真实单群 Shadow。

健康刷新也只完成了 Fake Provider 的代表性抽样：周期成功能够刷新 `HEALTHY`，超时会取消请求
并发布 `UNKNOWN`，没有运行事件循环时保持零 Provider 调用，TTL 到期后恢复 `UNKNOWN`。真实
Endpoint 的持续健康、错误率和配额仍须在候选部署后取得证据。

## 最短使用顺序

仓库提供 `ops/cli/render_astrbot_candidate.py`，用于把样板按 ID 合并进一个隔离的 AstrBot
数据目录，避免手工覆盖现有 Provider。先以关闭状态生成候选配置：

```bash
uv run --locked python ops/cli/render_astrbot_candidate.py \
  --template configs/astrbot/luna-terra-sol.candidate.example.json \
  --data-root /path/to/isolated-astrbot-data
```

脚本默认保持 Source、三个 Provider 和 Dududa Runtime 关闭。只有在仓库外准备好 Base URL、Key
与真实 Evidence 文件后，才可显式选择 `--mode shadow`；脚本不会把 Key 打印到标准输出，且仍会
保持投递关闭、kill switch 开启、群白名单为空。不要对正在运行的 AstrBot 数据目录直接执行。

1. 用上述脚本把 Source 和三个 Provider 合并到隔离的私有 AstrBot 配置，保留关闭状态。
2. 在私有环境中设置 Base URL 和 `DUDUDA_GPT56_API_KEY`，不要改仓库样板。
3. 在实际 AstrBot 路径验证 Provider ID、模型绑定、参数透传、输出上限、residency、retention、
   日志、deadline 和 cancellation。
4. 将结果写入仓库外 Evidence 文件，并在私有插件配置中设置
   `runtime_provider_evidence_path`。
5. 配置 `runtime_models_json`；完成真实 Conformance 后，接入外部健康采集或显式启用默认关闭的
   `runtime_health_probe_enabled`，确认 `UNKNOWN -> HEALTHY -> TTL 到期 UNKNOWN`，并抽样
   Provider 超时/错误仍只产生脱敏 `UNKNOWN`。
6. Preflight 完成前继续保持 Runtime、rollout、投递和主动出站关闭。

聊天数据的 4--5 小时抽样预算见 `docs/operations/s23-real-group-validation.md` 第 1.2 节；首轮按
分层小样测量吞吐，不把约 410 MB 原始记录一次性提交给模型。

私有 Evidence 解析、TTL 健康发布、默认关闭的刷新循环和三模型 Provider-level no-send 抽样已经
完成；真实运行 AstrBot Provider 注册、真实 Conformance、实际启用后的持续健康证据、部署切换
和单群 Shadow 仍未完成。S23 保持 `paused/partial`。
