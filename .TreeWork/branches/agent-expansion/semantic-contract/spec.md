# Branch Spec

Branch: semantic-contract
Parent: agent-expansion

## Development Design (the branch-level technical development thinking established before coding; organize subsections to fit the actual module or phase)

### Purpose And Compatibility Shape

Add explicit span, entity/reference evidence and semantic reject decisions
without changing the accepted S09 Perception Port, v1 DTOs, v1 schema or v1
canonical digests. The existing `decode_model_projection()` remains the exact
v1 reader used by Runtime. A new versioned reader accepts both N-1 v1 and N v2.

The v2 model payload is an additive top-level envelope: it retains every v1
model field and adds one strict `semantic` block. The reader projects the known
base fields through the unchanged v1 decoder, computes the exact base
projection digest, then binds the semantic block to that digest. A v2 payload
therefore has a deterministic v1 downgrade, while an old strict v1 reader still
fails closed rather than silently ignoring future fields.

### Semantic Contracts

- `TextSpan` binds one message ref, NFC-normalized surface, Unicode code-point
  half-open `[start, end)` offsets and a digest of the complete normalized
  message text.
- `EntityMention` adds kind, normalized value, confidence and bounded evidence
  refs to an exact span.
- `ReferenceMention` adds a mention span, target and explicit
  `STRUCTURAL | LINGUISTIC` link source. Structural targets must be backed by
  Connector reply/mention facts; linguistic links remain model evidence and
  never become identity, Scope or permission authority.
- `IntentCandidateV2` binds taxonomy revision, referenced entity slots,
  confidence and evidence.
- `SemanticProjectionV2` also binds the taxonomy revision at projection level,
  so an empty-intent `ABSTAIN` remains attributable and digest-sensitive.
- `SemanticDecision` is exactly `ACCEPT | CLARIFY | ABSTAIN` plus calibration,
  threshold-policy and reason revisions. It does not select Tier, Provider,
  target or Tool permission.

All collections are bounded, immutable, uniquely keyed and deterministically
ordered. Semantic v2 candidates must project exactly onto the legacy v1
entity/reference/intent candidates carried in the same payload; mismatch fails
closed. This prevents N and N-1 consumers from acting on contradictory facts.

### Text And Offset Authority

Validation first normalizes the complete referenced message to NFC. It checks
the full-text digest, code-point bounds, exact surface slice and evidence refs;
there is no guessed repair for a digest, surface or offset mismatch. Adapter
helpers convert UTF-8 byte and UTF-16 code-unit boundaries to normalized
Unicode code-point offsets. Invalid types, out-of-range boundaries, partial
UTF-8 sequences and split surrogate pairs are rejected.

### Schema, Codec And Validation

The v1 schema/ref and decoder remain byte-for-byte behaviorally compatible.
The v2 schema is strict Draft 2020-12 with no remote refs, closed objects,
bounded arrays/strings and exact integer checks. Versioned encode/decode tests
cover v1 round-trip, v2 round-trip, N/N-1 downgrade, unknown versions and
unknown properties. Whole-result validation binds context, base digest,
message/identity references, span text, slot entities, structural links and
decision consistency before exposing the semantic projection.

### Synthetic Schema Pilot

Fixed local 3-12-turn synthetic windows cover Chinese text, emoji, decomposed
Unicode, reply/@ structure, linguistic pronouns, missing slots, ambiguity and
OOS. The pilot proves schema/codec/invariant behavior only. It contains no
user data and cannot establish intent taxonomy quality, calibration, Chinese
multi-turn accuracy or production thresholds. No real model, Endpoint or
external dataset is used.

### Compatibility And External Gates

The v1 Runtime path remains authoritative and no semantic v2 decision gains
side-effect authority in this branch. Real quality requires authorized
conversation-cluster data, independent annotation, adjudication and held-out
evaluation; those remain external. Product taxonomy, unsupported-capability
policy and calibrated thresholds are not invented by synthetic fixtures.
