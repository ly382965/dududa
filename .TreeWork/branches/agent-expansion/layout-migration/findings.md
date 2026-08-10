# Findings

Branch: layout-migration

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Manifest v2 cannot become installation authority in S17. Moving the exact v1
  lock preserves a single editable source without fabricating license or hash
  evidence.
- Root compatibility uses symlinks/thin wrappers for one Release. S22 owns
  deletion after consumer and previous-Release recovery evidence.
- v1 marker comparison recognizes only the two path aliases created by S17;
  arbitrary marker normalization would weaken local-change detection.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Canonical host paths changed, while `./manage.sh`, root Compose/environment,
  old source directory paths and root lock remain compatible entrypoints.
- Container plugin/config/script/iCourse paths, AstrBot plugin IDs, Python
  distribution/import names and MCP Server ID `icourse` are unchanged.
- The installer reads only `third_party/plugins.lock.json`; compatibility
  symlinks are not second authorities.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Iris has no verified redistribution license for the pinned revision, so a
  future Manifest v2 release remains blocked unless evidence or a replacement
  is supplied.
- Compatibility links can become accidental permanent APIs if S22 does not
  enforce the one-Release deletion evidence.
