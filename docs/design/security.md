# Security And Privacy Design

Status: S03 foundational controls are implemented; runtime-wide enforcement,
production policy migration, and several later-phase controls remain pending.

## Security Objectives

- Default-deny privileged actions and fail closed on missing identity or Scope.
- Keep deterministic policy authoritative over models, prompts, Persona, tools,
  and external content.
- Prevent credentials and private runtime state from entering Git, traces,
  prompts, tool output, or public errors.
- Isolate conversations, users, groups, Bots, Personas, and tool contexts.
- Make every high-risk action attributable, reviewable, bounded, and reversible.
- Reduce container and third-party blast radius.

## Trust Boundaries

Untrusted inputs include:

- QQ messages, mentions, replies, attachments, nicknames, and forwarded content.
- Web pages, iCourse reviews, MCP output, and future campus services.
- Model completions, structured-output fields, and generated tool plans.
- Third-party plugin output and mutable upstream repositories.
- Provider error bodies and remote URLs.

Trusted only after validation:

- Connector-resolved platform, Bot, conversation, group, and user identities.
- Typed repository configuration with protected file ownership and mode.
- Versioned capability and Provider policies.
- Verified third-party manifest, integrity, patch, and license data.

Persona text is not a trust or authorization boundary.

## Authorization Model

```text
AuthorizationRequest
  actor: Actor
  conversation_scope: ConversationScope
  action: ActionId
  resource: ResourceRef
  capability: CapabilityId | None
  risk_level: RiskLevel
  metadata: immutable mapping
```

`AuthorizationPolicy.decide()` returns `ALLOW`, `DENY`, or
`REQUIRE_CONFIRMATION` plus stable reason codes. Missing roles, resource Scope,
or policy config returns `DENY`.

Current roles remain compatibility inputs:

```text
owner > platform/global admin or group admin > trusted > normal
muted is an explicit deny overlay
```

Roles alone are insufficient. Policy also checks context, action, resource,
privacy level, and capability. For example, trusted image generation does not
grant permission to export datasets or modify models.

The AstrBot adapter resolves `AstrMessageEvent` to `Actor`; core security code
never calls Event methods. Runtime-specific admin fallback is implemented by an
adapter and represented explicitly in the resolved roles.

## Owned Security Ports

