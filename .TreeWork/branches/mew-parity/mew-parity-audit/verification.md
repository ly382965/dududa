# Verification

Branch: mew-parity-audit

## Latest Verification

- Command: `Web 66+42 tests, 6 Playwright, build; repository 352 tests; live read-only NapCat/browser/artifact/deployment audit`
- Result: passed
- Coverage gap: One real account; no authorized QQ-visible mutations; three explicit NapCat gaps and documented minor Mew differences
- Recorded: unix:1785851264

## Evidence Detail

- `cd apps/web && npm test`: 66 frontend tests in 17 files and 42 server
  tests in 3 files passed.
- `cd apps/web && npm run build && npm run test:e2e && npm audit --omit=dev`:
  typecheck/build passed, all 6 desktop/mobile Playwright scenarios passed and
  the production dependency audit reported 0 vulnerabilities. The build kept
  a non-fatal 923 kB main-chunk warning.
- `PYTHONPATH=packages/dududa-agent/src:services/icourse-mcp/src python3 -m
  unittest discover -s tests -v`: 352 repository tests passed with 2 existing
  AstrBot-host-only skips.
- `python3 -m compileall -q plugins services scripts`, `python3
  scripts/check_secrets.py`, Compose parsing and `git diff --check` passed. The
  secret scan covered 476 files.
- Production bundle scanning found no test QQ ID, demo marker, OneBot token
  value, raw path, credential header or unrestricted/custom-face action name
  in the browser bundle. Browser/server hashes matched the running container.
- Loopback GET probes returned HTTP 200 and connected: 1/1 account online, 14
  conversations, 30/33 capabilities supported, 3 friends, 9 groups, 20 sampled
  group members, 20 sampled history messages, 3 essence entries, 1
  announcement, 4 root files and an account/conversation-bound zero-item
  favorites catalog. No QQ ID or handle was printed.
- Read-only Playwright at 1440x900 and 390x844 intercepted every non-GET API
  call. Both favorites views rendered without horizontal overflow,
  console/page/network/API errors, credential fields, browser auth headers or
  non-mark-read mutations. Evidence remains at
  `/tmp/dududa-live-final-desktop.png` and
  `/tmp/dududa-live-final-mobile.png`.
- Compose rebuilt and recreated only `dududa-web-1`. NapCat remained
  `31f83c81...` started `2026-07-30T10:05:36.202654074Z`; AstrBot remained
  `768a9ba2...` started `2026-07-30T10:05:36.205564647Z`.

Recorded on 2026-08-04 Asia/Shanghai.
