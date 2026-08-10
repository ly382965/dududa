# dududa-agent

`dududa-agent` 是 Dududa 2.0 的框架无关核心契约包，要求 Python 3.10 或更高版本。
它不依赖 AstrBot、模型/MCP/Iris 第三方 SDK；包含领域契约、安全组件，以及用于契约验证的
内存/JSON 参考 Adapter，以及 S12-S14 的离线 MCP/Capability/Memory Runtime 原语。
AstrBot Event/Result Adapter 位于插件目录，生产 Runtime 尚未切流。

## 当前范围

| 范围 | 状态 | 内容 |
| --- | --- | --- |
| S01 核心契约 | 已完成 | Actor、ConversationScope、Message、Delivery、Runtime State、错误和配置 |
| S02 Port/绑定 | 已完成 | canonical codec、版本协商、Protocol、Fake 和 Contract harness |
| S03 安全组件 | 已完成 | Authorization、Confirmation、Limiter/Budget、Content Safety、Redaction、Audit、幂等 |
| S04 Adapter 边界 | 已完成 | Attachment 参考 Repository；AstrBot Connector/Output 位于插件目录 |
| S06 Memory 边界 | 已完成 | Memory Scope/Selector/Repository、显式 Write Gate、内存/JSON Adapter |
| S07 Iris/迁移边界 | 已完成 | fail-closed Iris Protocol Adapter、隔离区和可逆离线迁移工具 |
| S14 Memory 生命周期/检索 | 已完成（离线） | 删除/tombstone、scoped export、archive/restore、M0/M1/M2、CJK BM25 与固定合成 Eval |
| S12-S13 MCP/Capability | 已完成（离线） | Unified MCP、iCourse compatibility、Fake extension 与有限 Capability Runtime |
| S15-S15E 回答/主动基础 | 已完成（离线） | Answer Profile、Persona、Scheduler、Source fixture、Digest/Probe no-send Shadow |
| S18 Eval/Trace | 已完成（离线） | 版本化 suite catalog、低敏 receipt 与 append-only Runtime phase Trace |

这里的“已完成”指相应离线实施步骤与退出测试完成。Offline Orchestrator 和
RuntimeStateStore 已存在，但真实 Provider、真实 Source Adapter、生产 Iris、生产 Trace sink、
生产切流和 S23 canary 均未完成，因此产品仍未达到生产就绪。

## 包结构

```text
dududa/
├── domain/          # 不可变领域 DTO 与值约束
├── contracts/       # canonical codec、版本与 binding receipt
├── ports/           # Core 拥有的 Protocol 和调用上下文
├── runtime/         # 离线 Orchestrator、显式 State 与低敏阶段 Trace
├── security/        # 确定性安全策略与服务
├── memory/          # Scope、Repository、Write Gate、参考 Adapter 和迁移逻辑
├── evaluation/      # 版本化合成 Eval runner；不包含真实用户数据或模型调用
├── adapters/        # 不依赖外部 SDK 的参考 Adapter
├── compatibility/   # TargetTalk/ReplyPolish 的纯兼容逻辑
└── testing/         # Fake 实现
```

核心 Package 只能导入 Python 标准库和 `dududa.*`。AstrBot Event、SDK Client、Credential、
文件句柄和可变平台对象不得进入领域 DTO。

## 本地安装

从仓库根目录执行：

```bash
./ops/cli/setup_dev.sh
source .venv/bin/activate
python -c 'import dududa; print(dududa.__version__)'
```

`setup_dev.sh` 使用 `uv` 创建隔离环境并以 editable 方式安装 `dududa-agent` 与 iCourse。
系统没有 `python` 命令时也不要向系统 Python 强制安装依赖；激活 `.venv` 后使用其中的
`python`。完整环境说明见 `docs/development/local-environment.md`。

构建发布产物时必须从不含旧 `build/`、`dist/`、`*.egg-info` 和 `__pycache__` 的干净源码
构建 wheel。CI 使用 wheel 安装，而不是依赖 editable 路径。

## 安全配置语义

`parse_security_config()` 使用严格 Schema。`role_constraints` 是 v2 配置的必填映射，不是
可省略的兼容字段：

- `role_permissions` 声明某角色可以申请的动作；
- 同一角色还必须有匹配动作或 `*` 的 constraint；
- constraint 同时限制 resource type/id、Capability、最大风险和必要 metadata；
- permission 不能借用另一角色的 constraint；
- 缺字段、未知字段、空约束或不匹配都默认拒绝。

旧 AstrBot 的 owner/admin/trusted/muted 配置暂由插件兼容层解析，没有直接替换成这份 v2
Schema。生产切流前必须提供显式配置迁移和权限矩阵回归。

## Memory 安全边界

- Selector 是由可信 Authority 签发并绑定 request/Actor/Scope/expiry 的授权证明，不是任意
  查询过滤器。
- Repository 只接受当前 Write Gate 实例真实签发且未过期的 decision。
- JSON Adapter 不覆盖 legacy JSON；临时文件独占创建并拒绝 symlink。
- Iris Adapter 只暴露 exact-scope Backend Protocol，不提供全局 fallback。
- Memory Port 等待遵守 deadline/cancellation；取消的 Iris 写入回滚本地暂存状态。
- S14 mutation 会递增 generation 并使旧 Snapshot/cursor fail closed；JSON v2 持久化
  tombstone 和重放证据，restore 以 destination/checkpoint tombstone 胜出。
- M0 no-memory、M1 recency 与纯 Python CJK BM25 只在已授权有界候选集上运行；固定合成
  Eval 不声明真实中文质量。
- 自动写入、Runtime Memory、Embedding/Hybrid、真实 Iris 和生产 Memory v2 仍关闭。

离线迁移 CLI 必须在已安装本 Package 的环境中运行：

```bash
source .venv/bin/activate
./ops/cli/migrate_memory_v2.py --help
```

正式迁移要求 source、destination、classification、backup directory 和 receipt；先执行
`--dry-run`，人工核对数量后再 apply。rollback 会校验 source、backup、destination 和
quarantine digest。不要对生产数据原地试跑。

## 验证

```bash
python -m dududa.evaluation.suite check evals/suite-v1.json \
  --profile s18-focused --receipt .TreeWork/out/eval-focused.json
python -m compileall -q packages apps services ops tests
python ops/cli/check_secrets.py
mkdir -p .TreeWork/out
docker compose --project-directory . --env-file deploy/env/.env.example \
  -f deploy/compose/compose.yml config --format json \
  > .TreeWork/out/compose.json
python ops/cli/dududa_ops.py compose-contract \
  --input .TreeWork/out/compose.json
```

宿主机没有 AstrBot 时，只有两项真实 registry/命令测试允许 skip；它们必须在重建后的派生
镜像中无 skip 通过。最新完整证据和残余边界见 `docs/refactor/PROGRESS.md`。

## 扩展规则

新增 Adapter 或 Backend 时复用 Core 拥有的 Protocol，并运行同一套 Contract Test。只由
Fake 证明的后续接口保持 `provisional`；至少一个真实或现有兼容 Adapter 通过后才冻结。
新平台、模型 Provider、Memory Backend 或 MCP Server 不得通过修改 Domain 来携带其 SDK
类型，也不得绕过 Scope、Authorization、Budget、deadline、cancellation 和幂等约束。
