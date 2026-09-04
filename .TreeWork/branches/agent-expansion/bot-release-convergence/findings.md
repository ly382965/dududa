# Findings

Branch: bot-release-convergence

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- The MCP screenshot's native-looking check buttons came from a missing `.mcp-check-button` stylesheet, not a stale asset. Fixed two-column cards and shared nowrap/ellipsis also cramped long status and check timestamps. Agent tabs are outside the settings scrollport; heading clipping was normal scrolling rather than a proven z-index defect. A scoped sticky/wrapping toolbar and width-adaptive cards correct the visible behavior without changing global layout or MCP state.
- The Web-only `31441a3` release passed frontend100/browser10/type/build and exact live CSS comparison. All 30 non-Web containers were unchanged. The browser fixture uses synthetic MCP data and Fake NapCat only; it does not send QQ or probe real MCP servers. Public auth302, Web/QQ connected and live MCP10/26 remained intact.
- Five PR10 services were deliberately disabled/unmapped and lacked production mounts/caches. Activate only the Web console extra catalog; shared Runtime providers and permissions remain unchanged. A fresh client health read is not a connection test.
- Official source checks found an incorrect CS party-notice URL, broken full-year campus dates, omitted pre-2019 tbody-less program tables and Physics sidebar noise. Corrected parsers produce bounded real caches; historical local recommendations remain explicitly unverified for current business hours.
- DeepSeek V4 Flash low / Flash high / Pro max are now applied to Runtime from external pool revision 14. The operator explicitly accepted default provider-managed retention. Evidence was regenerated using three actual AstrBot Provider calls and health probes; old GPT no-retention claims were not reused. CN/provider-managed is an explicit scoped policy, not a claim of zero retention or no training.
- Existing maximum reasoning mapped to xhigh (only high on DeepSeek), health probes had only 8 tokens, and short response budgets included no reasoning reserve. Added provider-specific mapping/probe and opt-in budget/privacy configuration with legacy defaults unchanged.
- The earlier `cdbc5f0` Web/MCP deployment passed all five connection checks and nonempty bounded queries with 26 catalog capabilities. The latest follow-up recreates only AstrBot as `0ef2a18-4.27.5`; immutable Core source is `5e243fd`. Web/MCP/NapCat and all 27 excluded containers retain their identities/image IDs/start times. Public Auth redirect remains intact, and live Runtime reports DeepSeek rather than GPT.
- The real missing bridge was between Web's external Key store and AstrBot's Source/Provider registration. Runtime resolves Provider objects during assembly; neither Key nor Base URL belongs in core business logic. The operator CLI prepares and installs external configuration with the host stopped, then restart reconstructs those objects. Future page saves alone still do not apply or hot-reload Runtime.
- AstrBot merges Provider-level fields over Source fields; replacing only Source left stale Key/Base URL overrides possible. The migration replaces each selected Provider row and validates bindings, while preserving unrelated providers/sources and rate/concurrency limits.
- An SDK retry plus AstrBot outer recovery loop violated the explicit bounded-call contract. The new patch disables both only for one-attempt calls, forwards allowlisted parameters, and removes raw completion/key-prefix logging. Nine actual Provider/SDK MockTransport cases passed, including timeout/cancellation and redaction.
- A fixed total output budget of 8000 could reject the configured 8192 direct + 4096 perception reservations before any request. Composition now covers both configured reservations; legacy defaults remain unchanged.
- The first synthetic “测试” prompt deferred on conflicting evidence despite a valid DeepSeek route. Static inspection supports verification-keyword disagreement as the cause; the exact runtime conflicting field was not captured. The ordinary greeting comparison generated a nonempty preview in 10.732 seconds with no QQ output, memory writes or tool calls. Neither policy nor text output was fabricated to force success.

- Missing historical-corpus environment caused the Agent fallback, not a missing Bandit. Formal routes now share policy/preview implementation but bypass corpus and personal-provider lookup entirely.
- Actual rollout controls must come from the Runtime's current control provider; startup config and stale status files can misreport a changed kill switch.
- Live core/sub2api differences were old committed implementations, not unique fixes to copy back. Arc is a real functional fork and requires an explicit compatibility decision.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added `/api/agent/{status,catalog,config,respond}` and authenticated plugin `GET runtime/status`; status includes a dedicated readiness explanation.
- Web/AstrBot share the independent Agent policy directory, writable only by Web and readable by AstrBot. Whole sensitive AstrBot config mounts are no longer needed by Web.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Provider Manager hot reload terminates old providers while the Runtime retains their object references. Saved Key pools cannot honestly be called applied without controlled reassembly and binding verification.
- An imported container rootfs omits bind mounts; separate consistent data backups remain essential to rollback.
- Runtime assembly readiness and model listings alone are not generation evidence. The old GPT upstream failed with HTTP 503; the new DeepSeek route additionally passed actual no-send Runtime generation. This does not certify long-request latency, every prompt, or autonomous QQ delivery quality.
- Preserved Arc previously downloaded missing dependencies on first startup, delaying readiness. The image now includes its exact installed public OpenCV 4.14.0.94 and pyparsing 3.1.4 distributions, with existing NumPy retained and imports checked. This removes the download blocker without replacing the legacy Arc command implementation.