```python
class AuthorizationEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"

@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    schema_version: int
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    resource: ResourceRef
    capability_id: str | None
    risk_level: RiskLevel
    metadata: Mapping[str, JsonValue]

@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    schema_version: int
    decision_id: str
    effect: AuthorizationEffect
    request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    resource_digest: DigestString
    capability_id: str | None
    risk_level: RiskLevel
    metadata_digest: DigestString
    policy_revision: str
    reason_codes: tuple[str, ...]
    decided_at: datetime
    expires_at: datetime

class AuthorizationPolicy(Protocol):
    async def decide(
        self,
        request: AuthorizationRequest,
        *,
        call: PortCallContext,
    ) -> AuthorizationDecision: ...

@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    schema_version: int
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    ttl: timedelta

@dataclass(frozen=True, slots=True)
class ConfirmationConsumeRequest:
    schema_version: int
    request_digest: DigestString
    confirmation_id: str
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    execution_id: str
    idempotency_key: str
    authorization: AuthorizationDecision

@dataclass(frozen=True, slots=True)
class ConfirmationRequirement:
    schema_version: int
    confirmation_id: str
    request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    public_prompt_key: str
    policy_revision: str
    created_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class ConfirmationGrant:
    schema_version: int
    confirmation_id: str
    consume_request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    payload_digest: DigestString
    required_permission: str
    execution_id: str
    idempotency_key: str
    authorization_digest: DigestString
    policy_revision: str
    created_at: datetime
    consumed_at: datetime
    expires_at: datetime

class ConfirmationService(Protocol):
    async def issue(
        self,
        request: ConfirmationRequest,
        *,
        call: PortCallContext,
    ) -> ConfirmationRequirement: ...

    async def consume(
        self,
        request: ConfirmationConsumeRequest,
        *,
        call: PortCallContext,
    ) -> ConfirmationGrant: ...

@dataclass(frozen=True, slots=True)
class InteractionLimitRequest:
    schema_version: int
    request_digest: DigestString
    actor: Actor
    conversation_scope: ConversationScope
    action: ActionId
    units: int
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class InteractionLease:
    schema_version: int
    lease_id: str
    allowed: bool
    request_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    action: ActionId
    units: int
    idempotency_key: str
    policy_revision: str
    reason_codes: tuple[str, ...]
    reserved_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class InteractionLeaseReceipt:
    schema_version: int
    lease_id: str
    idempotency_key: str
    disposition: Literal["committed", "released", "already_committed", "already_released"]
    limiter_revision: ComponentRevision
    recorded_at: datetime

class InteractionLimiter(Protocol):
    async def reserve(
        self,
        request: InteractionLimitRequest,
        *,
        call: PortCallContext,
    ) -> InteractionLease: ...

    async def commit(
        self,
        lease: InteractionLease,
        *,
        call: PortCallContext,
    ) -> InteractionLeaseReceipt: ...

    async def release(
        self,
        lease: InteractionLease,
        *,
        call: PortCallContext,
    ) -> InteractionLeaseReceipt: ...

@dataclass(frozen=True, slots=True)
class ResourceUsage:
    schema_version: int
    model_calls: int
    tool_steps: int
    retries: int
    input_tokens: int
    output_tokens: int
    cost_units: Decimal | None

@dataclass(frozen=True, slots=True)
class BudgetReservationRequest:
    schema_version: int
    request_digest: DigestString
    resource: ResourceRef
    maximum: ResourceUsage
    idempotency_key: str

@dataclass(frozen=True, slots=True)
class BudgetLease:
    schema_version: int
    lease_id: str
    request_digest: DigestString
    resource_digest: DigestString
    idempotency_key: str
    reserved: ResourceUsage
    policy_revision: str
    reserved_at: datetime
    expires_at: datetime

@dataclass(frozen=True, slots=True)
class BudgetReceipt:
    schema_version: int
    lease_id: str
    request_digest: DigestString
    usage_digest: DigestString
    idempotency_key: str
    disposition: Literal["settled", "released", "duplicate"]
    charged: ResourceUsage
    remaining: ResourceUsage
    recorded_at: datetime

class BudgetLedger(Protocol):
    async def reserve(
        self,
        request: BudgetReservationRequest,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetLease: ...

    async def settle(
        self,
        lease: BudgetLease,
        usage: ResourceUsage,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetReceipt: ...

    async def release(
        self,
        lease: BudgetLease,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> BudgetReceipt: ...

@dataclass(frozen=True, slots=True)
class RedactionRequest:
    schema_version: int
    value: JsonValue
    sensitivity: Sensitivity
    purpose: str

@dataclass(frozen=True, slots=True)
class RedactionResult:
    schema_version: int
    value: JsonValue
    changed: bool
    reason_codes: tuple[str, ...]
    redactor_revision: str

class Redactor(Protocol):
    def redact(self, request: RedactionRequest) -> RedactionResult: ...

@dataclass(frozen=True, slots=True)
class ContentSafetyRequest:
    schema_version: int
    request_id: str
    request_digest: DigestString
    stage: SafetyStage
    content: JsonValue
    content_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString

@dataclass(frozen=True, slots=True)
class ContentSafetyDecision:
    schema_version: int
    request_id: str
    stage: SafetyStage
    request_digest: DigestString
    content_digest: DigestString
    actor_digest: DigestString
    scope_digest: DigestString
    allowed: bool
    required_constraints: ResponseConstraints
    reason_codes: tuple[str, ...]
    policy_revision: str
    producer: ComponentRevision
    decided_at: datetime

class ContentSafetyPolicy(Protocol):
    async def evaluate(
        self,
        request: ContentSafetyRequest,
        *,
        call: PortCallContext,
    ) -> ContentSafetyDecision: ...

@dataclass(frozen=True, slots=True)
class AuditEvent:
    schema_version: int
    event_id: str
    event_digest: DigestString
    timestamp: datetime
    run_id: str | None
    operation_id: str
    trace_id: str
    span_id: str | None
    actor_digest: DigestString | None
    scope_digest: DigestString | None
    action: ActionId
    decision: str
    authorization_decision_id: str | None
    request_digest: DigestString
    policy_revisions: tuple[str, ...]
    component_revisions: tuple[ComponentRevision, ...]
    reason_codes: tuple[str, ...]
    resource_digest: DigestString
    sanitized_detail: JsonValue
    sensitivity: Sensitivity
    outcome: str

@dataclass(frozen=True, slots=True)
class AuditReceipt:
    schema_version: int
    event_id: str
    event_digest: DigestString
    persisted: bool
    sink_revision: str

@dataclass(frozen=True, slots=True)
class TraceReceipt:
    schema_version: int
    event_id: str
    accepted: bool
    sink_revision: str

class AuditSink(Protocol):
    async def write(
        self,
        event: AuditEvent,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> AuditReceipt: ...

class TraceSink(Protocol):
    async def emit(
        self,
        event: TraceEvent,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> TraceReceipt: ...

@dataclass(frozen=True, slots=True)
class SecretRef:
    schema_version: int
    namespace: str
    secret_id: str
    version_hint: str | None

class SecretConsumer(Protocol[T]):
    def __call__(self, secret: memoryview) -> T: ...

class SecretValue(Protocol):
    def use_once(self, consumer: SecretConsumer[T]) -> T: ...

class SecretResolver(Protocol):
    async def resolve(
        self,
        reference: SecretRef,
        *,
        call: PortCallContext | ServiceCallContext,
    ) -> SecretValue: ...
```

