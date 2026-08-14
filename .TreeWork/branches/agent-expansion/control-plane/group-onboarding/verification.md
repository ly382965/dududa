# Verification

Branch: group-onboarding

## Latest Verification

- Command: `PYTHONPATH=packages/dududa-agent/src .venv/bin/python -m unittest tests.unit.control_plane.test_foundation tests.unit.control_plane.test_onboarding` plus three focused import-boundary tests.
- Result: 11 tests passed. Covers pending zero-service, eligibility diff,
  confirmation binding, duplicate/CAS, strict failure, SQLite restart/LKG,
  managed-group recovery, Runtime snapshot and Python Web DTO projection.
- Command: targeted `ruff check` and `ruff format --check` over Control Plane,
  its Port/Adapter and focused tests.
- Result: all checks passed; 18 files formatted.
- Command: `vitest` for `ControlPlaneView.spec.ts` and the focused Node proxy
  case in `server/app.spec.ts`.
- Result: both test files passed. The Vue test exercises authoritative diff,
  activate, update, pause, resume, rollback and refresh recovery through a Fake
  Adapter; the Node test proves account-to-bot mapping and typed proxy calls.
- Command: `npm run build` in `apps/web`.
- Result: Vue/server typecheck and production builds passed. Vite reported only
  its non-blocking large-chunk warning.
- Command: Playwright visual sampling at 1440x900 and 390x844 with fixed API
  projections.
- Result: the onboarding workflow rendered at both widths; the mobile document
  width equaled its 390px viewport with no page-level horizontal overflow.
- Coverage gap: Production Core HTTP/operator identity adapters and real QQ
  activation remain external. No Connector/history/Perception/session path
  changed, so the authorized local Dududa corpus was deliberately not replayed.
- Recorded: 2026-08-14 Asia/Shanghai.
