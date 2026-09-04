# 嘟嘟哒群聊 100 题测试结果

对应问题表：[group-chat-100-questions.md](group-chat-100-questions.md)。

## 当前记录范围

- 记录日期：2026-09-04；核查工作树基线：`2a959ed`。这不是公网部署版本声明。
- 本报告先记录第 93–99 题的隔离证据映射；线上 93 题批次待主 Agent 补充。
- 本节执行真实群发送 **0** 次；使用合成消息、假客户端、假时钟和无发送 Web 测试。
- 复跑通过的是 20 项自动化检查，不是 20 道题或全部 100 道题通过。
- 当前不宣称全 100 题通过，也不把组件测试、HTTP 成功或模型预览等同于真实群聊端到端验收。

## 隔离93–99

### 93：MCP 超时后的明确失败提示 — 部分覆盖

- [OfflineToolRuntimeTests.test_verified_noncompleted_receipts_get_bounded_failure_delivery](../../tests/unit/runtime/test_tool_runtime.py#L346)：注入可信的 `FAILED` / `DEFERRED` Capability 收据，断言最终正文为“所需查询服务暂时不可用，请稍后再试。”、拒绝原因是 `capability_unavailable`、模型调用为 0，并进入正常投递授权路径。`CANCELLED` 分支不生成投递内容。
- [ManagedUnifiedMcpClientTests.test_dispatched_failure_is_unknown_and_never_retried](../../tests/unit/mcp/test_client.py#L353)：已派发的 MCP 传输失败被标为 `OUTCOME_UNKNOWN`，只创建一个 session，不重试产生未知副作用。
- 边界：上述 MCP fixture 是已派发后不可用，并非真实超时；终态失败 fixture 是通用查询服务。尚无一条“校园通知 MCP 超时 → Runtime → 聊天页面失败提示”的完整端到端用例，不能将第 93 题记为完整通过。

### 94：模型不可用时不得显示空白绿色成功 — 分层隔离通过

- [reports a missing model route instead of a successful empty preview](../../apps/web/server/agent-runtime.spec.ts#L120)：模拟 `model_route_not_found`，断言返回 503，提示包含“没有可用模型路由”。
- [preserves %s as a non-success outcome](../../apps/web/server/agent-runtime.spec.ts#L57)：分别覆盖 `no_reply`、`deferred`、`failed`、`empty`，保留真实终态与空候选，`generationObserved=false`，`outputCalls=0`、`memoryWrites=0`。
- [uses explicit internal Runtime status and keeps generated candidates in a local no-send session](../../apps/web/src/composables/useWorkspace.spec.ts#L802)：其失败分支断言结果正文包含原因、不存在 `tone=success` 的状态块，运行状态为 `error` / `warning`，生成步骤不能标为 `completed`；请求异常时状态为 `error`，`sendMessage` 从未调用。
- [AstrBotPreviewOutcomeTests.test_empty_terminal_outcomes_are_explicit_and_not_model_generation](../../tests/contracts/test_astrbot_web_runtime.py#L143)：Python 预览接口显式保留失败、延期、不回复及空结果，且无生成观察、无输出调用、无记忆写入。
- 补充：[StaticRouterTests.test_deadline_after_reserve_returns_typed_timeout_with_receipt](../../tests/unit/models/test_router.py#L1323) 验证预留后过期产生 `ModelFailureKind.TIMEOUT`，provider 调用为空、容量收据结算并释放活动租约。
- 边界：这是模型路由、预览契约与 UI 的分层证据；未中断生产模型服务，未发送真实群消息，不是生产故障端到端验收。

### 95：快速重复查询不得异常重复发送 — 部分覆盖

- [OfflineToolRuntimeTests.test_concurrent_duplicates_execute_one_tool_and_model_chain](../../tests/unit/runtime/test_tool_runtime.py#L549)：同一 run 的 50 个并发请求返回相同结果，Capability Runtime、工具 provider、模型分别仅调用一次。
- [AstrBotOutputContractTests.test_send_once_and_duplicate_returns_same_receipt](../../tests/contracts/test_astrbot_output.py#L337)：重复投递同一请求返回同一收据；总发送仍是原有三个分片，不因第二次投递增加。
- [AstrBotConnectorContractTests.test_group_reply_mention_attachment_and_dedup](../../tests/contracts/test_astrbot_connector.py#L113)：同一消息转换得到相同附件；去重键包含平台、Bot、会话和 messageId。
- 边界：这些测试覆盖同一消息/run/delivery 的重放，不覆盖用户以两个不同 messageId 发送相同“图书馆开放时间”文本时的内容级去重、提示或限流表现。

### 96：关闭自动搭话时安静，开启也不必答 — 控制逻辑隔离通过

- [ProactiveQuestionAcceptanceTests.test_disabled_or_zero_probability_is_silent_for_repeated_chat](../../tests/contracts/test_group_chat_proactive_acceptance.py#L32)：分别设置关闭且概率 100%、开启且概率 0%，连续 20 次输入都返回 false，历史读取和 bridge 调用均为空。
- [ProactiveQuestionAcceptanceTests.test_probability_does_not_require_every_message_to_reply](../../tests/contracts/test_group_chat_proactive_acceptance.py#L41)：概率 2%、固定随机值 0.5 时不触发，bridge 调用为空。
- 边界：证明普通非 @ 群消息的开关/概率门槛，不是对“我去吃饭了”的真实模型回答质量或真实自动投递验收。

### 97：材料不足时不无条件抢答 — 部分覆盖

- [ProactiveQuestionAcceptanceTests.test_insufficient_material_does_not_generate_a_guess](../../tests/contracts/test_group_chat_proactive_acceptance.py#L68)：历史仅含“有人知道这个问题吗？我先把材料找出来。”时不进入 Runtime，bridge 调用为空。
- [ProactiveQuestionAcceptanceTests.test_ineligible_event_never_enters_proactive_runtime](../../tests/contracts/test_group_chat_proactive_acceptance.py#L59)：@机器人、命令以及过短消息不会进入主动搭话路径。
- 边界：材料不足用例实际命中“历史不足三条”门槛，不证明历史足够多但缺乏相关材料时模型一定不猜测。未作模型语义质量或真实群抢答验收。

### 98：概率、冷却和每小时上限 — 控制逻辑隔离通过

- [ProactiveQuestionAcceptanceTests.test_cooldown_hourly_limit_and_window_expiry](../../tests/contracts/test_group_chat_proactive_acceptance.py#L46)：首次允许，59.999 秒时拦截，满 60 秒后允许；达到每小时两次上限后拦截，小时窗口到期恢复。最终 bridge 调用恰为三次。
- 同时复跑上述概率未命中和开关/零概率静默用例。
- 边界：时钟、随机数与投递成功都是 fake；证明确定性的控制逻辑，不是生产随机触发率统计或长期投递记录。

### 99：主动回复后不连续刷屏、不重复建议 — 部分覆盖

- [ProactiveTalkTests.test_exact_scope_reads_history_and_enters_short_proactive_runtime](../../tests/contracts/test_proactive_talk.py#L160)：第一次成功进入后立即重复返回 false，bridge 仅调用一次，主动搭话使用短回复提示。
- 第 98 题用例补充冷却、小时上限及窗口恢复证据；[ProactiveTalkTests.test_context_policy_stops_echo_before_entering_runtime](../../tests/contracts/test_proactive_talk.py#L330) 验证复读历史在进入 Runtime 前被拦截。
- 边界：能够证明短时间内不连续触发，不能证明跨冷却窗口后不会重复上一条建议。当前控制器记录发送时间而非上一条建议文本，未覆盖建议内容的语义去重。

### 复跑记录

在仓库根目录执行以下最小 Python 集合，**14 项通过**：

```bash
PYTHONPATH=packages/dududa-agent/src:apps/astrbot-plugins uv run python -m unittest \
  tests.contracts.test_group_chat_proactive_acceptance \
  tests.contracts.test_proactive_talk.ProactiveTalkTests.test_exact_scope_reads_history_and_enters_short_proactive_runtime \
  tests.contracts.test_proactive_talk.ProactiveTalkTests.test_context_policy_stops_echo_before_entering_runtime \
  tests.unit.runtime.test_tool_runtime.OfflineToolRuntimeTests.test_verified_noncompleted_receipts_get_bounded_failure_delivery \
  tests.unit.runtime.test_tool_runtime.OfflineToolRuntimeTests.test_concurrent_duplicates_execute_one_tool_and_model_chain \
  tests.contracts.test_astrbot_output.AstrBotOutputContractTests.test_send_once_and_duplicate_returns_same_receipt \
  tests.contracts.test_astrbot_connector.AstrBotConnectorContractTests.test_group_reply_mention_attachment_and_dedup \
  tests.contracts.test_astrbot_web_runtime.AstrBotPreviewOutcomeTests.test_empty_terminal_outcomes_are_explicit_and_not_model_generation \
  tests.unit.models.test_router.StaticRouterTests.test_deadline_after_reserve_returns_typed_timeout_with_receipt \
  tests.unit.mcp.test_client.ManagedUnifiedMcpClientTests.test_dispatched_failure_is_unknown_and_never_retried -v
```

在 `apps/web` 执行，分别 **5 项通过、1 项通过**；未匹配筛选条件的 17 项被跳过，未计入通过数：

```bash
npx vitest run --config vitest.server.config.ts server/agent-runtime.spec.ts -t 'reports a missing model route|preserves'
npx vitest run src/composables/useWorkspace.spec.ts -t 'uses explicit internal Runtime status'
```

没有为测试关闭生产 MCP/模型服务，没有修改生产配置，没有真实群发送，也没有读取群消息或凭据。

## 线上93题批次（待主 Agent 补充）

本节尚未记录结果。由主 Agent 补充实际运行版本、入口、批次数量、成功/失败/未测、各题脱敏摘要和必要的重试说明。不得仅以 HTTP 200 或模型名称判为通过，也不得据此将本报告改写为“100 题全部通过”。

## 总体判定

当前已记录：第 94 题分层故障呈现通过；第 96、98 题控制逻辑隔离通过；第 93、95、97、99 题部分覆盖。线上 93 题批次与真实群聊端到端结果尚未写入本报告；本节真实群发送为 0。
