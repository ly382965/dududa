# S09 Perception And Tiering Spec

## Scope And Outcome

Implement the deterministic S09 path that turns bounded, de-identified message
context into validated semantic evidence, a versioned task-complexity
assessment, a conservative social action and an auditable `haiku` / `sonnet` /
`opus` tier decision. S08 remains the only component that resolves the chosen
tier to a physical Provider endpoint.

S09 does not add Bandit learning, random exploration, online weight updates,
tools, Memory access, delivery, proactive group interruption or Provider-native
payload logic. The first runtime may consume S09 for direct chat, but S10 owns
that orchestration and its side-effect boundaries.

## Dependency Direction

```text
dududa.domain.task
        ^
        |
dududa.perception <--- dududa.runtime ---> dududa.models
        ^                  |
        |                  v
dududa.ports          ModelRouter port
```

- Semantic DTOs, rules, model/rule merge, whole-result validation, complexity
  assessment and social policy belong to `dududa.perception`.
- Tier configuration and deterministic tier choice belong to `dududa.models`.
- Router-backed Model Perception and projection from assessment to
  `TierSelectionContext` belong to `dududa.runtime` because they import both
  sides.
- Protocols belong to `dududa.ports`; Provider/AstrBot payloads remain in
  adapters.
- `dududa.perception` must not import `dududa.models`, and `dududa.models` must
  not import `dududa.perception`.

## Selection Pipeline

```text
bounded PerceptionContext
  -> RulePerception
  -> RouterBackedModelPerception (PERCEPTION, fixed HAIKU, strict Schema)
  -> whole ModelProjection Validator
  -> DeterministicPerceptionMerger
  -> PerceptionResult
  -> DeterministicComplexityAssessor
  -> TaskComplexityAssessment
  -> Runtime projection (role, privacy, token bound, budget)
  -> DeterministicModelTierPolicy
  -> TierDecision
  -> S08 StaticModelRouter
```

The bootstrap `PERCEPTION` call uses `BootstrapTierDecision` with exactly
`ModelRole.PERCEPTION` and `ModelTier.HAIKU`. It cannot depend on an assessment;
this breaks the otherwise recursive need to choose a model before estimating
difficulty. User text that names a tier, model or Provider is evidence only and
never becomes routing authority.

Social decision consumes the same validated `PerceptionResult`. It may
short-circuit later model work with `IGNORE`, `ASK_CLARIFICATION` or `DEFER`.
Computing the pure complexity assessment before that gate is allowed, but no
downstream Router call occurs for a terminal social action.

## De-identified Input Contract

`PerceptionContext` is not a raw `MessageEnvelope`. It contains:

- an opaque context ID and Scope digest;
- conversation kind and an opaque bot identity reference;
- an ordered, bounded tuple of `PerceptionMessage` values;
- one current message reference;
- opaque known identity references;
- a bounded list of capability categories, degraded components and an input
  token upper bound;
- a data classification used by Runtime when constructing the model request.

It also carries a versioned `PerceptionLimits` value. Core enforces both the
configured limits and immutable v1 hard ceilings for message/identity counts,
per-message and total characters, capability/degraded-component categories,
opaque reference lengths, candidate counts, evidence references and expected
tool steps. A caller cannot bypass boundedness by constructing the DTO directly
before S10 exists, even when a custom Router omits Schema validation.

Each message has an opaque message reference, opaque author reference, text,
same-context reply reference, resolved mention references and a trusted
bot-authored flag. Constructors reject duplicate or unknown references,
cross-context reply targets, an absent/non-terminal current message and an
unknown bot identity. The Model Perception serializer does not include raw QQ,
group, user, platform or authorization identifiers. S10 owns construction from
the Connector and must apply size limits before S09.

S09 Eval accepts only explicitly synthetic content. The existing general
redactor does not prove de-identification of names, QQ numbers, phone numbers
or student IDs; sanitized real chat data requires a separate PII review before
it may enter a future dataset.

## Semantic Contracts

All public values are frozen, slotted, Schema v1, defensively immutable and
canonical-digestible. Collections reject duplicates and use stable ordering.
Evidence references must resolve to messages in the current context.

`RulePerceptionResult` records deterministic facts: direct mention/reply,
question/command shape, speech acts, target identities, bounded lexical/shape
signals, tool-category hits and rule complexity signals.

`ModelPerceptionProjection` contains only semantic candidates:

- target identities, speech acts, topics, intents and entities;
- message/identity/topic references and ambiguities;
- tool need and requested capability categories;
- task kind, reasoning depth, estimated tool steps, verification need and
  typed complexity signals;
- confidence and evidence references.

It contains no tier, Provider, model ID, authorization, actor role, Scope or
free-form hidden reasoning. A Draft 2020-12 Schema rejects unknown properties.
The Core decoder independently checks exact keys and types after the S08 Codec.

