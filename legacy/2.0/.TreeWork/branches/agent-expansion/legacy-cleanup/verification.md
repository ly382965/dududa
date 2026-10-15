# Verification

Branch: legacy-cleanup

## Latest Verification

- Command: `Python 3.12 full 651/2; Python 3.10 S22 32/2; worker/root MCP; no-network image; wheel/import; Compose equivalence; secret/static`
- Result: verified
- Coverage gap: No Web/Eval/30-day rerun; no real Provider/source/QQ/human quality or online Bandit evidence
- Recorded: unix:1786378462

## Evidence Details

- Python 3.12 complete repository discovery: 651 tests passed, two
  AstrBot-host-only skips.
- Python 3.10 isolated S22 sample: 32 passed, two AstrBot-host-only skips;
  isolated worker tests: 2 passed; root worker/Capability contracts: 11 passed.
- No-network read-only AstrBot image smoke: 19 plugin tests passed; image
  `sha256:ca19efc3d7d6a1fc608f34ee80e057502b35143ed72619988ef9f6df1dbc5c0a`;
  actual iCourse composition was `unified/unified_ready`.
- Clean wheel install/import and `pip check`, root/canonical Compose byte
  equality, Compose contract `sha256:305745204859c1b50f120dcc697af0319df01e623e942b1e3ae03dd44ca5f0da`,
  824-file secret scan, import boundary, locks, Shell, compile, JSON and
  whitespace passed.
- Exact S19 archive commit `e303dc8`, mode 0600, 10,506,240 bytes, SHA-256
  `80500b51187905a45801e195a3d906adac2b11fcbced172a0657e3f00386dc77`.
