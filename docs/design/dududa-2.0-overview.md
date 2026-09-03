# Dududa 2.0 Design Overview

状态（2026-09-03）：S01–S22 的既定本地/离线范围与 S21 Bot Control Plane 已实现并验证。S23 已完成历史
语料 no-send Demo、控制台内测、候选模型工程和第一条 Dududa 2.0 自然语言 iCourse 本地
纵切，并进入群内明确 @ 的实时入站 Canary；Memory 生产读写、主动发送、在线 Bandit、完整
人工质量和真实 QQ 端到端回执仍按各模块边界推进。NotifAI 已在当前 main 纳入独立 MCP
Server、7 个 capability mapping 和 Web 目录。PR #10 的非重复规则已整理为默认关闭的
`astrbot_plugin_dududa_social`，五个非重复校园信息服务已作为 Registry-only、cache-only、
无 Capability mapping 的可选 Server 打包；它们不进入 Planner 或生产 health。当前证据以
`../refactor/PROGRESS.md`、`dududa-2.0-design-report.md` 及
`../integrations/pr10-selective-integration.md` 为准。

本日新增的 100 条原生消息 Runtime 模拟使用当前 Production Composition、Schema-accurate
本地 MCP fixture 和 Fake Delivery 完成 94/100 条 2.0 接管，6 条按 Connector/Admission 边界
保留 legacy；0 次真实 QQ 发送、0 次 Memory 写入、0 个未捕获异常。逐题结果和证据边界见
`../refactor/dududa-2.0-100-question-runtime-simulation-2026-09-03.md`。

Dududa 2.0 separates a framework-neutral Agent Runtime from AstrBot adapters,
MCP servers, model Providers, memory backends, and deployment. The repository
remains one Bot Runtime Monorepo so a single review can validate adapter,
runtime, service, operation, and compatibility changes together.

## Design Index

- Runtime and state machine: `runtime.md`
- Perception and Social Decision: `perception-and-social.md`
- Memory Scope, retrieval, and Write Gate: `memory.md`
- Capability and unified MCP runtime: `capability-and-mcp.md`
- Model-role routing: `model-routing.md`
- Conservative online learning and Contextual Bandit: `online-learning.md`
- Proactive conversation probes, subscriptions and scheduled digests: `proactive-messaging.md`
- Bot Control Plane and group-service onboarding: `bot-control-plane.md`
- Persona and OC rendering: `persona.md`
- Security, privacy, audit, and rate limits: `security.md`
- Target repository layout: `repository-layout.md`
- Migration summary: `migration-plan.md`
- Phase 0 historical baseline: `../refactor/current-state.md`
- Full target architecture: `../refactor/target-architecture.md`
- Detailed old/new mapping: `../refactor/migration-map.md`
- Reviewable phase plan: `../refactor/implementation-plan.md`
- Governed adaptive-runtime evolution research: `../research/deepseek-harness-inspired-dududa-evolution.md`
- PR #10 selective plugin/MCP integration: `../integrations/pr10-selective-integration.md`

## Non-Negotiable Boundaries

1. Adapters convert external types; core never reads AstrBot Events.
2. Runtime owns explicit state and bounded transitions.
3. Memory Scope is exact and fail-closed before semantic retrieval.
4. Social Decision is independent of Persona.
5. Model Router and Tool Router are separate.
6. Planner sees normalized, eligible Top-K capabilities.
7. MCP transport is hidden behind one Client and Registry.
8. Response Composer protects truth; OC Renderer only changes expression.
9. Existing plugin IDs, commands, and deployment entry points remain compatible
   until tested removal gates pass.
10. Secrets and production state never enter repository code, fixtures, traces,
    evals, or documentation.
11. Attachment bytes stay behind a scoped repository; only opaque references and
    bounded authorized streams cross adapter boundaries.
12. Online learning ranks only hard-filtered actions; propensity is logged before
    execution, and reward never offsets a security or privacy violation.
13. Answer Profile, Model Tier and Reasoning Profile are independent; Router
    consumes a validated visible-output budget but does not infer answer length.
14. Scheduler, Capability/MCP retrieval and platform delivery have separate
    owners. A timer never forges an inbound user message, and MCP never owns a
    subscription, target, send decision or DeliveryReceipt.
15. Proactive behavior is default-off and target-bound. Empty allowlists,
    missing authorization, quiet hours, limiter/audit failure, unsubscribe and
    kill switch all fail closed before delivery.
16. Web is the product Bot Control Plane, but every mutation goes through the
    same typed Core command authority; browser state never becomes Runtime
    policy, permission or delivery truth.
17. A newly joined group stays `PENDING_PROFILE` until an authorized Bot
    administrator activates a versioned `GroupServiceProfile`. Group Context,
    plugins, models and Bandit cannot widen that assignment.

## Delivery Strategy

The design is delivered additively. A pure package is established and tested
first. Existing plugins then become compatibility adapters one behavior at a
time. Memory and tool boundaries cut over only after isolation and contract
tests exist. Deployment paths move last, with root wrappers and rollback.

No target box in these documents should be interpreted as implemented unless
the progress document and tests identify its production entry point.
