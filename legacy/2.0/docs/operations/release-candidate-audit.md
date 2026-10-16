# Dududa S19 候选发布审计

## 1. 适用范围

本流程只验证本地、离线、无真实发送的候选发布形状。它不会调用模型 Provider、抓取实时来源、
读取真实聊天，也不会启动、停止或替换当前运行中的 NapCat/AstrBot Compose 栈。

权威入口：

- `configs/release/s19-pilot-slo-v1.json`：pilot SLO；
- `configs/release/legacy-surfaces-v1.json`：S22 前的兼容面目录；
- `ops/cli/audit_release_candidate.py`：严格 evidence/receipt CLI；
- `ops/cli/smoke_release_images.sh`：一次性镜像与无网容器 smoke。

所有正式 receipt 写入私有临时目录，文件权限为 `0600`。仓库只记录摘要、计数和结论，不提交
测试输出、绝对路径、环境变量、容器名称、凭据或用户标识。

## 2. Pilot SLO 的含义

当前 policy 把错误目标、重复投递、quiet hours/撤销后投递、未授权 Capability、跨 Scope
Memory 和敏感 Trace 的最大值固定为 `0`。SHORT/MEDIUM/LONG token 上限与代码保持
`128/512/1536`。

延迟和恢复值标记为 `pilot_default`，Provider 成本、真实 QQ 延迟、中文质量、打扰度和实时来源
新鲜度标记为 `external_pending`。因此 S19 通过后仍会输出 `s23_ready=false`；这不是生产
SLO 已达标的声明。

校验命令：

```bash
python ops/cli/audit_release_candidate.py policy-check \
  --input configs/release/s19-pilot-slo-v1.json
```

## 3. 生成消费者清单

清单只扫描 Git tracked UTF-8 文本，输出相对路径，不读取运行数据。`remove_candidate` 只是
S22 审查候选，不代表 S19 会删除；`retain_live` 和 `blocked_unknown` 必须保留。

```bash
python ops/cli/audit_release_candidate.py inventory \
  --root . \
  --definitions configs/release/legacy-surfaces-v1.json \
  --output /tmp/dududa-s19/inventory.json
```

旧 AstrBot `AuditLog` 单独列项。它可能记录 sender/group，不能使用 S18 Runtime Trace 的
脱敏证据替代审查。

## 4. Gate receipt

每个测试命令把完整输出留在私有临时目录。命令成功后只将输出文件摘要写入 gate receipt：

```bash
python ops/cli/audit_release_candidate.py gate \
  --gate-id python-3.12 \
  --status passed \
  --case-count 0 \
  --evidence /tmp/dududa-s19/python-3.12.log \
  --reason-code repository_tests_passed \
  --output /tmp/dududa-s19/gate-python-3.12.json
```

`gate-id` 是固定集合，不能通过配置加入 Shell 或任意 callable。最终候选缺少任一 gate、存在
重复/失败 gate、摘要漂移或 Git 工作区不干净时都会拒绝。

## 5. 镜像 smoke

```bash
ops/cli/smoke_release_images.sh \
  >/tmp/dududa-s19/release-images.json
```

脚本使用唯一 tag/容器名构建 AstrBot 和 Web 镜像。运行阶段固定 `--network none`：AstrBot
验证 agent package、MCP v1/v2 隔离、iCourse 空库握手和插件组合；Web 仅在容器 loopback
检查 `/api/health`。退出和失败路径都会删除临时容器，不执行 `docker compose up`，不引用生产
volume 或现有容器。

构建阶段在缺少本地 cache 时可能访问镜像和依赖 registry；这不等于应用访问 Provider、MCP
公网来源或 QQ。

## 6. 上一版本和候选 receipt

先从明确的上一 Git revision 生成只读 source archive：

```bash
python ops/cli/audit_release_candidate.py archive \
  --root . \
  --revision <40位上一版本提交> \
  --output /tmp/dududa-s19/previous-release.tar
```

全部固定 gate 通过后，用重复 `--gate` 参数聚合最终 receipt：

```bash
python ops/cli/audit_release_candidate.py candidate \
  --root . \
  --previous-revision <40位上一版本提交> \
  --previous-source /tmp/dududa-s19/previous-release.tar \
  --policy configs/release/s19-pilot-slo-v1.json \
  --inventory /tmp/dududa-s19/inventory.json \
  --gate /tmp/dududa-s19/gate-python-3.10.json \
  --gate /tmp/dududa-s19/gate-python-3.12.json \
  --output /tmp/dududa-s19/candidate.json
```

示例省略了其余必需 `--gate`；只有 18 个固定 gate 全部存在并通过才会生成候选 receipt。
最终 `passed_offline` 只关闭 S19，真实 Provider、来源、中文质量、QQ 和 S23 授权仍保持未完成。
