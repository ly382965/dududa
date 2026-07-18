# Security And Privacy Design

Status: Phase 1 design; several controls described here do not exist yet.

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

## Confirmation Binding

High-risk confirmations bind all of:

```text
confirmation_id
actor identity
conversation scope
action and canonical payload digest
required permission
created_at and expires_at
single-use state
```

Permission is re-evaluated when confirmation executes. Changing conversation,
payload, role, or expiry invalidates it. Logs never contain a raw sensitive
payload. Durable operations use durable confirmation state or clearly state
that a restart cancels them.

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

- Role/action/resource/context permission matrix and default deny.
- Confirmation actor, Scope, payload, expiry, single-use, and role recheck.
- Nested and value-based redaction with no raw secret in audit/trace/error.
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
