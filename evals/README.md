# Dududa 离线评测入口

`suite-v1.json` 只索引既有评测和 Contract，不定义任意命令或可调用对象。执行端使用
`dududa.evaluation.suite` 中的固定 Registry；新增 runner 必须经过代码审阅，不能由 JSON
加载 Python callable 或 Shell。

```bash
# 校验四套 committed bundle；会重放生成/摘要绑定
python -m dududa.evaluation.suite check evals/suite-v1.json \
  --profile committed-bundles \
  --receipt .TreeWork/out/eval-bundles.json

# S18 风险抽样：bundle + Router/MCP/Capability/Persona/Proactive/Trace
python -m dududa.evaluation.suite check evals/suite-v1.json \
  --profile s18-focused \
  --receipt .TreeWork/out/eval-focused.json

# CI/S19 使用的全仓 Python discovery 入口
python -m dududa.evaluation.suite check evals/suite-v1.json \
  --profile ci-python \
  --receipt .TreeWork/out/eval-python.json
```

Receipt 只保存版本、计数、状态、摘要、持续时间和外部门禁，不保存测试输出、正文、
Prompt、模型结果、工具参数、绝对路径、环境变量、凭据或 QQ 标识。它的 `passed` 仅表示
离线技术门禁通过；每套 bundle 的 `release_ready=false`、人工评审和真实数据门禁保持原样。

当前 committed bundle：

| Suite | 证据 | 不证明 |
| --- | --- | --- |
| Perception/Tiering v1 | 320 个合成 policy case、32 cluster | 真实模型质量或最低可用 Tier |
| Semantic v2 | 5 个 Schema/span/codec case | 真实中文多轮理解质量 |
| Memory v1 | 8 个 M0-M2 词法/隔离 case | 生产 Memory、Iris 或语义检索质量 |
| Response Profile v1 | 17 个机械约束 case、3x3 matrix | Persona 风格和真实 QQ 长度体验 |

其他模块在 catalog 中明确标为 `contract_suite`，不能冒充带人工标签的数据集 Eval。
