# Findings

Branch: mcp-v2-spike

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- ADOPT `mcp==2.0.0` for the S12 infrastructure implementation; retain v1.29
  at the root and on iCourse throughout the compatibility migration.
- Treat new unmapped Tool discovery as a compatible fact but never as an
  authorization. Reject mapped input/output Schema changes and expired
  Snapshots while retaining the last-known-good digest.
- Separate request timeout from bounded cleanup time. A 150 ms handshake
  timeout is delivered correctly, while v2 performs shielded process cleanup
  before returning; the Spike therefore verifies both timeout classification
  and a three-second total cleanup ceiling.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- ADR 0006 authorizes v2 only for the next S12 Adapter and binds the exact
  report digest. It does not alter an existing runtime Port.
- `spikes/mcp-v2/report.json` is a committed, sanitized contract artifact;
  `--check-report` fails if code, SDK behavior or evidence drifts.
- Python 3.10/3.12 verification requires distinct uv cache roots when runs may
  overlap.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Legacy mode is an SDK compatibility surface, not proof that iCourse is a v2
  Server. S12 must retain the old direct path until S22 migration evidence.
- The Spike proves local stdio behavior only. Real HTTP transport, credentials,
  live sources, production load and QQ behavior remain external gates.
- Linux `/proc` supplies the strongest file-descriptor evidence; child PID,
  task and close checks still run independently when `/proc` is unavailable.
