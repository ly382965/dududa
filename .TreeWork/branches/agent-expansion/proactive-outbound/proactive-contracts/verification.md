# Verification

Branch: proactive-contracts

## Latest Verification

- Command: `Python 3.10.20/3.12.13: 590 repository tests each; 30 proactive unit tests and 2 Port contracts under -W error; MCP v2/iCourse failure and lifecycle contracts; changed-file Ruff/format; uv lock; compileall; sdist/wheel install/import/pip check; 778-file secret scan; Shell/Compose/whitespace; Web 66+42 tests, typecheck and build`
- Result: `passed`; each full Python run has only the two existing AstrBot-derived-image skips,
  focused suites have zero skips, and all S15A offline acceptance checks pass.
- Coverage gap: No Scheduler durability, real source, model, production Actor/Grant registry,
  Output Adapter, QQ identifier or send was used. In-memory CAS/quota and synthetic fixtures prove
  contracts only; all proactive production paths remain absent and default-off.
- Recorded: `unix:1786340886` (`2026-08-10T05:48:06Z`)
