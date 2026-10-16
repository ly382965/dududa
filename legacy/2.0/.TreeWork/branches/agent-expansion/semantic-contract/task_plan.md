# Task Plan

Branch: semantic-contract
Parent: agent-expansion
Title: S09 Additive Semantic Contract

## Scope (owned work and boundary; not progress notes or implementation history)

- Add immutable semantic v2 contracts and exact span/offset validation.
- Add strict v2 schema plus a versioned v1/v2 encoder and reader.
- Preserve v1 DTO, schema, reader, digest and Perception Port behavior.
- Prove Connector structural authority and linguistic-reference separation.
- Run a fixed local 3-12-turn synthetic Schema pilot and repository regression.

## Acceptance (done checklist; not exploratory todos unless they decide completion)

- [x] Existing v1 schema, decoder, canonical digest goldens and Runtime tests remain unchanged.
- [x] The versioned reader accepts v1 and v2, and v2 deterministically downgrades to the exact v1 base projection.
- [x] `TextSpan` enforces NFC, Unicode code-point half-open offsets, full-text digest and exact surface binding.
- [x] UTF-8 byte and UTF-16 code-unit offset conversion rejects invalid or split boundaries.
- [x] Entity, reference, intent and decision DTOs are bounded, immutable, unique and digestible.
- [x] Structural references require Connector reply/@ evidence; linguistic references never grant structural authority.
- [x] Semantic v2 and legacy v1 candidates cannot disagree inside one envelope.
- [x] Unknown versions/properties, unknown refs, bad spans/digests, missing properties, dangling slot refs and inconsistent decisions fail closed; valid empty slots are represented explicitly by `CLARIFY`.
- [x] Synthetic 3-12-turn fixtures pass Schema dry-run without a real-quality claim.
- [x] Focused, dual-Python affected and repository safety tests pass.

## Local Steps (durable working steps toward acceptance; not session-only todos)

- [x] Implement semantic DTOs, digests and normalized offset helpers.
- [x] Implement strict v2 schema, versioned encode/decode and v1 downgrade.
- [x] Implement whole-envelope and Connector-authority validation.
- [x] Add v1 compatibility goldens and negative Contract tests.
- [x] Add fixed synthetic windows plus a machine-readable Schema pilot report.
- [x] Run focused, dual-Python affected and repository verification.
- [x] Record Verification, Findings and the coherent local commit.

## Out Of Scope (nearby work this branch must not absorb; not unrelated future ideas)

- Product intent taxonomy, unsupported-capability inventory or calibrated thresholds.
- Real QQ/group data, human annotation, model training or quality claims.
- Changes to Complexity, TierPolicy, Static Router, Connector authority or Runtime side effects.

## Dependencies (local or external prerequisites; branch-to-branch order belongs in tree.yaml)

1. Completed and integrated Production Shape gate.
2. Existing S09 v1 Perception contracts and synthetic policy regression assets.
3. Approved semantic evidence boundary in the root Spec and research report.

## Branch Intake Gate (inspect/reuse/create judgment; not after-the-fact branch sprawl justification)

- Inspect: existing v1 contracts/schema/decoder/validator, canonical codec and S09 fixtures.
- Reuse check: keep the v1 Projection and Perception Port; add a versioned envelope rather than replacing either.
- New branch rationale: Created from declarative `.TreeWork/tree.yaml`.
