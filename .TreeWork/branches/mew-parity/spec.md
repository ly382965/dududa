# Branch Spec

Branch: mew-parity
Parent: root

## Development Design

This epic owns the shared interpretation of Mew behavior over NapCat. Mew is
the source baseline for browser UX, state flow and tests; Dududa is the source
of truth for server-side credentials, concurrent accounts and deployment.

The dependency direction is fixed:

```text
Mew-adapted Vue views/components
  -> account-scoped Web stores/services
  -> typed Dududa HTTP/SSE contract
  -> allowlisted NapCat capability gateway
  -> per-account OneBot reverse WebSocket
```

No browser module imports a OneBot client, accepts an Access Token, or invents
QQ data. No server route forwards arbitrary action names. Shared message,
history, capability, identity and cache contracts belong to
`mew-parity-foundation`; chat and directory branches only extend endpoints and
views within those shapes.

The existing account rail and aggregate inbox are Dududa extensions to Mew.
Every Mew-derived key or singleton is made account-scoped before use. The Agent
Console stays present only as an honest disconnected surface and is not a
dependency of QQ parity.
