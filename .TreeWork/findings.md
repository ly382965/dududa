# Global Findings

## Decisions (project-wide conclusions learned during development; planned pre-coding design belongs in spec.md)

- The initial perception model must be statically pinned to `haiku`; otherwise
  difficulty-based selection is recursively dependent on itself.
- Complexity evidence and endpoint routing are one pipeline but not one module.
- Load snapshots are advisory eligibility evidence; atomic admission is required
  to prevent concurrent overbooking.
- S11 cannot use an image-only rollback because plugin source is bind-mounted;
  the rollback artifact must cover both image and plugin/config revision.

## Interface Or Contract Effects (effects crossing branch or product boundaries)

- The duplicate `RouteHint` definitions must converge on one shared immutable
  type before runtime integration.
- Delivery completion currently rejects real delivery statuses and must be
  corrected before S10 acknowledgement can be implemented.
- Runtime state needs immutable tier and route receipts without adding a new
  phase solely for model selection.

## Risks And Unknowns (project-wide residual hazards; not unfinished branch work)

- All S01-S07 implementation is currently uncommitted, so TreeWork isolation
  cannot see it until a selective baseline is established.
- Native DeepSeek and Anthropic model IDs/capabilities must remain Adapter
  configuration until verified; endpoint aliases cannot be treated as facts.
- The workspace does not establish authorization or credentials for a real QQ
  group canary.
- Token underestimation, stale load snapshots, duplicate delivery after restart,
  prompt-injected tier requests, and cross-tier privacy drift require explicit
  negative tests.
