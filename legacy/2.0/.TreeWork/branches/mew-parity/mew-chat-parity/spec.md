# Branch Spec

Branch: mew-chat-parity
Parent: mew-parity

## Development Design

Port Mew's chat behavior against Foundation contracts, not Milky. Reuse and
adapt `ChatPane`, `MessageBubble`, `MessageComposer`, chat window/scroller
composables, outgoing/composer/search services and related dialogs/tests.

The active window opens cached real messages first, reconciles the latest
NapCat page, loads older/newer pages by opaque cursors and keeps stable anchors
while TanStack Virtual measures dynamic media. It supports unread positioning,
jump-to-reply, return-to-latest, time separators, deduplication and bounded
in-memory windows. All window/cache keys include account ID.

The renderer covers the accepted segment union, refreshes expiring resources
through typed endpoints and displays explicit fallbacks. Message actions include
copy, reply, forward, recall, retry, nudge and `+1` only when account capability,
message ownership/time and target scene allow them.

The Tiptap composer supports text, links, newline, reply state, group member
mentions, all-mention role gating, QQ/custom faces, paste/drop/select images and
file selection. It serializes drafts without ephemeral media and sends ordered
segments through the gateway. Audio/video/file upload progress and failure are
visible; no optimistic sent state survives a failed OneBot response.

Conversation identity is carried through draft/reply events and upload
completion callbacks rather than inferred from whichever account is currently
selected. The directory branch supplies authoritative group-member candidates
and the current QQ role through the chat input boundary; until that data is
available, recent real senders remain usable and all-mention stays disabled.

Single-message forwarding uses NapCat's source-scene-specific single-forward
actions. Received merged-forward nodes are normalized recursively, including
NapCat's inline nested nodes, without fabricating retrievable forward IDs.
Message file URLs and expired media URLs are refreshed through typed,
conversation-bound endpoints and proxied with host, size, Range and attachment
controls.

Desktop context menus and mobile long-press/swipe gestures follow Mew while
retaining Dududa's account rail, aggregate inbox and Agent-panel breakpoint.
Mew unit/E2E tests are adapted with account-scoped fixtures plus new
cross-account and NapCat error tests.
