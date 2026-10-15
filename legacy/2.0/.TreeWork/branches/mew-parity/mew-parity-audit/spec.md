# Branch Spec

Branch: mew-parity-audit
Parent: mew-parity

## Development Design

Audit the integrated Web product against the pinned Mew behavior inventory and
the approved NapCat deviations. Build a capability matrix with direct test or
manual evidence for each chat, directory, notification, group-resource and
settings behavior. A missing NapCat action passes only when the capability and
UI are explicitly unavailable; visual presence without a real action fails.

Automated verification covers Unit, gateway contract, Playwright desktop/mobile,
typecheck/build, repository Python tests, Compose parsing, secret scan and
dependency audit. Two simulated concurrent NapCat transports prove account
isolation. Real-account verification is read-only by default: connection,
identity, lists, recent conversations, history, members/resources and incoming
events. Sending, recall, request decisions and destructive group/file operations
are performed only with explicit authority.

Playwright screenshots and console/network traces check blank states, overflow,
overlap, long names/messages, media loading, mobile panel transitions and
virtual-scroll stability. The audit also inspects the production bundle and API
responses for demo data, tokens, cookies, raw paths and unrestricted actions.
