# Findings

Branch: static-router

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Route-plan identity must exclude runtime observations while the full
  `RouteDecision` binds every admission, settlement, attempt and terminal
  outcome. A fallback changes execution identity, not the frozen initial plan.
- Operational counters are explicitly external to this admission-controller
  instance. Local windows own locally admitted RPM/TPM/in-flight state and are
  never added to a snapshot that already contains the same calls.
- A Provider call has a dispatch boundary. Failures before it release capacity;
  failures after it with unknown usage settle at the reservation ceiling.
  Deadline expiry may create a conservative settled receipt without a Provider
  attempt and is valid only for terminal timeout/cancellation.
- Provider extensions cannot be trusted to sanitize their own `ErrorInfo`.
  Core retains failure kind and outcome-known state but rebuilds all public
  codes/messages/reasons before writing a route receipt.
- Adapter-local timeout and bounded task cleanup prove caller liveness only.
  Real binding enablement separately requires evidence that the downstream
  request enforces deadline and cancellation.
- Outcome-unknown errors are idempotency results, not permission to issue the
  same host call again. They are replayed from a bounded TTL/LRU tombstone.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added immutable catalog, operational, admission, estimation, candidate-plan,
  attempt and execution-receipt DTOs plus their canonical digests.
- Added `ModelRoutingRegistry`, `ModelOperationalStateRegistry`,
  `ModelAdmissionController`, `ModelInvocationEstimator` and `ModelOutputCodec`
  implementations/ports used by `StaticModelRouter`.
- `LoadCounterScope.EXTERNAL_TO_ADMISSION_CONTROLLER` is required for current
  in-memory admission snapshots.
- `max_schema_repairs` is explicit and restricted to zero or one for S08.
- `AstrBotProviderBindingEvidence` now binds exact model/residency/retention and
  single-request, output-limit, deadline, cancellation and logging evidence.
- The AstrBot plugin declares `jsonschema>=4.10,<5`; CI, development setup and
  the derived image install that dependency.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Pinned AstrBot 4.26.2 cannot currently prove the evidence required to enable
  its OpenAI/Anthropic bindings. Compatible harness coverage must not be
  misrepresented as production-host evidence.
- The in-memory registries, admission windows and idempotency ledger are
  process-local. A multi-process deployment will require a shared atomic
  implementation behind the same ports, without changing Core routing rules.
- Conservative unknown-usage settlement can overcharge a Runtime budget. This
  is deliberate fail-closed behavior and should remain visible in receipts and
  metrics rather than being silently corrected.
