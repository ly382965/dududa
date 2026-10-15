# Findings

Branch: preview-context-repair

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Formal Runtime previously discarded browser history. The fix fetches through
  the scoped Hub and discards browser messages before budget heuristics.
  Dependency injection and the authenticated host preview support isolated
  synthetic verification without reading a private group transcript.
- The existing serialized-input budget remains 8,000. History selects a bounded
  newest suffix; current instruction stays separate. JSON metadata provides
  observed time and Asia/Shanghai display timezone. Recent context never proves
  a complete day. Original source IDs become internal scoped message refs.
- Verification-required remains a monotone OR; disagreement on that flag alone
  no longer adds a redundant conflict. Explicit summary, rewrite, translation
  and formatting aliases normalize to authoritative bounded_transformation;
  other task, permission and safety conflicts remain.
- Q20 is not a demonstrated Composer/Renderer punctuation rewrite: these paths
  preserve direct content. No generic output-constraint parser was added;
  exact live-model compliance is not claimed.
- Zero probability is configuration, not a Runtime failure. Saved and unsaved
  zero states are explained without changing the probability or group policy.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Optional authenticated host history has accountId, conversationId, source
  (server_recent or synthetic), truncated and messages. Records have id,
  senderId, senderName, content, timezone-aware timestamp or null, and optional
  replyToId. Scope must match; extra role fields are rejected. Limits before
  Core's tighter serialized budget: 100 records, 2,000 content characters each,
  36,000 total. Reply refs bind only retained earlier items.
- Additive response evidence: outcome, runtimeState, generationObserved and
  coverage (source, partial, truncated, historyMessagesRead, oldestAt, newestAt).
  messagesRead includes the current instruction. A configured model label is
  not evidence that generation ran.
- HTTP 200 is not sufficient for success: no_reply, deferred, failed, reaction
  or empty results show an explanation. Nonzero output/memory counters are
  rejected by the client, not silently coerced to zero.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Recording fake-provider tests prove both model inputs include prior facts,
  not live model classification or summary quality.
- Hub history may be recent or incomplete; coverage always remains partial,
  including empty or unavailable history.
- Production composition needs the separately locked MCP v2 worker environment
  in addition to the main test Python environment.