`PerceptionResult` is the merger output and records component revisions,
model-projection status, stable reason codes and receipt digests rather than
raw prompts, model output or hidden reasoning.

## Rule, Model, Validation And Merge Behavior

`DeterministicRulePerception` recognizes only configured, reviewable signals:
mention/reply facts, private-message directness, explicit question/command
shape, code blocks, URLs, list/constraint shape and configured capability
keywords. Lexicons and thresholds have a component/config revision. Rules do
not guess authorization or physical models.

`RouterBackedModelPerception` serializes the bounded context as canonical JSON,
wraps it in a revisioned instruction that treats content as data, sets no
`RouteHint`, and invokes S08 with a generated bootstrap Haiku authority. The
Router validates structured output and performs its one bounded repair.

The whole model projection is discarded if any property, enum, confidence,
identity, message evidence, reference target, capability category or evidence
binding is invalid. There is no partial JSON salvage. Timeout/cancellation is
propagated when the enclosing run must stop; ordinary model unavailability or
invalid output falls back to rules with a stable failure kind and a confidence
ceiling below the normal-tier threshold.

The merger is deterministic:

1. trusted rule mention/reply/command facts and response targets win; a model
   cannot add another known group identity to the delivery target;
2. model candidates may add semantics but cannot remove rule facts;
3. equal normalized candidates merge evidence and use the conservative
   confidence;
4. incompatible candidates set `conflicting_evidence` and lower confidence;
5. output collections are sorted by stable semantic keys, never arrival order.

## Complexity Assessment

`DeterministicComplexityAssessor` receives only validated context statistics
and `PerceptionResult`. It emits the existing `TaskComplexityAssessment` with
level, confidence, task kind, context pressure, reasoning depth, expected tool
steps, ambiguity, verification need, conflicts, typed reason codes, evidence
references and assessor revision. It never emits a tier or endpoint.

Initial high-complexity signals are independently auditable categories such as
`deep_reasoning`, `multi_constraint_synthesis`, `independent_verification`,
`multi_step_tool_plan` and `cross_artifact_analysis`. A high level requires at
least two configured independent high signals. A low level requires explicit
low-task evidence, shallow reasoning, zero expected tool steps, low ambiguity,
no verification requirement and no conflict. Everything else is medium.

Assessment confidence is the conservative minimum confidence of decisive
semantic evidence. Rule/model disagreement and model fallback are capped below
the TierPolicy low-confidence threshold. Confidence is a calibrated quality
claim about the whole assessment, not permission and not a hidden reasoning
score.

Context pressure is computed from the bounded token estimate and versioned
thresholds. It remains orthogonal to semantic level: long but simple input may
be `LOW` complexity with `HIGH` context pressure, while short formal reasoning
may be `HIGH` complexity with `LOW` pressure.

## Deterministic Tier Policy

The policy consumes `TierSelectionContext`; it never reads message text.
Versioned `TierPolicyDefinition` remains role-specific. Initial behavior is:

```text
conflicting evidence                         -> default SONNET
confidence below configured threshold       -> default SONNET
clear low-complexity assessment              -> HAIKU
HIGH + enough configured high signals
     + high-tier confidence + role allowlist -> OPUS
otherwise                                    -> default SONNET
```

The initial test policy uses `0.60` as the low-confidence threshold, `0.85` as
the high-tier threshold and two high signals. These are configuration values,
not implementation constants.

Budget is applied after the uncapped decision. Explicit semantic fields in the
definition establish the fallback sequence `high -> default -> low`; enum
ordinals are never used. The first affordable allowed tier becomes
`selected_tier`. A downgrade records `uncapped_tier` and
`ConfidenceHandling.BUDGET_CAPPED`. If no allowed tier can meet model-call,
input-token, generated-token and configured cost floors, the policy raises a
typed budget error instead of fabricating a decision. `cost_units_remaining`
of `None` follows the existing Router convention and means there is no explicit
cost ceiling.

Reasoning depth remains separate from tier. S09 records the assessed task depth
but S08 currently binds one configured `reasoning_profile_id` per Role and
requires every request to use it. S09 therefore uses that fixed Role profile;
dynamic per-request profile selection requires a later explicit Router-policy
contract extension. An Adapter must still prove support rather than silently
ignoring the configured profile.

## Initial Social Policy

`DeterministicSocialDecisionPolicy` is a pure, ordered hard-rule chain over the
validated result and a read-only `DecisionSignals` projection:

1. self/duplicate or unknown target -> `IGNORE`;
2. response authorization denied -> `IGNORE`;
3. private-data/group-policy boundary -> `DEFER`;
4. no explicit mention/reply/private interaction in S10 scope -> `IGNORE`;
5. tool required while tools are disabled or unauthorized -> `DEFER`;
6. unresolved high-value ambiguity with a bounded question key ->
   `ASK_CLARIFICATION`;
