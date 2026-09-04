# Findings

Branch: bot-release-convergence

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Missing historical-corpus environment caused the Agent fallback, not a missing Bandit. Formal routes now share policy/preview implementation but bypass corpus and personal-provider lookup entirely.
- Actual rollout controls must come from the Runtime's current control provider; startup config and stale status files can misreport a changed kill switch.
- Live core/sub2api differences were old committed implementations, not unique fixes to copy back. Arc is a real functional fork and requires an explicit compatibility decision.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Added `/api/agent/{status,catalog,config,respond}` and authenticated plugin `GET runtime/status`; status includes a dedicated readiness explanation.
- Web/AstrBot share the independent Agent policy directory, writable only by Web and readable by AstrBot. Whole sensitive AstrBot config mounts are no longer needed by Web.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Provider Manager hot reload terminates old providers while the Runtime retains their object references. Saved Key pools cannot honestly be called applied without controlled reassembly and binding verification.
- An imported container rootfs omits bind mounts; separate consistent data backups remain essential to rollback.
