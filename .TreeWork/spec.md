# Project Spec

## Development Design (the project-level technical development thinking established before coding; organize subsections to fit the actual project)

### Starting Point

The current worktree implements the S01-S07 foundations but has not committed
them. The pure `dududa-agent` package, Connector/Output adapters, security
services, memory boundary, compatibility extraction, and 116-test baseline are
implementation truth. The legacy AstrBot handlers remain production authority.
`apps/web` and the Sub2API plugin are concurrent unrelated work and are outside
this project's write and commit scope.

Before isolated TreeWork branches can depend on the new package, the Lead will
create a selective baseline commit containing only the documented S01-S07
delivery and TreeWork metadata. No unrelated path is staged. Every later branch
is integrated in dependency order and revalidated against that baseline.

### Integrated Model Selection Architecture

```text
Message/Context
  -> bootstrap PERCEPTION route fixed to allowed HAIKU endpoints
  -> RulePerception + ModelPerception
  -> PerceptionMerger + whole-result Validator
  -> TaskComplexityAssessment
  -> Runtime projection to TierSelectionContext
  -> DeterministicTierPolicy -> TierDecision
  -> StaticModelRouter hard filters + fixed endpoint priority
  -> admitted Provider endpoint
  -> DIRECT_CHAT result
```

Difficulty assessment and routing form one `ModelSelectionPipeline`, but their
types remain in modules that preserve dependency direction. Perception owns
semantic evidence. Model selection owns tier policy and endpoint routing.
Runtime performs the projection between them. Neither module imports the
other's DTOs, and the Router never calls Perception recursively.

`ModelRole` describes the responsibility of a call. `ModelTier` describes an
operator-defined capability/cost class. `ReasoningProfile` describes requested
reasoning behavior. They are orthogonal and no enum ordinal implies a fallback
edge. A model or user message never selects a Provider directly.

### Shared Contracts

All public DTOs are frozen, slotted, versioned, defensively immutable, and use
the existing canonical digest and component-revision conventions.

- `TaskComplexityAssessment` records level, confidence, task kind, context
  pressure, reasoning depth, expected tool steps, ambiguity, verification need,
  evidence/reason codes, and assessor revision. It cannot contain a tier,
  Provider ID, model ID, or opaque hidden reasoning.
- `TierSelectionContext` is a minimal projection that combines validated task
  signals with role, privacy, budget and explicit operator policy.
- `TierDecision` records requested tier, policy revision, assessment digest,
  confidence handling, and reason codes.
- `ModelEndpointDescriptor` has stable `endpoint_id`, Provider-native
  `model_id`, tier, capabilities, supported reasoning profiles, privacy and
  processing declarations, and an opaque shared quota-pool reference.
- Context gating uses a conservative input-token upper bound, independent input
  limit when declared, total context limit, and output limit.
- `EndpointTrafficPolicy` contains concurrency/RPM/TPM/queue/latency/error,
  minimum-sample, cooldown and snapshot-age thresholds. Mutable observations
  live in a separate revisioned load snapshot.
- `RouteDecision` preserves the routing/catalog/load revisions, eligible and
  rejected candidates with stable reasons, selected endpoint and reasoning
  profile, and attempt/fallback receipts without raw prompt or output.

Provider-specific reasoning parameters belong to Adapter configuration. Catalog
publication fails when an enabled endpoint cannot map a required profile;
silently dropping reasoning parameters is a contract violation.

### Deterministic Routing And Reliability

One call acquires one immutable catalog/policy snapshot and one bounded health
snapshot. The selection order is:

1. role and tier allowlist;
2. data class, external-processing permission, residency and retention;
3. modality, structured-output level, reasoning profile and context limits;
4. total deadline, call/token/cost budget;
5. health, cooldown, load freshness and hard traffic thresholds;
6. a valid legacy route preference that can only reorder eligible endpoints;
7. policy priority followed by `endpoint_id` as a stable tie-breaker;
8. atomic capacity reservation immediately before Provider invocation.

Traffic observations change eligibility, not static ranking. Missing or stale
production observations are not interpreted as zero load. Endpoints sharing a
quota pool reserve against the same atomic controller.