Every top-level request, decision, lease, receipt, persisted record, and event is
immutable and schema-versioned. The caller supplies a canonical `request_digest`,
the owning service recomputes it, and every authorization-type result repeats it.
Authorization additionally binds capability, risk and metadata; content safety
binds actor, Scope, stage and exact content; limiter binds Actor, units and
idempotency key. Consumers recompute and reject every mismatch rather than choosing
the more permissive snapshot. Confirmation consume and limiter/budget
reserve/commit/release are atomic and concurrency-safe. A `ServiceCallContext`
identifies a background service but never replaces the Actor and authorization
evidence embedded in a durable command.

The Runtime reserves worst-case local budget before invoking a component. A
shared `BudgetLedger` is additionally required when limits span processes or
runs. Missing or unknown usage is charged at the reservation ceiling. Security
and privileged mutations use required Audit receipts and fail closed when the
sink cannot commit; low-risk Trace is explicitly best effort. `SecretValue` is
an opaque infrastructure object that cannot enter Domain DTOs, model inputs,
tool plans, trace, audit detail, exceptions, or `repr`.

## Confirmation Binding

High-risk confirmations bind all of:

```text
confirmation_id
actor identity
conversation scope
action and canonical payload digest
required permission
execution ID and idempotency key
the current authorization decision digest
created_at and expires_at
single-use state
```

Permission is re-evaluated when confirmation executes. Changing conversation,
payload, permission, execution ID, role, or expiry invalidates it. `consume()`
atomically tombstones the confirmation and returns a grant usable only for the
bound execution/idempotency key; replay for another command fails closed. Logs
never contain a raw sensitive payload. Durable operations use durable confirmation
state or clearly state that a restart cancels them.

## Privacy Classification

