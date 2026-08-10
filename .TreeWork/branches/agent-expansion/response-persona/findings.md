# Findings

Branch: response-persona

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- S10 stores Social Decision at DECIDED, but the tool-backed visible answer is not eligible
  until Capability validation. Therefore direct/clarification publish ResponsePlan at DECIDED,
  while USE_TOOLS publishes it at VALIDATED; Tool Planning never consumes AnswerProfile.
- `FinalResponse.blocks` are not QQ delivery parts. The hard part-count gate must reuse the
  existing DeliveryRequestBuilder/`plan_delivery_parts` result before send authorization;
  response-layer character estimates are admission evidence only.
- The current deterministic Renderer copies text byte-for-byte and does not load the legacy
  Persona prompt. S15 may prove typed asset/digest/fallback and expression-safety contracts,
  but real OC style quality remains an external human-evaluation gate.
- Resolving Persona only when rendering creates a generation race: a checkpoint restored after
  Catalog publication could render under a different definition. PersonaResolution therefore
  publishes atomically with ResponsePlan and becomes immutable Runtime State evidence; Renderer
  and final validation consume it instead of resolving mutable current Catalog state.
- A Catalog digest alone is insufficient for replay because a run also needs an immutable
  generation lookup. The Registry therefore keeps bounded published snapshots and rejects foreign
  or tampered snapshots while retaining an explicit fixed-version neutral fallback.
- The 3x3 Eval is a mechanical contract gate, not a response-quality benchmark. Its committed
  report intentionally remains `release_ready=false` until human examples and real platform
  constraints exist.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- A new framework-neutral `dududa.responses` package and response-specific Ports own Profile
  selection, evidence, immutable Plan, policy-unit counting and reservation projection.
- `ModelRequest` now has an additive pair of Plan digest/visible-output fields. Migrated visible
  calls use both; legacy calls may omit both only until their owning Runtime path is migrated.
- Feature flag `response_profiles` is the additive checkpoint boundary: enabled states require a
  bound selection request/Plan at the action-specific phase; disabled states reject partial Plan
  artifacts and retain the S10 readable shape.
- Actual delivery part enforcement occurs on `DeliveryAuthorizationIntent.part_intents` before
  authorization. The test Runtime's former five-byte synthetic part size was replaced with a
  realistic bounded fixture so Profile part ceilings test policy rather than fixture pathology.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Dududa's Unicode/CJK visible Token unit is deterministic but is not a Provider tokenizer.
  Real Endpoint conformance must separately prove provider limits and usage semantics.
- ProfileValidation intentionally proves typed requirement IDs and mechanical bounds only.
  RenderValidator remains responsible for exact values/text, and human review remains responsible
  for semantic completeness, naturalness and whether LONG is genuinely useful rather than padded.
