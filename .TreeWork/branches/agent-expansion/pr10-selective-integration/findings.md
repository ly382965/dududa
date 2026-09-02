# Findings

Branch: pr10-selective-integration

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- PR #10 is a source set, not a mergeable branch. The duplicate Core, old
  layouts, academic-calendar, ustc-notice, direct model/MCP paths, AMap helper,
  and automatic event chain stay excluded.
- The non-duplicate social rules are delivered as a separate
  `astrbot_plugin_dududa_social` plugin. Explicit namespaced commands are the
  only AstrBot handlers; all default gates deny access until an operator opts
  in.
- The five selected MCP services are Registry-only optional assets. Keeping
  them out of `configs/astrbot/mcp_server.json` and capability definitions /
  mappings is necessary because the current composition creates Provider
  descriptors and health state for configured mappings even when disabled.
- Each optional MCP exposes exactly one cache-read query tool. Refresh,
  robots, detail and data-maintenance operations remain operator CLI concerns;
  no credential or arbitrary external URL is part of the model-facing surface.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added five strict Server Registry JSON definitions, all `enabled=false`,
  with fixed stdio endpoints, empty SecretRefs, one-tool allowlists and bounded
  timeout/concurrency policies.
- Added five canonical service packages, independent cache roots and read-only
  source mounts in the existing AstrBot/mcp-console image and Compose services;
  the Compose service set itself remains `web`, `mcp-console`, `astrbot`, and
  `napcat`.
- Added the `/dududa-social` command namespace and owned-plugin installation
  entry. Its SQLite state is independent and Scope-keyed; no existing Core
  command, route, or state schema is replaced.
- Added CI-style per-directory contract tests and repository contracts that
  assert default-off/Planner exclusion and preservation of active services.
- The review exposed and fixed three local contract defects before handoff:
  the social help command now obeys the global Scope gate, `local-recs`
  explicit IDs now actually upsert, and notice parsers/CLI paths reject
  malformed, oversized, or external-source URLs.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Optional cache contents are not a freshness guarantee; enabling a service
  later requires source review, cache operations, capability mapping, health,
  and Planner evidence in a separate change.
- The social policy contains structured crisis signals but intentionally does
  not diagnose, generate, or deliver an automatic support response.
- Full historical repository tests retain pre-existing red baseline items;
  only the focused evidence listed in Verification is attributable to this
  branch.
