# Project Spec

## Development Design (the project-level technical development thinking established before coding; organize subsections to fit the actual project)

### Starting Point

S01-S07 are committed as the framework foundation. S08 selection contracts and
the static Router are integrated, and S09 Perception/Tiering is integrated and
verified through Python 3.10/3.12 at control commit `18d4958`. The S09 synthetic
Eval has 320 material profiles in 32 template families and reports
`technical_pass=true`; `release_ready=false` remains honest until a human
reviews those template families. The legacy AstrBot handlers remain production
authority.

`apps/web` and its deployment integration are now an accepted project scope.
They currently exist as an untracked/dirty but verified NapCat multi-account
prototype in the control workspace. The Sub2API plugin remains unrelated user
work and stays outside all Web commits. Before isolated Web branches begin, the
Lead creates a selective Web baseline containing only Web-owned paths and
Web-specific hunks; no Sub2API or model-runtime changes are staged with it.

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
- `BootstrapTierDecision` explicitly authorizes only the pre-assessment
  `PERCEPTION/HAIKU` call and records its policy revision without inventing an
  assessment digest.
- `TierSelectionContext` carries the immutable validated assessment itself plus
  role, privacy, token bound and budget; it does not duplicate independently
  forgeable assessment scalars. Operator-configured high-complexity reason
  codes determine the signal count used by TierPolicy.
- `TierDecision` records requested tier, policy revision, assessment digest,
  confidence handling, and reason codes.
- `ModelEndpointDescriptor` has stable `endpoint_id`, Provider-native
  `model_id`, tier, capabilities, supported reasoning profiles, privacy and
  processing declarations, and an opaque shared quota-pool reference.
- Context gating uses a conservative input-token upper bound, independent input
  limit when declared, total context limit, and output limit.
- `ModelInvocationEstimator` receives the complete request, Endpoint and
  ReasoningProfile and estimates prompt/Schema/Provider wrapping, total
  generated output and cost before admission. Reasoning usage is an optional
  subset of generated tokens and is never charged twice.
- TierPolicy has an explicit input/generated-token/cost floor for every allowed
  Tier, so an Opus proposal can be recorded and deterministically budget-capped.
- `EndpointTrafficPolicy` contains concurrency/RPM/TPM/queue/latency/error,
  minimum-sample, cooldown and snapshot-age thresholds. Mutable observations
  live in a separate revisioned load snapshot.
- `RouteDecision` preserves the routing/catalog/load revisions, eligible and
  rejected candidates with stable reasons, selected endpoint and reasoning
  profile, and attempt/fallback receipts without raw prompt or output.
- Deterministic request, tier and route-plan fingerprints exclude correlation
  IDs, wall-clock observations and attempt latency; full receipt digests retain
  those execution facts. Provider request and prompt revisions bind each
  attempt.

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

The committed S09 Eval labels the expected output of the frozen deterministic
policy (`policy_gold`); it does not claim an empirically minimum sufficient
real-model tier. Only a future blinded same-task, per-tier quality study may
make that claim. Splits are clustered by template family and conversation
lineage. Reports bind every artifact and prediction digest, separate
development/held-out and per-stratum metrics, use applicable family counts for
hard gates, and distinguish technical pass from human release review.

### S10 Offline Runtime

The first Orchestrator accepts bounded pure-text private messages and group
messages that explicitly mention the current Bot. A reply-only group message is
not admitted because current-message context cannot prove that the referenced
message was authored by the Bot; trusted reply history is deferred. Memory,
tools, attachments and proactive chat are disabled. User feature flags cannot
enable them.

The current-message builder creates a de-identified `PerceptionContext` plus a
separate validated identity binding used only after Perception to map an opaque
response target back to the current Scope. Raw platform IDs never enter either
model request. Response authorization uses `message.respond` over the current
conversation; final delivery obtains a separately bound `message.send`
decision over the immutable Delivery intent.

Router-backed Perception gains an additive execution receipt containing no
prompt or output text: whether a model call started, request fingerprint,
sanitized `RouteDecision`, reported usage and failure kind. Runtime persists
this receipt, the `TaskComplexityAssessment`, `TierDecision`, the direct-chat
route receipt and conservative charged usage without adding another phase.
The total Runtime budget is split into configured Perception and Direct Chat
reservations. Each child call sees only its reservation; a started call is
charged its full reservation when any Provider attempt lacks complete usage,
so failure and retry cannot create optimistic remaining budget.

Direct Chat accepts only a bounded text response and projects it into a
versioned `DirectChatContent` before composition. `ASK_CLARIFICATION` uses a
configured deterministic message and does not call the downstream Router.
`IGNORE` and `DEFER` complete without visible output in S10. The minimal
Composer, deterministic single-Persona renderer and validator preserve facts,
citations, refusal, targets and immutable constraints; final content safety is
bound to the recomputed rendered digest.

The in-memory Runtime State Store atomically creates a checkpoint and message
dedup record, performs revision CAS, keeps bounded unexpired checkpoints and
tombstones, and provides revision waiting for same-process single-flight.
Concurrent duplicates with the same start digest wait for and reuse one result;
the same message with a different start digest is a conflict. Capacity never
evicts an unexpired record.