Reliability has three separately bounded operations: retry the same endpoint,
fail over to another endpoint in the same tier, and traverse an explicitly
configured cross-tier edge. Every attempt rechecks deadline, budget, privacy,
capability and capacity. Authentication, invalid request, safety refusal and a
second structured-output validation failure stop rather than seeking a more
permissive Provider. Context overflow may traverse only an explicit edge to an
endpoint whose declared limit is sufficient.

### Perception, Complexity And Tier Policy

Rule Perception extracts deterministic mention, reply, command, lexical and
shape signals. Model Perception uses the fixed `PERCEPTION/haiku` route and a
strict versioned output schema. Invalid model output is discarded as a whole.
The merger gives deterministic evidence precedence and the validator ensures
all identity/reference evidence belongs to the current ContextSnapshot.

Initial TierPolicy is conservative and deterministic:

- clear low-complexity extraction/rewrite/simple answer evidence may select
  `haiku`;
- low confidence, rule/model conflict, or ordinary direct chat selects
  `sonnet`;
- `opus` requires multiple validated high-complexity signals, a configured
  confidence threshold, sufficient budget and an allowed role policy;
- long context is a capability pressure signal, not proof of semantic
  difficulty;
- prompt text requesting a named tier or model is untrusted data.

Evaluation labels complexity by the lowest tier that meets a frozen quality
threshold on the same sanitized task, not by subjective difficulty. Splits are
clustered by full conversation/group. Reports include under-routing quality
violations, minimum-sufficient-tier agreement, unnecessary Opus escalation,
calibration, cost, latency, and task/context/privacy strata.

### S10 Offline Runtime

The first Orchestrator supports only explicit mentions and direct replies.
Memory, tools, attachments requiring preprocessing, and proactive chat are
disabled. It provides a testable in-memory state store, current-message context
builder, deterministic social policy, direct-chat model call, minimal response
composer, one pass-through/deterministic persona renderer, render validation,
and two-stage delivery acknowledgement.

Before orchestration, contract drift is corrected: successful/partial/failed or
unknown delivery completion must be representable; `reconcile_delivery()` and
one authoritative `DeliveryConstraints` shape must match design and code.
Visible output ends at `READY_TO_EMIT`; only a caller-provided delivery receipt
advances acknowledgement/completion. Cancellation and deadlines stop new work,
unknown side effects are not retried, and the total budget covers both the
bootstrap perception and direct-chat calls.

`ShadowRunner` is a separate side-effect-denying composition. It has no real
OutputAdapter, Memory writer, Tool executor or event-stop capability. A shadow
candidate may be evaluated and traced but cannot be converted into an external
send.

### S11 Controlled Rollout

Typed configuration defines `off`, `shadow`, and `canary`, with an independent
delivery enable switch, allowlisted group IDs, revision and kill-switch state.
The AstrBot bridge checks admission before launching work and checks the
kill-switch again immediately before delivery.

Shadow never claims event ownership. Canary can claim only an allowlisted group
message that explicitly mentions the current bot, is pure supported input, and
requires neither tools nor memory. Once claimed, exactly one path owns delivery;
failure cannot asynchronously fall back to the old handler and create a second
reply. Persistent CAS/dedup state and delivery tombstones protect concurrent and
restart replay cases.

Metrics are low-cardinality and sanitized: mode, role/tier/endpoint revision,
candidate versus actual outcome, latency/TTFT, token/cost usage, fallback/error
kind, under-route and unnecessary-escalation evaluation. Raw messages, prompts,
model output, QQ IDs, credentials and Provider error bodies are excluded.

Real-group execution remains an external action. Code, simulation, configuration
and rollback rehearsal can be completed locally; actual shadow/canary evidence
requires an explicitly authorized group and credentials.

### Verification And Change Discipline

Each implementation branch has focused Unit, Contract, negative and failure
tests. The final audit reruns the full Python suite, import boundaries, compile,
secret scan, shell, Compose parse, whitespace checks, wheel/image/plugin smoke
where affected, and a requirement-by-requirement audit. Branch-local success is
not evidence that the S08-S11 objective is complete.

Bandit, random weights and learned online routing have no implementation hook in
this project beyond reproducible static decision receipts that a later S20 can
consume after a separate design review.
