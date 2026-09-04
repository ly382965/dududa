# Findings

Branch: bot-release-convergence

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Five PR10 services were deliberately disabled/unmapped and lacked production mounts/caches. Activate only the Web console extra catalog; shared Runtime providers and permissions remain unchanged. A fresh client health read is not a connection test.
- Official source checks found an incorrect CS party-notice URL, broken full-year campus dates, omitted pre-2019 tbody-less program tables and Physics sidebar noise. Corrected parsers produce bounded real caches; historical local recommendations remain explicitly unverified for current business hours.
- Saved DeepSeek pools are official API V4: Flash low / Flash high / Pro max. Three bounded synthetic requests returned HTTP 200 and visible output. Sonnet was enabled by explicit operator approval. Runtime migration remains pending separate informed provider-retention approval; current no-retention policy must not be misrepresented.
- Existing maximum reasoning mapped to xhigh (only high on DeepSeek), health probes had only 8 tokens, and short response budgets included no reasoning reserve. Added provider-specific mapping/probe and opt-in budget/privacy configuration with legacy defaults unchanged.
- Live `cdbc5f0` Web/MCP deployment passed all five connection checks and nonempty bounded queries through Web, with 26 catalog capabilities and intact public Auth redirect. AstrBot/NapCat were not recreated; 27 excluded container identities, image IDs and start times match the private baseline. Runtime still reports the old GPT mapping, not the saved DeepSeek pool revision 11.

- Missing historical-corpus environment caused the Agent fallback, not a missing Bandit. Formal routes now share policy/preview implementation but bypass corpus and personal-provider lookup entirely.
- Actual rollout controls must come from the Runtime's current control provider; startup config and stale status files can misreport a changed kill switch.
- Live core/sub2api differences were old committed implementations, not unique fixes to copy back. Arc is a real functional fork and requires an explicit compatibility decision.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added `/api/agent/{status,catalog,config,respond}` and authenticated plugin `GET runtime/status`; status includes a dedicated readiness explanation.
- Web/AstrBot share the independent Agent policy directory, writable only by Web and readable by AstrBot. Whole sensitive AstrBot config mounts are no longer needed by Web.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Provider Manager hot reload terminates old providers while the Runtime retains their object references. Saved Key pools cannot honestly be called applied without controlled reassembly and binding verification.
- An imported container rootfs omits bind mounts; separate consistent data backups remain essential to rollback.
- Runtime assembly readiness is not model-call health. Live smoke found upstream HTTP 503 even for a bounded synthetic low-reasoning call; listing the model does not establish successful generation. Missing routes now produce an explicit Web error.
- Preserved Arc downloads its missing OpenCV dependency on first new-host startup, delaying AstrBot HTTP readiness. Post-host activation successfully retries the initial pre-Provider Runtime assembly; no stale startup failure should override the later ready state.
