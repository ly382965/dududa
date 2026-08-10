# Adding A Persona

Status: S15 offline Persona Catalog/Resolver/Renderer is implemented. The
runtime seed remains limited to `dududa`; additional product Personas and
human style evaluation remain pending.

## Boundary

A Persona controls expression: tone, phrasing, address terms, and light
emotional style. It does not control facts, permissions, memory Scope, Social
Decision, capability eligibility, tool results, citations, or safety policy.

## Planned Files

```text
configs/personas/<persona-id>/persona.yaml
configs/personas/<persona-id>/voice.md
configs/personas/<persona-id>/lore.md       # optional
configs/personas/<persona-id>/examples.yaml # optional
```

`persona.yaml` declares schema version, stable ID, display name, locale,
renderer options, compatible output modes, and references to versioned content.
`voice.md` owns expression rules; optional lore and examples remain expression
inputs, not authorization or factual sources. None may contain a Provider key,
QQ ID, private relationship data, or runtime path.

## Procedure

1. Choose a stable lowercase ID that will not be reused.
2. Add validated metadata and `voice.md` under the Persona config root; add lore
   or examples only when they are needed.
3. Keep factual, permission, privacy, and tool instructions out of style text;
   reference system-owned policies instead.
4. Register the Persona in the typed Persona Registry configuration.
5. Add loader/schema and safety-boundary tests.
6. Add OC rendering fixtures showing tone without changing protected facts.
7. Add a seed migration only if the runtime must install the Persona into
   AstrBot; make it idempotent and schema-aware.
8. Test selection, fallback, missing files, and rollback with synthetic data.

## Required Tests

- Metadata and referenced-content schema validation.
- Stable ID and duplicate detection.
- Prompt file remains inside the Persona directory.
- No credential or runtime-data pattern.
- Renderer cannot change protected numbers, citations, decisions, error codes,
  or tool results.
- Missing/invalid Persona uses an explicit safe fallback.
- Persona switch does not cross memory Scope.

## Current Compatibility

The compatibility seed uses `configs/personas/dududa.json` and `dududa.md`.
Future Persona assets must preserve the current Catalog generation, seed
script, Compose mount, tests and rollback contracts in the same review.
