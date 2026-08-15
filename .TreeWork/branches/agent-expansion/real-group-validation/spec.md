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

### Authorized Offline Historical-Corpus Stage

Before the live ladder, S23 may process the user-authorized static export at
`/home/mmdustc/temp` entirely offline. This stage is evidence preparation, not
current Dududa traffic and not authorization to reconnect the exported account,
read live QQ state or send a message. Private chat is excluded. Source and
derived text, identity mappings, labels, models and the rendered Demo remain
outside Git under the configured private dataset root.

The offline stage is one vertical pipeline:

1. **S23A Historical Corpus Intake** classifies every input file, parses
   directory JSONL first, ZIP JSONL only for missing records and message-bearing
   HTML last, then normalizes group messages with opaque identities and the
   stable `(conversation_ref, normalized_message_id)` key. Conflicting bodies,
   mentions or elements are recorded without blocking unrelated records.
2. **S23B Conversation Window Dataset** builds 3--12 message, past-only windows
   separated by group and time, projects them to the existing
   `PerceptionContext`, and deterministically samples 50 then a time-boxed
   target across observable conversation shapes.
3. **S23C Semantic v2 Silver Annotation** sends only selected, de-identified
   text windows to one fixed medium Teacher through the Responses-compatible
   Endpoint. Existing Semantic v2 schema, decoder and validator own the model
   projection; dataset-only topic/task/tool/complexity/profile/confidence fields
   remain sidecars. Invalid and uncertain output enters a review queue and is
   never called Gold.
4. **S23D Local Student Training And Evaluation** trains lightweight local
   classifiers for tool need, semantic complexity and answer profile. Splits
   are isolated by conversation/group. Reported metrics are Silver agreement,
   not production semantic accuracy, and Student output does not enter the
   production Router.
5. **S23E Private No-Send Product Demo** renders the corpus, annotation,
   validation and Student results into a reusable localhost-only HTML artifact.
   Reopening it performs no Provider call, Tool call, Memory write, Bandit
   learning or QQ send.

The batch CLI reuses `MessageEnvelope`, Perception/Semantic v2,
`TierPolicy` and `ResponsePlan` contracts rather than defining a parallel
runtime. Attachments contribute only typed metadata; no uploaded code, HTML,
remote resource or media content is executed or fetched. Focused synthetic
tests plus staged 5/50/target Teacher runs are sufficient for this development
artifact; the stage does not add a new release gate.

### Offline Runtime Budget And Sampling

The S23A--S23E product Demo is a time-boxed development run. It targets four
hours and stops launching new Teacher requests early enough to finish local
training, evaluation, Demo generation, documentation and focused verification
within a hard five-hour wall-clock budget.

The 5-request Schema smoke and 50-request distributed pilot measure actual
valid-label throughput, including retries and rate limiting. After the pilot,
the runner selects the largest feasible target from 240, 360, 480 or 600
windows using observed throughput with a 25 percent time reserve. It may use
fewer than 240 only when the Endpoint or corpus cannot support that target; the
resulting limitation must be reported rather than hidden.

Sampling quality is defined by coverage before count: conversation-isolated
splits, bounded contribution from any one group, coverage of the available
conversation-shape buckets and deliberate inclusion of ambiguous, reply,
mention and media-boundary cases. Terra remains the single Teacher so that a
smaller run does not trade time savings for label-policy drift. Completed
responses are reused on restart; transient calls receive at most one retry.
Sol and Luna are not added to the labeling path merely to fill the target.

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
Placeholder, expired, missing-digest or `s23_ready=false` manifests are not
structurally ready. Cross-target, stale or unresolved referenced evidence must
fail the later live Preflight.

The checker proves manifest completeness only. Its report uses
`validation_scope=manifest_only`, may set `manifest_ready=true`, and always
sets `live_execution_authorized=false`. Preflight must resolve and verify the
referenced authorization, release, Endpoint, health, source, projection and
preceding-stage evidence against the exact target before execution. A
well-formed digest or `live=true` declaration is never evidence by itself.

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

The static historical export and one private Responses-compatible Teacher
Endpoint are now authorized for the offline S23A--S23E stage only. This does not
satisfy any live gate. S23 live execution still waits for an operator-supplied
authorization packet and private SecretRefs. The current pilot SLO remains
`s23_ready=false`; campus/arXiv/industry live Source Adapters and proactive
production Projection/Output composition do not exist. iCourse remains the
only real MCP Server and does not substitute for a news source.

Any Adapter needed after real source/Provider facts arrive is implemented and
contract-tested inside the existing Port boundary before the corresponding
stage is authorized. Fixtures cannot be presented as live evidence.

### Completion Evidence

The current goal completes when S23A--S23E have reproducible private artifacts,
real Silver labels, group-isolated Student metrics, full eligible-window offline
predictions, an openable no-send Demo, synchronized documents and local commits.
That milestone must remain explicitly distinct from live S23 completion.

Later live completion still requires the exact single-group ladder receipts,
frozen SLO report, zero safety counters, behavior-specific grants, source
citations/freshness, delivery reconciliation, kill-switch and rollback evidence,
and an executed retention/deletion record. Offline corpus evidence, prior
S19/S22 artifacts and S20 synthetic OPE cannot substitute for those receipts.
