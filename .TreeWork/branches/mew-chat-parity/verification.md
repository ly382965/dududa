# Verification

Branch: mew-chat-parity

## Latest Verification

- Command: `npm run build && npm test -- --run && npm run test:e2e && npm audit --omit=dev && git diff --check`
- Result: passed
- Coverage gap: Real NapCat checks remain read-only until QQ-visible mutation authority; full member and all-mention role data integrates in mew-directory-parity.
- Recorded: unix:1785834561