7. otherwise -> `DIRECT_REPLY`.

The v1 enum can represent future actions, but this branch does not emit
probabilistic proactive replies or execute tools. Persona cannot alter the
action, targets, permission or facts.

## Determinism, Receipts And Errors

Canonical domains cover context, rule result, model projection, merged result,
social decision and Eval artifacts. Plan fingerprints exclude generated IDs,
timestamps and observed latency; execution receipts retain them. Logs and
reports contain digests, revisions, enums and stable reason codes, never raw
message text, prompts, model output, platform IDs, credentials or Provider
error bodies.

Model Perception derives its idempotency key from the complete deterministic
`ModelRequest` plan fingerprint (which excludes request ID and the key itself),
not from message context alone. Prompt, Schema, reasoning or privacy-policy
changes visible in the S09 request therefore cannot collide with a cached
request from an older plan.

Public boundaries raise `DududaError` with stable categories/codes. Model
fallback records a sanitized failure enum. Programming defects do not copy an
exception string into a receipt. Cancellation/deadline checks occur before
starting Model Perception and before accepting its result.

## Evaluation Design

Commit a versioned, offline, no-network synthetic Eval bundle. The technical
target is 320 cases from 32 agent-reviewed scenario templates with 10 distinct
deterministic text variants each: 80 development cases and 240 held-out cases.
Human review remains an explicit release gate. Variants are correlated samples,
not independent observations. Cluster lineage (group, conversation, reply
chain, time window and template family) cannot cross splits; all dedicated
security-negative template families remain in the held-out split.

The bundle separates:

- cases and synthetic provenance;
- gold perception, complexity, social and policy-tier labels;
- fixed model projections/failures;
- split manifest, quality rubric, Eval plan and data card;
- dataset, prediction-set and report digests with component revisions.

The runner strictly validates exact keys and types, rejects duplicate JSON
keys and non-finite numbers, proves every record against the frozen synthetic
generator, verifies all record/set/manifest/split/rubric/plan digests and binds
those digests into the report. Recomputed record digests cannot legitimize an
extra platform-ID field, modified split or different message text.

`policy_gold` means the expected result of the frozen deterministic policy. It
must not be described as the empirically minimum sufficient real-model tier.
Only blinded same-task per-tier output judging against a frozen quality rubric
may use `empirical_frozen_quality`.

Coverage includes clear low tasks, default Sonnet, multi-signal high tasks,
low confidence/conflict, long-simple and short-hard inputs, role/budget caps,
invalid model output, prompt injection, cross-Scope/wrong-target references,
private data and unauthorized tools. Reports include counts and denominators
for Schema validity/fallback, intent/entity/reference/target metrics, tool-need
recall, complexity/tier agreement, policy under-selection, policy-unexpected
Opus, budget-cap correctness, confidence calibration, social actions and every
hard-policy violation. Tier agreement, under-selection and unexpected Opus are explicitly
policy-regression metrics, not real-model minimum-quality claims. Every hard
gate reports its own applicable case count and independent template-family
cluster count. A zero-event one-sided 95% binomial upper bound uses only those
applicable clusters, never all 320 correlated variants, and is not described as
zero real-world risk. Because the synthetic template families are designed, not
randomly sampled from production traffic, the bound is explicitly nominal
under an independent Bernoulli-cluster assumption rather than a deployment
risk estimate.

The runner freezes fixtures, policy/revisions, budget, clock and Router
snapshot, disables network, isolates cluster state and proves identical
prediction fingerprints under normal, reverse and fixed-shuffle order. Reports
separate `technical_pass` from `release_ready`; the latter remains false until
human review is recorded.

## Acceptance

- Rule, Model, validator and merger paths have focused positive, malformed,
  fallback, prompt-injection, cross-Scope and wrong-target tests.
- Model Perception can route only through bootstrap `PERCEPTION/HAIKU` and
  cannot create normal tier authority.
- Complexity and tier decisions implement the conservative rules and budget
  behavior above with stable digests and reason codes.
- Social policy has zero wrong-target, unauthorized-tool, cross-Scope and hard
  policy violations in committed negative fixtures.
- Fixed inputs, fixtures, clock, policy and revisions produce identical plan
  fingerprints across repeated and reordered Eval runs.
- The synthetic Eval bundle has 200-500 Schema-valid cases, no cluster leakage,
  distinct within-family variants, complete provenance/labels, strict artifact
  binding, per-split/per-stratum metrics and honest label/review-state claims.
- Python 3.10 and 3.12 focused/full tests, import boundaries, warnings/error
  async tests, Ruff/format, compileall, secret scan and diff checks pass, apart
  from explicitly recorded untouched repository baselines.
