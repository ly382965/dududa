# Findings

Branch: unified-mcp

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- MCP v2 is adopted only inside a separately locked transport worker. The root
  runtime and existing iCourse FastMCP Server remain on v1.29; this preserves
  compatibility without creating a second policy plane.
- Strict JSON under `config/mcp/servers/` is the Registry authority. Discovery
  may refresh facts but cannot create a business Capability or widen a Tool
  allowlist.
- Worker and MCP Server require distinct parent-owned kill scopes because MCP
  v2 stdio starts the Server in a separate process session. Container init is
  required to reap adopted descendants after forced failure paths.
- Compatibility fallback is selected once at composition time. An unknown or
  failed Unified call never silently retries through Legacy transport.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Core now exports immutable MCP DTOs, stable error categories and the
  `UnifiedMcpClient` Port; infrastructure provides Registry, managed Client and
  subprocess worker implementations.
- Production Registry contains only iCourse. A second test Fake needs only a
  JSON Server definition plus a provisional Capability mapping fixture; no
  Domain, Runtime or generic Client branch is required.
- The iCourse public-read-only fixture contains only `icourse_stats`,
  `search_courses`, `get_course(refresh=false)` and `get_reviews`. Crawl,
  refresh, export, robots and online-search surfaces are not model-visible.
- The AstrBot plugin adds an explicit iCourse Client mode, closes Unified
  resources at termination and keeps the native MCP template disabled by
  default.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Streamable HTTP has an injected, socket-blocked offline Contract only; no real
  HTTP MCP Endpoint, credential or network behavior is claimed.
- The real-compatible iCourse evidence uses an empty temporary database and no
  crawl. Live service quality and external availability remain unproven by
  design.
- The derived image emits existing upstream `jieba` and AstrBot registration
  deprecation warnings. They do not affect S12 behavior but remain dependency
  maintenance debt.
