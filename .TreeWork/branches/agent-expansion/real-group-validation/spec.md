# Branch Spec

Branch: real-group-validation
Parent: agent-expansion

## Development Design

### Purpose And Authority Boundary

S23 is an evidence-producing validation phase, not a broad production launch.
It connects the already verified runtime to one explicitly authorized QQ group,
then enables inbound reply, digest and probe behavior one at a time. Each
behavior has its own grant, window, budget, kill switch and rollback condition.
No grant is inherited by a later behavior or a later group.

The branch may add environment-specific Adapters and composition needed to run
an approved behavior, but it must implement existing Ports and policies. It
cannot redesign the Router, Capability, Memory, ResponsePlan, Scheduler,
proactive authority or Output contracts. Deterministic code continues to own
target, Scope, permission, budget, schedule and every send.

### Readiness Manifest

Before any read of real group data, a low-sensitivity, canonical readiness
manifest binds:

- exact candidate and rollback release digests;
- the frozen SLO revision with `s23_ready=true` and all safety maxima at zero;
- one bot-account reference, target-group reference, test-user references and
  a bounded authorization window;
- SecretRefs only, never Provider, NapCat or OneBot credential values;
- real Endpoint conformance evidence and the exact enabled role/tier bindings;
- data purpose, readable window, retention deadline, deletion owner and audit
  location;
- behavior-specific grant, maximum runs/messages, allowed Capabilities, quiet
  hours, kill-switch owner and stop conditions;
- for digests, approved live Source Adapter evidence, source allowlist,
  provenance/freshness policy and citation requirements;
- for probes, a real group Projection Adapter, group-level target, Memory off,
  no personal mention, long cooldown and no-response stop behavior.

The readiness checker is pure and fail closed. It resolves no Secret, reads no
chat, calls no Provider or source, changes no container and sends no message.
Placeholder, expired, cross-target, missing-digest or `s23_ready=false`
manifests are not executable.

### Ordered Validation Ladder

S23 uses one fixed ladder. Every stage creates a separate sanitized receipt and
must be explicitly promoted by the operator after review:

1. **Preflight**: verify release/rollback artifacts, conformance, private
   SecretRef resolution, SLO, grants, health, clock and kill switches without
   reading group content.
2. **No-send/no-write Shadow**: read only the authorized time window, execute
   the real perception/routing path, record low-cardinality evidence and prove
   zero Output, Tool write and Memory read/write side effects.
3. **Explicit-mention inbound Canary**: only approved test users in the same
   group may trigger bounded replies through a structured explicit `@`.
4. **Manual digest Canary**: one operator-triggered occurrence uses approved
   live public sources, citations and the exact target; no schedule is active.
5. **Scheduled digest Canary**: only after manual digest evidence, enable one
   bounded schedule with timezone, quiet hours, misfire and unsubscribe checks.
6. **Low-frequency group Probe Canary**: only after inbound and digest gates,
   enable one group-level probe grant; no personal Memory, `@`, auto-follow-up
   or send after no response.
7. **Closeout**: disable all canaries, reconcile receipts, execute the data
   deletion/retention plan, test the kill switch and rollback command, and
   publish a sanitized incident/SLO report.

Expansion to 3–5 groups is a new authorization and release decision after S23
single-group completion. It is not inherited from the first group and is not
required to claim the bounded S23 single-group validation complete.

### Promotion And Stop Rules

Promotion is manual and per behavior. The following counters must remain zero:
wrong target, duplicate delivery, quiet-hour delivery, revoked/expired-grant
delivery, unauthorized Capability, cross-Scope Memory, uncited or stale digest,
sensitive Trace, personal probe target and unknown delivery outcome. Any
nonzero counter, health `UNKNOWN`, missing receipt, stale conformance evidence,
unresolved delivery, SLO breach or kill-switch failure immediately disables
that behavior and invokes the frozen rollback procedure. A failed behavior does
not authorize continuing with another behavior.

Latency, TTFT, token, cost, source freshness, answer profile and operator/user
feedback are reported against the frozen SLO without changing thresholds after
observing results. Raw chat, prompt, answer, QQ/group/user IDs, credential
values and Provider error bodies are excluded from committed evidence.

### External And Engineering Gates

The current repository has completed all local predecessors, but S23 cannot
start real execution until the operator supplies the authorization packet and
private SecretRefs. At branch start the current pilot SLO still says
`s23_ready=false`; no real Provider Endpoint is enableable; campus/arXiv/
industry live Source Adapters and proactive production Projection/Output
composition do not exist. iCourse remains the only real MCP Server and does not
substitute for a news source.

Any Adapter needed after real source/Provider facts arrive is implemented and
contract-tested inside the existing Port boundary before the corresponding
stage is authorized. Fixtures cannot be presented as live evidence.

### Completion Evidence

Completion requires the exact single-group ladder receipts, frozen SLO report,
zero safety counters, behavior-specific grants, source citations/freshness,
delivery reconciliation, kill-switch and rollback evidence, and an executed
retention/deletion record. Local simulations, prior S19/S22 artifacts or S20
synthetic OPE are prerequisites/supporting evidence, not substitutes for these
real receipts.