| Level | Examples | Default handling |
| --- | --- | --- |
| Public | Public course title, public documentation | May enter normal context with provenance |
| Personal | User preference, nickname | Narrow Scope; no unrelated-user disclosure |
| Sensitive | Schedule, grades, health, location, private conversation | Private context, explicit purpose and retention |
| Restricted | Password, token, Cookie, private key, login state | Never store or send to model/tool; redact and reject |

Data minimization applies before model or tool calls. A capability receives only
fields declared in its versioned input schema and authorized for its privacy
level.

## Redaction

Redaction is a dedicated service used by audit, trace, errors, operation logs,
and tool calls. It combines:

- normalized sensitive field-name matching;
- credential value patterns;
- configured secret-value fingerprints without storing plaintext;
- URL user-info and sensitive query removal;
- bounded external body and path handling;
- recursive redaction for mappings and sequences.

Redaction returns both sanitized data and reason codes. It must be idempotent.
Tests include secrets embedded under ordinary keys and nested structures, which
the current audit implementation does not catch.

## Audit

```text
AuditEvent
  event_id
  timestamp
  trace_id
  actor_ref
  conversation_ref
  action
  decision
  reason_codes
  resource_ref
  sanitized_detail
  outcome
```

Raw QQ/group IDs are retained only where an operational requirement justifies
them; otherwise use a keyed pseudonymous reference. Audit sinks define file
mode, rotation, retention, integrity, and concurrency behavior. The user-facing
`logs errors` query filters severity and category rather than returning an
unfiltered tail.

Auditing failure policy depends on risk: a high-risk mutating action fails
closed if its required audit cannot be written; low-risk chat may continue with
a local health signal.

## Rate Limits And Budgets

Limits can apply by platform, Bot, conversation, user, action, capability, and
model role. Policies include burst, sustained rate, concurrent executions,
elapsed time, model cost, tool steps, and external crawl limits.

Planner loops always have a maximum step count. Retries consume budget and use
classified backoff. Repeating the same capability with the same canonical
arguments is detected and stopped unless a validator explicitly requests one
safe retry.

## Tool And MCP Security

Before execution:

1. Retrieve only context-eligible capabilities.
2. Check permission and privacy level.
3. Validate arguments against a versioned schema.
4. Canonicalize resource references and paths.
5. Redact audit detail.
6. Enforce timeout, call count, cost, and idempotence policy.

After execution:

1. Normalize error and output envelopes.
2. Validate output schema and resource limits.
3. Treat returned text as untrusted data.
4. Remove secrets and unsafe URLs/content before model context.
5. Record outcome metrics without raw payloads.

File tools receive an approved repository/root abstraction, never an arbitrary
host path. The current iCourse `export_dataset(output_path)` must be removed from
model eligibility or constrained to a dedicated export root before it is
registered as a standard capability.

## Model And Prompt Security

- Models propose semantic interpretations, plans, and language; they do not
  grant permission, broaden Scope, or approve retries.
- Structured output is schema-validated and bounded.
- External content is delimited and labeled as untrusted data.
- System, policy, capability, and Persona layers are composed separately.
- Persona cannot override facts, tool status, permissions, privacy, or safety.
- Provider credentials are resolved by an injected gateway and never returned
  to core or read by command handlers.
- Prompt and completion capture is disabled by default in tracing.

## Memory Security

Memory exact Scope filtering precedes semantic retrieval. Missing metadata,
backend capability, or group/user identity fails closed. Private-origin content
cannot enter group context by model judgment. The complete contract and
isolation matrix are in `memory.md`.

## Connector And Output Security

Adapters validate identity consistency and reject malformed envelopes. Output
adapters constrain component type, size, URL scheme, attachment source, and QQ
forward-node limits. A global decoration hook remains compatibility behavior,
not the final output-security boundary.

## Runtime Configuration And Secrets

- Repository config contains only schemas, safe defaults, and symbolic IDs.
- `.env`, Provider config, QQ identifiers, login state, memory, and databases
  remain runtime-private.
