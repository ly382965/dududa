# Findings

Branch: memory-retrieval

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- A bounded in-process BM25 ranker is sufficient for the S14 experiment. It
  preserves the approved CJK/Okapi comparison without introducing a second
  persistent derived store or SQLite tokenizer/runtime variance before there
  is measured need.
- Repository state revision is distinct from implementation revision. Every
  mutation invalidates older snapshots and cursors; query time must equal the
  trusted snapshot/request time.
- Tombstones win permanently over ordinary writes and every restore source.
  Disaster recovery needs a checkpoint at or beyond the recovery fence; an old
  archive alone cannot prove knowledge of later deletion.
- Free-text semantic contradiction inference is not honest without a
  structured fact contract. S14 closes optimistic version, duplicate and
  mutation conflicts but defers subject/predicate/temporal conflict groups.
- The JSON v2 Eval state is a reference-Adapter test mirror, not a stable Eval
  Domain DTO. Its storage coupling is explicit in the manifest.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- `MemoryRepository` now includes `MemoryAdministration`; public delete,
  tombstone, export, archive/restore, rank and retrieval DTOs are versioned,
  immutable and canonical-digest bound.
- `runtime.state.MemoryRetrievalResult` now points to the formal Memory DTO;
  S10's no-Memory/default-off validation is unchanged.
- JSON schema v2 is the crash-stable reference state. The v1 scoped reader is
  retained and upgrades only on a successful mutation; legacy pre-Scope JSON
  remains read-only quarantine.
- `dududa.evaluation` lazily exports the reproducible Memory bundle generator,
  runner and checker. No model, network, SQLite extension or external Memory
  framework enters Core.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- The synthetic M2 gain can catch implementation drift but cannot estimate
  real-language utility, subgroup behavior or production leakage probability.
- Legacy `/remember`, fuzzy `/forget` and direct export still bypass the new
  application boundary. They remain production authority until a later
  consumer migration with rollback evidence; this branch makes no safety claim
  about those commands.
- Production Iris behavior, licensing, delete semantics and migration remain
  unproved. Its current Protocol/Fake evidence must not be described as a real
  backend integration.