Before orchestration, contract drift is corrected. `CompletionReceipt`
represents real `SUCCEEDED`, `PARTIAL`, `FAILED` and `UNKNOWN` delivery status;
`AgentRuntime` includes idempotent acknowledgement and reconciliation; and the
single authoritative `DeliveryConstraints` uses Schema version, maximum parts,
UTF-8 bytes per part, forward-bundle permission, allowed attachment schemes and
a reconciliation window. Visible output stops at `READY_TO_EMIT`; a separate
offline delivery driver calls `OutputAdapter` and then acknowledgement. Late
receipts merge monotonically without moving `COMPLETED` back to an earlier
phase.

`ShadowRunner` is a separate side-effect-denying composition. Its constructor
has no OutputAdapter, Memory writer, Tool executor or event-stop capability,
and its public receipt contains only sanitized outcome and decision digests,
never a `DeliveryRequest`, AuthorizationDecision or response body.

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

### Mew/NapCat Web Parity

#### Source And Ownership Boundary

Mew commit `97df34b3c8ca1747b92003fa3bb6566a58668a3f` is the accepted
functional baseline, not merely a visual reference. Dududa may adapt Mew's Vue
Router, Pinia stores, Dexie services, TanStack Virtual windowing, Tiptap
composer, message renderers, dialogs, group views, styles and tests. The Milky
connection singleton and browser-held Access Token are not imported.

The browser talks only to a typed same-origin Dududa HTTP/SSE API. The server
owns authenticated NapCat reverse WebSockets and an allowlisted action surface.
No endpoint accepts an arbitrary OneBot action name. Credentials, raw local
paths, cookies and OneBot tokens are never serialized to the browser.

#### Account Runtime And API Keys

The existing server `Map<accountId, AccountState>` remains the connection
authority. Every API route and event identifies an account, and all stable UI
keys use `accountId + scene + peerId`; messages additionally retain both the
OneBot `message_id` and `message_seq`. Requests validate that route account,
connection self ID and event self ID agree.

The server exposes a per-account capability document derived from the NapCat
implementation/version and guarded probes. Views render actions only when the
capability is supported and the current QQ role permits it. Known gaps such as
peer pin synchronization, group-folder rename and complete friend-request
history are represented explicitly and never produce optimistic local success.

#### Rich Message Contract

The current flattened `content + attachments` DTO is replaced by a normalized,
loss-aware segment union covering text/link, mention/all-mention, reply, QQ and
custom faces, image, audio, video, file, market face, forwarded content,
Markdown/light-app JSON and unknown segments. Unknown data is bounded and
displayed as unsupported content without exposing raw sensitive event objects.

Outgoing messages use the same domain segment union and a server-side converter
to OneBot arrays. Browser files cross a size- and MIME-limited upload endpoint;
large files use NapCat upload actions rather than raw browser paths. Media
download/proxy endpoints use host allowlists, byte limits, Range and safe
Content-Disposition where appropriate. Action-specific deadlines separate text,
media and file operations.

#### History, Events And Persistence

NapCat is authoritative. History APIs expose stable cursors based on message
sequence and direction rather than only a latest-message limit. Normalized SSE
events cover created/sent/recalled messages, requests, nudges, member changes,
admin/mute/name changes, files and connection/capability changes. A refresh
repairs missed or unrecognized events.

Mew's Dexie layout is adapted so every message, conversation, draft, history
range and event key includes `accountId`. IndexedDB contains only values obtained
from NapCat plus operator drafts and derived UI metadata. It supports cached-
first opening, bidirectional history coverage, local search and quota cleanup;
clearing it cannot invoke a QQ mutation. Ephemeral Blob/Base64 media is never
persisted.

#### UI And Routes

The workspace retains Dududa's account rail, account filters and combined inbox
while restoring Mew's `/chat`, `/contacts`, `/notifications` and `/settings`
surfaces. The chat branch owns virtual history, scroll anchoring, message
rendering/actions, search, Tiptap composition, drafts, upload and desktop/mobile
gestures. The directory branch owns contacts, request handling, members, group
settings, essence messages, announcements, files and storage/settings views.

There is no browser connect/authentication form. With no account, the app shows
the real NapCat reverse-connection status and setup location. The Agent Console
continues to report that its runtime is unavailable; no local Agent session,
run, tool or reply-draft fixture is permitted.

#### Compatibility And Verification

Mew's unit and Playwright cases are ported or adapted as behavior contracts.
Gateway tests use an in-memory NapCat transport only in test code and cover
action mapping, malformed payloads, capability gaps, pagination, upload limits,
destructive operations and concurrent-account isolation. Production verification
uses connected NapCat accounts, without sending destructive or user-visible
mutations unless explicitly authorized. Desktop and mobile screenshots, console
errors, layout overlap and virtual-scroll stability are audited against the Mew
baseline.

### Verification And Change Discipline

Each implementation branch has focused Unit, Contract, negative and failure
tests. The final audits rerun the full Python and Web suites, import boundaries,
typecheck/build, secret scan, shell, Compose parse, whitespace checks,
wheel/image/plugin smoke where affected, and a requirement-by-requirement
audit. Branch-local success is not evidence that its project epic is complete.

Bandit, random weights and learned online routing have no implementation hook in
this project beyond reproducible static decision receipts that a later S20 can
consume after a separate design review.
