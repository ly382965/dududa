# Verification

Branch: mew-parity-foundation

## Latest Verification

- Command: `npm test`; `npm run typecheck`; `npm run build`;
  `npm run test:e2e`; `npm audit --omit=dev`; full Python unittest discovery;
  Compose parse; secret scan; `git diff --check`.
- Result: passed. Web: 11 browser Unit + 14 gateway Unit/Contract + 3
  Playwright; production client/server build; zero production dependency
  vulnerabilities. Repository Python regression passed with the two expected
  host-only AstrBot skips. Compose and 439-file secret scan passed.
- Coverage gap: real NapCat read-only inspection and any QQ-visible/destructive
  mutation remain reserved for `mew-parity-audit` and explicit authority.
- Recorded: 2026-08-04 Asia/Shanghai.