- Config files with secrets use restricted mode and atomic writes.
- Parsing errors are explicit; they do not silently become empty config.
- Model IDs, policies, and capability metadata are externalized and validated.
- Secret rotation does not require rebuilding a repository image.

## Container And Network Security

Design requirements for the deployment phase:

- Validate and minimize the NapCat mount instead of sharing all AstrBot data.
- Document which service requires the external edge network; avoid attaching a
  service without an external consumer.
- Keep host management ports on loopback by default.
- Add health checks before automated upgrade/rollback decisions.
- Evaluate non-root users, dropped capabilities, read-only roots, tmpfs, resource
  limits, and service-specific writable mounts against upstream requirements.
- Never test these changes by mutating production first.

## Third-Party Supply Chain

One manifest records source, exact version/commit/digest, install mode, patch
hashes, tree integrity, license status/files, and Python/system dependencies.
Unknown or missing license status blocks distribution decisions. Install
receipts include the normalized manifest hash and installed tree hash.

Vendored AGPL code remains isolated from the MIT core package. Patch changes are
reviewed as security-sensitive code and tested behaviorally.

## Error Handling

Public errors use stable categories and safe wording. Raw stack traces, Provider
bodies, database paths, commands, and credentials stay in protected diagnostic
channels after redaction.

Security validation, permission, and privacy errors are not retried. Transient
external failures may retry within policy. A missing security dependency fails
closed for privileged operations.

## Required Tests

- Shared Contract Tests for `AuthorizationPolicy`, `ConfirmationService`,
  `InteractionLimiter`, `BudgetLedger`, `Redactor`, `ContentSafetyPolicy`,
  `AuditSink`, `TraceSink`, and `SecretResolver` across Fake and real adapters.
- Role/action/resource/context permission matrix and default deny.
- Canonical request digest tampering for Authorization capability/risk/metadata,
  Content Safety Actor/Scope/stage/content, and every lease/receipt fails closed.
- Confirmation actor, Scope, payload, required permission, execution/idempotency key,
  current authorization, expiry, single-use/tombstone, and role recheck.
- Concurrent limiter reservations cannot all pass from one stale snapshot;
  Actor/units/key binding, commit/release, expiry, retries, and idempotency are atomic.
- Required audit failure blocks high-risk mutations; best-effort Trace failure
  never gets reported as a durable audit receipt.
- Nested and value-based redaction with no raw secret in audit/trace/error.
- Content Safety request/decision stage and content digest binding; required constraints must
  be present in the exact `ValidatedFinalResponse` being delivered.
- ServiceCallContext principal cannot replace the original Actor authorization in a queued command.
- Audit event/receipt bind run/operation, policy/component revisions and event/request digests.
- Cross-user/group/private/Bot/Persona memory isolation.
- Capability privacy and permission eligibility before planning.
- Path traversal, absolute path, symlink, and overwrite restrictions.
- Prompt injection in message, web, review, MCP, and Provider error content.
- Planner maximum steps, repeated calls, timeout, and retry budget.
- Output component size, node count, truncation, and URL scheme.
- Manifest integrity, patch hash, license fields, and safe install target.
- Container mount and network contract tests.

## Current State And Migration

Current strengths are ignored runtime state, loopback host ports, pinned images
and Git commits, read-only source mounts, `no-new-privileges`, local scanning,
Gitleaks, some audit scrubbing, high-risk confirmation, and an Iris patch.

Current gaps include framework-coupled policies, incomplete redaction, narrow
confirmation binding, fail-open memory edges, direct credential lookup for
images, arbitrary iCourse export paths, excessive shared mounts, incomplete
third-party license/integrity data, and mostly structural tests.

Security extraction begins with pure Actor, Scope, permission, redaction, audit,
and error contracts. Existing adapters call them through compatibility wrappers
before any behavior is removed. Every cutover requires negative tests and a
rollback flag.
