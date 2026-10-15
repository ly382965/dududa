# Findings

Branch: mew-parity

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Mew is a behavior and interaction baseline, not Dududa's runtime core.
  Dududa replaces Mew's browser-held Milky singleton with a server-owned
  multi-account NapCat map and account-scoped HTTP/SSE/cache contracts.
- The observable QQ workflows are reproduced at the mapped capability level.
  Dududa additionally provides an aggregate inbox and account rail; it does not
  claim byte-for-byte Mew internals or visuals.
- Real-data caching is accepted only for NapCat-derived values, operator drafts
  and derived metadata. It remains bounded and clearable, and cache cleanup
  never invokes a QQ mutation.
- The Agent Console is an honest unavailable shell and is not evidence of an
  Agent runtime implementation.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- The browser uses fixed same-origin routes and SSE only. It never receives an
  Access Token, raw OneBot action proxy, cookie-based identity session or local
  filesystem path.
- Every account, conversation, message, notification, capability, draft,
  history range, upload and group-resource handle carries an account scope.
- NapCat 4.18.7 custom favorites are available through short-lived HMAC
  handles; the browser cannot supply or recover the remote QQ media URL.
- Production remains bound to host loopback and is deployed by recreating only
  the Web Compose service.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- One real account was connected during audit; automated two-transport tests
  are the current concurrent-account evidence.
- Real QQ-visible/destructive operations were not authorized. The fake NapCat
  contract suite covers their mapping, validation and failure behavior.
- The three explicit NapCat gaps and smaller Mew presentation differences are
  frozen in the child audit findings.
- The approximately 923 kB browser main chunk is a later performance concern,
  not a functional release failure.
