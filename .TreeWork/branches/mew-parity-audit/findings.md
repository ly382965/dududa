# Findings

Branch: mew-parity-audit

## Decisions (conclusions or decision changes learned during implementation; planned pre-coding design belongs in spec.md)

- Mew commit `97df34b3c8ca1747b92003fa3bb6566a58668a3f` is the
  observable client baseline and NapCat `4.18.7` is the inspected OneBot
  baseline.
- Dududa does not reuse Mew's Milky connection/data core. It preserves the
  interaction model while replacing the core with a multi-account server
  gateway: Vue views -> account-scoped stores/cache -> typed same-origin API ->
  allowlisted NapCat OneBot actions.
- Audit review found that `fetch_custom_face` exists in NapCat 4.18.7. The
  former unsupported state was therefore an implementation defect, not a
  protocol gap. Commit `854ebb4` closes it with bounded account/conversation
  handles and a Mew-style default/favorites picker.
- The same audit closed two smaller observable deltas: message search now uses
  Mew's NFKC, case-folded, multi-term pinyin matching, and the conversation
  list restores and displays all account-scoped rich drafts.

### Capability Matrix

| Surface | Mew baseline | Dududa/NapCat outcome | Evidence |
|---|---|---|---|
| History and virtualization | Bidirectional history, stable anchoring, virtual rows | Equivalent cursor history, cached-first open, 5,000-row active bound and dynamic virtual measurement | `useWorkspace.ts`, `ChatPane.vue`, history/cache tests and Playwright |
| Search and drafts | Sender/date/text search, NFKC/pinyin, rich draft marker | Equivalent account/conversation-scoped search and rich drafts; stale cleanup reads cannot restore cleared input | `database.ts`, `ConversationSidebar.vue`, 66 frontend tests |
| Text, links, reply and mention | Rich rendering/composition and reply jumps | Mapped to typed OneBot segments; reply target loading and authoritative all-mention role checks are preserved | mapper, composer, hub and message bubble tests |
| QQ and custom faces | Catalog plus account favorites | QQ faces are mapped directly; NapCat favorites use 10-minute HMAC handles and same-origin previews without browser-visible source URLs | custom-face gateway/schema/composer tests |
| Image, audio, video and files | Render, upload/send and download | Equivalent bounded browser upload, OneBot send and allowlisted media/file proxy with Range and safe disposition | gateway, upload and message bubble tests |
| Forward, Markdown and light apps | Forward viewer, Markdown, structured application cards | Forward nesting and safe Markdown are equivalent; light apps use a safe generic structured card rather than every Mew-specific visual variant | mapper, Markdown and viewer tests |
| Unknown segments | Honest unsupported state | Loss-aware bounded fallback is shown without exposing a raw OneBot payload | mapper and message bubble tests |
| Contacts and routing | Friends/groups, pinyin search, deep chat route | Equivalent, with account filters and an aggregate multi-account inbox added | contacts/search tests and desktop/mobile E2E |
| Notifications | Live requests, history and accept/reject | Live friend/group requests, group history, cache and atomic resolution are mapped; ordinary friend history is explicitly unavailable | directory store and gateway tests |
| Group members/management | Members, roles, admin, kick, card/name/mute/quit | Equivalent typed actions with fresh authoritative role checks before mutations | group dialog, hub and app tests |
| Essence, announcements and files | Browse/manage group resources | Equivalent read/manage actions, signed account/group handles and guarded upload; folder rename is explicitly unavailable | resource panel and gateway tests |
| Settings/cache | Theme, cache scope/statistics, backfill and cleanup | Equivalent account-aware IndexedDB statistics, bounded backfill/cancel and generation-safe cleanup | settings/database/history tests |
| Multi-account isolation | Mew is one active client | Dududa extension: concurrent transport map, aggregate inbox and account-prefixed message/draft/cache/capability keys | two-transport gateway tests and two-account Playwright |
| Agent Console | Not part of Mew | Intentionally unavailable; no fake sessions, runs, configs or results are produced | `AgentConsole.vue`, empty server projections and E2E |

### Explicit Unavailable States

| Capability | Reason |
|---|---|
| `directory.peer_pin` | Inspected NapCat 4.18.7 has no QQ synchronized peer-pin mutation action. |
| `request.friend.history` | NapCat exposes live requests and suspicious-request data, but not complete ordinary friend-request history. |
| `group.folder.rename` | Inspected NapCat 4.18.7 has no group-folder rename action. |

These three are returned as `unsupported` and the UI does not report optimistic
success. The connected account reported 30 supported and 3 unsupported actions.

### Non-Identical Details

- Mew persists nudge events as timeline rows; Dududa currently supports the
  typed nudge action but does not persist incoming nudge notices in the cached
  message timeline.
- Mew has more specialized light-app cards and a raw-segment developer mode.
  Dududa keeps a generic safe card and deliberately omits raw payload copying.
- Dududa does not fetch remote images embedded in pasted HTML. Clipboard and
  drag/drop files use bounded uploads, avoiding a browser-controlled remote URL
  path into OneBot.
- Reply summaries depend on normalized NapCat reply data when the referenced
  message is outside recoverable history. The UI still shows an honest fallback
  and can page backward to a known target.
- Essence data is bounded to the NapCat response (at most 500 audit-visible
  items) and paged in the UI, rather than using Mew's Milky server cursor.

## Interface Or Contract Effects (outward effects on commands, state, APIs, generated files, or public contracts)

- Production browser routes remain credential-free. The OneBot token is read
  only from `/run/secrets/onebot_access_token` by the server.
- `GET .../custom-faces` returns only account/conversation binding metadata,
  HMAC handles, relative preview routes and expiry. Sending accepts only a
  32-hex `custom_face` handle; the server resolves the allowlisted QQ URL.
- IndexedDB contains only NapCat-derived messages, conversations,
  notifications, coverage, operator drafts and derived metadata. Keys include
  `accountId`; media blobs and remote source URLs are not persisted.
- Production deployment remains loopback-only at `127.0.0.1:5173`; unknown
  hosts receive 421 and unknown API routes cannot proxy arbitrary actions.

## Risks And Unknowns (latent hazards after branch work; not unfinished tasks)

- Only one real NapCat account was available. Automated two-transport and
  browser tests prove concurrent isolation, but a two-real-account manual run
  remains environment-dependent.
- No real send, recall, request decision, member/group mutation or file mutation
  was authorized. Their evidence is the in-memory NapCat contract suite.
- The connected account had zero favorite faces, so the real endpoint and empty
  UI were exercised; favorite preview/send used the fake NapCat suite only.
- The main browser chunk is about 923 kB (about 314 kB gzip). It is functional
  but remains a code-splitting performance follow-up.
- Formal browser evidence intercepted the app's normal `markRead` POST. An
  earlier visual launch used the normal client path and may have marked the
  selected conversation read; no message send or management mutation occurred.
- Screenshots contain real QQ data and remain mode-0600 files under `/tmp`;
  they are evidence only and must not be published as fixtures.
