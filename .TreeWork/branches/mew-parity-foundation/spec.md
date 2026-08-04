# Branch Spec

Branch: mew-parity-foundation
Parent: mew-parity

## Development Design

### Baseline And Dependencies

First preserve the existing real-NapCat Web prototype in a selective commit.
Web-owned whole paths are `apps/web`, `docker/web`,
`scripts/configure_napcat_web.py` and its test. Root deployment files include
mixed user work and only Web-specific hunks may be staged. Sub2API and Agent
runtime paths are forbidden.

The Vue application adopts the Mew-compatible foundation dependencies: Vue
Router, Pinia, Dexie, Zod and VueUse. TanStack Virtual and Tiptap may be added
here so downstream source ports share one lockfile, but user-facing behavior
belongs to the chat branch.

### Domain Contracts

All public Web types are account-scoped and validated at the server boundary.
`ConversationRef` contains `accountId`, `scene` and `peerId` and produces one
stable encoded key. `ChatMessage` retains stable domain ID, OneBot
`messageId`, `messageSeq`, sender, direction, timestamps and an ordered segment
array. The segment union is loss-aware and bounded:

- text/link and Markdown/light-app payload summaries;
- mention/all-mention and reply references;
- QQ face, custom/market face;
- image, audio, video and file resources;
- forwarded-message references; and
- an explicit unknown segment with safe type/summary, never the raw event.

Outgoing content uses a smaller validated union whose conversion to OneBot
arrays lives only on the server. Existing text-only requests remain compatible
during migration.

### Capabilities And History

Each account publishes implementation metadata and a typed capability map.
Capabilities distinguish unsupported implementation, insufficient QQ role,
temporarily unavailable connection and supported action. The server derives
static support from the inspected NapCat version and applies dynamic role checks
when the target group/member is known.

History returns `HistoryPage { messages, beforeCursor, afterCursor,
hasMoreBefore, hasMoreAfter }`. Cursors encode message sequence/direction but
are treated as opaque by the browser. Requests are bounded to 1-100 messages,
deduplicate stable message IDs and never claim coverage beyond NapCat's result.

### Persistence

Dexie owns only browser cache. Tables cover conversations, messages,
historyRanges, conversationEvents and drafts. Every primary/index prefix begins
with `accountId` and conversation key. Writes strip Blob/Data/Base64 upload
sources and other ephemeral resource credentials. Cache-first reads are always
followed by NapCat refresh where connectivity permits. Quota cleanup deletes
oldest cached content without invoking gateway mutations.

### Events And Security

SSE events carry account-scoped normalized message/recall/runtime/capability
events. Unknown OneBot events are ignored or trigger bounded refresh, never sent
raw to the browser. The gateway retains timing-safe reverse-WebSocket token
authentication and self-ID checks. Browser writes remain same-origin and the
service stays loopback-only until a separate trusted proxy-auth design exists.

Foundation tests prove schema validation, rich-segment round trips, cursor
semantics, two-account isolation, no token/raw-event leakage, cache partitioning
and migration from the current snapshot contract.
